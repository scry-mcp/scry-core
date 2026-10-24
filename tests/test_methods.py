"""`scry_core.methods`: a fold dispatches on `method`, refuses an argument the method does not
take naming it, and leaves a method's defaults to the method."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import methods
from scry_core.reply_contract import Invalid


def _add(ref: str, text: str = "note") -> dict[str, Any]:
    return {"ref": ref, "text": text}


def _clear(ref: str = "all", *, progress: str = "none") -> dict[str, Any]:
    return {"cleared": ref, "progress": progress}


def _judge(**given: Any) -> None:
    if given.get("ref") == "bad":
        raise Invalid("bad_argument", "ref='bad'")


FOLD = {"add": methods.Method(_add, _judge, lambda a, r: f"{r['ref']}: {r['text']}"),
        "clear": methods.Method(_clear, _judge, lambda a, r: f"cleared {r['cleared']}")}


def test_the_method_named_runs_on_what_it_was_given_and_its_own_defaults() -> None:
    chosen, given = methods.chosen(FOLD, {"method": "add", "ref": "0x10", "text": ""})
    assert given == {"ref": "0x10"} and chosen.run(given) == {"ref": "0x10", "text": "note"}
    chosen, given = methods.chosen(FOLD, {"method": "clear", "ref": None})
    assert chosen.run(given) == {"cleared": "all", "progress": "none"}
    assert methods.dispatch(FOLD, {"method": "clear"}, {"progress": "bar"})["progress"] == "bar"
    assert methods.dispatch(FOLD, {"method": "add", "ref": "r"}, {"progress": "bar"}) == {
        "ref": "r", "text": "note"}, "a body that takes no extra is not handed it"
    with pytest.raises(Invalid, match="does not take `progress`; it takes `ref`$"):
        methods.chosen(FOLD, {"method": "clear", "progress": "x"})
    assert methods.dispatch(FOLD, {"method": "add"}) == {"ref": "", "text": "note"}


def test_an_argument_the_method_does_not_take_and_an_unknown_method_are_refused() -> None:
    with pytest.raises(Invalid, match="method `clear` does not take `text`; it takes `ref`") as e:
        methods.chosen(FOLD, {"method": "clear", "text": "x"})
    assert e.value.code == "bad_argument"
    for bad in ("nope", None, 3):
        with pytest.raises(Invalid, match="method is one of"):
            methods.chosen(FOLD, {"method": bad})


def test_the_check_and_the_line_are_the_chosen_methods() -> None:
    check = methods.fold_check(FOLD)
    check(method="add", ref="0x10")
    with pytest.raises(Invalid, match="ref='bad'"):
        check(method="add", ref="bad")
    with pytest.raises(Invalid, match="does not take `text`"):
        check(method="clear", text="t")
    line = methods.fold_line("comment_write", FOLD)
    assert line({"method": "clear"}, {"cleared": "all"}) == "comment_write clear: cleared all"
