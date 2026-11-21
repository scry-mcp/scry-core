"""`scry_core.notes`: the note a disassembled line carries from the base, for the operands a server
parsed, kept to what the base names and to what the instruction states or the registers hold."""

from __future__ import annotations

from pathlib import Path

import pytest
from null_server import KNOWLEDGE, an_entry, write_dictionary

from scry_core import notes
from scry_core.knowledge import Base
from scry_core.notes import Note, Operand


@pytest.fixture
def base(tmp_path: Path) -> Base:
    write_dictionary(tmp_path, "vectors", "vector", "ibm-pc", [
        an_entry("0x21", "DOS", address=0x84, length=4), an_entry("0x10", "video BIOS",
                                                                   address=0x40, length=4)])
    write_dictionary(tmp_path, "memory", "memory", "ibm-pc", [
        an_entry("0x449", "video mode"), an_entry("0x400..0x4FF", "BIOS data area")])
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x3C8", "DAC write address", access="write"),
        an_entry("0x3C8", "DAC address, read back", access="read"),
        an_entry("0x61", "speaker control")])
    loaded = Base.load(KNOWLEDGE / "null", tmp_path)
    assert loaded.faults() == []
    return loaded


def _note(base: Base, *operands: Operand) -> Note | None:
    return notes.note(base, "ibm-pc", operands)


def test_a_port_the_instruction_states_is_named_for_the_access_it_makes(base: Base) -> None:
    assert _note(base, Operand("port", 0x3C8, "write")) == Note("DAC write address (0x3C8)", False)
    assert _note(base, Operand("port", 0x3C8, "read")) == \
        Note("DAC address, read back (0x3C8)", False)


def test_a_port_with_one_entry_for_both_accesses_is_named_whichever_the_line_makes(
        base: Base) -> None:
    assert _note(base, Operand("port", 0x61, "write")) == Note("speaker control (0x61)", False)
    assert _note(base, Operand("port", 0x61)) == Note("speaker control (0x61)", False)


def test_an_interrupt_is_named_by_its_vector_and_by_its_function_when_the_registers_say(
        base: Base) -> None:
    assert _note(base, Operand("interrupt", 0x21)) == Note("DOS (0x21)", False)
    assert _note(base, Operand("interrupt", 0x21, function=(0x4C,), live=True)) == \
        Note("DOS (0x21); exit (0x4C)", True)
    assert _note(base, Operand("interrupt", 0x21, function=(0x4D, 0x01))) == \
        Note("DOS (0x21); get return code (0x4D)", False)


def test_an_address_the_instruction_names_outright_is_named_with_how_far_in_it_is(
        base: Base) -> None:
    assert _note(base, Operand("address", 0x449)) == Note("video mode (0x449)", False)
    assert _note(base, Operand("address", 0x450)) == Note("BIOS data area+0x50 (0x450)", False)


def test_what_the_base_cannot_name_is_left_out_and_a_line_naming_nothing_has_no_note(
        base: Base) -> None:
    assert _note(base, Operand("port", 0x999, "write"), Operand("interrupt", 0x77,
                                                               function=(1,)),
                 Operand("address", 0x7FFF0)) is None
    assert _note(base) is None
    assert _note(base, Operand("port", 0x999), Operand("port", 0x61)) == \
        Note("speaker control (0x61)", False)


def test_a_line_says_it_was_named_from_live_registers_only_when_one_of_its_notes_was(
        base: Base) -> None:
    both = _note(base, Operand("port", 0x3C8, "write"), Operand("port", 0x61, live=True))
    assert both == Note("DAC write address (0x3C8); speaker control (0x61)", True)
    assert _note(base, Operand("port", 0x61), Operand("port", 0x61, live=True)) == \
        Note("speaker control (0x61)", False), "the same name stated outright is not live"


def test_only_the_piece_a_register_gave_is_live_whichever_order_the_operands_come_in(
        base: Base) -> None:
    static, live = Operand("port", 0x61), Operand("port", 0x61, live=True)
    assert _note(base, static, live) == _note(base, live, static) == \
        Note("speaker control (0x61)", False)
    vector_only = Operand("interrupt", 0x21, function=(0x99,), live=True)
    assert _note(base, vector_only) == Note("DOS (0x21)", False), \
        "the vector is in the instruction's bytes, only the function came from registers"


@pytest.mark.parametrize("operand", [Operand("port", -1), Operand("port", 2**60),
                                     Operand("address", -5), Operand("address", 2**63),
                                     Operand("address", 2**64), Operand("interrupt", 0x1FF)])
def test_a_value_no_key_can_spell_names_nothing_and_raises_nothing(
        base: Base, operand: Operand) -> None:
    assert _note(base, operand) is None



def test_a_variant_is_named_in_a_note_only_when_the_instruction_at_a_stop_holds_its_register(
        tmp_path: Path) -> None:
    write_dictionary(tmp_path, "vectors", "vector", "ibm-pc", [
        an_entry("0x10", "video BIOS", address=0x40, length=4)])
    write_dictionary(tmp_path, "calls", "call", "ibm-pc", [
        an_entry("0x10/0x12", "alternate select"), an_entry("0x10/0x12/BL=0x36", "video refresh")])
    base = Base.load(tmp_path)
    assert base.faults() == []
    at_stop = Operand("interrupt", 0x10, function=(0x12,), live=True,
                      registers={"BL": 0x36})
    assert _note(base, at_stop) == Note("video BIOS (0x10); video refresh (BL=0x36)", True)
    assert _note(base, Operand("interrupt", 0x10, function=(0x12,), live=True)) == \
        Note("video BIOS (0x10); alternate select (0x12)", True)
    assert _note(base, Operand("interrupt", 0x10, function=(0x12,),
                               registers={"BL": 0x99})) == \
        Note("video BIOS (0x10); alternate select (0x12)", False)
    assert _note(base, Operand("interrupt", 0x10, registers={"AX": 0x1200})) == \
        Note("video BIOS (0x10); alternate select (0x12)", False)
    assert _note(base, Operand("interrupt", 0x10, registers={"AH": 0x12, "BL": 0x36})) == \
        Note("video BIOS (0x10); video refresh (BL=0x36)", True), \
        "a variant a register picked is live even when the operand does not say so"
    assert _note(base, Operand("interrupt", 0x10, function=(0x13,),
                               registers={"AH": 0x12, "BL": 0x36})) == \
        Note("video BIOS (0x10); video refresh (BL=0x36)", True), "the stop's registers win"
