"""How each kind of entry spells its key, and the numbers a key stands for.

A dictionary holds a key in the one canonical spelling of its kind, so two entries of one number
cannot hide behind two spellings; a query is read leniently (`0x3c8`, a range) and compared by
number. `span` is what the database's range index stores: the first and last number the key covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Kinds whose key is a number (or a few), so a range index can answer "what is between".
KINDS = ("vector", "call", "error", "port", "irq", "memory", "input", "device", "register",
         "command")
NUMBERED = ("vector", "call", "error", "port", "irq", "memory", "register", "command")
#: Kinds whose key may be a range `A..B`: an area of memory, a bank of registers or of commands.
RANGED = ("memory", "register", "command")

_DECIMAL = re.compile(r"0|[1-9][0-9]*")
_HEX = re.compile(r"0[xX]([0-9a-fA-F]+)")
_SEG_OFF = re.compile(r"([0-9a-fA-F]{4}):([0-9a-fA-F]{4})")
_DEVICE = re.compile(r"[a-z0-9][a-z0-9_-]*")
#: The widest a number is held: a 32-bit address space and a little more.
_BITS = 48


def fits(value: int) -> bool:
    """A number the base holds: at most `_BITS` wide, so SQLite stores it."""
    return 0 <= value.bit_length() <= _BITS


def decimal(text: str, what: str) -> int:
    """`text` as a decimal number of the base's width, or `KeyFault`."""
    if not _DECIMAL.fullmatch(text) or len(text) > _BITS // 3 or not fits(int(text)):
        raise KeyFault(f"{what} {text!r} is a decimal number up to {_BITS} bits")
    return int(text)


class KeyFault(ValueError):
    """A key that is not one of its kind, in prose for the person who wrote or typed it."""


@dataclass(frozen=True)
class Span:
    """The numbers a key covers, inclusive, and the parts of a key of several (`0x21/0x4C`)."""

    lo: int | None
    hi: int | None
    parts: tuple[int, ...] = ()


def _hex(text: str, what: str) -> int:
    found = _HEX.fullmatch(text)
    if not found:
        raise KeyFault(f"{what} {text!r} is `0x` and hex digits")
    value = int(found.group(1), 16)
    if value.bit_length() > _BITS:
        raise KeyFault(f"{what} {text!r} is wider than {_BITS} bits")
    return value


def _shown(value: int) -> str:
    return f"0x{value:02X}"


def canonical(kind: str, key: str) -> str:
    """`key` in the one spelling of `kind`, or `KeyFault`: hex as `0x` and upper-case digits, at
    least two; `error` and `irq` decimal; a `vector` either; a `call` its parts by `/`; a `memory`
    key `SSSS:OOOO`, an address or a range `A..B`; a `register` or `command` an address or a
    range."""
    if not isinstance(key, str) or not key or key != key.strip():
        raise KeyFault(f"a key is text with no space around it; got {key!r}")
    if kind not in KINDS:
        raise KeyFault(f"{kind!r} is not a kind: {', '.join(KINDS)}")
    if kind == "input":
        if len(key) > 64 or not key.isprintable():
            raise KeyFault(f"an input key is printable text up to 64 characters; got {key!r}")
        return key
    if kind == "device":
        if not _DEVICE.fullmatch(key):
            raise KeyFault(f"a device key is lower-case letters, digits, `_` and `-`; got {key!r}")
        return key
    if kind in ("error", "irq") or (kind == "vector" and _DECIMAL.fullmatch(key)):
        return str(decimal(key, f"a {kind} key"))
    if kind == "vector":
        return _shown(_hex(key, "a vector key"))
    if kind == "call":
        parts = key.split("/")
        if not 2 <= len(parts) <= 3:
            raise KeyFault(f"a call key is INT/AH or INT/AH/AL, hex; got {key!r}")
        values = [_hex(p, "a call part") for p in parts]
        if any(v > 0xFF for v in values):
            raise KeyFault(f"a call part is a byte; got {key!r}")
        return "/".join(_shown(v) for v in values)
    seg = _SEG_OFF.fullmatch(key) if kind == "memory" else None
    if seg:
        return f"{seg.group(1).upper()}:{seg.group(2).upper()}"
    if kind in RANGED and ".." in key:
        first, _, last = key.partition("..")
        low, high = _hex(first, f"a {kind} range"), _hex(last, f"a {kind} range")
        if high < low:
            raise KeyFault(f"a {kind} range runs upward; got {key!r}")
        return f"{_shown(low)}..{_shown(high)}"
    return _shown(_hex(key, f"a {kind} key"))


def span(kind: str, key: str) -> Span:
    """The numbers a canonical `key` of `kind` covers: nothing for `input` and `device`, the
    interrupt of a `call` (its parts beside), the linear address of `SEG:OFF`."""
    if kind in ("input", "device"):
        return Span(None, None)
    if kind in ("error", "irq"):
        n = int(key)
        return Span(n, n, (n,))
    if kind == "call":
        parts = tuple(int(p, 16) for p in key.split("/"))
        return Span(parts[0], parts[0], parts)
    seg = _SEG_OFF.fullmatch(key) if kind == "memory" else None
    if seg:
        n = int(seg.group(1), 16) * 16 + int(seg.group(2), 16)
        return Span(n, n, (n,))
    if kind in RANGED and ".." in key:
        first, _, last = key.partition("..")
        return Span(int(first, 16), int(last, 16))
    n = int(key) if _DECIMAL.fullmatch(key) else int(key, 16)
    return Span(n, n, (n,))


def query(kind: str, text: str) -> tuple[str, Span]:
    """A caller's `key` for `kind`: the canonical key (or the range `A..B`) and its span. Lenient
    where `canonical` is strict: `0x3c8`, a `vector` or a `memory` as a decimal-free hex number."""
    if not isinstance(text, str) or not text.strip():
        raise KeyFault("a key is not empty")
    text = text.strip()
    if kind in ("input", "device"):
        return text, Span(None, None)
    if kind == "call" and ".." in text:
        starts, ends = _bounds(text)
        return text, Span(starts[0], ends[0])
    if kind == "call" and "/" not in text:
        number = _hex(text, "an interrupt")
        if number > 0xFF:
            raise KeyFault(f"an interrupt is a byte; got {text!r}")
        return _shown(number), Span(number, number, (number,))
    if ".." in text and kind != "memory":
        first, _, last = text.partition("..")
        if ".." in last:
            raise KeyFault(f"a range has two ends; got {text!r}")
        low = span(kind, canonical(kind, first.strip())).lo
        high = span(kind, canonical(kind, last.strip())).lo
        if low is None or high is None or high < low:
            raise KeyFault(f"a range runs upward and holds two keys of its kind; got {text!r}")
        return f"{canonical(kind, first.strip())}..{canonical(kind, last.strip())}", Span(low, high)
    key = canonical(kind, text)
    return key, span(kind, key)


def _bounds(text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    low_text, _, high_text = text.partition("..")
    low = query("call", low_text.strip())[1].parts
    high = query("call", high_text.strip())[1].parts if high_text else low
    if high < low:
        raise KeyFault(f"a range runs upward; got {text!r}")
    return low, high


def call_bounds(kind: str, key: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """The parts a call query asks from and to (`0x21` is `(0x21,)`, `a..b` two keys), or None
    when `key` does not ask for calls: no kind, and no `/` in the key."""
    if not key or (kind != "call" and not (not kind and "/" in key)):
        return None
    return _bounds(key)
