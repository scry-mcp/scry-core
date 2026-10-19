"""The one plural rule every server's lines say a count by."""
from __future__ import annotations

from scry_core import prose


def test_a_count_takes_its_noun_in_its_number() -> None:
    assert [prose.counted(n, "step") for n in (0, 1, 2)] == ["0 steps", "1 step", "2 steps"]
    assert prose.counted(3, "entry", "entries") == "3 entries"
    assert prose.counted(1, "entry", "entries") == "1 entry"


def test_a_verb_agrees_with_its_count() -> None:
    assert (prose.agrees(1, "was", "were"), prose.agrees(0, "was", "were")) == ("was", "were")
