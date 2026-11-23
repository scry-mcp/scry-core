"""A demo's clip with the presence layers drawn in, from the run's timeline (`timeline`) and the
frames alone: the edge, the pointer, the keycaps and the call captions, by the rules the live
overlay follows (`overlay_timeline`, `presence.Look`) and richer than an emulator draws them.
Only this module imports Pillow and numpy, the `decorate` extra.

Honest to the run: a frame shows only what its call and its input were. The pointer is drawn
from its first real position on, passes through every position the server sent at the frame it
was sent (of two sent at one frame, the later), and only the path between two of them is eased:
a slight curve and an overshoot that settles before it arrives. A button's press is a ripple and
a brief squeeze of the pointer on its frame. A recording holds only frames the machine ran, so
no frame of a clip is one the session held stopped, and the pause layer has nothing to mark.

The clock is the clip's own: an emulator frame is `1 / rate` seconds, and a call is captioned
from the frame it began at. A call that ran no frame (a read, a stop) is captioned at the frame
it was made on, so the captions' repeat and hold (`overlay_timeline.Captions`) are reckoned in
the clip's seconds. A caption too wide for its band scrolls a whole travel inside the span of
its own call, so a long text is read in full, never cut and never left half-read. Calls are read
from the last rewind of the machine (a state load) before the clip, because frames before it are
no longer this clip's. A demo's camera is
not work the demo does: a `record` step is not captioned, and its cut shows only what the
machine runs.

Deterministic: no clock, no randomness, a bitmap font, so a clip decorated twice is the same
pixels. `python -m scry_core.decorate` makes one decorated loop from a recording.
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
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from scry_core import motion, placement, timeline
from scry_core import overlay as ov
from scry_core import overlay_timeline as tl
from scry_core.demo import RECORD_TOOL
from scry_core.presence import LOOK, Look, mark_of
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
CAPTION_IN_S = 0.15
ZOOM_S = 0.8
#: Display pixels per bitmap-font pixel, per this many display rows.
ROWS_PER_SCALE = 240
SINE_AMPLITUDE = 0.25
SINE_WAVES = 1.5
SINE_HZ = 0.8
RASTER_HZ = 0.5
POINTER_SHAPE = ((0, 0), (0, 16), (4, 12), (7, 19), (10, 18), (7, 11), (12, 11))
POINTER_UNITS = 19
#: The tool that is a demo's camera rather than work it does: its calls are not captioned.
CAMERA_TOOLS = (RECORD_TOOL,)


@dataclass(frozen=True)
class Zoom:
    """A push in on `box` (x, y, width, height in the guest's pixels) from emulator frame
    `first` to `last`, eased in and out over `ZOOM_S`."""

    first: int
    last: int
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class Style:
    """What a demo draws: `layers` as `overlay.Overlay.asked` names them, less those its server
    cannot draw (MAME's pointer), `place`, the band the captions take (the keycaps take the other
    edge), the live overlay's `look`, and the flourishes a demo may ask for: a sine scroller, a
    raster bar behind the captions, a zoom."""

    layers: tuple[ov.Layer, ...] = ov.OVERLAY.asked()
    place: placement.Band = "bottom"
    look: Look = LOOK
    sine: bool = False
    raster: bool = False
    zooms: tuple[Zoom, ...] = ()

    @classmethod
    def of(cls, overlay: ov.Overlay, lacking: Sequence[ov.Layer] = (), **flourishes: Any
           ) -> Style:
        """The style of `overlay`, a game's `.scry/` profile or a demo's own, less `lacking`.
        The band does not move, so an overlay that asks for `auto` gets `bottom`."""
        return cls(tuple(layer for layer in overlay.asked() if layer not in lacking),
                   "top" if overlay.place == "top" else "bottom", **flourishes)


@dataclass(frozen=True)
class Clip:
    """Pictures as shown, each with the emulator frame it is; `box` is the part of the guest's
    picture they show, and the guest's frames a second is `rate`."""

    frames: Sequence[int]
    pictures: Sequence[motion.Picture]
    box: motion.Box
    rate: Fraction


@dataclass(frozen=True)
class _Call:
    tool: str
    text: str
    tint: tl.Kind
    begin: float
    end: float
    camera: bool = False


@dataclass
class _Plan:
    """What the clip's timeline says, in the clip's seconds."""

    calls: list[_Call] = field(default_factory=list)
    #: Keys and pointer buttons, as the top row draws them, in the order they went down or up.
    marks: list[tuple[float, str, bool]] = field(default_factory=list)
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
    """The frames a call ran from and to; a rewind ran none, at the frame it left the machine."""
    before, after = call["before"], call["after"]
    return (after, after) if after < before else (before, after)


def _span(calls: Sequence[Mapping[str, Any]], frames: tuple[int, int]) -> list[Mapping[str, Any]]:
    """The calls a clip of `frames` (first, last) may show: from the last rewind before the last
    call that reaches into the clip, up to that call."""
    first, last = frames
    counted = [call for call in calls if call["before"] is not None]
    reaching = [n for n, call in enumerate(counted)
                if _ran(call)[0] <= last and _ran(call)[1] >= first]
    if not reaching:
        raise Invalid(f"the timeline names no call over frames {first} to {last}, so nothing "
                      "says what the clip shows")
    end = begin = reaching[-1]
    while begin > 0 and counted[begin]["after"] >= counted[begin]["before"] \
            and counted[begin - 1]["after"] <= counted[begin]["before"]:
        begin -= 1
    return counted[begin:end + 1]


def _plan(document: Mapping[str, Any], clip: Clip) -> _Plan:
    zero = clip.frames[0]

    def at(frame: int) -> float:
        return float((frame - zero) / clip.rate)

    plan = _Plan()
    pressed: list[float] = []
    for call in _span(document["calls"], (min(clip.frames), max(clip.frames))):
        began, ended = _ran(call)
        plan.calls.append(_Call(call["tool"], call["caption"]["text"], call["caption"]["tint"],
                                at(began), at(ended), call["tool"] in CAMERA_TOOLS))
        for event in call["events"]:
            when = at(event["frame"])
            if event["kind"] == "key":
                plan.marks.append((when, event["name"], event["down"]))
            elif event["kind"] == "pointer":
                x, y = _shown(clip.box, clip.pictures[0], event["x"], event["y"])
                plan.points = [p for p in plan.points if p[0] < when] + [(when, x, y)]
            elif event["kind"] == "button":
                plan.marks.append((when, mark_of(event["name"]), event["down"]))
                if event["down"]:
                    pressed.append(when)
    for when in pressed:
        if (where := pointer_at(plan.points, when)) is not None:
            plan.presses.append((when, *where))
    return plan


def _shown(box: motion.Box, picture: motion.Picture, x: int, y: int) -> tuple[float, float]:
    """A guest pixel's centre in the shown picture."""
    return ((x - box.x + 0.5) * picture.width / box.width,
            (y - box.y + 0.5) * picture.height / box.height)


class _Font:
    """The bitmap font Pillow carries, each pixel a `scale` x `scale` block."""

    def __init__(self, scale: int) -> None:
        self.scale = scale
        self._font = ImageFont.load_default_imagefont()
        box = self._font.getbbox("M")
        self.width, self.height = int(box[2]) * scale, int(box[3]) * scale
        self._masks: dict[str, Image.Image] = {}

    def mask(self, text: str) -> Image.Image:
        """`text`'s pixels; a character the font has no glyph for is `?`."""
        text = "".join(c if " " <= c <= "~" else "?" for c in text)
        if text not in self._masks:
            small = Image.new("L", (max(1, len(text)) * self.width // self.scale,
                                    self.height // self.scale))
            ImageDraw.Draw(small).text((0, 0), text, fill=255, font=self._font)
            self._masks[text] = small.resize((small.width * self.scale,
                                              small.height * self.scale), Image.Resampling.NEAREST)
        return self._masks[text]


def _scroll_px_s(travel: int, span_s: float | None, cps_px_s: float) -> float:
    """The pixels a second a caption wider than its band moves: one full travel (`room + wide`)
    inside the span of its own call when that span is known and not empty, else the speed
    `scroll_cps` names, so a text too long for its band is scrolled whole, never cut."""
    return travel / span_s if span_s else cps_px_s


def _rgba(rgb: int, alpha: float) -> tuple[int, int, int, int]:
    return ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF,
            round(255 * max(0.0, min(1.0, alpha))))


def _stamp(layer: Image.Image, mask: Image.Image, rgba: tuple[int, int, int, int],
           at: tuple[int, int]) -> None:
    """`mask` painted in `rgba` into the full-size `layer` at `at`, clipped at its sides."""
    layer.paste(Image.new("RGBA", mask.size, rgba), at, mask)


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
        self.font = _Font(max(1, first.height // ROWS_PER_SCALE))
        self.edge = _edge_mask(*self.size, self.look)
        self.captions = tl.Captions(self.look.tints, self.look.caption_hold_s)
        self.keycaps = tl.Keycaps(self.look.keycap_min_s)
        self.fed_calls, self.fed_marks, self.ended = 0, 0, 0
        self.pending_ends: list[float] = []
        self.band: placement.Band = style.place
        self.serial, self.serial_at = 0, 0.0
        self.last_pointer: tuple[float, float] | None = None

    def frame(self, picture: motion.Picture, t: float) -> motion.Picture:
        base = Image.frombytes("RGB", self.size, picture.rgb)
        base, view = self._zoomed(base, t)
        self._feed(t)
        art = Image.new("RGBA", self.size, (0, 0, 0, 0))
        if "calls" in self.style.layers:
            self._caption(art, t)
        if "keys" in self.style.layers:
            self._keycaps(art, t)
        if "pointer" in self.style.layers:
            self._pointer(art, t, view)
        shown = self._edged(base, t)
        shown.alpha_composite(art)
        return motion.Picture(*self.size, shown.convert("RGB").tobytes(), picture.ms)

    def _feed(self, t: float) -> None:
        calls = self.plan.calls
        while True:
            due_end = min(self.pending_ends, default=math.inf)
            due_call = calls[self.fed_calls].begin if self.fed_calls < len(calls) else math.inf
            if min(due_end, due_call) > t:
                break
            if due_end <= due_call:
                self.pending_ends.remove(due_end)
                call = calls[self.ended]
                self.ended += 1
                if not call.camera:
                    self.captions.ended(False, call.tint == "refused", due_end)
            else:
                call = calls[self.fed_calls]
                self.fed_calls += 1
                if not call.camera:
                    self.captions.began(call.tool, {}, call.tint == "read", False, call.begin,
                                        text=call.text, span=call.end - call.begin)
                self.pending_ends.append(call.end)
        while self.fed_marks < len(self.plan.marks) and self.plan.marks[self.fed_marks][0] <= t:
            when, name, down = self.plan.marks[self.fed_marks]
            self.fed_marks += 1
            (self.keycaps.down if down else self.keycaps.up)(name, when)

    def _acting(self, t: float) -> float:
        """The edge's alpha: bright while a call that is not a read runs, fading back after."""
        look, ended = self.look, -math.inf
        for call in self.plan.calls:
            if call.tint == "read" or call.end <= call.begin or call.begin > t:
                continue
            if t < call.end:
                return look.acting_alpha
            ended = max(ended, call.end)
        faded = (t - ended) / look.fade_s
        return look.held_alpha + (look.acting_alpha - look.held_alpha) * max(0.0, 1 - faded)

    def _edged(self, base: Image.Image, t: float) -> Image.Image:
        alpha = self.edge * self._acting(t)
        rgb = np.array(_rgba(self.look.rgb, 1)[:3], dtype=np.float32)
        pixels = np.asarray(base, dtype=np.float32)
        out = pixels * (1 - alpha[..., None]) + rgb * alpha[..., None]
        return Image.fromarray(np.rint(out).astype(np.uint8), "RGB").convert("RGBA")

    def _band_box(self) -> tuple[int, int, int, int]:
        width, height = self.size
        tall = self.font.height + 2 * self.font.scale * 2
        margin = max(self.font.scale * 2, round(self.look.edge * min(width, height)))
        y = margin if self.band == "top" else height - margin - tall
        return margin, y, width - margin, y + tall

    def _caption(self, art: Image.Image, t: float) -> None:
        caption = self.captions.shown(t)
        if caption is None:
            return
        if caption.serial != self.serial:
            self.serial, self.serial_at = caption.serial, t
        fade = min(1.0, (t - self.serial_at) / CAPTION_IN_S)
        left, top, right, bottom = self._band_box()
        draw = ImageDraw.Draw(art)
        if self.style.raster:
            self._raster(draw, (left, top, right, bottom), caption.rgb, t, fade)
        else:
            draw.rectangle((left, top, right - 1, bottom - 1),
                           fill=_rgba(caption.rgb, self.look.caption_alpha * fade))
        room = right - left - 2 * self.font.width
        wide = len(caption.text) * self.font.width
        y = top + (bottom - top - self.font.height) // 2
        colour = _rgba(self.look.caption_text_rgb, fade)
        if wide <= room:
            x0 = left + (right - left - wide) / 2
        else:
            speed = _scroll_px_s(room + wide, caption.span,
                                 self.look.scroll_cps * self.font.width)
            travel = (t - self.serial_at) * speed % (room + wide)
            x0 = left + self.font.width + room - travel
        text = Image.new("RGBA", self.size, (0, 0, 0, 0))
        for n, char in enumerate(caption.text):
            x = round(x0 + n * self.font.width)
            if x + self.font.width < left or x > right or char == " ":
                continue
            lift = 0
            if self.style.sine:
                phase = 2 * math.pi * (SINE_WAVES * x / self.size[0] + SINE_HZ * t)
                lift = round(SINE_AMPLITUDE * self.font.height * math.sin(phase))
            _stamp(text, self.font.mask(char), colour, (x, y + lift))
        inside = Image.new("L", self.size, 0)
        ImageDraw.Draw(inside).rectangle((left, 0 if self.style.sine else top, right - 1,
                                          self.size[1] if self.style.sine else bottom - 1),
                                         fill=255)
        text.putalpha(Image.fromarray(
            np.minimum(np.asarray(text.getchannel("A")), np.asarray(inside)), "L"))
        art.alpha_composite(text)

    def _raster(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], rgb: int,
                t: float, fade: float) -> None:
        """A copper bar: the tint brightest along a line that sweeps the band, row by row."""
        left, top, right, bottom = box
        tall = bottom - top
        centre = (0.5 + 0.5 * math.sin(2 * math.pi * RASTER_HZ * t)) * (tall - 1)
        for row in range(tall):
            light = 1 - abs(row - centre) / tall
            r, g, b, _ = _rgba(rgb, 1)
            shade = (round(r * light), round(g * light), round(b * light))
            draw.line((left, top + row, right - 1, top + row),
                      fill=(*shade, round(255 * self.look.caption_alpha * fade)))

    def _keycap_boxes(self, names: Sequence[str]
                      ) -> list[tuple[str, tuple[int, int, int, int]]]:
        """Where each held key's mark goes: on the edge the caption band does not use, never
        over the band and never over another mark. When the row is full the oldest marks make
        room, so the key being pressed is always the one shown."""
        width, height = self.size
        left, top, right, bottom = self._band_box()
        pad = self.font.scale * 2
        tall = self.font.height + 2 * pad
        margin = left
        y = (height - margin - tall) if self.band == "top" else margin
        out: list[tuple[str, tuple[int, int, int, int]]] = []
        x = left
        for name in reversed(names):
            wide = len(name) * self.font.width + 2 * pad
            if x + wide > right:
                break
            out.append((name, (x, y, x + wide, y + tall)))
            x += wide + pad
        return out

    def _keycaps(self, art: Image.Image, t: float) -> None:
        shown = self.keycaps.shown(t)
        if not shown:
            return
        boxes = self._keycap_boxes(list(shown))
        if not boxes:
            return
        pad = self.font.scale * 2
        caps = Image.new("RGBA", self.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(caps)
        for name, (x0, y0, x1, y1) in boxes:
            draw.rounded_rectangle((x0, y0, x1, y1), radius=pad * 2,
                                   fill=_rgba(self.look.keycap_rgb, self.look.keycap_alpha),
                                   outline=_rgba(self.look.keycap_text_rgb, 0.5), width=1)
            _stamp(caps, self.font.mask(name), _rgba(self.look.keycap_text_rgb, 1),
                   (x0 + pad, y0 + pad))
        art.alpha_composite(caps)

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
        description="Make a demo's loop from one stretch of a recording, with the presence "
                    "layers drawn in from the run's timeline.")
    parser.add_argument("recording", type=Path, help="the AVI the run wrote")
    parser.add_argument("--timeline", type=Path, required=True,
                        help="the run's <transcript>-timeline.json")
    parser.add_argument("--at", type=int, required=True,
                        help="the emulator frame the recording's first frame shows")
    parser.add_argument("--first", type=int, default=0, help="the recording's first frame shown")
    parser.add_argument("--frames", type=int, required=True, help="how many frames are shown")
    parser.add_argument("--out", type=Path, required=True, help="the loop.webp to write")
    parser.add_argument("--place", choices=("top", "bottom"), default="bottom",
                        help="the band the captions take; the keycaps take the other edge")
    parser.add_argument("--without", action="append", default=[],
                        choices=("calls", "keys", "pointer", "pause"),
                        help="a layer not drawn; repeat for more")
    parser.add_argument("--sine", action="store_true", help="the captions as a sine scroller")
    parser.add_argument("--raster", action="store_true", help="a raster bar behind the captions")
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
        asked = ov.Overlay.model_validate({**{layer: False for layer in args.without},
                                           "place": args.place})
        style = Style.of(asked, sine=args.sine, raster=args.raster)
        document = timeline.loads(text)
        with tempfile.TemporaryDirectory() as work:
            built = motion.build([motion.Cut(args.recording, args.first, args.frames)],
                                 Path(work), for_loop(document, [args.at], style))
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
