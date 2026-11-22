"""The verdict each emulator owes on each official row of an entry: exactly one of a note
`differs` or `absent`, or a closure `agrees`, naming the row."""

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
    (a_note("A", "mame", "absent", "2", MAME, "17"),
     "row 2 has 2 verdicts of mame (note 5, note A): exactly one"),
    (a_note("A", "mame", "differs", "3", MAME, "17"),
     "row 3 has 2 verdicts of mame (note A, closure mame:src/devices/machine/chipx.cpp:24-27)"),
    (closed_with({"ref": DOSBOX, "lines": "4", "as": "agrees", "row": "2"}),
     "row 2 has 2 verdicts of dosbox-x (note 7, closure dosbox-x:src/hardware/chipx.cpp:4)")])
def test_two_verdicts_of_one_emulator_on_one_row_are_red(world: World, change: Change,
                                                         fault: str) -> None:
    world.edit("command", change)
    assert any(f.startswith(fault) for f in result(world).faults), result(world).faults


def test_a_verdict_of_one_emulator_does_not_stand_for_the_other(world: World) -> None:
    world.edit("command", set_row("7", of="mame", quotes=[{"ref": MAME, "lines": "17"}]))
    assert any(f.startswith("row 2 has 2 verdicts of mame") for f in result(world).faults)
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
    assert ("mame closure mame:src/devices/machine/chipx.cpp:24-27 names row 9, which is no "
            "`doc` row of the entry") in result(world).faults


def test_an_agrees_that_names_no_row_is_refused_by_the_format(world: World) -> None:
    def change(doc: dict[str, Any]) -> None:
        for c in entry_doc(doc)["closed"]:
            if c["as"] == "agrees":
                del c["row"]
    _, faults = rows.read(world.edit("command", change))
    assert any("names the `doc` row they do" in f for f in faults)


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


def test_an_agrees_over_the_decode_of_the_key_is_used_by_it(world: World) -> None:
    world.edit("command", closed_with({"ref": MAME, "lines": "13", "as": "agrees", "row": "1"}))
    assert result(world).faults == []
