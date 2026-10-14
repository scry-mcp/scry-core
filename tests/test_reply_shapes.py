"""The shape guard's judge and its two wraps, on replies of the test's own: a word carrying
another shape is refused wherever it sits, and each wrap judges the reply it is handed."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import reply_shapes as shapes


@pytest.mark.parametrize("reply", [
    {"truncated": 3},
    {"rows": [{"name": "a", "truncated": 1}]},
    {"pages": ({"truncated": "yes"},)},
])
def test_a_word_in_another_shape_is_refused_at_any_depth(reply: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="holds `truncated` to bool"):
        shapes._judge(reply, "reply")


def test_the_shape_it_holds_passes_and_a_bool_is_not_an_int() -> None:
    shapes._judge({"truncated": False, "rows": [{"truncated": True}], "n": 3}, "reply")
    assert not isinstance(1, bool), "the direction the table relies on"


def test_both_wraps_judge_what_they_are_handed() -> None:
    envelope = shapes._wrap_envelope(lambda reply: reply)
    summary = shapes._wrap_summary(lambda name, args, reply: f"{name}: {reply['status']}")
    assert envelope({"status": "ok", "truncated": False}) == {"status": "ok", "truncated": False}
    assert summary("t", {}, {"status": "ok"}) == "t: ok"
    with pytest.raises(AssertionError):
        envelope({"status": "ok", "truncated": 2})
    with pytest.raises(AssertionError):
        summary("t", {}, {"status": "ok", "truncated": 2})
