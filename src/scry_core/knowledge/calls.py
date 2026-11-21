"""The entry a stop's registers pick for an interrupt call, asked by every namer and note."""

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
    """The entry, and whether a register's value picked it (a variant)."""

    entry: Entry
    selected: bool


def register_value(registers: Mapping[str, int], name: str) -> int | None:
    """Register `name` from itself, its word or its two bytes; None when they do not say."""
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
    """The entry for `INT interrupt` and `registers` (upper-case names): the most specific one they
    reach, a variant before the entry it varies; None when the base names none or AH is unknown."""
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
