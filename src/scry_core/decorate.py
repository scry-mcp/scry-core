"""A demo's clip with the presence layers drawn in, from the run's timeline (`timeline`) and the
frames alone: the edge, the pointer and a zoom. Only this module imports Pillow and numpy, the
`decorate` extra.

Honest to the run: a frame shows only what its call and its input were. The pointer is drawn
from its first real position on, passes through every position the server sent at the frame it
was sent (of two sent at one frame, the later), and only the path between two of them is eased:
a slight curve and an overshoot that settles before it arrives. A button's press is a ripple and
a brief squeeze of the pointer on its frame.

The clock is the clip's own: an emulator frame is `1 / rate` seconds. Calls are read from the
last rewind of the machine (a state load) before the clip, because frames before it are no
longer this clip's.

Deterministic: no clock, no randomness, so a clip decorated twice is the same pixels.
`python -m scry_core.decorate` makes one decorated loop from a recording.
"""

from __future__ import annotations

import argparse
import math
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from scry_core import motion, timeline
from scry_core import overlay as ov
from scry_core.presence import LOOK, Look
from scry_core.verdict import EXIT_INVALID, EXIT_PASS, Invalid

#: The seconds a pointer takes over the last stretch to a new position; before that it waits.
MOVE_S = 0.45
#: How far the path bows off the straight line, as a share of its length.
CURVE = 0.08
#: easeOutBack's overshoot; 0 is none.
OVERSHOOT = 1.2
RIPPLE_S = 0.5
PRESS_S = 0.15
PRESSED = 0.82
GHOSTS = 5
#: Pixels of motion between two frames below which no blur is drawn.
BLUR_FROM_PX = 6.0
ZOOM_S = 0.8
POINTER_SHAPE = ((0, 0), (0, 16), (4, 12), (7, 19), (10, 18), (7, 11), (12, 11))
POINTER_UNITS = 19


@dataclass(frozen=True)
class Zoom:
    """A push in on `box` (x, y, width, height in the guest's pixels) from emulator frame
    `first` to `last`, eased in and out over `ZOOM_S`."""

    first: int
    last: int
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class Style:
    """What a demo draws: `layers` as `overlay.Overlay.asked` names them, the live overlay's
    `look`, and a zoom."""

    layers: tuple[ov.Layer, ...] = ov.OVERLAY.asked()
    look: Look = LOOK
    zooms: tuple[Zoom, ...] = ()


@dataclass(frozen=True)
class Clip:
    """Pictures as shown, each with the emulator frame it is; `box` is the part of the guest's
    picture they show, and the guest's frames a second is `rate`."""

    frames: Sequence[int]
    pictures: Sequence[motion.Picture]
    box: motion.Box
    rate: Fraction


@dataclass
class _Plan:
    """What the clip's timeline says, in the clip's seconds."""

    points: list[tuple[float, float, float]] = field(default_factory=list)
    presses: list[tuple[float, float, float]] = field(default_factory=list)


def pointer_at(points: Sequence[tuple[float, float, float]], t: float
               ) -> tuple[float, float] | None:
    """Where the pointer is drawn at `t`, given its real positions `(t, x, y)` in order: None
    before the first, exactly a position at its time, eased between two."""
    if not points or t < points[0][0]:
        return None
    for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:], strict=False):
        if t0 <= t < t1:
            window = min(MOVE_S, t1 - t0)
            u = (t - (t1 - window)) / window
            if u <= 0:
                return x0, y0
            e = 1 + (OVERSHOOT + 1) * (u - 1) ** 3 + OVERSHOOT * (u - 1) ** 2
            dx, dy = x1 - x0, y1 - y0
            bow = CURVE * math.sin(math.pi * u)
            return x0 + dx * e - dy * bow, y0 + dy * e + dx * bow
    last = [p for p in points if p[0] <= t][-1]
    return last[1], last[2]


