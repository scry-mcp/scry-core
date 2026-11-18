"""The PNG codec, held on rasters built by hand: each colour type through the encoder and back,
every row filter decoded from a file an independent writer in this test made (its own filters
and zlib by hand, Paeth rows included), and each kind the decoder refuses refused by name."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable

import pytest

from scry_core import png

#: A 4x3 RGB raster, every pixel a different colour, so a misplaced byte cannot pass.
RGB_ROWS = [[(10, 20, 30), (200, 100, 50), (0, 255, 128), (7, 7, 7)],
            [(255, 0, 0), (12, 34, 56), (99, 98, 97), (1, 2, 3)],
            [(250, 251, 252), (0, 0, 0), (128, 64, 32), (66, 6, 166)]]
RGB = png.Raster(4, 3, bytes(c for row in RGB_ROWS for px in row for c in px))
PALETTE = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255))
INDEXED = png.Raster(4, 3, bytes([0, 1, 2, 3, 3, 2, 1, 0, 1, 1, 2, 2]), PALETTE)


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(
        ">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _filtered(row: bytes, prior: bytes, kind: int, depth: int) -> bytes:
    """`row` FILTERED by `kind`, the writer's side of the PNG specification, written here so the
    decoder is held to the specification and not to its own inverse."""
    def left(i: int) -> int:
        return row[i - depth] if i >= depth else 0

    def up_left(i: int) -> int:
        return prior[i - depth] if i >= depth else 0

    predict: Callable[[int], int] = {0: lambda i: 0, 1: left, 2: lambda i: prior[i],
               3: lambda i: (left(i) + prior[i]) // 2,
               4: lambda i: _paeth(left(i), prior[i], up_left(i))}[kind]
    return bytes((row[i] - predict(i)) & 0xFF for i in range(len(row)))


def _with_idat(raster: png.Raster, raw: bytes) -> bytes:
    """An RGB PNG of `raster`'s size whose image data is `raw`, inflated as it stands."""
    return (png.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(
        ">IIBBBBB", raster.width, raster.height, 8, png.RGB, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def _independent(raster: png.Raster, kinds: list[int], colour: int, bits: int = 8,
                 interlace: int = 0) -> bytes:
    """A PNG of `raster` with row `y` filtered by `kinds[y]`, written without the codec."""
    depth = raster.depth
    stride = raster.width * depth
    raw, prior = b"", bytes(stride)
    for y in range(raster.height):
        row = raster.pixels[y * stride:(y + 1) * stride]
        raw += bytes([kinds[y]]) + _filtered(row, prior, kinds[y], depth)
        prior = row
    out = png.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(
        ">IIBBBBB", raster.width, raster.height, bits, colour, 0, 0, interlace))
    if raster.palette is not None:
        out += _chunk(b"PLTE", bytes(c for e in raster.palette for c in e))
    return out + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


@pytest.mark.parametrize("raster", [RGB, INDEXED], ids=["rgb", "indexed"])
def test_the_encoder_and_the_decoder_agree_on_both_colour_types(raster: png.Raster) -> None:
    assert png.decode(png.encode(raster)) == raster


@pytest.mark.parametrize("kinds", [[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3], [4, 4, 4],
                                   [4, 3, 1]], ids=["none", "sub", "up", "average", "paeth",
                                                    "mixed"])
@pytest.mark.parametrize("raster", [RGB, INDEXED], ids=["rgb", "indexed"])
def test_every_row_filter_of_an_independent_writer_decodes(raster: png.Raster,
                                                           kinds: list[int]) -> None:
    colour = png.INDEXED if raster.palette is not None else png.RGB
    assert png.decode(_independent(raster, kinds, colour)) == raster


def test_the_paeth_rows_really_differ_from_the_raw_rows() -> None:
    """The control of the filter cases: a filtered row that equalled the raw one would let a
    decoder that ignores the filter byte pass."""
    stride = RGB.width * 3
    second = RGB.pixels[stride:2 * stride]
    assert _filtered(second, RGB.pixels[:stride], 4, 3) != second


def test_a_transparent_index_is_written_and_skipped_on_reading() -> None:
    data = png.encode(INDEXED, clear=2)
    assert _chunk(b"tRNS", b"\xff\xff\x00") in data
    assert png.decode(data) == INDEXED


@pytest.mark.parametrize("raster, clear, said", [
    (png.Raster(1, 1, b"\x04", PALETTE), None, "index 4 is past the 4 entries"),
    (INDEXED, 4, "index 4 is past"),
    (RGB, 0, "needs an indexed raster"),
])
def test_what_no_viewer_could_draw_is_not_encoded(raster: png.Raster, clear: int | None,
                                                  said: str) -> None:
    with pytest.raises(ValueError, match=said):
        png.encode(raster, clear)


@pytest.mark.parametrize("colour, said", [(0, "greyscale"), (4, "greyscale with alpha"),
                                          (6, "RGB with alpha"), (5, "not a PNG type")])
def test_other_colour_types_are_refused_by_name(colour: int, said: str) -> None:
    with pytest.raises(png.NotAPicture, match=f"colour type {colour} \\({said}\\)"):
        png.decode(_independent(RGB, [0, 0, 0], colour))


@pytest.mark.parametrize("make, said", [
    (lambda: _independent(RGB, [0, 0, 0], png.RGB, bits=16), "16 bits a sample"),
    (lambda: _independent(RGB, [0, 0, 0], png.RGB, interlace=1), "interlaced"),
    (lambda: _with_idat(RGB, b"\x00" + bytes(12) + b"\x05" + bytes(12) + b"\x00" + bytes(12)),
     "row 1 names filter 5"),
    (lambda: b"GIF89a", "signature"),
    (lambda: png.encode(RGB)[:-12], "ends before its IEND"),
    (lambda: png.encode(RGB)[:21], "cut short"),
    (lambda: png.PNG_SIGNATURE + _chunk(b"IEND", b""), "IHDR is not the first chunk"),
    (lambda: png.PNG_SIGNATURE + _chunk(b"IHDR", bytes(12)) + _chunk(b"IEND", b""),
     "no IHDR chunk of 13 bytes"),
])
def test_what_is_not_a_readable_picture_is_refused_saying_what(make: object, said: str) -> None:
    with pytest.raises(png.NotAPicture, match=said):
        png.decode(make())  # type: ignore[operator]


def test_a_broken_crc_a_short_stream_and_bad_indices_are_refused() -> None:
    data = bytearray(png.encode(RGB))
    data[-20] ^= 0xFF                               # inside the IDAT body
    with pytest.raises(png.NotAPicture, match="fails its CRC"):
        png.decode(bytes(data))
    header = png.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
    with pytest.raises(png.NotAPicture, match="does not inflate"):
        png.decode(header + _chunk(b"IDAT", b"junk") + _chunk(b"IEND", b""))
    with pytest.raises(png.NotAPicture, match="needs 39"):
        png.decode(header + _chunk(b"IDAT", zlib.compress(b"\x00" * 13)) + _chunk(b"IEND", b""))
    past = _independent(png.Raster(1, 1, b"\x03", PALETTE[:2]), [0], png.INDEXED)
    with pytest.raises(png.NotAPicture, match="index 3 is past the 2 entries"):
        png.decode(past)
    with pytest.raises(png.NotAPicture, match="PLTE is 0 bytes"):
        png.decode(_independent(INDEXED, [0, 0, 0], png.INDEXED).replace(
            _chunk(b"PLTE", bytes(c for e in PALETTE for c in e)), b""))


def test_enlargement_squares_every_pixel_and_keeps_indices() -> None:
    big = png.enlarged(INDEXED, 2)
    assert (big.width, big.height, big.palette) == (8, 6, PALETTE)
    assert big.pixels[:8] == bytes([0, 0, 1, 1, 2, 2, 3, 3])
    assert big.pixels[8:16] == big.pixels[:8]
    assert png.enlarged(RGB, 3).pixels[:9] == bytes((10, 20, 30)) * 3
    assert png.enlarged(RGB, 1) is RGB


def test_an_animation_holds_its_frames_in_sequence() -> None:
    data = png.encode_animation([RGB, RGB], (1, 10))
    assert data.count(b"fcTL") == 2 and data.count(b"fdAT") == 1 and b"acTL" in data
    assert png.decode(data) == RGB                  # its still image is the first frame
    with pytest.raises(ValueError, match="at least one frame"):
        png.encode_animation([], (1, 10))
    with pytest.raises(ValueError, match="first one's size"):
        png.encode_animation([RGB, INDEXED], (1, 10))


@pytest.mark.parametrize("args, said", [((0, 1, b""), "at least 1x1"),
                                        ((2, 1, b"\x00" * 5), "is 6 bytes; got 5"),
                                        ((1, 1, b"\x00", ()), "1..256 entries"),
                                        ((1, 1, b"\x00", ((0, 0, 0, 0),)), r"\(r, g, b\)"),
                                        ((1, 1, b"\x00", ((0, 0, 256),)), "each 0..255")])
def test_a_raster_of_the_wrong_shape_is_refused(args: tuple[object, ...], said: str) -> None:
    with pytest.raises(ValueError, match=said):
        png.Raster(*args)  # type: ignore[arg-type]


def test_a_zero_sized_picture_is_refused_by_name() -> None:
    header = png.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 0, 3, 8, 2, 0, 0, 0))
    with pytest.raises(png.NotAPicture, match="IHDR says 0x3"):
        png.decode(header + _chunk(b"IDAT", zlib.compress(b"\x00" * 3)) + _chunk(b"IEND", b""))


