from __future__ import annotations

import hashlib

import pytest

from scry_core import judges, raster
from scry_core.png import Raster
from scry_core.reply_contract import Invalid

PALETTE = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255))
#: 4x3, indices row by row.
INDEXED = Raster(4, 3, bytes([0, 1, 2, 3,
                              3, 2, 1, 0,
                              1, 1, 2, 2]), PALETTE)


def _rgb(width: int, height: int, colour: tuple[int, int, int]) -> Raster:
    return Raster(width, height, bytes(colour) * (width * height))


def _with(base: Raster, points: dict[tuple[int, int], tuple[int, int, int]]) -> Raster:
    px = bytearray(base.pixels)
    for (x, y), c in points.items():
        at = (y * base.width + x) * 3
        px[at:at + 3] = bytes(c)
    return Raster(base.width, base.height, bytes(px))


def test_the_signature_is_its_definition() -> None:
    """Recomputed from the definition: tag, kind, crop size, then the cells resolved through the
    palette."""
    crop = [1, 1, 2, 2]
    cells = bytes((255, 0, 0)) + bytes((255, 255, 255)) + bytes((255, 255, 255)) + bytes(
        (255, 0, 0))
    want = hashlib.blake2b(b"scry-sig/1|pixel|2x2|" + cells, digest_size=8).hexdigest()
    assert raster.picture_signature(INDEXED, crop) == want
    assert len(want) == 16 and want == want.lower()


def test_one_palette_entry_moves_the_signature_and_an_index_alone_does_not() -> None:
    """Another colour is another screen; the same colours under other indices are not."""
    other = Raster(4, 3, INDEXED.pixels, (*PALETTE[:3], (0, 0, 254)))
    assert raster.picture_signature(other) != raster.picture_signature(INDEXED)
    swapped = Raster(4, 3, bytes({0: 1, 1: 0, 2: 2, 3: 3}[i] for i in INDEXED.pixels),
                     (PALETTE[1], PALETTE[0], *PALETTE[2:]))
    assert raster.picture_signature(swapped) == raster.picture_signature(INDEXED)
    as_rgb = Raster(4, 3, raster.rgb(INDEXED))
    assert raster.picture_signature(as_rgb) == raster.picture_signature(INDEXED)


def test_an_index_cell_is_three_bytes_little_endian_and_a_wider_index_is_refused() -> None:
    assert raster.index_cells([1, 0x0203, 0xFFFFFF]) == bytes([1, 0, 0, 3, 2, 0, 255, 255, 255])
    want = hashlib.blake2b(b"scry-sig/1|index|1x1|" + bytes([4, 0, 0]),
                           digest_size=8).hexdigest()
    assert raster.signature("index", 1, 1, raster.index_cells([4])) == want
    with pytest.raises(Invalid, match="past 2\\^24") as e:
        raster.index_cells([1 << 24])
    assert e.value.code == "unexpected_answer"


def test_a_text_cell_signature_hashes_its_seven_bytes_and_its_kind() -> None:
    cells = bytes([0x41, 255, 255, 255, 0, 0, 170])
    want = hashlib.blake2b(b"scry-sig/1|text|1x1|" + cells, digest_size=8).hexdigest()
    assert raster.signature("text", 1, 1, cells) == want
    assert raster.signature("pixel", 1, 1, cells[:3]) != raster.signature("text", 1, 1, cells)
    with pytest.raises(ValueError, match="are 7 bytes; got 3"):
        raster.signature("text", 1, 1, cells[:3])


