"""A demo's moving picture: stretches cut from a run's recordings, assembled into one animated
WebP that loops for ever.

`build` takes the cuts in the order they play and answers the file's bytes with the milliseconds
each cut lasts. ffmpeg decodes the frames and libwebp's `img2webp` assembles them, because an
ffmpeg build may carry no WebP encoder; without either program `programs` refuses by name.

Nothing is staged: a cut is frames of the recording as they were written. Frames are dropped to
stay within `RATE_MAX` a second and each kept one lasts as long as those it stands for, so the
picture runs at the machine's speed; a capture the emulator doubled is halved back to the
machine's own pixels; equal frames in a row become one that lasts as long as all of them. Rows
and columns at the edges that are one colour, the same in every frame, are cut (a game's verb
area left empty in a cutscene), so what moves fills the width; `still` cuts the demo's picture
the same way. The frames are then written scaled up a whole number of times, each pixel a sharp
block, as far as `FIT` holds them: a README cannot ask its reader's browser for sharp pixels, so
the file has them.

Refused, as `Invalid`: more than `CUTS_MAX` cuts, one outside `CUT_SECONDS`, more than
`LOOP_SECONDS` in all, a cut past the end of its recording, a recording that does not read as an
AVI, and a file that passes `BUDGET_BYTES` both lossless and lossy.
"""

from __future__ import annotations

import math
import re
import shutil
import struct
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from scry_core import avi, png
from scry_core.verdict import Invalid

LOOP_NAME = "loop.webp"
CUTS_MAX = 3
#: The seconds one cut may last, and all of them together.
CUT_SECONDS = (1.0, 3.0)
LOOP_SECONDS = 6.0
#: Half a frame of slack at any rate a recording has, so `3 s` of 70.09 Hz is not refused.
SLACK_SECONDS = 0.02
RATE_MAX = 30
BUDGET_BYTES = 400_000
#: The width and height a loop's frames are scaled up towards and never past.
FIT = (960, 600)
LOSSY_QUALITY = 80
PROGRAMS = ("ffmpeg", "img2webp")
#: The share of a capture's frames that are whole 2x2 blocks when the emulator doubled it: a
#: frame the program redrew between two scan lines of one row is not, and is halved with the rest.
DOUBLED_SHARE = 0.9

_STRH = b"strh"
_SCALE_AT, _RATE_AT = 20, 24
_PPM_HEAD = re.compile(rb"P6\s+(\d+)\s+(\d+)\s+255\s")


@dataclass(frozen=True)
class Cut:
    """`frames` frames of the recording `source`, from its frame `first` (0 the first)."""

    source: Path
    first: int
    frames: int


@dataclass(frozen=True)
class Box:
    """The `width` x `height` pixels from (`x`, `y`) a loop keeps of its `whole` frames."""

    x: int
    y: int
    width: int
    height: int
    whole: tuple[int, int]


@dataclass(frozen=True)
class Built:
    """The loop's bytes, the milliseconds each cut lasts, whether it is lossless, and the part
    of its frames it shows."""

    data: bytes
    cut_ms: tuple[int, ...]
    lossless: bool
    kept: Box


@dataclass(frozen=True)
class Picture:
    """One frame as raw RGB, and the milliseconds it stays on screen."""

    width: int
    height: int
    rgb: bytes
    ms: int


def programs() -> dict[str, str]:
    """Where each program a loop is made with is; `Invalid` names the ones that are missing."""
    found = {name: shutil.which(name) for name in PROGRAMS}
    if missing := [name for name, path in found.items() if path is None]:
        raise Invalid(f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} not on "
                      f"PATH, and a demo's {LOOP_NAME} is made with {' and '.join(PROGRAMS)}")
    return {name: path for name, path in found.items() if path is not None}


def rate(head: bytes) -> Fraction | None:
    """The frames a second an AVI's video stream declares, or None."""
    at = head.find(_STRH)
    if at < 0 or head[at + 8:at + 12] != b"vids" or len(head) < at + 8 + _RATE_AT + 4:
        return None
    scale, per = struct.unpack_from("<II", head, at + 8 + _SCALE_AT)
    return Fraction(per, scale) if scale and per else None


