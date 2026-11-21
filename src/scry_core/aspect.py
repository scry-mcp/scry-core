"""A game's picture shown at 4:3 by growing its short side, so no pixel row or column is lost."""

from __future__ import annotations

from fractions import Fraction

DISPLAY = Fraction(4, 3)


def scale(width: int, height: int) -> tuple[Fraction, Fraction]:
    """What a frame's columns and rows grow by to be 4:3."""
    if Fraction(width, height) >= DISPLAY:
        return Fraction(1), width / DISPLAY / height
    return DISPLAY * height / width, Fraction(1)


def shown(width: int, height: int) -> tuple[int, int]:
    across, down = scale(width, height)
    return round(width * across), round(height * down)


def axis(whole: int, wide: int, start: int, stop: int) -> list[int]:
    """The source index from `start` of each shown pixel within `start` to `stop`."""
    first, last = -(-start * wide // whole), -(-stop * wide // whole)
    return [i * whole // wide - start for i in range(first, last)]


def display(whole: tuple[int, int], crop: tuple[int, int, int, int],
            times: int) -> tuple[list[int], list[int]]:
    """The shown columns and rows of a crop (x, y, width, height) of a frame, `times` larger."""
    across, down = whole[0] * times, whole[1] * times
    wide, high = shown(across, down)
    x, y, width, height = (value * times for value in crop)
    return axis(across, wide, x, x + width), axis(down, high, y, y + height)
