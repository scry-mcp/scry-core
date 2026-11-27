"""The verdict each emulator owes on each official row of an entry: one class of `agrees`
closures, `unfollowed` closures, or notes `differs` or `absent`, naming the row."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from rows_world import World, build, drop_row, entry_doc, result, set_row

from scry_core.knowledge import rows

MAME = "mame:src/devices/machine/chipx.cpp"
DOSBOX = "dosbox-x:src/hardware/chipx.cpp"
Change = Callable[[dict[str, Any]], None]


@pytest.fixture
def world(tmp_path: Any) -> World:
    return build(tmp_path)


def closed_with(*closures: dict[str, str]) -> Change:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].extend(closures)
    return change


def a_note(n: str, of: str, vs: str, row: str, ref: str, lines: str) -> Change:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["rows"].append({"n": n, "on": "when", "of": of, "vs": vs, "row": row,
                                       "text": "A note.", "quotes": [{"ref": ref, "lines": lines}]})
    return change


def verdict_faults(world: World, name: str = "command") -> list[str]:
    return [f for f in result(world, name).faults if "verdict" in f or "names row" in f]


def test_every_official_row_but_an_is_has_one_verdict_from_each_emulator(world: World) -> None:
    assert verdict_faults(world) == []


def test_an_is_row_owes_no_verdict(world: World) -> None:
    assert not any("row 1 " in f for f in result(world).faults)


@pytest.mark.parametrize(("change", "fault"), [
    (drop_row("5"), "row 2 has no verdict of mame"),
    (drop_row("7"), "row 2 has no verdict of dosbox-x"),
    (drop_row("8"), "row 3 has no verdict of dosbox-x"),
    (lambda doc: entry_doc(doc).update(
        closed=[c for c in entry_doc(doc)["closed"] if c["as"] != "agrees"]),
     "row 3 has no verdict of mame")])
def test_an_official_row_no_emulator_judged_is_red(world: World, change: Change,
                                                   fault: str) -> None:
    world.edit("command", change)
    assert any(f.startswith(fault) for f in result(world).faults)


@pytest.mark.parametrize(("change", "fault"), [
    (a_note("A", "mame", "differs", "3", MAME, "17"),
     "row 3 has verdicts of mame of 2 classes (note A, agrees "
     "mame:src/devices/machine/chipx.cpp:24-27)"),
    (closed_with({"ref": DOSBOX, "lines": "11", "as": "agrees", "row": "2"}),
     "row 2 has verdicts of dosbox-x of 2 classes (note 7, agrees "
     "dosbox-x:src/hardware/chipx.cpp:11)"),
    (closed_with({"ref": MAME, "lines": "26", "as": "agrees", "row": "1"},
                 {"ref": MAME, "lines": "27", "as": "unfollowed", "row": "1"}),
     "row 1 has verdicts of mame of 2 classes")])
def test_two_classes_of_verdict_of_one_emulator_on_one_row_are_red(world: World, change: Change,
                                                                   fault: str) -> None:
    world.edit("command", change)
    assert any(f.startswith(fault) for f in result(world).faults), result(world).faults


def test_an_is_row_that_carries_verdicts_holds_them_to_one_class(world: World) -> None:
    world.edit("command", closed_with({"ref": MAME, "lines": "26", "as": "agrees", "row": "1"}))
    world.edit("command", a_note("A", "mame", "differs", "1", MAME, "17"))
    assert any(f.startswith("row 1 has verdicts of mame of 2 classes")
               for f in result(world).faults)


def test_several_notes_of_one_emulator_on_one_row_are_one_verdict(world: World) -> None:
    world.edit("command", a_note("A", "mame", "differs", "2", MAME, "17"))
    assert verdict_faults(world) == []


def test_several_agrees_of_one_emulator_on_one_row_are_one_verdict(world: World) -> None:
    world.edit("command", lambda doc: entry_doc(doc).update(closed=[
        *[c for c in entry_doc(doc)["closed"] if c["as"] != "agrees"],
        {"ref": MAME, "lines": "24-26", "as": "agrees", "row": "3"},
        {"ref": MAME, "lines": "27", "as": "agrees", "row": "3"}]))
    assert result(world).faults == []


def test_a_verdict_of_one_emulator_does_not_stand_for_the_other(world: World) -> None:
    world.edit("command", set_row("7", of="mame", vs="differs", quotes=[
        {"ref": MAME, "lines": "17"}]))
    assert any(f.startswith("row 2 has no verdict of dosbox-x") for f in result(world).faults)


@pytest.mark.parametrize("named", ["9", "4"])
def test_a_note_that_names_a_row_that_is_not_a_doc_row_is_red(world: World, named: str) -> None:
    world.edit("command", set_row("5", row=named))
    assert f"mame note 5 names row {named}, which is no `doc` row of the entry" in result(
        world).faults


def test_an_agrees_that_names_a_row_that_is_not_there_is_red(world: World) -> None:
    def change(doc: dict[str, Any]) -> None:
        for c in entry_doc(doc)["closed"]:
            if c["as"] == "agrees":
                c["row"] = "9"
    world.edit("command", change)
    assert ("mame agrees mame:src/devices/machine/chipx.cpp:24-27 names row 9, which is no "
            "`doc` row of the entry") in result(world).faults


def test_an_agrees_that_names_no_row_is_refused_by_the_format(world: World) -> None:
    def change(doc: dict[str, Any]) -> None:
        for c in entry_doc(doc)["closed"]:
            if c["as"] == "agrees":
                del c["row"]
    _, faults = rows.read(world.edit("command", change))
    assert any("names the `doc` row they are a verdict on" in f for f in faults)


def test_a_dictionary_owes_a_verdict_of_the_emulators_it_has_code_of_only(world: World) -> None:
    assert world.dictionary("call").emulators == ("dosbox-x",)
    assert world.dictionary("command").emulators == ("dosbox-x", "mame")
    assert verdict_faults(world, "call") == []


def test_a_note_of_an_emulator_the_dictionary_has_no_code_of_still_names_a_doc_row(
        world: World) -> None:
    world.edit("call", a_note("M", "mame", "differs", "99", MAME, "10"))
    assert "mame note M names row 99, which is no `doc` row of the entry" in result(
        world, "call").faults


def test_one_line_of_an_emulator_may_do_what_several_official_rows_say(world: World) -> None:
    world.edit("command", closed_with({"ref": MAME, "lines": "24-27", "as": "agrees",
                                       "row": "1"}))
    assert result(world).faults == []


def test_an_agrees_over_the_decode_of_the_key_alone_proves_nothing(world: World) -> None:
    world.edit("command", closed_with({"ref": MAME, "lines": "13", "as": "agrees", "row": "1"}))
    assert result(world).faults == [
        "agrees mame:src/devices/machine/chipx.cpp:13 on row 1: its lines hold no effect, only "
        "key: an `agrees` cites the store, the local it sets, the returned value or the branch "
        "body that does the row, or on an `in` row the line that hands the register on; a "
        "call counts when the callee table follows it (`open`) and the verdict cites its body"]
