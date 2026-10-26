"""The family table both servers render their roster from."""

from __future__ import annotations

import pytest

from scry_core import roster
from scry_core.roster import Roster

ROSTER = Roster(families=(("Session", ("start", "close")), ("Read", ("read", "log")),
                          ("Lists", ("list_a", "list_b"))),
                answering=("close", "log", "list_a", "list_b", "registers(from_last_stop=True)"))


def test_the_roster_lists_every_family_in_order() -> None:
    assert ROSTER.text() == "Session: start, close. Read: read, log. Lists: list_a, list_b."


def test_a_family_that_answers_whole_is_named_once() -> None:
    assert ROSTER.running_sentence() == (
        "these answer: Lists whole, and close, log, registers(from_last_stop=True).")
    assert ROSTER.answering_named() == {"close", "log", "list_a", "list_b",
                                        "registers(from_last_stop=True)"}
    whole = Roster(ROSTER.families, ("start", "close", "list_a", "list_b"))
    assert whole.running_sentence() == "these answer: Session and Lists whole."
    loose = Roster(ROSTER.families, ("log",))
    assert loose.running_sentence() == "these answer: log."

def test_the_partition_names_what_breaks_it() -> None:
    assert ROSTER.unlisted(["start", "close", "read", "log", "list_a", "list_b"]) == []
    broken = Roster((("A", ("x", "y")), ("B", ("y",))), ())
    assert broken.unlisted(["x", "z"]) == ["held twice: y", "in no family: z",
                                           "not registered: y"]


def test_what_answers_while_running_is_the_running_ops_the_registers_and_the_non_steps() -> None:
    from scry_core.roster import answers_while_running
    assert answers_while_running({"b", "a"}, {"start", "close", "perform"}, {"start"}) == [
        "a", "b", "registers(from_last_stop=True)", "close", "perform"]


def test_a_fold_that_answers_by_some_methods_is_named_with_them() -> None:
    assert roster.by_method({"status", "scan", "map_write"},
                            {"scan": ("clear",), "map_write": ("load", "save")}) == {
        "status", "scan(method=clear)", "map_write(method=load|save)"}


GATE = roster.RunningGate(
    ops=frozenset({"status", "comment_write", "gfx_film"}),
    methods={"comment_write": ("save",)},
    needs_stop={"gfx_film": lambda a: bool(a.get("trigger"))})


@pytest.mark.parametrize(("op", "args", "answers"), [
    ("status", {}, True), ("step", {}, False),
    ("comment_write", {"method": "save"}, True), ("comment_write", {"method": "set"}, False),
    ("gfx_film", {}, True), ("gfx_film", {"trigger": "vblank"}, False),
    ("registers", {"from_last_stop": True}, True), ("registers", {}, False)])
def test_the_running_gate_answers_by_op_by_method_and_by_gesture(
        op: str, args: dict[str, object], answers: bool) -> None:
    assert GATE.answers(op, args) is answers


def test_the_running_gate_names_what_it_lists_as_by_method_does() -> None:
    assert GATE.listed() == roster.by_method(GATE.ops, GATE.methods)


def test_a_fold_that_answers_running_with_no_methods_named_is_refused() -> None:
    """Named whole, every method of it would answer a running machine, the ones that need a stop
    too; a method the fold lacks is a typo the gate would carry silently."""
    folds = {"comment_write": ("save", "set"), "scan": ("start", "clear")}
    GATE.check_folds(folds)
    with pytest.raises(ValueError, match="scan answers a running machine with no methods named"):
        roster.RunningGate(ops=frozenset({"scan"}), methods={}).check_folds(folds)
    with pytest.raises(ValueError, match="comment_write names `sav`, which it lacks"):
        roster.RunningGate(ops=frozenset({"comment_write"}),
                           methods={"comment_write": ("sav",)}).check_folds(folds)
    with pytest.raises(ValueError, match="methods for scan, which is not among the ops"):
        roster.RunningGate(ops=frozenset(), methods={"scan": ("clear",)})