@pytest.mark.parametrize("crop, said", [
    ([1, 0, 4, 3], r"crop \[1, 0\] \+ 4x3 leaves the picture, which is 4x3"),
    ([0, 1, 4, 3], "leaves"),
    ([0, 0, 0, 1], r"is \[x, y, width, height\]"),
    ([-1, 0, 1, 1], "at or above zero"),
    ([0, 0, 1], r"crop=\[0, 0, 1\] is"),
    ([0, 0, True, 1], r"crop=\[0, 0, True, 1\] is"),
    ("0,0,1,1", "crop='0,0,1,1' is"),
])
def test_a_crop_one_pixel_off_or_misshapen_is_refused(crop: object, said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        raster.picture_signature(INDEXED, crop)  # type: ignore[arg-type]
    assert e.value.code == "bad_argument"
    assert raster.inside([0, 0, 4, 3], 4, 3) == (0, 0, 4, 3)     # the edge itself is inside


def test_a_crop_keeps_the_palette_and_the_whole_crop_is_the_picture() -> None:
    part = raster.cropped(INDEXED, [2, 1, 2, 2])
    assert part == Raster(2, 2, bytes([1, 0, 2, 2]), PALETTE)
    assert raster.cropped(INDEXED, None) is INDEXED


def test_a_diff_counts_its_box_by_hand() -> None:
    """Pixels changed at (1, 0) and (3, 2) give the box [1, 0, 3, 3]."""
    a = _rgb(4, 3, (10, 10, 10))
    b = _with(a, {(1, 0): (210, 10, 10), (3, 2): (10, 10, 15)})
    got = raster.diff(a, b)
    assert got == {"differing_pixels": 2, "bbox": [1, 0, 3, 3], "max_delta": [200, 0, 5],
                   "compared": [0, 0, 4, 3]}
    assert raster.diff(a, b, tolerance=5)["bbox"] == [1, 0, 1, 1]
    nothing = {"available": False, "why": "no pixel differs"}
    assert raster.diff(a, b, crop=[0, 1, 2, 2])["bbox"] == nothing
    assert raster.diff(a, a) == {"differing_pixels": 0, "bbox": nothing, "max_delta": [0, 0, 0],
                                 "compared": [0, 0, 4, 3]}


def test_a_shifted_diff_finds_a_moved_sprite_equal() -> None:
    """A pixel moved from (1, 1) to (2, 1) matches under shift [1, 0] over the columns both
    cover."""
    base = _rgb(4, 3, (0, 0, 0))
    a = _with(base, {(1, 1): (255, 0, 0)})
    b = _with(base, {(2, 1): (255, 0, 0)})
    assert raster.diff(a, b)["differing_pixels"] == 2
    got = raster.diff(a, b, shift=[1, 0])
    assert got["differing_pixels"] == 0 and got["compared"] == [0, 0, 3, 3]
    assert raster.diff(a, b, shift=[-1, 2])["compared"] == [1, 0, 3, 1]
    with pytest.raises(Invalid, match="wholly off itself"):
        raster.diff(a, b, shift=[4, 0])


def test_a_box_is_in_the_first_pictures_pixels_under_a_crop_and_a_shift() -> None:
    """Under a crop and a shift the box still names the first picture's coordinates."""
    base = _rgb(4, 3, (0, 0, 0))
    a = _with(base, {(2, 2): (50, 0, 0)})
    assert raster.diff(a, base, crop=[1, 1, 3, 2])["bbox"] == [2, 2, 1, 1]
    b = _with(base, {(0, 0): (9, 9, 9)})
    got = raster.diff(a, b, crop=[0, 0, 4, 3], shift=[-1, -1])
    assert got["compared"] == [1, 1, 3, 2]
    assert got["bbox"] == [1, 1, 2, 2] and got["differing_pixels"] == 2
    assert raster.diff(base, b, shift=[-1, -1])["bbox"] == [1, 1, 1, 1]
    assert raster.diff(base, b, shift=[0, 1])["differing_pixels"] == 0


def test_pictures_of_two_sizes_need_a_crop_inside_both() -> None:
    a, b = _rgb(4, 3, (1, 1, 1)), _rgb(3, 3, (1, 1, 1))
    with pytest.raises(Invalid, match="4x3 and 3x3"):
        raster.diff(a, b)
    with pytest.raises(Invalid, match="leaves the second picture"):
        raster.diff(a, b, crop=[1, 0, 3, 3])
    assert raster.diff(a, b, crop=[0, 0, 3, 3])["differing_pixels"] == 0


def test_a_picture_a_whole_multiple_of_the_other_is_told_it_may_be_an_enlarged_view() -> None:
    """A view's PNG is enlarged by its `scale`, so the refusal names the factor."""
    big, small = _rgb(16, 12, (1, 1, 1)), _rgb(4, 3, (1, 1, 1))
    for a, b, which in ((big, small, "the first is 4x the second"),
                        (small, big, "the second is 4x the first")):
        with pytest.raises(Invalid, match=rf"{which}.*`scale=1`"):
            raster.diff(a, b)
    with pytest.raises(Invalid) as plain:
        raster.diff(_rgb(4, 3, (1, 1, 1)), _rgb(3, 3, (1, 1, 1)))
    assert "scale" not in str(plain.value), "no factor, no hint"


def test_the_region_measures() -> None:
    a = _rgb(4, 3, (0, 0, 0))
    b = _with(a, {(0, 0): (9, 9, 9), (3, 2): (9, 9, 9)})
    assert raster.changed_pixels(a, b) == 2
    assert raster.changed_pixels(a, b, [1, 0, 3, 2]) == 0
    ref = _rgb(2, 1, (0, 0, 0))
    assert raster.match_fraction(b, ref, [0, 0, 2, 1]) == 0.5
    assert raster.match_fraction(b, ref, [1, 0, 2, 1]) == 1.0
    with pytest.raises(Invalid, match="`ref` is 2x1 and the crop is 3x1"):
        raster.match_fraction(b, ref, [0, 0, 3, 1])


@pytest.mark.parametrize("shift", [[1], [1, 2, 3], [1.0, 0], [True, 0], "1,0"])
def test_a_misshapen_shift_is_refused(shift: object) -> None:
    with pytest.raises(Invalid, match=r"shift=.* is \[dx, dy\]"):
        judges.shift(shift)
    assert judges.shift([-3, 4]) == (-3, 4)
