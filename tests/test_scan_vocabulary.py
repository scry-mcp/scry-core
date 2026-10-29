"""The scan words' invariants."""

from __future__ import annotations

from scry_core import scan_vocabulary as words


def test_the_default_hit_count_fits_inside_the_most_a_call_lists() -> None:
    assert 0 < words.HITS_DEFAULT <= words.HITS_MAX


def test_cell_widths_are_whole_powers_of_two_and_comparisons_are_distinct() -> None:
    assert all(b > 0 and b & (b - 1) == 0 for b in words.CELL_BYTES)
    assert len(set(words.OPERATORS)) == len(words.OPERATORS)
