"""A bus access as a tap reports it: the data of its bus word and the mask of the lanes it
drove, read alike on both servers whatever the width and byte order."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from scry_core import value_format as vf


def lane_shift(at: int, width: int, data_width: int, endianness: str) -> int:
    """Right shift for `width` bytes at byte `at` of the word; big-endian puts the lowest
    address in the high lane."""
    nb = data_width // 8
    return (nb - width - at) * 8 if endianness == "big" else at * 8


def lanes(offset: int, data: int, mask: int, data_width: int,
          endianness: str) -> list[tuple[int, int]]:
    """The bytes a bus access drove, as (address, byte) in address order."""
    out: list[tuple[int, int]] = []
    for i in range(data_width // 8):
        shift = lane_shift(i, 1, data_width, endianness)
        if (mask >> shift) & 0xFF:
            out.append((offset + i, (data >> shift) & 0xFF))
    return out


def value_rows(values: Iterable[tuple[int, int, int, int]], addr: int, width: int, fmt: str,
               data_width: int, endianness: str, shown: int,
               place: Callable[[int], str]) -> list[dict[str, Any]]:
    """A count watch's value table from `(offset, data, mask, count)`, most written first;
    `value` only when one access covers the range whole, else `partial`."""
    rows: list[dict[str, Any]] = []
    for offset, data, mask, count in sorted(values, key=lambda r: (-r[3], r[0], r[1]))[:shown]:
        inside = [(a, b) for a, b in lanes(offset, data, mask, data_width, endianness)
                  if addr <= a < addr + width]
        row: dict[str, Any] = {"at": place(inside[0][0] if inside else offset),
                               "raw_hex": bytes(b for _a, b in inside).hex(), "count": count}
        if [a for a, _b in inside] == list(range(addr, addr + width)):
            try:
                row["value"] = vf.parse(fmt).decode(bytes(b for _a, b in inside), endianness,
                                                    width)
            except vf.FormatError:
                row["partial"] = True
        else:
            row["partial"] = True
        rows.append(row)
    return rows