def facts(source: Path) -> tuple[int, Fraction]:
    """The frames a finished recording holds and its rate; `Invalid` when it is not one."""
    try:
        data = source.read_bytes()
    except OSError as e:
        raise Invalid(f"the recording {source} cannot be read ({type(e).__name__})") from e
    header, per_second = avi.parse(data), rate(data[:avi.WITHIN])
    if header is None or per_second is None:
        raise Invalid(f"{source} does not read as an AVI with a video stream")
    return avi.count(data), per_second


def step_of(per_second: Fraction) -> int:
    """Every how many frames one is kept, so no more than `RATE_MAX` a second play."""
    return max(1, math.ceil(per_second / RATE_MAX))


def durations(frames: int, per_second: Fraction, step: int) -> list[int]:
    """The milliseconds each kept frame of a cut lasts: together, the cut's own length."""
    edges = [round(1000 * Fraction(n) / per_second) for n in (*range(0, frames, step), frames)]
    return [b - a for a, b in zip(edges, edges[1:], strict=False)]


def planned(cuts: Sequence[Cut]) -> list[tuple[Cut, Fraction, int]]:
    """Each cut with its recording's rate and the step its frames are kept at; `Invalid` when
    the cuts break a limit of the loop."""
    if not 1 <= len(cuts) <= CUTS_MAX:
        raise Invalid(f"a loop shows 1 to {CUTS_MAX} moments, and this one has {len(cuts)}")
    plan, total = [], 0.0
    for n, cut in enumerate(cuts, start=1):
        held, per_second = facts(cut.source)
        if cut.first < 0 or cut.frames < 1 or cut.first + cut.frames > held:
            raise Invalid(f"moment {n} asks frames {cut.first} to {cut.first + cut.frames - 1} "
                          f"of {cut.source}, which holds {held}")
        seconds = float(cut.frames / per_second)
        if not CUT_SECONDS[0] - SLACK_SECONDS <= seconds <= CUT_SECONDS[1] + SLACK_SECONDS:
            raise Invalid(f"moment {n} lasts {seconds:.2f} s ({cut.frames} frames at "
                          f"{float(per_second):.2f} a second), and a moment lasts "
                          f"{CUT_SECONDS[0]:g} to {CUT_SECONDS[1]:g} s")
        total += seconds
        plan.append((cut, per_second, step_of(per_second)))
    if total > LOOP_SECONDS + SLACK_SECONDS:
        raise Invalid(f"the moments last {total:.2f} s together, and a loop lasts at most "
                      f"{LOOP_SECONDS:g} s: show less")
    return plan


def lasting(cuts: Sequence[Cut]) -> tuple[int, ...]:
    """The milliseconds each cut lasts in the loop; `Invalid` as `planned` refuses."""
    return tuple(sum(durations(cut.frames, per_second, step))
                 for cut, per_second, step in planned(cuts))


def doubled(picture: Picture) -> bool:
    """Whether every pixel of the frame is a 2x2 block of one colour."""
    w, h, rgb = picture.width, picture.height, picture.rgb
    if w % 2 or h % 2:
        return False
    row = w * 3
    for y in range(0, h, 2):
        line = rgb[y * row:(y + 1) * row]
        if line != rgb[(y + 1) * row:(y + 2) * row]:
            return False
        if any(line[c::6] != line[c + 3::6] for c in range(3)):
            return False
    return True