def _ran(call: Mapping[str, Any]) -> tuple[int, int]:
    """The frames a call ran from and to; a rewind ran none, at the frame it left the machine,
    and a call whose reply named one frame only is placed at it."""
    before, after = call["before"], call["after"]
    before = after if before is None else before
    after = before if after is None else after
    return (after, after) if after < before else (before, after)


def _span(calls: Sequence[Mapping[str, Any]], frames: tuple[int, int]) -> list[Mapping[str, Any]]:
    """The calls a clip of `frames` (first, last) may show: from the last rewind before the last
    call that reaches into the clip, up to that call."""
    first, last = frames
    counted = [call for call in calls
               if call["before"] is not None or call["after"] is not None]
    reaching = [n for n, call in enumerate(counted)
                if _ran(call)[0] <= last and _ran(call)[1] >= first]
    if not reaching:
        raise Invalid(f"the timeline names no call over frames {first} to {last}, so nothing "
                      "says what the clip shows")
    end = begin = reaching[-1]
    while begin > 0 and _ran(counted[begin])[1] >= _ran(counted[begin])[0] \
            and _ran(counted[begin - 1])[1] <= _ran(counted[begin])[0]:
        begin -= 1
    return counted[begin:end + 1]


def _plan(document: Mapping[str, Any], clip: Clip) -> _Plan:
    zero = clip.frames[0]

    def at(frame: int) -> float:
        return float((frame - zero) / clip.rate)

    plan = _Plan()
    pressed: list[float] = []
    for call in _span(document["calls"], (min(clip.frames), max(clip.frames))):
        for event in call["events"]:
            when = at(event["frame"])
            if event["kind"] == "pointer":
                x, y = _shown(clip.box, clip.pictures[0], event["x"], event["y"])
                plan.points = [p for p in plan.points if p[0] < when] + [(when, x, y)]
            elif event["kind"] == "button" and event["down"]:
                pressed.append(when)
    for when in pressed:
        if (where := pointer_at(plan.points, when)) is not None:
            plan.presses.append((when, *where))
    return plan


def _shown(box: motion.Box, picture: motion.Picture, x: int, y: int) -> tuple[float, float]:
    """A guest pixel's centre in the shown picture."""
    return ((x - box.x + 0.5) * picture.width / box.width,
            (y - box.y + 0.5) * picture.height / box.height)


def _rgba(rgb: int, alpha: float) -> tuple[int, int, int, int]:
    return ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF,
            round(255 * max(0.0, min(1.0, alpha))))


