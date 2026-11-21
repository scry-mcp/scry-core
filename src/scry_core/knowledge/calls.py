"""Which entry of the base a stop's registers pick for an interrupt call: the variant a register
selects when that register is known, else the call itself. A server's namer, a caption and a
disassembly note all ask here, so a variant is named the same way everywhere."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scry_core.knowledge import keys
from scry_core.knowledge.database import Base
from scry_core.knowledge.entry import Entry

#: A word register and the byte registers it holds, high then low.
_HALVES = {"AX": ("AH", "AL"), "BX": ("BH", "BL"), "CX": ("CH", "CL"), "DX": ("DH", "DL")}


@dataclass(frozen=True)
class Resolved:
    """The entry a call resolved to, and whether a register's value picked it (a variant)."""

    entry: Entry
    selected: bool


def register_value(registers: Mapping[str, int], name: str) -> int | None:
    """The value of register `name` (`AH`, `BX`), from itself or from the word that holds it or
    the two bytes that make it, and None when the registers do not say."""
    if name in registers:
        return registers[name]
    for word, (high, low) in _HALVES.items():
        if name == word and high in registers and low in registers:
            return registers[high] << 8 | registers[low]
        if name in (high, low) and word in registers:
            return registers[word] >> 8 & 0xFF if name == high else registers[word] & 0xFF
    return None


def _variant(base: Base, scope: str, key: str, registers: Mapping[str, int]) -> Entry | None:
    for entry in base.variants(scope, key):
        picked = keys.span("call", entry.key).selector
        assert picked is not None
        value = register_value(registers, picked.register)
        if value is not None and picked.lo <= value <= picked.hi:
            return entry
    return None


def resolve(base: Base, scope: str, interrupt: int,
            registers: Mapping[str, int]) -> Resolved | None:
    """The entry for `INT interrupt` with `registers` (names upper-case: `AH`, `AX`, `BL`...): the
    most specific one they reach, a variant first where its selector's register is known and
    its value is the variant's, then the function's own entry, then the function's shorter key
    (`INT/AH` after `INT/AH/AL`). None when the base names none, or the registers say no AH."""
    ah = register_value(registers, "AH")
    if ah is None:
        return None
    al = register_value(registers, "AL")
    tiers = [(interrupt, ah, al), (interrupt, ah)] if al is not None else [(interrupt, ah)]
    for numbers in tiers:
        key = keys.canonical("call", "/".join(f"0x{n:X}" for n in numbers))
        found = _variant(base, scope, key, registers)
        if found is not None:
            return Resolved(found, True)
        found = base.get("call", key, scope)
        if found is not None:
            return Resolved(found, False)
    return None
