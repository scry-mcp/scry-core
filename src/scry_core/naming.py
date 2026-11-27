"""What a number is called in a reply: the `names` block, the names in a summary, and `Guarded`,
which keeps a server's namer from failing the call it names. The `names` argument of `start`
turns the reply's names off."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, NotRequired, Protocol

from pydantic import Field as Described
from typing_extensions import TypedDict

from scry_core import abbreviation
from scry_core.knowledge import KINDS as BASE_KINDS
from scry_core.knowledge import calls
from scry_core.knowledge.index import E, Index

#: What a name can be of: a kind of the base, or a symbol of the program.
KINDS = (*BASE_KINDS, "symbol")
BLOCK_MAX = 24
#: A reply's `names` item names the call's own arguments under `given.<argument>`.
GIVEN = "given."

ARGUMENT = ("Name the numbers a reply shows: a port, interrupt, address or key gets its name in "
            "the reply's `names`, its summary and a disassembled line's note. `false` leaves "
            "replies bare.")
ASK = ("`names`: `false` leaves a reply's numbers bare, with no `names` field, no name in its "
       "summary and no note on a disassembled line.")
Switch = Annotated[bool, Described(description=ARGUMENT)]


@dataclass(frozen=True)
class Named:
    """What one number is called. `delta`: bytes past the start of a symbol or a range; `id` and
    `device`: the base entry and its device, when it comes from the base; `shown`: how a tool's
    summary spells the number, when that differs."""

    kind: str
    name: str
    number: str
    delta: int = 0
    id: str = ""
    device: str = ""
    shown: str = field(default="", compare=False)


class NameItem(TypedDict):
    """One item of a reply's `names`."""

    field: str
    number: str
    kind: str
    name: str
    delta: NotRequired[int]
    id: NotRequired[str]
    device: NotRequired[str]


class NamesFailed(TypedDict):
    """What `status` says once a namer failed."""

    count: int
    last: str


class Namer(Protocol):
    """Reads only what the server holds in memory, never the emulator: it runs under the lock."""

    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        """Per argument, what its value is called; an argument it cannot name is absent."""

    def reply(self, tool: str, reply: Mapping[str, Any]) -> Sequence[tuple[str, Named]]:
        """Per number field of this reply, by its `Field.path`; never changes the reply."""


@dataclass(frozen=True)
class Field:
    """A number field of a reply: `path` (`a.b`, `a[].b` for each item of a list), the `kind` it is
    named as, and `shown`, how the summary spells it when that differs (`INT {:02X}`)."""

    path: str
    kind: str
    shown: str = ""


@dataclass(frozen=True)
class Seen:
    """A number the walk found, at the field's `path`."""

    path: str
    field: Field
    value: int | str

    @property
    def spelled(self) -> str:
        """The number as the summary spells it, or empty when as the field does."""
        if not self.field.shown or isinstance(self.value, str):
            return ""
        try:
            return self.field.shown.format(self.value)
        except (ValueError, IndexError, KeyError):
            return ""


def walk(reply: Mapping[str, Any], fields: Sequence[Field]) -> Iterator[Seen]:
    """Each number `reply` holds at the `fields`' paths, field by field."""
    for f in fields:
        for value in _at(reply, f.path.split(".")):
            if isinstance(value, str) and value or isinstance(value, int) and \
                    not isinstance(value, bool):
                yield Seen(f.path, f, value)


def _at(node: Any, parts: Sequence[str]) -> Iterator[Any]:
    if not parts:
        yield node
        return
    head, rest = parts[0], parts[1:]
    many = head.endswith("[]")
    key = head[:-2] if many else head
    if not isinstance(node, Mapping) or key not in node:
        return
    child = node[key]
    if not many:
        yield from _at(child, rest)
    elif isinstance(child, list):
        for each in child:
            yield from _at(each, rest)


def _checked(found: Iterable[tuple[str, Named]]) -> list[tuple[str, Named]]:
    """What a namer answered, or `ValueError` for what names nothing."""
    out = list(found)
    for path, n in out:
        if not (isinstance(path, str) and path and isinstance(n, Named)
                and n.kind in KINDS and all(isinstance(t, str) for t in (
                    n.name, n.number, n.id, n.device, n.shown))
                and n.name.strip() and n.number.strip() and isinstance(n.delta, int)
                and not isinstance(n.delta, bool) and n.delta >= 0):
            raise ValueError(f"a namer answered {path!r}: {n!r}, which names nothing")
    return out


