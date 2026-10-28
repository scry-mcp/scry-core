"""The one plural rule every server's lines say a count by."""
from __future__ import annotations

from scry_core import prose


def test_a_count_takes_its_noun_in_its_number() -> None:
    assert [prose.counted(n, "step") for n in (0, 1, 2)] == ["0 steps", "1 step", "2 steps"]
    assert prose.counted(3, "entry", "entries") == "3 entries"
    assert prose.counted(1, "entry", "entries") == "1 entry"


def test_a_verb_agrees_with_its_count() -> None:
    assert (prose.agrees(1, "was", "were"), prose.agrees(0, "was", "were")) == ("was", "were")


def test_a_refusal_is_cut_at_a_word_and_says_its_code() -> None:
    assert prose.clipped("a" * prose.REFUSAL_CHARS_SHOWN) == "a" * prose.REFUSAL_CHARS_SHOWN
    assert prose.clipped("a" * 100 + " " + "b" * 30) == "a" * 100 + "..."
    assert prose.clipped("a" * 121) == "a" * 120 + "...", "no word to cut at: cut at the limit"
    line = prose.refusal("screen_map_find",
                         {"status": "INVALID", "code": "needs_call", "message": "x"})
    assert line == "screen_map_find: INVALID (needs_call), x"


def test_a_reads_bytes_are_shown_whole_up_to_the_ceiling_then_counted() -> None:
    assert prose.hex_clipped("0300") == "0300"
    whole = "ab" * prose.HEX_BYTES_SHOWN
    assert prose.hex_clipped(whole) == whole
    assert prose.hex_clipped(whole + "cdef") == whole + "... (2 more bytes in `hex`)"
