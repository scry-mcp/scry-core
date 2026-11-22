"""What the lines of a verdict must show (`rows check`). An `agrees` cites an effect of the
emulator: a store, a call to a callee that `writes` the guest's state, an assignment to a local,
the return of a value, a line of a table it reads, and on a row about an input register the line
that hands that register to a call or a local; a line that is only a header, a condition, a
dispatch, a label or a call shows nothing done. A call counts when the callee table follows it
(`open`) and the verdict also cites an effect in its body; a call with several bodies (`virtual`)
counts only when the verdict cites an effect in each of them. An `agrees` marked `nothing` cites
instead one whole body that stores nothing of what its row names, for a row that says a thing is
left unchanged or nothing is returned. An `unfollowed` closes a call the table does not follow,
and a line of it that holds an effect of the entry's own code holds such a call too. An `absent`
note cites the whole body where the thing would be, never a line beside it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from scry_core.knowledge import cover
from scry_core.knowledge.callees import Callees, Decision, last_name
from scry_core.knowledge.quote import PARTY, QUOTE_LINES, Sources, span, split_ref
from scry_core.knowledge.rows import (
    QUOTES_PER_ROW,
    VERDICT_CLOSURES,
    Closure,
    Dictionary,
    Entry,
    Region,
    Row,
)

#: The callee decisions that leave what a call does unread: another entry's, the engine's, or one
#: of several bodies. A `none` callee is one the table says does nothing a row is about.
UNFOLLOWED = ("shared", "engine", "virtual")
#: The item kinds that are something the emulator does, whatever line holds them.
EFFECTS = ("store", "local", "list")
#: What a row says about, when it is about registers the guest hands in: `in AL`, `in DS:DX`.
INPUT = "in"
_NAMED = re.compile(r"\b(?:[A-D][XLH]|SI|DI|BP|SP|IP|[CDES]S)\b")
#: A DOSBox-X callback returns `CBRET_*` to its dispatcher, never a value the guest sees.
#: A store to a guest register, the 32-bit ones included.
_GUEST = re.compile(r"(?<![\w.>])reg_e?(?:[abcd][xlh]|[sd]i|[sb]p|ip|flags)\b")
_VALUE = re.compile(r"(?:return|throw)\s*(?!CBRET_)\S")
_EMPTY = ": its lines hold no effect, only "
_ASKED = (": an `agrees` cites the store, the local it sets, the returned value or the branch "
          "body that does the row, or on an `in` row the line that hands the register on; a "
          "call counts when the callee table follows it (`open`) and the verdict cites its body")


def _handed_in(row: Row) -> frozenset[str]:
    """The families of the registers an `in` row is about, none for any other row."""
    on = row.on.split(" ", 1)
    if on[0] != INPUT or len(on) < 2:
        return frozenset()
    return frozenset(cover.family("reg_" + name) for name in _NAMED.findall(on[1].upper()))


def is_effect(item: cover.Item, inputs: frozenset[str]) -> bool:
    """Whether the item is something done; `inputs` are the registers the row is about when it
    is an `in` row, whose line that hands one of them on shows it."""
    return (item.kind in EFFECTS
            or (item.kind == "input" and cover.family(item.text.split(" ", 1)[0]) in inputs)
            or (item.kind == "exit" and bool(_VALUE.match(item.text))))


def _overlaps(named: str, stored: str) -> bool:
    """Whether a store to the register `stored` changes the register `named`: AX holds AL and
    AH, which do not hold each other."""
    named, stored = named.removeprefix("e"), stored.removeprefix("e")
    if named == stored:
        return True
    halves = all(len(r) == 2 and r[0] in "abcd" and r[1] in "lhx" for r in (named, stored))
    return halves and named[0] == stored[0] and "x" in (named[1], stored[1])


def _named(row: Row) -> list[str]:
    """The guest registers a row names, in its subject or its sentence."""
    return [r.lower() for r in _NAMED.findall(f"{row.on} {row.text}".upper())]


@dataclass(frozen=True)
class Listed:
    """An item, the file and function of the region that lists it, and the callee decision when
    it is a call."""

    ref: str
    item: cover.Item
    function: str = ""
    how: Decision | None = None

    @property
    def writes(self) -> bool:
        return self.item.kind == "call" and self.how is not None and self.how.kind == "writes"


def _effect(x: Listed, inputs: frozenset[str]) -> bool:
    return x.writes or is_effect(x.item, inputs)


@dataclass
class Proof:
    faults: list[str] = field(default_factory=list)
    #: The closures that lie in a body of a `virtual` call and so close what that body does.
    used: set[int] = field(default_factory=set)


def _inside(listed: Iterable[Listed], ref: str, first: int, last: int) -> list[Listed]:
    return [x for x in listed if x.ref == ref and first <= x.item.line <= last]


def _bodies_of(dictionary: Dictionary, sources: Sources, callees: Callees,
               listed: Sequence[Listed]) -> dict[str, list[Listed]]:
    """The items of every body a `virtual` call met in the entry's regions may reach, by the
    callee it is a body of."""
    header = dictionary.header
    out: dict[str, list[Listed]] = {}
    for x in listed:
        if x.how is None or x.how.kind != "virtual":
            continue
        scheme = split_ref(x.ref)[0]
        for file, function in x.how.implementations:
            ref = f"{scheme}:{file}"
            key = f"{ref} {function}"
            if key in out:
                continue
            party = PARTY[scheme]
            got = cover.list_function("\n".join(sources.lines(ref)), function,
                                      defined=header.defines.get(party, ()),
                                      stores=header.stores.get(party, ""))
            out[key] = [Listed(ref, i, function, callees.of(scheme, file, i.text)
                               if i.kind == "call" else None) for i in got.items]
    return out


def _kinds(items: Sequence[Listed]) -> str:
    return ", ".join(sorted({x.item.kind for x in items})) or "no listed item"


def _agrees(c: Closure, verdict: Sequence[Closure], listed: Sequence[Listed],
            bodies: dict[str, list[Listed]], inputs: frozenset[str]) -> list[str]:
    where = f"agrees {c.ref}:{c.lines} on row {c.row}"
    inside = _inside(listed, c.ref, c.first, c.last)
    virtual = [x for x in inside if x.how is not None and x.how.kind == "virtual"]
    out = []
    for x in virtual:
        assert x.how is not None
        scheme = split_ref(x.ref)[0]
        missing = []
        for file, function in x.how.implementations:
            ref = f"{scheme}:{file}"
            body = bodies[f"{ref} {function}"]
            if not any(_effect(y, inputs) for v in verdict
                       for y in _inside(body, v.ref, v.first, v.last)):
                missing.append(f"{file} {function}")
        if missing:
            out.append(f"{where} goes through {x.item.text}, which has several bodies, and cites "
                       f"no effect in {', '.join(missing)}: cite each, or write a `differs` note "
                       "per body that departs, or close the call `unfollowed`")
    if virtual or any(_effect(x, inputs) for x in inside):
        return out
    opened = {(split_ref(x.ref)[0], last_name(x.how.detail or x.item.text)) for x in inside
              if x.how is not None and x.how.kind == "open"}
    if any(_effect(y, inputs) and (split_ref(y.ref)[0], last_name(y.function)) in opened
           for v in verdict
           for y in _inside(listed, v.ref, v.first, v.last)):
        return out
    out.append(f"{where}{_EMPTY}{_kinds(inside)}{_ASKED}")
    return out


def _unfollowed(c: Closure, listed: Sequence[Listed], inputs: frozenset[str]) -> list[str]:
    inside = _inside(listed, c.ref, c.first, c.last)
    calls = {x.item.line for x in inside
             if x.item.kind == "call" and x.how is not None and x.how.kind in UNFOLLOWED}
    if not calls:
        return [f"unfollowed {c.ref}:{c.lines} on row {c.row}: its lines hold no call the callee "
                "table leaves unfollowed (only "
                f"{_kinds(inside)}); a behaviour the code shows is an `agrees` or a note"]
    shown = [x for x in inside if _effect(x, inputs) and x.item.line not in calls]
    if not shown:
        return []
    lines = ", ".join(str(n) for n in sorted({x.item.line for x in shown}))
    return [f"unfollowed {c.ref}:{c.lines} on row {c.row}: line {lines} holds an effect of the "
            f"entry's own code ({_kinds(shown)}) and no call the table leaves unfollowed: what "
            "those lines show is an `agrees` or a note, and an `unfollowed` cites the call"]


def _whole(dictionary: Dictionary, sources: Sources, spans: Sequence[tuple[Region, int, int]],
           ref: str, cited: tuple[int, int]) -> bool:
    """Whether the lines `cited` of `ref` are one whole body inside a region of the entry: the
    region itself, a case, a block or a branch the lister reads in it, or a section."""
    party = PARTY[split_ref(ref)[0]]
    for region, first, last in spans:
        if region.ref != ref:
            continue
        if region.lines:
            whole = {span(region.lines)}
        else:
            got = cover.bodies("\n".join(sources.lines(ref)), region.function,
                               defined=dictionary.header.defines.get(party, ()))
            whole = {b for b in got if first <= b[0] and b[1] <= last} | {(first, last)}
        if cited in whole:
            return True
    return False


def _nothing(c: Closure, row: Row | None, inside: Sequence[Listed], whole: bool) -> list[str]:
    """An `agrees` marked `nothing` cites one whole body that stores none of the guest registers
    its row names (or anything, when it names none or the code is not DOSBox-X's, which alone
    writes registers as `reg_*`) and calls nothing whose effect the table leaves unread."""
    where = f"agrees {c.ref}:{c.lines} on row {c.row}, marked `nothing`"
    if not whole:
        return [f"{where}: it cites one whole body (a function, a case, a branch or a section of "
                "a region of the entry), and these lines are none"]
    named = _named(row) if row and c.party == "dosbox-x" else []
    stored, unread = [], []
    for x in inside:
        if x.item.kind == "store" and named:
            hit = [r.removeprefix("reg_") for r in _GUEST.findall(x.item.text)]
            if any(_overlaps(n, h) for n in named for h in hit):
                stored.append(x)
        elif (x.item.kind == "store" or x.writes) and not named:
            stored.append(x)
        elif x.item.kind == "call" and not x.writes and (x.how is None or x.how.kind != "none"):
            unread.append(x)
    out = []
    if stored:
        lines = ", ".join(str(x.item.line) for x in stored)
        what = ", ".join(n.upper() for n in named) or "anything"
        out.append(f"{where}: line {lines} stores {what}, which the row says is left as it was: "
                   "the body does what the row names, so the verdict is an `agrees` of its "
                   "effect or a note")
    if unread:
        calls = ", ".join(f"{x.item.text} (line {x.item.line})" for x in unread)
        out.append(f"{where}: it calls {calls}, whose effect the callee table does not read: "
                   "a body that does nothing calls only what the table says does nothing")
    return out


def _absent(row: Row, dictionary: Dictionary, sources: Sources,
            spans: Sequence[tuple[Region, int, int]]) -> list[str]:
    """An `absent` note cites, in one file, exactly one whole body inside a region of the
    entry."""
    by_ref: dict[str, set[int]] = defaultdict(set)
    for q in row.quotes:
        by_ref[q.ref] |= set(range(q.first, q.last + 1))
    if len(by_ref) == 1:
        ref, lines = next(iter(by_ref.items()))
        cited = (min(lines), max(lines))
        if len(lines) == cited[1] - cited[0] + 1 and _whole(dictionary, sources, spans, ref,
                                                            cited):
            return []
    quoted = ", ".join(f"{q.ref}:{q.lines}" for q in row.quotes)
    return [f"row {row.n}: an `absent` note cites the whole body where the thing would be (a "
            f"function, a case, a branch or a section of a region of the entry), and {quoted} "
            "is none"]


def prove(dictionary: Dictionary, entry: Entry, sources: Sources, callees: Callees,
          listed: Sequence[Listed], spans: Sequence[tuple[Region, int, int]]) -> Proof:
    """The faults of the entry's verdicts; `spans` are its regions with the lines each lists.
    `Invalid` when a body a call may reach cannot be read."""
    proof = Proof()
    bodies = _bodies_of(dictionary, sources, callees, listed)
    closures = list(entry.closed)
    docs = {r.n: r for r in entry.rows if r.of == "doc"}
    handed = {n: _handed_in(r) for n, r in docs.items()}
    for k, c in enumerate(closures):
        inputs = handed.get(c.row, frozenset())
        held = [y for b in bodies.values() for y in _inside(b, c.ref, c.first, c.last)]
        verdict = [v for v in closures if v.reason == c.reason and v.row == c.row
                   and v.party == c.party]
        if c.reason in VERDICT_CLOSURES and len(verdict) > QUOTES_PER_ROW and c is verdict[0]:
            proof.faults.append(f"{c.reason} of {c.party} on row {c.row} cites {len(verdict)} "
                                f"places, over {QUOTES_PER_ROW}: a verdict cites as a row quotes")
        if c.reason in VERDICT_CLOSURES and c.last - c.first + 1 > QUOTE_LINES:
            proof.faults.append(f"{c.reason} {c.ref}:{c.lines} on row {c.row}: "
                                f"{c.last - c.first + 1} lines, over {QUOTE_LINES}: a verdict "
                                "cites the lines that show it, as a quote does")
        if c.nothing:
            proof.used.add(k)
            proof.faults += _nothing(c, docs.get(c.row), _inside(listed, c.ref, c.first, c.last),
                                     _whole(dictionary, sources, spans, c.ref, (c.first, c.last)))
        elif c.reason == "agrees" and held and not _inside(listed, c.ref, c.first, c.last):
            proof.used.add(k)
            if not any(_effect(y, inputs) for y in held):
                proof.faults.append(f"agrees {c.ref}:{c.lines} on row {c.row}{_EMPTY}"
                                    f"{_kinds(held)}{_ASKED}")
        elif c.reason == "agrees":
            proof.faults += _agrees(c, verdict, listed, bodies, inputs)
        elif c.reason == "unfollowed":
            proof.faults += _unfollowed(c, listed, inputs)
    for row in entry.rows:
        if row.vs == "absent":
            proof.faults += _absent(row, dictionary, sources, spans)
    return proof