def _edge_mask(width: int, height: int, look: Look) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Per pixel, the share of the edge's alpha: 1 at the border, falling in `look.steps` steps
    to 0 at `look.edge` of the shorter side."""
    thick = max(1, round(look.edge * min(width, height)))
    xs, ys = np.arange(width), np.arange(height)
    inward = np.minimum(np.minimum(ys, height - 1 - ys)[:, None],
                        np.minimum(xs, width - 1 - xs)[None, :])
    step = np.floor(inward * look.steps / thick)
    return np.clip(1 - step / look.steps, 0, 1).astype(np.float32)


class _Painter:
    """Draws one clip's frames, holding what one frame passes to the next."""

    def __init__(self, clip: Clip, style: Style, plan: _Plan) -> None:
        first = clip.pictures[0]
        self.size = (first.width, first.height)
        self.style, self.look, self.plan, self.clip = style, style.look, plan, clip
        self.edge = _edge_mask(*self.size, self.look)
        self.last_pointer: tuple[float, float] | None = None

    def frame(self, picture: motion.Picture, t: float) -> motion.Picture:
        base = Image.frombytes("RGB", self.size, picture.rgb)
        base, view = self._zoomed(base, t)
        art = Image.new("RGBA", self.size, (0, 0, 0, 0))
        if "pointer" in self.style.layers:
            self._pointer(art, t, view)
        shown = self._edged(base)
        shown.alpha_composite(art)
        return motion.Picture(*self.size, shown.convert("RGB").tobytes(), picture.ms)

    def _edged(self, base: Image.Image) -> Image.Image:
        alpha = self.edge * self.look.held_alpha
        rgb = np.array(_rgba(self.look.rgb, 1)[:3], dtype=np.float32)
        pixels = np.asarray(base, dtype=np.float32)
        out = pixels * (1 - alpha[..., None]) + rgb * alpha[..., None]
        return Image.fromarray(np.rint(out).astype(np.uint8), "RGB").convert("RGBA")

    def _zoomed(self, base: Image.Image, t: float
                ) -> tuple[Image.Image, tuple[float, float, float, float]]:
        """The picture pushed in on a zoom's box, and the part of the picture it shows."""
        width, height = self.size
        whole = (0.0, 0.0, float(width), float(height))
        for zoom in self.style.zooms:
            begin = float((zoom.first - self.clip.frames[0]) / self.clip.rate)
            end = float((zoom.last - self.clip.frames[0]) / self.clip.rate)
            if not begin <= t <= end:
                continue
            ease = min(1.0, (t - begin) / ZOOM_S, (end - t) / ZOOM_S)
            ease = ease * ease * (3 - 2 * ease)
            x, y, w, h = zoom.box
            x0, y0 = _shown(self.clip.box, self.clip.pictures[0], x, y)
            x1, y1 = _shown(self.clip.box, self.clip.pictures[0], x + w, y + h)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            scale = min(1.0, max((x1 - x0) / width, (y1 - y0) / height, 0.05))
            rw, rh = width * scale, height * scale
            rx = min(max(cx - rw / 2, 0.0), width - rw)
            ry = min(max(cy - rh / 2, 0.0), height - rh)
            view = (rx * ease, ry * ease, width + (rw - width) * ease,
                    height + (rh - height) * ease)
            box = (view[0], view[1], view[0] + view[2], view[1] + view[3])
            return base.resize(self.size, Image.Resampling.BICUBIC, box=box), view
        return base, whole

    def _pointer(self, art: Image.Image, t: float, view: tuple[float, float, float, float]
                 ) -> None:
        where = pointer_at(self.plan.points, t)
        if where is None:
            return
        rx, ry, rw, rh = view
        width, height = self.size

        def placed(x: float, y: float) -> tuple[float, float]:
            return (x - rx) * width / rw, (y - ry) * height / rh

        x, y = placed(*where)
        unit = max(1.0, height / 360)
        for when, px, py in self.plan.presses:
            u = (t - when) / RIPPLE_S
            if 0 <= u < 1:
                cx, cy = placed(px, py)
                r = unit * (4 + 22 * u)
                ImageDraw.Draw(art).ellipse((cx - r, cy - r, cx + r, cy + r),
                                            outline=_rgba(0xFFFFFF, 0.9 * (1 - u)),
                                            width=max(1, round(unit * 2 * (1 - u))))
        pressed = any(0 <= t - when < PRESS_S for when, _, _ in self.plan.presses)
        size = unit * (PRESSED if pressed else 1.0)
        trail = self.last_pointer
        self.last_pointer = (x, y)
        if trail is not None and math.dist(trail, (x, y)) >= BLUR_FROM_PX:
            for n in range(GHOSTS, 0, -1):
                share = n / (GHOSTS + 1)
                gx = x + (trail[0] - x) * share
                gy = y + (trail[1] - y) * share
                self._arrow(art, gx, gy, size, 0.35 * (1 - share), shadow=False)
        self._arrow(art, x, y, size, 1.0, shadow=True)

    def _arrow(self, art: Image.Image, x: float, y: float, size: float, alpha: float,
               shadow: bool) -> None:
        shape = [(x + px * size, y + py * size) for px, py in POINTER_SHAPE]
        if shadow:
            reach = math.ceil(POINTER_UNITS * size + 6 * size)
            soft = Image.new("RGBA", art.size, (0, 0, 0, 0))
            ImageDraw.Draw(soft).polygon([(px + 2 * size, py + 2 * size) for px, py in shape],
                                         fill=(0, 0, 0, round(90 * alpha)))
            area = (max(0, math.floor(x) - 2), max(0, math.floor(y) - 2),
                    min(art.width, math.floor(x) + reach), min(art.height, math.floor(y) + reach))
            if area[0] < area[2] and area[1] < area[3]:
                part = soft.crop(area).filter(ImageFilter.GaussianBlur(max(1.0, size * 1.5)))
                art.alpha_composite(part, area[:2])
        ImageDraw.Draw(art).polygon(shape, fill=_rgba(0xFFFFFF, alpha),
                                    outline=_rgba(0x000000, alpha), width=max(1, round(size)))
        tip = (round(x), round(y))
        if 0 <= tip[0] < art.width and 0 <= tip[1] < art.height:
            art.putpixel(tip, _rgba(0xFFFFFF, alpha))


