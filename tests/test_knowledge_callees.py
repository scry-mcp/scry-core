"""`scry_core.knowledge.callees`: one decision a function, used by every entry that meets it."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scry_core.knowledge import callees


def table(**rows: Any) -> str:
    return json.dumps({"format": callees.FORMAT, "callees": rows})


@pytest.mark.parametrize("text", [
    "open", "open:control_w", "engine", "shared:pit8253:register:0x00",
    *(f"none:{r}" for r in callees.NONE_REASONS)])
def test_every_decision_of_the_set_is_read(text: str) -> None:
    assert callees.decision(text).spelled() == text


@pytest.mark.parametrize("text", ["", "none", "none:other", "shared:", "open:", "closed", "Engine",
                                  "engine:x"])
def test_a_decision_outside_the_set_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="no decision"):
        callees.decision(text)


def test_a_function_is_found_by_its_file_first_then_its_name() -> None:
    got = callees.parse(table(**{"mame:update": "engine", "mame:a.cpp update": "open",
                                 "mame:x::tick": "none:log", "mame:tick": "engine"}))

    def spelled(file: str, name: str) -> str:
        found = got.of("mame", file, name)
        assert found is not None
        return found.spelled()
    assert spelled("a.cpp", "update") == "open"
    assert spelled("b.cpp", "update") == "engine"
    assert spelled("b.cpp", "x::tick") == "none:log"
    assert spelled("b.cpp", "y->tick") == "engine"


def test_a_function_nobody_decided_has_no_decision() -> None:
    assert callees.parse(table()).of("mame", "a.cpp", "update") is None
    assert callees.Callees().of("dosbox-x", "a.cpp", "update") is None


def test_the_scheme_keeps_two_emulators_apart() -> None:
    got = callees.parse(table(**{"mame:LOG": "none:log"}))
    assert got.of("dosbox-x", "a.cpp", "LOG") is None


@pytest.mark.parametrize("text", [
    "not json", "[]", json.dumps({"format": "other", "callees": {}}),
    json.dumps({"format": callees.FORMAT}),
    table(update="engine"), table(**{"mame:update": 3}), table(**{"mame:update": "maybe"}),
    table(**{"rbil61:update": "engine"})])
def test_a_table_that_is_not_one_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="callee table|decision|text|scheme"):
        callees.parse(text)


def test_a_call_with_several_bodies_lists_each_of_them() -> None:
    got = callees.parse(table(**{"dosbox-x:FileOpen": [
        "src/dos/drive_local.cpp localDrive::FileOpen",
        "src/dos/drive_fat.cpp fatDrive::FileOpen"]}))
    found = got.of("dosbox-x", "src/dos/dos_files.cpp", "Drives[drive]->FileOpen")
    assert found is not None and found.spelled() == "virtual"
    assert found.implementations == (("src/dos/drive_local.cpp", "localDrive::FileOpen"),
                                     ("src/dos/drive_fat.cpp", "fatDrive::FileOpen"))


@pytest.mark.parametrize("bodies", [
    [], ["a.cpp f"], ["a.cpp f", "a.cpp f"], ["a.cpp f", "g"], ["a.cpp f", 3]])
def test_a_call_with_several_bodies_that_does_not_list_two_is_refused(bodies: list[Any]) -> None:
    with pytest.raises(ValueError, match="several bodies"):
        callees.parse(table(**{"mame:read": bodies}))