def halved(picture: Picture) -> Picture:
    """The frame at half its size, one pixel of each 2x2 block."""
    w, h, rgb = picture.width, picture.height, picture.rgb
    row = w * 3
    lines = []
    for y in range(0, h, 2):
        line = rgb[y * row:(y + 1) * row]
        out = bytearray(row // 2)
        for c in range(3):
            out[c::3] = line[c::6]
        lines.append(bytes(out))
    return Picture(w // 2, h // 2, b"".join(lines), picture.ms)


def factor(width: int, height: int) -> int:
    """The whole number of times a frame of this size is scaled up: the most that stays within
    `FIT`, and 1 for a frame already past half of it."""
    return max(1, min(FIT[0] // width, FIT[1] // height))


def scaled(picture: Picture, times: int) -> Picture:
    """The frame with each pixel a `times` x `times` block of its colour."""
    if times == 1:
        return picture
    w, rgb = picture.width, picture.rgb
    row = w * 3
    lines = []
    for y in range(picture.height):
        line = rgb[y * row:(y + 1) * row]
        out = bytearray(row * times)
        for n in range(times):
            for c in range(3):
                out[n * 3 + c::3 * times] = line[c::3]
        lines.append(bytes(out) * times)
    return Picture(w * times, picture.height * times, b"".join(lines), picture.ms)


def kept(pictures: Sequence[Picture]) -> Box:
    """The part of the frames left once every edge row, then every edge column of what is left,
    that is one colour, the same in every frame, is cut; frames that would leave nothing are kept
    whole."""
    width, height = pictures[0].width, pictures[0].height

    def solid(pixels: Sequence[bytes]) -> bytes | None:
        first = pixels[0][:3]
        return first if all(row == first * (len(row) // 3) for row in pixels) else None

    def row(y: int) -> bool:
        return solid([p.rgb[y * width * 3:(y + 1) * width * 3] for p in pictures]) is not None

    top, bottom = 0, height
    while top < bottom and row(top):
        top += 1
    while bottom > top and row(bottom - 1):
        bottom -= 1

    def column(x: int) -> bool:
        return solid([b"".join(p.rgb[(y * width + x) * 3:(y * width + x + 1) * 3]
                               for y in range(top, bottom)) for p in pictures]) is not None

    left, right = 0, width
    while left < right and column(left):
        left += 1
    while right > left and column(right - 1):
        right -= 1
    if left == right:
        return Box(0, 0, width, height, (width, height))
    return Box(left, top, right - left, bottom - top, (width, height))


def cropped(picture: Picture, box: Box) -> Picture:
    if (box.width, box.height) == box.whole:
        return picture
    row = picture.width * 3
    rgb = b"".join(picture.rgb[y * row + box.x * 3:y * row + (box.x + box.width) * 3]
                   for y in range(box.y, box.y + box.height))
    return Picture(box.width, box.height, rgb, picture.ms)


def still(data: bytes, box: Box) -> bytes:
    """The demo's PNG `data` cut as its loop is, at its own scale; `Invalid` when it is not a
    whole number of times the loop's frames."""
    if (box.width, box.height) == box.whole:
        return data
    try:
        raster = png.decode(data)
    except png.NotAPicture as e:
        raise Invalid(f"the still does not read as a picture ({e})") from e
    times = raster.width // box.whole[0]
    if times < 1 or (raster.width, raster.height) != (box.whole[0] * times,
                                                       box.whole[1] * times):
        raise Invalid(f"the still is {raster.width}x{raster.height}, not a whole number of times "
                      f"the loop's {box.whole[0]}x{box.whole[1]} frames, so it cannot be cut as "
                      "the loop is")
    return png.encode(png.cropped(raster, box.x * times, box.y * times, box.width * times,
                                  box.height * times))


def merged(pictures: Sequence[Picture]) -> list[Picture]:
    """Equal frames in a row as one that lasts as long as all of them."""
    out: list[Picture] = []
    for picture in pictures:
        if out and (out[-1].width, out[-1].height, out[-1].rgb) == (
                picture.width, picture.height, picture.rgb):
            out[-1] = Picture(picture.width, picture.height, picture.rgb,
                              out[-1].ms + picture.ms)
        else:
            out.append(picture)
    return out


def read_ppm(data: bytes) -> tuple[int, int, bytes]:
    """A binary PPM's width, height and RGB bytes; `Invalid` for anything else."""
    head = _PPM_HEAD.match(data)
    if head is None:
        raise Invalid("ffmpeg wrote a frame that is not an 8-bit binary PPM")
    width, height = int(head[1]), int(head[2])
    rgb = data[head.end():]
    if len(rgb) != width * height * 3:
        raise Invalid(f"a {width}x{height} frame holds {len(rgb)} bytes of pixels")
    return width, height, rgb


def ppm(picture: Picture) -> bytes:
    return b"P6\n%d %d\n255\n" % (picture.width, picture.height) + picture.rgb


def _said(done: subprocess.CompletedProcess[str]) -> str:
    lines = done.stderr.strip().splitlines()
    return lines[-1] if lines else "no words"


def _frames(ffmpeg: str, cut: Cut, per_second: Fraction, step: int, work: Path) -> list[Picture]:
    """The kept frames of `cut`, decoded into `work` and read back."""
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("*.ppm"):
        old.unlink()
    last = cut.first + cut.frames - 1
    picked = f"select='between(n,{cut.first},{last})*not(mod(n-{cut.first},{step}))'"
    done = subprocess.run([ffmpeg, "-v", "error", "-i", str(cut.source), "-vf", picked,
                           "-fps_mode", "passthrough", "-pix_fmt", "rgb24",
                           str(work / "%05d.ppm")], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Invalid(f"ffmpeg refused to decode {cut.source} (exit {done.returncode}): "
                      f"{_said(done)}")
    files = sorted(work.glob("*.ppm"))
    lasting = durations(cut.frames, per_second, step)
    if len(files) != len(lasting):
        raise Invalid(f"ffmpeg decoded {len(files)} frames of {cut.source} where frames "
                      f"{cut.first} to {last}, one in {step}, are {len(lasting)}")
    return [Picture(*read_ppm(file.read_bytes()), ms) for file, ms in
            zip(files, lasting, strict=True)]


def _assembled(img2webp: str, pictures: Sequence[Picture], work: Path, lossless: bool,
               times: int) -> bytes:
    """`pictures`, each scaled up `times`, as one animated WebP written in `work` and read
    back."""
    work.mkdir(parents=True, exist_ok=True)
    out = work / LOOP_NAME
    argv = [img2webp, "-loop", "0", "-min_size"]
    for n, picture in enumerate(pictures):
        file = work / f"frame-{n:05d}.ppm"
        file.write_bytes(ppm(scaled(picture, times)))
        argv += ["-lossless"] if lossless else ["-lossy", "-q", str(LOSSY_QUALITY)]
        argv += ["-d", str(picture.ms), str(file)]
    done = subprocess.run([*argv, "-o", str(out)], capture_output=True, text=True, check=False)
    if done.returncode != 0 or not out.is_file():
        raise Invalid(f"img2webp refused to assemble the loop (exit {done.returncode}): "
                      f"{_said(done)}")
    return out.read_bytes()


def build(cuts: Sequence[Cut], work: Path) -> Built:
    """The loop of `cuts`, made in `work`: lossless where it fits `BUDGET_BYTES`, else lossy,
    else `Invalid` naming its bytes."""
    plan = planned(cuts)
    found = programs()
    per_cut = [_frames(found["ffmpeg"], cut, per_second, step, work / f"cut-{n}")
               for n, (cut, per_second, step) in enumerate(plan, start=1)]
    cut_ms = tuple(sum(picture.ms for picture in pictures) for pictures in per_cut)
    pictures = [picture for group in per_cut for picture in group]
    if sum(doubled(picture) for picture in pictures) >= DOUBLED_SHARE * len(pictures):
        pictures = [halved(picture) for picture in pictures]
    if sizes := {(p.width, p.height) for p in pictures} - {(pictures[0].width,
                                                            pictures[0].height)}:
        raise Invalid(f"the moments are not one size: {pictures[0].width}x{pictures[0].height} "
                      f"and {sorted(sizes)}; a loop shows one video mode")
    pictures = merged(pictures)
    box = kept(pictures)
    pictures = merged([cropped(picture, box) for picture in pictures])
    times = factor(box.width, box.height)
    weighed = []
    for lossless in (True, False):
        data = _assembled(found["img2webp"], pictures, work / "webp", lossless, times)
        if len(data) <= BUDGET_BYTES:
            return Built(data, cut_ms, lossless, box)
        weighed.append(f"{len(data)} bytes {'lossless' if lossless else 'lossy'}")
    raise Invalid(f"the loop is {' and '.join(weighed)}, past the {BUDGET_BYTES}-byte budget: "
                  "show less")
