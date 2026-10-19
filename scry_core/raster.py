"""What a picture is compared by: its crop, its signature, its difference from another, and the
measures a region is tracked by. No emulator here: a server hands in cells or a decoded PNG.

ONE SIGNATURE for both servers, so "is it the same screen" has one answer whoever asks and a
number can be cached or documented once. It is BLAKE2b with an 8-byte digest, written as 16
lowercase hex characters (a string, because a JSON integer past 2^53 loses digits in a JavaScript
client), over `scry-sig/1|<kind>|<w>x<h>|` and then the cells of the crop, row by row, where `w`
and `h` are the crop's: the signature says what a region shows, wherever it sits. A cell is its
RESOLVED colour, never an index: a pixel is its RGB triplet; a text cell is its code page 437
byte and the RGB its attribute gives the foreground and the background. So a palette change is a
signature change, and two screens that look the same have one signature.

A CROP is `[x, y, width, height]` inside the picture, width and height at least one. One that
leaves the picture is refused, never padded: a padded crop compares pixels nobody drew.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, Literal

from scry_core.judges import Rect, rect
from scry_core.png import Raster
from scry_core.reply_contract import Invalid, unavailable

Kind = Literal["pixel", "text"]
#: Bytes a cell of each kind: an RGB triplet; a CP437 byte and two triplets.
CELL_BYTES: dict[str, int] = {"pixel": 3, "text": 7}
SIGNATURE_TAG = b"scry-sig/1"
SIGNATURE_BYTES = 8

def inside(crop: Sequence[int] | None, width: int, height: int, what: str = "the picture",
           name: str = "crop") -> Rect:
    """The rectangle `crop` names (the whole `width` x `height` when None), judged to lie inside
    it: one that leaves is refused with the size, never padded."""
    if crop is None:
        return 0, 0, width, height
    x, y, w, h = rect(name, crop)
    if x + w > width or y + h > height:
        raise Invalid("bad_argument", f"{name} [{x}, {y}] + {w}x{h} leaves {what}, which is "
                      f"{width}x{height}; a crop is never padded")
    return x, y, w, h


def rgb(raster: Raster) -> bytes:
    """`raster`'s pixels as RGB triplets, an indexed one resolved through its palette."""
    if raster.palette is None:
        return raster.pixels
    lut = [bytes(c) for c in raster.palette]
    return b"".join(lut[i] for i in raster.pixels)


def cells_of(cells: bytes, width: int, cell: int, area: Rect) -> bytes:
    """The cells of `area`, row by row, out of `cells` laid `width` cells to a row."""
    x, y, w, h = area
    stride = width * cell
    return b"".join(cells[(y + r) * stride + x * cell:(y + r) * stride + (x + w) * cell]
                    for r in range(h))


def signature(kind: Kind, width: int, height: int, cells: bytes,
              crop: Sequence[int] | None = None) -> str:
    """The signature of the `crop` of a `width` x `height` grid of `kind` cells (the module
    docstring says what is hashed). `cells` of the wrong length is the server's bug."""
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
    """The signature of a picture's pixels, resolved: the same number the screen it shows has."""
    return signature("pixel", raster.width, raster.height, rgb(raster), crop)


def cropped(raster: Raster, crop: Sequence[int] | None) -> Raster:
    """The part of `raster` inside `crop`, keeping its palette."""
    area = inside(crop, raster.width, raster.height)
    if area == (0, 0, raster.width, raster.height):
        return raster
    return Raster(area[2], area[3], cells_of(raster.pixels, raster.width, raster.depth, area),
                  raster.palette)


def _enlarged(a: Raster, b: Raster) -> str:
    """What to say when one picture is the other's size times a whole factor: a view's PNG is
    enlarged by its `scale`, and a crop of it would compare a corner of the enlargement."""
    for big, small, which in ((a, b, "the first is {}x the second"),
                              (b, a, "the second is {}x the first")):
        factor, rest = divmod(big.width, small.width)
        if factor > 1 and not rest and big.height == small.height * factor:
            return (f"; {which.format(factor)}, as a view's PNG is enlarged by its `scale`: ask "
                    "the view at `scale=1`")
    return ""


def diff(a: Raster, b: Raster, crop: Sequence[int] | None = None,
         shift: Sequence[int] = (0, 0), tolerance: int = 0) -> dict[str, Any]:
    """`a` against `b`: pixel (x, y) of `a` against (x + dx, y + dy) of `b`, over the part of
    `crop` (on both pictures) where both lie inside it; a channel within `tolerance` counts as
    equal. Answers `differing_pixels`, `bbox` (`[x, y, w, h]` in `a`'s coordinates, unavailable
    when none differ), `max_delta` per channel, and `compared`, the rectangle of `a` compared."""
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
    # The box's edges, kept as the scan goes: a list of every differing pixel would be the
    # whole picture's worth of ints for one rectangle.
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
    """How many pixels of `crop` differ between two pictures of one size."""
    return int(diff(previous, current, crop)["differing_pixels"])


def match_fraction(raster: Raster, ref: Raster, crop: Sequence[int] | None = None) -> float:
    """The fraction of `crop`'s pixels equal to `ref`, a picture of the crop's size."""
    area = inside(crop, raster.width, raster.height)
    if (ref.width, ref.height) != area[2:]:
        raise Invalid("bad_argument", f"`ref` is {ref.width}x{ref.height} and the crop is "
                      f"{area[2]}x{area[3]}: a reference is a picture of the crop's size")
    part = rgb(cropped(raster, area))
    want = rgb(ref)
    same = sum(part[i:i + 3] == want[i:i + 3] for i in range(0, len(part), 3))
    return same / (area[2] * area[3])
