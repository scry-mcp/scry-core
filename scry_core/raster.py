"""Crop, signature, difference and match measures over a picture.

The signature is shared by both servers: BLAKE2b with an 8-byte digest, 16 lowercase hex
characters (a string, because a JSON integer past 2^53 loses digits in JavaScript), over
`scry-sig/1|<kind>|<w>x<h>|` and then the crop's cells row by row, `w` and `h` being the crop's.
A cell is its resolved colour (a text cell: its CP437 byte plus foreground and background RGB),
so a palette change changes the signature. An `index` cell is a pixel's palette index instead,
three bytes little-endian (`index_cells`): a screen known by what the program drew, whatever
palette shows it.

A crop is `[x, y, width, height]` inside the picture, width and height at least one; one that
leaves the picture is refused, never padded.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from scry_core.judges import Rect, rect
from scry_core.png import Raster
from scry_core.reply_contract import Invalid, unavailable

Kind = Literal["pixel", "text", "index"]
#: Bytes per cell: RGB; a CP437 byte and two RGB; a palette index.
CELL_BYTES: dict[str, int] = {"pixel": 3, "text": 7, "index": 3}
SIGNATURE_TAG = b"scry-sig/1"
SIGNATURE_BYTES = 8

def inside(crop: Sequence[int] | None, width: int, height: int, what: str = "the picture",
           name: str = "crop") -> Rect:
    """The rectangle `crop` names (the whole picture when None); one that leaves it is refused."""
    if crop is None:
        return 0, 0, width, height
    x, y, w, h = rect(name, crop)
    if x + w > width or y + h > height:
        raise Invalid("bad_argument", f"{name} [{x}, {y}] + {w}x{h} leaves {what}, which is "
                      f"{width}x{height}; a crop is never padded")
    return x, y, w, h


def rgb(raster: Raster) -> bytes:
    """`raster`'s pixels as RGB triplets, resolving any palette."""
    if raster.palette is None:
        return raster.pixels
    lut = [bytes(c) for c in raster.palette]
    return b"".join(lut[i] for i in raster.pixels)


def index_cells(indices: Iterable[int]) -> bytes:
    """Palette indices as `index` cells; one outside three bytes is refused, never wrapped."""
    try:
        return b"".join(i.to_bytes(3, "little") for i in indices)
    except OverflowError:
        raise Invalid("unexpected_answer", "a palette index outside 0..2^24-1 cannot be an "
                      "`index` cell") from None


def cells_of(cells: bytes, width: int, cell: int, area: Rect) -> bytes:
    """The cells of `area`, row by row, out of `cells` `width` to a row."""
    x, y, w, h = area
    stride = width * cell
    return b"".join(cells[(y + r) * stride + x * cell:(y + r) * stride + (x + w) * cell]
                    for r in range(h))


def signature(kind: Kind, width: int, height: int, cells: bytes,
              crop: Sequence[int] | None = None) -> str:
    """The signature of the `crop` of `kind` cells; a wrong `cells` length is ValueError."""
    size = CELL_BYTES[kind]
    if len(cells) != width * height * size:
        raise ValueError(f"{width}x{height} {kind} cells are {width * height * size} bytes; got "
                         f"{len(cells)}")
    area = inside(crop, width, height)
    digest = hashlib.blake2b(digest_size=SIGNATURE_BYTES)
    digest.update(b"%s|%s|%dx%d|" % (SIGNATURE_TAG, kind.encode(), area[2], area[3]))
    digest.update(cells_of(cells, width, size, area))
    return digest.hexdigest()


def picture_signature(raster: Raster, crop: Sequence[int] | None = None) -> str:
    """The signature of a picture's pixels."""
    return signature("pixel", raster.width, raster.height, rgb(raster), crop)


def cropped(raster: Raster, crop: Sequence[int] | None) -> Raster:
    """The part of `raster` inside `crop`."""
    area = inside(crop, raster.width, raster.height)
    if area == (0, 0, raster.width, raster.height):
        return raster
    return Raster(area[2], area[3], cells_of(raster.pixels, raster.width, raster.depth, area),
                  raster.palette)


