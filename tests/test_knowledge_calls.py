"""`scry_core.knowledge.calls`: the entry a stop's registers pick for an interrupt, the variant
only when the selector's register is known and the parent otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest
from null_server import an_entry, write_dictionary

from scry_core import knowledge
from scry_core.knowledge import calls


@pytest.fixture
def base(tmp_path: Path) -> knowledge.Base:
    write_dictionary(tmp_path, "int10", "call", "ibm-pc", [
        an_entry("0x10/0x12", "alternate select"),
        an_entry("0x10/0x12/BL=0x36", "video refresh"),
        an_entry("0x10/0x12/BL=0x31..0x32", "default palette"),
        an_entry("0x10/0x13", "write string"),
        an_entry("0x10/0x1C/BL=0x01", "save state"),
        an_entry("0x15/0xC2", "pointing device"),
        an_entry("0x15/0xC2/AL=0x00..0x01", "enable"),
        an_entry("0x15/0xC2/0x05", "set data size"),
        an_entry("0x21/0x4C", "exit")])
    loaded = knowledge.Base.load(tmp_path)
    assert loaded.faults() == []
    return loaded


def pick(base: knowledge.Base, interrupt: int, **registers: int) -> tuple[str, bool] | None:
    got = calls.resolve(base, "ibm-pc", interrupt, registers)
    return (got.entry.key, got.selected) if got else None


@pytest.mark.parametrize(("registers", "answer"), [
    ({"AH": 0x12, "BL": 0x36}, ("0x10/0x12/BL=0x36", True)),
    ({"AH": 0x12, "BL": 0x32}, ("0x10/0x12/BL=0x31..0x32", True)),
    ({"AX": 0x1200, "BX": 0x0031}, ("0x10/0x12/BL=0x31..0x32", True)),
    ({"AH": 0x12, "BX": 0x1236}, ("0x10/0x12/BL=0x36", True)),
    ({"AH": 0x12}, ("0x10/0x12", False)),
    ({"AH": 0x12, "BL": 0x99}, ("0x10/0x12", False)),
    ({"AH": 0x12, "BH": 0x36}, ("0x10/0x12", False)),
    ({"AH": 0x13, "BL": 0x36}, ("0x10/0x13", False)),
    ({"AH": 0x1C}, None),
    ({"AH": 0x1C, "BL": 0x02}, None),
    ({"AH": 0x1C, "BL": 0x01}, ("0x10/0x1C/BL=0x01", True)),
    ({}, None), ({"BL": 0x36}, None)])
def test_a_variant_is_named_only_when_its_register_is_known(
        base: knowledge.Base, registers: dict[str, int], answer: tuple[str, bool] | None) -> None:
    assert pick(base, 0x10, **registers) == answer


def test_the_function_of_the_call_is_the_most_specific_entry_the_registers_reach(
        base: knowledge.Base) -> None:
    assert pick(base, 0x15, AH=0xC2, AL=0x05) == ("0x15/0xC2/0x05", False)
    assert pick(base, 0x15, AH=0xC2, AL=0x01) == ("0x15/0xC2/AL=0x00..0x01", True)
    assert pick(base, 0x15, AX=0xC200) == ("0x15/0xC2/AL=0x00..0x01", True)
    assert pick(base, 0x15, AH=0xC2) == ("0x15/0xC2", False)
    assert pick(base, 0x15, AH=0xC2, AL=0x07) == ("0x15/0xC2", False)
    assert pick(base, 0x21, AH=0x4C, AL=0x00) == ("0x21/0x4C", False)


@pytest.mark.parametrize(("registers", "name", "value"), [
    ({"AX": 0x1234}, "AH", 0x12), ({"AX": 0x1234}, "AL", 0x34), ({"AH": 1, "AL": 2}, "AX", 0x0102),
    ({"AH": 1}, "AX", None), ({"AL": 2}, "AX", None), ({"BX": 0xABCD}, "BH", 0xAB),
    ({"CX": 0xABCD}, "CL", 0xCD), ({"DX": 0xABCD}, "DH", 0xAB), ({"SI": 7}, "SI", 7),
    ({"SI": 7}, "DI", None), ({"AH": 1, "AX": 0x0234}, "AH", 1), ({}, "BL", None)])
def test_a_register_is_read_directly_or_from_the_word_that_holds_it(
        registers: dict[str, int], name: str, value: int | None) -> None:
    assert calls.register_value(registers, name) == value
