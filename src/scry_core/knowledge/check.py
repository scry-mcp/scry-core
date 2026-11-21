"""The checks a server's dictionaries are held to, each one a list of faults in prose that names
the file to write or the entry to fix. `scry_core.conformance.KnowledgeContract` runs them in a
server's own test suite; an empty list is a pass only when the check examined something, which
the contract asserts apart.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from scry_core.knowledge import keys, sources, text
from scry_core.knowledge.database import Base
from scry_core.knowledge.entry import Entry
from scry_core.knowledge.lock import COMMAND, Lock
from scry_core.knowledge.sources import SourceIndex
from scry_core.knowledge.support import Support

#: How many words of the base's own names the fallback comparison asks, so it runs on any base.
WORDS_ASKED = 400


def _kinds_of(base: Base, scope: str) -> set[str]:
    return {d.kind for d in base.dictionaries if d.scope == scope}


def owed_dictionaries(base: Base, support: Support) -> list[str]:
    """Every declared scope, device and chip has a dictionary of each kind it owes, and a
    declared device or chip its `device` entry; a device only placed says why."""
    out: list[str] = []
    for s in support.scopes:
        for kind in s.written:
            if kind not in _kinds_of(base, s.name):
                out.append(f"{s.name} is declared {s.support} and has no dictionary of kind "
                           f"{kind}: write knowledge/{s.name}-{kind}s.json, each entry with "
                           "its source")
    for who, scope, owes in [(d, "", d.written) for d in support.devices] + [
            (c, "chip", c.written) for c in support.chips]:
        if base.device_entry(scope, who.name) is None:
            out.append(f"{who.name} is declared and has no `device` entry: write it with its "
                       "source")
        placed = getattr(who, "placed_only", "")
        for kind in owes:
            if kind not in _kinds_of(base, who.name) and not placed:
                out.append(f"{who.name} is declared and has no dictionary of kind {kind}: "
                           f"write knowledge/{who.name}.json, or declare it placed_only with why")
        for inner in getattr(who, "inside", ()):
            if base.device_entry(scope, inner) is None:
                out.append(f"{who.name} holds {inner}, which has no `device` entry")
    return out


def undeclared(base: Base, support: Support, code_scopes: Iterable[str]) -> list[str]:
    """No dictionary is of a scope the declaration lacks, and the code names no scope the
    declaration lacks."""
    names = support.names()
    out = [f"{d.file} is for {d.scope}, which support.py does not declare"
           for d in base.dictionaries if d.scope not in names]
    out += [f"the code names {c} and support.py does not declare it: declare it with its "
            "dictionaries" for c in sorted(set(code_scopes) - names)]
    return out


def against_sources(base: Base, index: SourceIndex) -> list[str]:
    """Every machine-checked source of every entry is a row of the index, quotes it character
    for character, and carries the key the entry has."""
    out: list[str] = []
    for e in base.entries():
        for src in e.sources:
            scheme, _ = sources.split(src.ref)
            if not sources.SCHEMES[scheme].machine_checked:
                continue
            row = index.rows.get(src.ref)
            where = f"{e.dictionary} {e.key}"
            if row is None:
                out.append(f"{where} cites {src.ref}, which is no row of the source index")
            elif row.line != src.cites:
                out.append(f"{where} cites {src.cites!r}, and {src.ref} reads {row.line!r}")
            elif row.key and _same_key(e, row.key):
                continue
            elif row.key:
                out.append(f"{where}: {src.ref} is the source of {row.key}, not of {e.key}")
    return out


def _same_key(e: Entry, other: str) -> bool:
    try:
        return keys.canonical(e.kind, other) == e.key
    except keys.KeyFault:
        return other == e.key


def covered(base: Base, index: SourceIndex) -> list[str]:
    """Every key of the list a dictionary must cover is an entry or is left out with a reason,
    and a left-out key is on the list and no entry."""
    out: list[str] = []
    groups: dict[str, list[str]] = {}
    for d in base.dictionaries:
        groups.setdefault(d.complete_against, []).append(d.dictionary)
    for against, names in groups.items():
        wanted = index.lists.get(against)
        if wanted is None:
            out.append(f"{', '.join(names)} must cover {against!r} and the source index has no "
                       "such list")
            continue
        named = {e.key for e in base.entries() if e.dictionary in names}
        left = {k for d in base.dictionaries if d.complete_against == against
                for k, _ in d.left_out}
        listed = {_canonical_loose(k) for k in wanted}
        missing = sorted(listed - named - {_canonical_loose(k) for k in left})
        if missing:
            out.append(f"{', '.join(names)} covers {len(listed) - len(missing)} of the "
                       f"{len(listed)} keys of {against}; missing: {', '.join(missing)}: name "
                       "each, or list it under left_out with why")
        out += [f"{', '.join(names)}: left_out names {k}, which {against} does not list"
                for k in sorted({_canonical_loose(k) for k in left} - listed)]
        out += [f"{', '.join(names)}: {k} is left out and is also an entry"
                for k in sorted({_canonical_loose(k) for k in left} & named)]
    return out


def _canonical_loose(key: str) -> str:
    for kind in ("call", "port", "vector"):
        try:
            return keys.canonical(kind, key)
        except keys.KeyFault:
            continue
    return key


def relations(base: Base) -> list[str]:
    """Every relation resolves: a `device` names a device entry, `contains` and a register's
    `reached` port name entries that exist, and a register dictionary's scope is a device."""
    out: list[str] = []
    for e in base.entries():
        where = f"{e.kind}s {e.key}" if e.kind != "device" else f"device {e.key}"
        if e.device and base.device_entry(e.scope, e.device) is None:
            out.append(f"{where}: device {e.device!r} names no device entry")
        for inner in e.contains:
            if base.device_entry(e.scope, inner) is None:
                out.append(f"{where}: contains {inner!r}, which is no device entry")
        if e.kind in ("register", "command") and base.device_entry("", e.scope) is None:
            out.append(f"{e.dictionary} is a dictionary of {e.kind}s of {e.scope!r}, which is "
                       "no device entry")
        for way, ids in base.related(e).reached.items():
            out += [f"{where}: reached {way} names {i!r}, which is no port entry"
                    for i in ids if i.lower().startswith("0x")]
    return sorted(set(out))