def _enlarged(a: Raster, b: Raster) -> str:
    """The hint for one picture being the other enlarged by a whole factor."""
    for big, small, which in ((a, b, "the first is {}x the second"),
                              (b, a, "the second is {}x the first")):
        factor, rest = divmod(big.width, small.width)
        if factor > 1 and not rest and big.height == small.height * factor:
            return (f"; {which.format(factor)}, as a view's PNG is enlarged by its `scale`: ask "
                    "the view at `scale=1`")
    return ""


def diff(a: Raster, b: Raster, crop: Sequence[int] | None = None,
         shift: Sequence[int] = (0, 0), tolerance: int = 0) -> dict[str, Any]:
    """`a` against `b` shifted by `shift`, within `crop`; a channel within `tolerance` is equal.
    Answers `differing_pixels`, `bbox` (`[x, y, w, h]` in `a`'s coordinates), `max_delta` per
    channel and `compared`, the rectangle of `a` compared."""
    if crop is None and (a.width, a.height) != (b.width, b.height):
        raise Invalid("bad_argument", f"the pictures are {a.width}x{a.height} and "
                      f"{b.width}x{b.height}: name a `crop` that lies inside both"
                      + _enlarged(a, b))
    x0, y0, w, h = inside(crop, a.width, a.height, "the first picture")
    inside(crop, b.width, b.height, "the second picture")
    dx, dy = shift
    left, top = max(x0, x0 - dx), max(y0, y0 - dy)
    right, bottom = min(x0 + w, x0 + w - dx), min(y0 + h, y0 + h - dy)
    if right <= left or bottom <= top:
        raise Invalid("bad_argument", f"shift [{dx}, {dy}] moves the {w}x{h} crop wholly off "
                      "itself: nothing is left to compare")
    pa, pb = rgb(a), rgb(b)
    differing, peak = 0, [0, 0, 0]
    # Edges kept as the scan goes: a list of every differing pixel would be a picture's worth.
    x_lo, y_lo, x_hi, y_hi = right, bottom, left - 1, top - 1
    for y in range(top, bottom):
        ra = (y * a.width) * 3
        rb = ((y + dy) * b.width + dx) * 3
        row_a = pa[ra + left * 3:ra + right * 3]
        row_b = pb[rb + left * 3:rb + right * 3]
        if row_a == row_b:
            continue
        for i in range(0, len(row_a), 3):
            deltas = [abs(row_a[i + c] - row_b[i + c]) for c in range(3)]
            for c in range(3):
                peak[c] = max(peak[c], deltas[c])
            if max(deltas) > tolerance:
                differing += 1
                x = left + i // 3
                x_lo, x_hi = min(x_lo, x), max(x_hi, x)
                y_lo, y_hi = min(y_lo, y), max(y_hi, y)
    bbox = ([x_lo, y_lo, x_hi - x_lo + 1, y_hi - y_lo + 1] if differing
            else unavailable("no pixel differs"))
    return {"differing_pixels": differing, "bbox": bbox, "max_delta": peak,
            "compared": [left, top, right - left, bottom - top]}


def changed_pixels(previous: Raster, current: Raster, crop: Sequence[int] | None = None) -> int:
    """How many pixels of `crop` differ between two same-size pictures."""
    return int(diff(previous, current, crop)["differing_pixels"])


def match_fraction(raster: Raster, ref: Raster, crop: Sequence[int] | None = None) -> float:
    """The fraction of `crop`'s pixels equal to `ref`."""
    area = inside(crop, raster.width, raster.height)
    if (ref.width, ref.height) != area[2:]:
        raise Invalid("bad_argument", f"`ref` is {ref.width}x{ref.height} and the crop is "
                      f"{area[2]}x{area[3]}: a reference is a picture of the crop's size")
    part = rgb(cropped(raster, area))
    want = rgb(ref)
    same = sum(part[i:i + 3] == want[i:i + 3] for i in range(0, len(part), 3))
    return same / (area[2] * area[3])
