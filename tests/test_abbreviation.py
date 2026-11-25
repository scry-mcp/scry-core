"""`scry_core.abbreviation`: a name as a summary writes it, cut to its width with the cut
marked, the offset inside it beside it, and printable ASCII."""

from __future__ import annotations

from typing import Any

from scry_core import abbreviation as ab
from scry_core.naming import Named


def _n(name: str, number: str, **fields: Any) -> Named:
    return Named("port", name, number, **fields)


def test_a_name_is_written_with_its_number_beside_it() -> None:
    assert ab.name_text(_n("DAC write address", "0x3C8")) == "DAC write address"
    assert ab.name_text(Named("symbol", "score", "0x9405")) == "score"


def test_an_address_inside_a_symbol_says_how_far_in() -> None:
    assert ab.name_text(Named("symbol", "count_coin", "0xb58c", delta=9)) == "count_coin+0x9"


def test_a_name_is_cut_at_its_width_and_its_offset_is_never() -> None:
    long = "a_function_name_that_is_far_too_long_for_a_caption"
    text = ab.name_text(Named("symbol", long, "0x123456789ABCDEF0123456"))
    assert text == f"{long[:ab.NAME_WIDTH - len(ab.CUT)]}{ab.CUT}"
    assert len(text) == ab.NAME_WIDTH
    assert ab.name_text(Named("symbol", "x", "0x1", delta=0x123456)) == "x+0x123456"


def test_a_name_with_no_printable_ascii_is_written_printable() -> None:
    assert ab.name_text(Named("symbol", "café\tx", "1")) == "caf? x"
    assert all(" " <= c <= "~" for c in ab.name_text(Named("symbol", "ñ" * 40, "1")))


def test_a_name_that_runs_over_several_lines_is_one_line() -> None:
    assert ab.name_text(Named("symbol", "a\n  b", "1")) == "a b"