def test_an_inflate_past_the_declared_size_stops_there() -> None:
    """A 1x1 RGB picture is 4 bytes of image data; a stream of 64 MiB of zeros behind it is
    refused as one byte too long, never inflated whole."""
    header = png.PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    bomb = zlib.compress(bytes(64 << 20), 9)
    with pytest.raises(png.NotAPicture, match="is 5 bytes where 1x1 needs 4"):
        png.decode(header + _chunk(b"IDAT", bomb) + _chunk(b"IEND", b""))


def test_image_data_split_over_several_idat_chunks_is_one_stream() -> None:
    data = png.encode(RGB)
    at = data.index(b"IDAT") - 4
    (length,) = struct.unpack(">I", data[at:at + 4])
    body = data[at + 8:at + 8 + length]
    split = _chunk(b"IDAT", body[:5]) + _chunk(b"IDAT", body[5:])
    assert png.decode(data[:at] + split + data[at + 12 + length:]) == RGB


def test_chunks_out_of_order_and_a_negative_clear_are_refused() -> None:
    data = png.encode(INDEXED)
    ihdr = data[8:8 + 25]
    with pytest.raises(png.NotAPicture, match="IHDR is not the first chunk"):
        png.decode(png.PNG_SIGNATURE + data[8 + 25:-12] + ihdr + data[-12:])
    plte = data.index(b"PLTE") - 4
    idat = data.index(b"IDAT") - 4
    moved = data[:plte] + data[idat:-12] + data[plte:idat] + data[-12:]
    with pytest.raises(png.NotAPicture, match="PLTE after the image data"):
        png.decode(moved)
    with pytest.raises(ValueError, match="clear=-1"):
        png.encode(INDEXED, clear=-1)


