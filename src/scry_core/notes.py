"""The note a disassembled line carries from the base, apart from a person's comments. An operand
the instruction states outright is named for any line; one a register holds (`out dx, al`, the
`AH` of an `int 21h`) only for the instruction at a stop, and `Note.live` says so."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from scry_core import abbreviation
from scry_core.knowledge import KeyFault, calls
from scry_core.knowledge import keys as keyspelling
from scry_core.knowledge.index import E, Index
from scry_core.naming import Named

Access = Literal["read", "write", ""]


@dataclass(frozen=True)
class Operand:
    """What an instruction refers to. `function`: `AH`, then `AL`, when known; `registers`: the
    stop's registers by upper-case name (`BL`, `BX`), which pick a call's variant, and which only
    the instruction at a stop has; `live`: the value came from a stop's registers, not the
    instruction's bytes."""

    kind: Literal["port", "interrupt", "address"]
    value: int
    access: Access = ""
    function: tuple[int, ...] = ()
    live: bool = False
    registers: Mapping[str, int] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class Note:
    """`name (number)` per operand the base names, and whether any came from live registers."""

    text: str
    live: bool


def note(base: Index[E], scope: str, operands: Sequence[Operand], *, names_on: bool) -> Note | None:
    """The note for `operands` in `scope`, or None when the base names none or the session's
    `names` switch is off. A piece is live only when no operand states it outright."""
    if not names_on:
        return None
    parts: dict[str, bool] = {}
    for operand in operands:
        for text, live in _named(base, scope, operand):
            parts[text] = parts.get(text, True) and live
    return Note("; ".join(parts), any(parts.values())) if parts else None


def _named(base: Index[E], scope: str, o: Operand) -> list[tuple[str, bool]]:
    try:
        if o.kind == "port":
            return [(t, o.live) for t in _entry(base, "port", o.value, scope, o.access)]
        if o.kind == "interrupt":
            return [*((t, False) for t in _entry(base, "vector", o.value, scope)),
                    *_call(base, scope, o)]
        found = base.at(o.value, scope) if keyspelling.fits(o.value) else None
        return [(_text(e.name, o.value, delta), o.live) for e, delta in [found]] if found else []
    except KeyFault:
        return []


def _entry(base: Index[E], kind: str, value: int, scope: str, access: Access = "") -> list[str]:
    key = keyspelling.canonical(kind, f"0x{value:X}")
    found = (base.get(kind, key, scope, access) if access else None) \
        or base.get(kind, key, scope)
    return [_text(found.name, value)] if found else []


def _call(base: Index[E], scope: str, o: Operand) -> list[tuple[str, bool]]:
    known = dict(o.registers)
    for name, byte in zip(("AH", "AL"), o.function, strict=False):
        known.setdefault(name, byte)
    got = calls.resolve(base, scope, o.value, known)
    if got is None:
        return []
    picked = keyspelling.span("call", got.entry.key).selector
    if not got.selected or picked is None:
        function = calls.register_value(known, "AH")
        assert function is not None
        return [(_text(got.entry.name, function), o.live)]
    value = calls.register_value(known, picked.register)
    assert value is not None
    return [(_text(got.entry.name, f"{picked.register}=0x{value:02X}"), True)]


def _text(name: str, number: int | str, delta: int = 0) -> str:
    shown = number if isinstance(number, str) else f"0x{number:02X}"
    return f"{abbreviation.name_text(Named('symbol', name, '', delta))} ({shown})"