def distinct(seen: Iterable[tuple[str, Named]]) -> list[tuple[str, Named]]:
    """The first of each distinct fact; every `given.<argument>` stays, a demo reads each."""
    held: set[tuple[str, str, str, str, int]] = set()
    out: list[tuple[str, Named]] = []
    for path, n in seen:
        key = (n.number, n.kind, n.name, n.id, n.delta)
        if key not in held or path.startswith(GIVEN):
            held.add(key)
            out.append((path, n))
    return out


def item(path: str, n: Named) -> NameItem:
    """`n` as an item of a reply's `names`."""
    made: NameItem = {"field": path, "number": n.number, "kind": n.kind, "name": n.name}
    if n.delta:
        made["delta"] = n.delta
    if n.id:
        made["id"] = n.id
    if n.device:
        made["device"] = n.device
    return made


def block(seen: Iterable[tuple[str, Named]]) -> tuple[list[NameItem], int]:
    """The items of a reply's `names` (`BLOCK_MAX` at most) and how many more were named."""
    every = distinct(seen)
    return [item(p, n) for p, n in every[:BLOCK_MAX]], max(0, len(every) - BLOCK_MAX)


def arguments_of(items: object) -> dict[str, Named]:
    """The names of a call's own arguments, from a reply's `names` items `given.<argument>`."""
    out: dict[str, Named] = {}
    if not isinstance(items, list):
        return out
    for each in items:
        if not (isinstance(each, Mapping) and isinstance(each.get("field"), str)
                and each["field"].startswith(GIVEN)):
            continue
        try:
            n = Named(each["kind"], each["name"], each["number"], each.get("delta", 0),
                      each.get("id", ""), each.get("device", ""))
            _checked([(each["field"], n)])
        except (KeyError, ValueError):
            continue
        out.setdefault(each["field"][len(GIVEN):], n)
    return out


def named_call(base: Index[E], scope: str, interrupt: int,
               registers: Mapping[str, int]) -> Named | None:
    """What `INT interrupt` is called given a stop's `registers`; the number is the entry's key."""
    got = calls.resolve(base, scope, interrupt, registers)
    if got is None:
        return None
    return Named("call", got.entry.name, got.entry.key, id=got.entry.id)


def _whole(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-Za-z_]){re.escape(token)}(?![0-9A-Za-z_])")


def in_summary(summary: str, named: Iterable[Named]) -> str:
    """`summary` with ` (name)` after the first whole occurrence of each number it prints."""
    inserts: dict[int, str] = {}
    for n in named:
        found = _whole(n.shown or n.number).search(summary)
        if found is None or found.end() in inserts:
            continue
        label = abbreviation.name_text(n)
        if not summary.startswith(f" ({label})", found.end()):
            inserts[found.end()] = f" ({label})"
    out, at = [], 0
    for end in sorted(inserts):
        out += [summary[at:end], inserts[end]]
        at = end
    return "".join([*out, summary[at:]])


@dataclass(frozen=True)
class Closed:
    """A reply's summary and `names` once named."""

    summary: str
    names: list[NameItem]
    cut: int


class Guarded:
    """A namer that never fails the call it names: a raise, or an answer that names nothing, gives
    no names and is counted for `status`, never said in the call's own reply."""

    def __init__(self, namer: Namer) -> None:
        self._namer = namer
        self._count = 0
        self._last = ""

    def failed(self) -> NamesFailed | None:
        """None while there has been no failure."""
        return {"count": self._count, "last": self._last} if self._count else None

    def _failure(self, e: Exception) -> None:
        self._count += 1
        self._last = f"{type(e).__name__}: {e}"

    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        try:
            named = self._namer.arguments(tool, given)
            _checked((GIVEN + a, n) for a, n in named.items())
            return dict(named)
        except Exception as e:  # a name never fails the call it names
            self._failure(e)
            return {}

    def close(self, tool: str, reply: Mapping[str, Any], arguments: Mapping[str, Named],
              summary: str) -> Closed:
        """The reply's names and summary; as given, with no names, when the namer failed."""
        try:
            seen = [(GIVEN + a, n) for a, n in arguments.items()]
            seen += _checked(self._namer.reply(tool, reply))
            every = distinct(seen)
            items, cut = block(every)
            return Closed(in_summary(summary, (n for _, n in every)), items, cut)
        except Exception as e:  # a name never fails the call it names
            self._failure(e)
            return Closed(summary, [], 0)