def both_sources(base: Base, index: SourceIndex) -> list[str]:
    """A dictionary that says both sources exist has both on every entry, and where both carry
    read and write marks that differ the entry says so in `differs`."""
    out: list[str] = []
    both = {d.dictionary for d in base.dictionaries if d.both}
    for e in base.entries():
        roles = {s.role: s for s in e.sources}
        if e.dictionary in both and set(roles) != set(sources.ROLES):
            out.append(f"{e.dictionary} {e.key} cites {sorted(roles)} and its dictionary says "
                       "both sources exist: cite both, or list the key under left_out")
        marks = {r: index.rows[s.ref].marks for r, s in roles.items()
                 if s.ref in index.rows and index.rows[s.ref].marks}
        if len(marks) == 2 and len(set(marks.values())) > 1 and not e.differs:
            out.append(f"{e.dictionary} {e.key}: the documentation marks it "
                       f"{marks['documentation']} and the emulator {marks['emulator']}; say so "
                       "in differs")
    return out


def names_unique(base: Base) -> list[str]:
    """An alias is not another entry's name in the same scope and kind."""
    names = {(e.scope, e.kind, e.name.casefold()): e for e in base.entries()}
    out: list[str] = []
    for e in base.entries():
        for a in e.aliases:
            other = names.get((e.scope, e.kind, a.casefold()))
            if other is not None and other.id != e.id:
                out.append(f"alias {a!r} of {e.id} is the name of {other.id}")
    return out


def reworded(base: Base) -> list[str]:
    """A checked entry is as it was checked: its seal, over its text and its check, equals the one
    its `checked` record holds. A correction is a new write and a new check."""
    return [f"{e.id} is checked and it changed (seal {e.digest[:12]}, checked "
            f"{e.checked.digest[:12]}): a checked entry is never reworded; a correction is a "
            f"new write and a new check by another session, sealed with {COMMAND}"
            for e in base.entries() if e.checked is not None and e.checked.digest != e.digest]


def locked(base: Base, lock: Lock) -> list[str]:
    """The lock and the base agree: each locked entry is still an entry, still checked and at the
    seal it was locked at, and each checked entry is locked."""
    out: list[str] = []
    for id_, sealed in lock.checked.items():
        e = base.by_id(id_)
        if e is None:
            out.append(f"{id_} is locked and is no entry any more: a checked entry is never "
                       "removed; if it is retired for good, delete its line from the lock")
        elif e.checked is None:
            out.append(f"{id_} is locked and is no longer checked: its `checked` record is "
                       f"gone; put it back, or check the entry again with {COMMAND}")
        elif e.digest != sealed:
            out.append(f"{id_} is locked at {sealed[:12]} and now seals as {e.digest[:12]}: a "
                       f"checked entry is never touched; a correction is checked anew by "
                       f"another session and sealed with {COMMAND}")
    out += [f"{e.id} is checked and is not in the lock: seal it with {COMMAND}"
            for e in base.entries() if e.checked is not None and e.id not in lock.checked]
    return out


def held(base: Base) -> list[str]:
    """The database holds what the files hold: each entry is found by its id, its key, its
    name and its words, and a range over its number."""
    out: list[str] = []
    for e in base.entries():
        if base.by_id(e.id) != e:
            out.append(f"{e.id} did not load by id")
            continue
        if base.get(e.kind, e.key, e.scope, e.access) != e:
            out.append(f"{e.id} is not found by its kind, key and scope")
        if e not in base.by_alias(e.name):
            out.append(f"{e.id} is not found by its name")
        if e not in base.search(words=e.name, scopes=(e.scope,), limit=len(base)).entries and (
                text.terms(e.name)):
            out.append(f"{e.id} is not found by the words of its name")
        if e.lo is not None and e.kind != "call" and e not in base.search(
                kind=e.kind, key=e.key, scopes=(e.scope,), limit=len(base)).entries:
            out.append(f"{e.id} is not found by its key")
    return out


def _asked(base: Base) -> list[str]:
    asked: list[str] = []
    for e in base.entries():
        found = text.words(" ".join((e.name, *e.aliases, e.description)))
        asked += [found[0], f"{found[0][:3]}*"] if found else []
        if len(found) > 1:
            asked.append(f"{found[0]} {found[-1]}")
        if len(asked) >= WORDS_ASKED:
            break
    return sorted(set(asked))


def fallback_differs(of: Callable[[bool | None], Base]) -> list[str]:
    """One set of searches over one base gives equal rows in equal order through FTS5 and
    through the index of our own. `of(False)` is the base with FTS5 forced off; `of(None)` the
    host's choice, which is only a second path where the host has FTS5."""
    ours, host = of(False), of(None)
    out: list[str] = []
    if ours.uses_fts5:
        return ["the base asked for no FTS5 and used it"]
    if not host.uses_fts5:
        return out
    for asked in _asked(ours):
        a = [e.id for e in ours.search(words=asked, limit=50).entries]
        b = [e.id for e in host.search(words=asked, limit=50).entries]
        if a != b:
            first = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
                         min(len(a), len(b)))
            out.append(f"text {asked!r}: fts5 answers {len(b)} rows and the fallback {len(a)}; "
                       f"the first difference is at row {first}")
    return out