STYLE = Style()


def decorate(document: Mapping[str, Any], clip: Clip, style: Style = STYLE
             ) -> list[motion.Picture]:
    """`clip`'s pictures with `style`'s layers drawn from `document`, a loaded timeline
    (`timeline.loads`); `Invalid` for a clip the timeline says nothing about."""
    if not clip.pictures or len(clip.frames) != len(clip.pictures):
        raise Invalid(f"a clip is its pictures and a frame for each; this one has "
                      f"{len(clip.pictures)} pictures and {len(clip.frames)} frames")
    if {(p.width, p.height) for p in clip.pictures} != {(clip.pictures[0].width,
                                                       clip.pictures[0].height)}:
        raise Invalid("a clip's pictures are one size")
    painter = _Painter(clip, style, _plan(document, clip))
    zero = clip.frames[0]
    return [painter.frame(picture, float((frame - zero) / clip.rate))
            for frame, picture in zip(clip.frames, clip.pictures, strict=True)]


def for_loop(document: Mapping[str, Any], starts: Sequence[int], style: Style = STYLE
             ) -> motion.Decorator:
    """What `motion.build` decorates each cut with: cut `n`'s recording shows, at its frame 0,
    the emulator frame `starts[n]`."""
    def each(n: int, numbers: Sequence[int], pictures: Sequence[motion.Picture],
             rate: Fraction, box: motion.Box) -> list[motion.Picture]:
        return decorate(document, Clip([starts[n] + k for k in numbers], pictures, box, rate),
                        style)
    return each


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scry_core.decorate",
        description="Make a demo's loop from one stretch of a recording, with the pointer "
                    "drawn in from the run's timeline.")
    parser.add_argument("recording", type=Path, help="the AVI the run wrote")
    parser.add_argument("--timeline", type=Path, required=True,
                        help="the run's <transcript>-timeline.json")
    parser.add_argument("--at", type=int, required=True,
                        help="the emulator frame the recording's first frame shows")
    parser.add_argument("--first", type=int, default=0, help="the recording's first frame shown")
    parser.add_argument("--frames", type=int, required=True, help="how many frames are shown")
    parser.add_argument("--out", type=Path, required=True, help="the loop.webp to write")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None,
         write: Callable[[str], object] = print) -> int:
    """Exit 0 with the loop written, 3 (INVALID) with why it was not."""
    args = _arguments(argv)
    try:
        try:
            text = args.timeline.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            raise Invalid(f"the timeline {args.timeline} cannot be read "
                          f"({type(e).__name__}), and a clip is decorated only from its run's "
                          "timeline") from e
        document = timeline.loads(text)
        with tempfile.TemporaryDirectory() as work:
            built = motion.build([motion.Cut(args.recording, args.first, args.frames)],
                                 Path(work), for_loop(document, [args.at], STYLE))
        try:
            args.out.write_bytes(built.data)
        except OSError as e:
            raise Invalid(f"the loop cannot be written to {args.out} "
                          f"({type(e).__name__})") from e
    except Invalid as e:
        write(f"INVALID: {e}")
        return EXIT_INVALID
    write(f"wrote {args.out}: {len(built.data)} bytes, "
          f"{'lossless' if built.lossless else 'lossy'}")
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
