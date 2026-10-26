"""A tap's bus access read back as bytes and as a value table, on both byte orders and bus widths
the two servers' taps report: a 68000's 16-bit big-endian bus, a V30's 16-bit little-endian one,
and the dword lanes DOSBox-X's taps report."""

from __future__ import annotations

import pytest

from scry_core import bus_writes
from scry_core import value_format as vf


@pytest.mark.parametrize(
    ("event", "landed"),
    [
        ((0x2031FE, 0x0001, 0xFFFF, 16, "big"), [(0x2031FE, 0x00), (0x2031FF, 0x01)]),
        ((0x20351C, 0xD8D8, 0xFF00, 16, "big"), [(0x20351C, 0xD8)]),
        ((0x20351C, 0xD8D8, 0x00FF, 16, "big"), [(0x20351D, 0xD8)]),
        ((0x1000, 0xBEEF, 0x00FF, 16, "little"), [(0x1000, 0xEF)]),
        ((0x1000, 0x11223344, 0xFFFFFFFF, 32, "big"),
         [(0x1000, 0x11), (0x1001, 0x22), (0x1002, 0x33), (0x1003, 0x44)]),
        ((0x8278, 0x00420000, 0x00FF0000, 32, "little"), [(0x827A, 0x42)]),
        ((0x1000, 0x5A, 0xFF, 8, "big"), [(0x1000, 0x5A)]),
    ],
)
def test_the_lanes_an_access_drove_are_decoded_by_mask_and_byte_order(
    event: tuple[int, int, int, int, str], landed: list[tuple[int, int]]
) -> None:
    """A byte write on the 16-bit big-endian bus lands the HIGH lane at the even address."""
    assert bus_writes.lanes(*event) == landed


def _place(addr: int) -> str:
    return f"{addr:#x}"


# A counter's dword, as DOSBox-X's tap tallies it: the byte written alone 3 times as 5, a word
# over it and its neighbour once, and a byte of the neighbour twice.
DWORD_ROWS = [(0x8278, 0x05, 0xFF, 3), (0x8278, 0x0706, 0xFFFF, 1), (0x8278, 0x0900, 0xFF00, 2)]


def test_a_whole_access_decodes_to_its_value_and_a_part_of_the_range_is_partial() -> None:
    rows = bus_writes.value_rows(DWORD_ROWS, 0x8278, 1, "u8", 32, "little", 5, _place)
    assert rows == [
        {"at": "0x8278", "raw_hex": "05", "count": 3, "value": 5},
        {"at": "0x8278", "raw_hex": "", "count": 2, "partial": True},
        {"at": "0x8278", "raw_hex": "06", "count": 1, "value": 6}]
    word = bus_writes.value_rows(DWORD_ROWS, 0x8278, 2, "u16", 32, "little", 5, _place)
    assert [r.get("value") for r in word] == [None, None, 0x0706]
    assert word[1] == {"at": "0x8279", "raw_hex": "09", "count": 2, "partial": True}


def test_the_table_is_ranked_by_count_and_cut_at_shown() -> None:
    rows = bus_writes.value_rows(DWORD_ROWS, 0x8278, 1, "u8", 32, "little", 1, _place)
    assert [r["count"] for r in rows] == [3]


def test_a_value_is_decoded_in_the_byte_order_given() -> None:
    event = [(0x2031FE, 0x0102, 0xFFFF, 1)]
    assert bus_writes.value_rows(event, 0x2031FE, 2, "u16", 16, "big", 1, _place)[0]["value"] \
        == 0x0102
    assert bus_writes.value_rows(event, 0x2031FE, 2, "u16", 16, "little", 1, _place)[0][
        "value"] == 0x0102


def test_an_access_the_format_cannot_decode_is_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    class Refusing:
        def decode(self, raw: bytes, order: str, width: int) -> object:
            raise vf.FormatError("no")

    monkeypatch.setattr(vf, "parse", lambda fmt: Refusing())
    rows = bus_writes.value_rows(DWORD_ROWS[:1], 0x8278, 1, "u8", 32, "little", 1, _place)
    assert rows == [{"at": "0x8278", "raw_hex": "05", "count": 3, "partial": True}]
