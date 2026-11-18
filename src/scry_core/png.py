"""One stdlib PNG codec for both servers: indexed or RGB, a transparent index, APNG, enlargement, a
decoder.

No Pillow: the indexed form keeps the palette index of every pixel in the file, so a golden
compares pens and not colours that two pens can share.

The decoder reads 8 bits a sample, no interlace, indexed (type 3) or RGB (type 2), all five row
filters, every CRC checked, the image data inflated no further than the header declares. Other
kinds are refused by name, and ancillary chunks are skipped: a `tRNS` says how a viewer draws an
index, not which index the pixel holds.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from scry_core.prose import counted

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PLTE_MAX = 256
INDEXED, RGB = 3, 2            # PNG colour types
OTHER_KINDS = {0: "greyscale", 4: "greyscale with alpha", 6: "RGB with alpha"}
_FILTER_NONE = b"\x00"
ZLIB_LEVEL = 6
#: A header claiming more pixels is refused before anything is allocated.
PIXELS_MAX = 1 << 26


class NotAPicture(ValueError):
    """A file this decoder cannot read as a picture, with what it met."""


@dataclass(frozen=True)
class Raster:
    """One byte per pixel with a `palette` of `(r, g, b)` entries, or three bytes per pixel
    without."""

    width: int
    height: int
    pixels: bytes
    palette: tuple[tuple[int, int, int], ...] | None = None

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError(f"a raster is at least 1x1; got {self.width}x{self.height}")
        need = self.width * self.height * self.depth
        if len(self.pixels) != need:
            raise ValueError(f"{self.width}x{self.height} at {counted(self.depth, 'byte')} a "
                             f"pixel is {need} bytes; got {len(self.pixels)}")
        if self.palette is not None:
            if not 1 <= len(self.palette) <= PLTE_MAX:
                raise ValueError(f"a PLTE holds 1..{PLTE_MAX} entries; got {len(self.palette)}")
            if any(len(e) != 3 or not all(0 <= c <= 255 for c in e) for e in self.palette):
                raise ValueError("a PLTE entry is (r, g, b), each 0..255")

    @property
    def depth(self) -> int:
        """Bytes a pixel: 1 for an index, 3 for RGB."""
        return 1 if self.palette is not None else 3


def enlarged(raster: Raster, factor: int) -> Raster:
    """`raster` with every pixel a `factor` x `factor` square, so an indexed picture keeps its
    indices."""
    if factor == 1:
        return raster
    depth = raster.depth
    stride = raster.width * depth
    rows = []
    for y in range(raster.height):
        row = raster.pixels[y * stride:(y + 1) * stride]
        wide = b"".join(row[x:x + depth] * factor for x in range(0, stride, depth))
        rows.append(wide * factor)
    return Raster(raster.width * factor, raster.height * factor, b"".join(rows), raster.palette)


def cropped(raster: Raster, x: int, y: int, width: int, height: int) -> Raster:
    """The `width` x `height` rectangle of `raster` from (`x`, `y`), its palette kept."""
    if x < 0 or y < 0 or x + width > raster.width or y + height > raster.height:
        raise ValueError(f"a {width}x{height} rectangle from ({x}, {y}) is not within "
                         f"{raster.width}x{raster.height}")
    if (width, height) == (raster.width, raster.height):
        return raster
    depth, stride = raster.depth, raster.width * raster.depth
    rows = [raster.pixels[row * stride + x * depth:row * stride + (x + width) * depth]
            for row in range(y, y + height)]
    return Raster(width, height, b"".join(rows), raster.palette)


def cut_from(whole: Raster, part: Raster) -> bool:
    """Whether `part` is a rectangle of `whole`, pixel for pixel under the same palette."""
    if part.palette != whole.palette or part.width > whole.width or part.height > whole.height:
        return False
    depth = whole.depth
    stride, span = whole.width * depth, part.width * depth
    rows = [whole.pixels[n * stride:(n + 1) * stride] for n in range(whole.height)]
    wanted = [part.pixels[n * span:(n + 1) * span] for n in range(part.height)]
    for top in range(whole.height - part.height + 1):
        at = rows[top].find(wanted[0])
        while at >= 0:
            if at % depth == 0 and all(rows[top + n][at:at + span] == wanted[n]
                                       for n in range(1, part.height)):
                return True
            at = rows[top].find(wanted[0], at + 1)
    return False


def encode(raster: Raster, clear: int | None = None) -> bytes:
    """The PNG file of `raster`. `clear` names one index of an indexed raster drawn fully
    transparent (a `tRNS` chunk); an index past the palette is refused."""
    if clear is not None and clear < 0:
        raise ValueError(f"clear={clear} is not an index")
    if raster.palette is not None:
        top = max(raster.pixels) if clear is None else max(max(raster.pixels), clear)
        if top >= len(raster.palette):
            raise ValueError(f"index {top} is past the {len(raster.palette)} entries of the "
                             "palette")
    elif clear is not None:
        raise ValueError("a transparent index needs an indexed raster")
    out = _head(raster)
    if clear is not None:
        out.append(_chunk(b"tRNS", b"\xff" * clear + b"\x00"))
    out += [_chunk(b"IDAT", _stream(raster)), _chunk(b"IEND", b"")]
    return b"".join(out)


def encode_animation(frames: list[Raster], delay: tuple[int, int]) -> bytes:
    """An APNG of `frames`, each shown for `delay` (numerator, denominator, in seconds), looping for
    ever. The first frame is also the still image; all frames share its size and palette."""
    if not frames:
        raise ValueError("an animation has at least one frame")
    first = frames[0]
    for f in frames[1:]:
        if (f.width, f.height, f.palette) != (first.width, first.height, first.palette):
            raise ValueError("every frame of an animation has the first one's size and palette")
    out = _head(first)
    out.append(_chunk(b"acTL", struct.pack(">II", len(frames), 0)))
    seq = 0
    for i, frame in enumerate(frames):
        out.append(_chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, frame.width, frame.height, 0,
                                               0, delay[0], delay[1], 0, 0)))
        seq += 1
        if i == 0:
            out.append(_chunk(b"IDAT", _stream(frame)))
        else:
            out.append(_chunk(b"fdAT", struct.pack(">I", seq) + _stream(frame)))
            seq += 1
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def decode(data: bytes) -> Raster:
    """The raster a PNG file holds, or `NotAPicture` saying what it met."""
    if not data.startswith(PNG_SIGNATURE):
        raise NotAPicture("not a PNG: the file does not open with the PNG signature")
    pos, header, palette = len(PNG_SIGNATURE), b"", b""
    idat: list[bytes] = []
    while True:
        if pos + 8 > len(data):
            raise NotAPicture("the file ends before its IEND chunk")
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise NotAPicture(f"the {kind!r} chunk is cut short")
        if struct.unpack(">I", crc)[0] != zlib.crc32(kind + body) & 0xFFFFFFFF:
            raise NotAPicture(f"the {kind!r} chunk fails its CRC")
        if (kind == b"IHDR") != (pos == len(PNG_SIGNATURE)):
            raise NotAPicture("IHDR is not the first chunk, or comes twice")
        pos += 12 + length
        if kind == b"IHDR":
            header = body
        elif kind == b"PLTE":
            if idat:
                raise NotAPicture("PLTE after the image data: a palette precedes it")
            palette = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if len(header) != 13:
        raise NotAPicture("no IHDR chunk of 13 bytes")
    width, height, bits, colour, _, _, interlace = struct.unpack(">IIBBBBB", header)
    if colour not in (INDEXED, RGB):
        raise NotAPicture(f"colour type {colour} ({OTHER_KINDS.get(colour, 'not a PNG type')}): "
                          "this reads indexed and RGB pictures only")
    if bits != 8:
        raise NotAPicture(f"{bits} bits a sample: this reads 8 only")
    if interlace:
        raise NotAPicture("an interlaced PNG: this reads non-interlaced ones only")
    if width < 1 or height < 1 or width * height > PIXELS_MAX:
        raise NotAPicture(f"IHDR says {width}x{height}: a picture here is at least 1x1 and at "
                          f"most {PIXELS_MAX} pixels")
    entries = None
    if colour == INDEXED:
        if not palette or len(palette) % 3 or len(palette) // 3 > PLTE_MAX:
            raise NotAPicture(f"an indexed PNG whose PLTE is {len(palette)} bytes")
        entries = tuple((palette[i], palette[i + 1], palette[i + 2])
                        for i in range(0, len(palette), 3))
    depth = 1 if colour == INDEXED else 3
    # The extra byte tells "too long" from "exact"; a small file can inflate to gigabytes.
    expected = height * (width * depth + 1)
    try:
        raw = zlib.decompressobj().decompress(b"".join(idat), expected + 1)
    except zlib.error as e:
        raise NotAPicture(f"the image data does not inflate: {e}") from None
    pixels = _unfiltered(raw, width, height, depth)
    if entries is not None and max(pixels) >= len(entries):
        raise NotAPicture(f"index {max(pixels)} is past the {len(entries)} entries of the PLTE")
    return Raster(width, height, pixels, entries)


def _unfiltered(raw: bytes, width: int, height: int, depth: int) -> bytes:
    """The rows of `raw` with each row's filter undone: None, Sub, Up, Average, Paeth."""
    stride = width * depth
    if len(raw) != height * (stride + 1):
        raise NotAPicture(f"the image data is {len(raw)} bytes where {width}x{height} needs "
                          f"{height * (stride + 1)}")
    out = bytearray()
    prior = bytearray(stride)
    for y in range(height):
        at = y * (stride + 1)
        kind, row = raw[at], bytearray(raw[at + 1:at + 1 + stride])
        if kind == 1:
            for i in range(depth, stride):
                row[i] = (row[i] + row[i - depth]) & 0xFF
        elif kind == 2:
            row = bytearray((r + p) & 0xFF for r, p in zip(row, prior, strict=True))
        elif kind == 3:
            for i in range(stride):
                left = row[i - depth] if i >= depth else 0
                row[i] = (row[i] + ((left + prior[i]) >> 1)) & 0xFF
        elif kind == 4:
            for i in range(stride):
                a = row[i - depth] if i >= depth else 0
                b = prior[i]
                c = prior[i - depth] if i >= depth else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        elif kind != 0:
            raise NotAPicture(f"row {y} names filter {kind}; PNG has filters 0 to 4")
        out += row
        prior = row
    return bytes(out)


def _head(raster: Raster) -> list[bytes]:
    """The signature, `IHDR`, and `PLTE` if indexed."""
    header = struct.pack(">IIBBBBB", raster.width, raster.height, 8,
                         INDEXED if raster.palette is not None else RGB, 0, 0, 0)
    out = [PNG_SIGNATURE, _chunk(b"IHDR", header)]
    if raster.palette is not None:
        out.append(_chunk(b"PLTE", b"".join(bytes(c) for c in raster.palette)))
    return out


def _stream(raster: Raster) -> bytes:
    """The compressed image data of `raster`, filter none on every row."""
    stride = raster.width * raster.depth
    body = b"".join(_FILTER_NONE + raster.pixels[y * stride:(y + 1) * stride]
                    for y in range(raster.height))
    return zlib.compress(body, ZLIB_LEVEL)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
