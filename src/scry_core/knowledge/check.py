"""The checks a base of rows is held to, each a list of faults naming the entry to fix.
`scry_core.conformance.KnowledgeContract` runs them; an empty list passes only when the check
examined something, which the contract asserts apart.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from scry_core.knowledge import text
from scry_core.knowledge.index import Index

#: How many words of the base's own names the fallback comparison asks, so it runs on any base.
WORDS_ASKED = 400


def names_unique(base: Index[Any]) -> list[str]:
    """An alias is not another entry's name in the same scope and kind."""
    names = {(e.scope, e.kind, e.name.casefold()): e for e in base.entries()}
    out: list[str] = []
    for e in base.entries():
        for a in e.aliases:
            other = names.get((e.scope, e.kind, a.casefold()))
            if other is not None and other.id != e.id:
                out.append(f"alias {a!r} of {e.id} is the name of {other.id}")
    return out


def held(base: Index[Any]) -> list[str]:
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


def _asked(base: Index[Any]) -> list[str]:
    asked: list[str] = []
    for e in base.entries():
        found = text.words(" ".join((e.name, *e.aliases, getattr(e, "description", ""))))
        asked += [found[0], f"{found[0][:3]}*"] if found else []
        if len(found) > 1:
            asked.append(f"{found[0]} {found[-1]}")
        if len(asked) >= WORDS_ASKED:
            break
    return sorted(set(asked))


def fallback_differs(of: Callable[[bool | None], Index[Any]],
                     asked: Sequence[str] | None = None) -> list[str]:
    """One set of searches over one base gives equal rows in equal order through FTS5 and
    through the index of our own. `of(False)` forces FTS5 off; `of(None)` is the host's choice,
    a second path only where the host has FTS5. `asked` defaults to the entries' own words."""
    ours, host = of(False), of(None)
    out: list[str] = []
    if ours.uses_fts5:
        return ["the base asked for no FTS5 and used it"]
    if not host.uses_fts5:
        return out
    for words in (asked if asked is not None else _asked(ours)):
        a = [e.id for e in ours.search(words=words, limit=50).entries]
        b = [e.id for e in host.search(words=words, limit=50).entries]
        if a != b:
            first = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
                         min(len(a), len(b)))
            out.append(f"text {words!r}: fts5 answers {len(b)} rows and the fallback {len(a)}; "
                       f"the first difference is at row {first}")
    return out
