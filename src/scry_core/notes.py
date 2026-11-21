"""The note a disassembled line carries from the base, apart from a person's comments. An operand
the instruction states outright is named for any line; one a register holds (`out dx, al`, the
`AH` of an `int 21h`) only for the instruction at a stop, and `Note.live` says so."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from scry_core import abbreviation
from scry_core.knowledge import Base, KeyFault
from scry_core.knowledge import keys as keyspelling
from scry_core.naming import Named

Access = Literal["read", "write", ""]


@dataclass(frozen=True)
class Operand:
    """What an instruction refers to. `function`: `AH`, then `AL`, when known; `live`: the value
    came from a stop's registers, not the instruction's bytes."""

    kind: Literal["port", "interrupt", "address"]
    value: int
    access: Access = ""
    function: tuple[int, ...] = ()
    live: bool = False


@dataclass(frozen=True)
class Note:
    """`name (number)` per operand the base names, and whether any came from live registers."""

    text: str
    live: bool


def note(base: Base, scope: str, operands: Sequence[Operand]) -> Note | None:
    """The note for `operands` in `scope`, or None when the base names none. A piece is live only
    when no operand states it outright."""
    parts: dict[str, bool] = {}
    for operand in operands:
        for text, live in _named(base, scope, operand):
            parts[text] = parts.get(text, True) and live
    return Note("; ".join(parts), any(parts.values())) if parts else None


def _named(base: Base, scope: str, o: Operand) -> list[tuple[str, bool]]:
    try:
        if o.kind == "port":
            return [(t, o.live) for t in _entry(base, "port", o.value, scope, o.access)]
        if o.kind == "interrupt":
            return [*((t, False) for t in _entry(base, "vector", o.value, scope)),
                    *((t, o.live) for t in _call(base, scope, o))]
        found = base.at(o.value, scope) if keyspelling.fits(o.value) else None
        return [(_text(e.name, o.value, delta), o.live) for e, delta in [found]] if found else []
    except KeyFault:
        return []


def _entry(base: Base, kind: str, value: int, scope: str, access: Access = "") -> list[str]:
    key = keyspelling.canonical(kind, f"0x{value:X}")
    found = (base.get(kind, key, scope, access) if access else None) \
        or base.get(kind, key, scope)
    return [_text(found.name, value)] if found else []


def _call(base: Base, scope: str, o: Operand) -> list[str]:
    if not o.function:
        return []
    for parts in (o.function[:2], o.function[:1]):
        key = keyspelling.canonical("call", "/".join(f"0x{p:X}" for p in (o.value, *parts)))
        if found := base.get("call", key, scope):
            return [_text(found.name, o.function[0])]
    return []


def _text(name: str, number: int, delta: int = 0) -> str:
    return f"{abbreviation.name_text(Named('symbol', name, '', delta))} (0x{number:02X})"