def test_a_crop_keeps_the_rectangle_it_names_and_its_palette() -> None:
    part = png.cropped(RGB, 1, 1, 2, 2)
    assert (part.width, part.height) == (2, 2)
    assert part.pixels == bytes(c for row in RGB_ROWS[1:3] for px in row[1:3] for c in px)
    small = png.cropped(INDEXED, 2, 0, 2, 3)
    assert small.palette == PALETTE and small.pixels == bytes([2, 3, 1, 0, 2, 2])
    assert png.cropped(RGB, 0, 0, 4, 3) is RGB
    with pytest.raises(ValueError, match=r"a 3x1 rectangle from \(2, 0\) is not within 4x3"):
        png.cropped(RGB, 2, 0, 3, 1)


def test_a_picture_is_told_cut_from_another_only_where_it_sits_in_it() -> None:
    assert png.cut_from(RGB, png.cropped(RGB, 1, 1, 3, 2))
    assert png.cut_from(RGB, RGB) and png.cut_from(INDEXED, png.cropped(INDEXED, 0, 1, 2, 2))
    moved = bytearray(png.cropped(RGB, 1, 1, 3, 2).pixels)
    moved[-1] ^= 1
    assert not png.cut_from(RGB, png.Raster(3, 2, bytes(moved))), "its last pixel differs"
    assert not png.cut_from(png.cropped(RGB, 1, 1, 3, 2), RGB), "a part holds no bigger whole"
    assert not png.cut_from(INDEXED, png.Raster(4, 3, INDEXED.pixels, PALETTE[::-1])), \
        "the same indices under another palette are another picture"
    straddle = png.Raster(2, 1, bytes((20, 30, 200, 100, 50, 0)))
    assert not png.cut_from(RGB, straddle), "bytes that meet across two pixels are no pixels"
