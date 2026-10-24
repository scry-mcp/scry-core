"""`scry_core.methods`: a fold dispatches on `method`, refuses an argument the method does not
take naming it, and leaves a method's defaults to the method."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import methods
from scry_core.reply_contract import Invalid


def _add(ref: str, text: str = "note") -> dict[str, Any]:
    return {"ref": ref, "text": text}


def _clear(ref: str = "all") -> dict[str, Any]:
    return {"cleared": ref}


def _judge(**given: Any) -> None:
    if given.get("ref") == "bad":
        raise Invalid("bad_argument", "ref='bad'")


FOLD = {"add": methods.Method(_add, _judge, lambda r: f"{r['ref']}: {r['text']}"),
        "clear": methods.Method(_clear, _judge, lambda r: f"cleared {r['cleared']}")}


def test_the_method_named_runs_on_what_it_was_given_and_its_own_defaults() -> None:
    chosen, given = methods.chosen(FOLD, {"method": "add", "ref": "0x10", "text": ""})
    assert given == {"ref": "0x10"} and chosen.run(given) == {"ref": "0x10", "text": "note"}
    chosen, given = methods.chosen(FOLD, {"method": "clear", "ref": None})
    assert chosen.run(given) == {"cleared": "all"}
    assert methods.chosen(FOLD, {"method": "add"})[0].run({}) == {"ref": "", "text": "note"}


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
