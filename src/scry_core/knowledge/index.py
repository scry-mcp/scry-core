"""The lookups of a base, in an SQLite database in memory, whatever shape its entries are written
in: by id, by key, by range of numbers or addresses, by alias, by device, by words.

A base subclasses `Index`, inserts each entry it loads with `_insert` and builds an entry from its
row with `_entry` when one is asked for, so what it holds is the rows and no Python object per
entry. A text search asks FTS5 when the host's SQLite has it, else an index kept in Python that
only such a host builds; both rank by the field a word was found in, best first (`FIELDS`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from scry_core.knowledge import keys, text

_SCHEMA = """
CREATE TABLE entry (
  n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, kind TEXT NOT NULL,
  key TEXT NOT NULL, access TEXT NOT NULL, lo INTEGER, hi INTEGER,
  a_lo INTEGER, a_hi INTEGER, name TEXT NOT NULL, device TEXT NOT NULL, h INTEGER NOT NULL
  {extra});
CREATE TABLE alias (alias TEXT NOT NULL, n INTEGER NOT NULL);
CREATE TABLE relation (n INTEGER NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL,
                       PRIMARY KEY (n, rel, target)) WITHOUT ROWID;
CREATE TABLE device_port (n INTEGER NOT NULL, lo INTEGER NOT NULL, hi INTEGER NOT NULL);
CREATE TABLE held (id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                   key TEXT NOT NULL, lo INTEGER, hi INTEGER, device TEXT NOT NULL) WITHOUT ROWID;
CREATE INDEX entry_exact ON entry (kind, key, scope);
CREATE INDEX entry_range ON entry (kind, scope, lo, hi);
CREATE INDEX entry_address ON entry (scope, a_lo, a_hi);
CREATE INDEX entry_device ON entry (device, kind, lo);
CREATE INDEX alias_exact ON alias (alias);
CREATE INDEX relation_target ON relation (rel, target);
CREATE INDEX device_port_range ON device_port (lo, hi);
"""
COLUMNS = "n, id, scope, kind, key, access, lo, hi, a_lo, a_hi, name, device, h"
_ORDER = "scope, kind, lo IS NULL, lo, key, access"


class Keyed(Protocol):
    """What the lookups read of an entry, whatever its shape."""

    @property
    def id(self) -> str: ...
    @property
    def scope(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def access(self) -> str: ...
    @property
    def device(self) -> str: ...
    @property
    def contains(self) -> tuple[str, ...]: ...
    @property
    def lo(self) -> int | None: ...
    @property
    def hi(self) -> int | None: ...
    @property
    def a_lo(self) -> int | None: ...

    def short(self) -> dict[str, Any]: ...


E = TypeVar("E", bound=Keyed)


@dataclass
class Found(Generic[E]):
    """What `search` answers: the first `limit` entries, how many matched, how many entries of that
    kind and scope were searched, and, when nothing matched, the nearest ones."""

    entries: list[E] = field(default_factory=list)
    total: int = 0
    examined: int = 0
    nearest: list[E] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.total > len(self.entries)


def _walk(folder: Traversable) -> Iterator[tuple[str, str]]:
    for item in sorted(folder.iterdir(), key=lambda i: i.name):
        if item.is_dir():
            yield from _walk(item)
        elif item.name.endswith(".json"):
            yield item.name, item.read_text(encoding="utf-8")


def files(source: str | Path, directory: str) -> Iterator[tuple[str, str]]:
    """Each `.json` file of a directory, or of the `directory` of the package `source` names, with
    its text."""
    if isinstance(source, Path):
        if not source.is_dir():
            raise FileNotFoundError(f"no such directory: {source.name}")
        for path in sorted(source.rglob("*.json")):
            yield str(path.relative_to(source)), path.read_text(encoding="utf-8")
    else:
        yield from _walk(resources.files(source) / directory)


class Index(Generic[E]):
    """The database and its lookups. A subclass names its text fields (`FIELDS`, best first), the
    columns it adds to an entry's row (`EXTRA`, the SQL of each) and how a row becomes an entry
    (`_entry`); it calls `_finish` once every entry is in."""

    FIELDS: tuple[str, ...] = ()
    EXTRA: tuple[str, ...] = ()

    def __init__(self, fts5: bool | None, pins: Mapping[str, str] | None) -> None:
        self.pins: Mapping[str, str] = dict(pins or {})
        self.file_faults: list[str] = []
        self.entry_faults: list[str] = []
        self.load_faults: list[str] = []
        self._count = 0
        #: The highest number of a register or a command loaded per dictionary, scope and kind:
        #: an entry above it overlaps nothing, so the common ordered file never asks the database.
        self._top: dict[tuple[int, str, str], int] = {}
        self._columns = ", ".join((COLUMNS, *(c.split()[0] for c in self.EXTRA)))
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.executescript(_SCHEMA.format(extra="".join(f", {c}" for c in self.EXTRA)))
        self.uses_fts5 = fts5 is not False and self._create_fts()
        self._fallback = None if self.uses_fts5 else text.Fallback(self.FIELDS)

    def _fts(self) -> str:
        return (f"CREATE VIRTUAL TABLE entry_text USING fts5 ({', '.join(self.FIELDS)}, "
                "content='', tokenize='unicode61 remove_diacritics 2', detail=column)")

    def _create_fts(self) -> bool:
        try:
            self._db.execute(self._fts())
        except sqlite3.OperationalError:
            return False
        return True

    def _finish(self) -> None:
        if self._fallback is not None:
            self._fallback.freeze()
        self._db.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        """Release the database; a base that is dropped is closed the same way."""
        self._db.close()

    def __del__(self) -> None:
        if hasattr(self, "_db"):
            self.close()

    def _entry(self, row: Sequence[Any]) -> E:
        raise NotImplementedError

    def _hold(self, got: Keyed) -> None:
        """Keep of an entry held back only what says it exists: its id, kind, key and device."""
        self._db.execute("INSERT OR IGNORE INTO held VALUES (?,?,?,?,?,?,?)",
                         (got.id, got.scope, got.kind, got.key, got.lo, got.hi, got.device))

    def _clash(self, got: Keyed, h: int) -> str:
        """Why `got` cannot join the entries loaded, or empty."""
        variant = self._variant_clash(got)
        if variant:
            return f"{got.id} {variant}; the second is skipped"
        clash = self._overlap(got, h)
        if clash:
            return (f"{got.id} overlaps {clash} in its dictionary and access does not tell them "
                    "apart; the second is skipped")
        return ""

    def _insert(self, got: Keyed, h: int, extra: Sequence[object], aliases: Iterable[str],
                words: Mapping[str, str], a_hi: int | None = None) -> int | None:
        """Adds `got`'s row, its aliases and its words; None when its id is already an entry."""
        marks = ",".join("?" * (12 + len(extra)))
        added = self._db.execute(
            f"INSERT OR IGNORE INTO entry ({self._columns}) VALUES (NULL,{marks})",
            (got.id, got.scope, got.kind, got.key, got.access, got.lo, got.hi, got.a_lo, a_hi,
             got.name, got.device, h, *extra))
        if not added.rowcount:
            return None
        n = added.lastrowid
        assert n is not None
        self._count += 1
        if got.kind in ("register", "command") and got.hi is not None:
            top = self._top.get((h, got.kind, got.scope))
            self._top[(h, got.kind, got.scope)] = got.hi if top is None else max(top, got.hi)
        self._db.executemany("INSERT INTO alias VALUES (?,?)",
                             [(a, n) for a in sorted({a.casefold() for a in (got.name, *aliases)})])
        split = {k: text.words(v) for k, v in words.items()}
        if self._fallback is None:
            self._db.execute(f"INSERT INTO entry_text (rowid, {', '.join(self.FIELDS)}) VALUES "
                             f"(?{',?' * len(self.FIELDS)})",
                             (n, *(" ".join(split[f]) for f in self.FIELDS)))
        else:
            self._fallback.add(n, {k: set(w) for k, w in split.items()})
        return n

    @property
    def held_back(self) -> int:
        """How many entries the base holds back."""
        return int(self._db.execute("SELECT COUNT(*) FROM held").fetchone()[0])

    def unconfirmed(self, id: str = "", kind: str = "", key: str = "", device: str = "",
                    scopes: Iterable[str] = ()) -> list[str]:
        """The ids of the entries held back that a question with these filters would have matched
        had they been loaded: what `search` takes, but for words, which no held entry keeps."""
        if id:
            return [i for (i,) in self._db.execute("SELECT id FROM held WHERE id = ?", (id,))]
        where, args = _base_filters(kind, tuple(scopes))
        clauses, more = [where], list(args)
        number = _key_clause(kind, key, clauses, more) if key else None
        if device:
            keep = sorted(self._closure(device))
            marks = ",".join("?" * len(keep))
            clauses.append(f"(device IN ({marks}) OR (kind IN ('register','command') "
                           f"AND scope IN ({marks})) OR (kind = 'device' AND key = ?))")
            more += [*keep, *keep, device]
        return [i for i, k, row_key in self._db.execute(
            f"SELECT id, kind, key FROM held WHERE {' AND '.join(clauses)} ORDER BY id", more)
            if number is None or _prefix_of(kind, key, k, row_key)]

    def held_scopes(self) -> list[str]:
        """The scopes that have entries held back, sorted."""
        return [s for (s,) in self._db.execute("SELECT DISTINCT scope FROM held ORDER BY scope")]

    def _overlap(self, got: Keyed, h: int) -> str:
        """The id of an entry already loaded from the same dictionary whose numbers overlap `got`'s
        and whose access does not differ from its own: only registers and commands, whose banks
        must name one entry for a number (a memory area may hold another)."""
        if got.kind not in ("register", "command") or got.lo is None or got.hi is None:
            return ""
        top = self._top.get((h, got.kind, got.scope))
        if top is None or got.lo > top:
            return ""
        for id_, access in self._db.execute(
                "SELECT id, access FROM entry WHERE kind = ? AND scope = ? AND h = ? "
                "AND lo <= ? AND hi >= ? ORDER BY n", (got.kind, got.scope, h, got.hi, got.lo)):
            if id_ != got.id and not (access and got.access and access != got.access):
                return str(id_)
        return ""

    def variants(self, scope: str, parent: str) -> list[E]:
        """The variants of the call `parent` (`0x10/0x12`) in `scope`, in load order: the entries
        whose key is the parent's and a selector."""
        if keys.call_selector("call", parent) is not None:
            return []
        parts = keys.span("call", parent).parts
        return [self._of(n) for n, key in self._db.execute(
            "SELECT n, key FROM entry WHERE kind = 'call' AND scope = ? AND lo = ? AND key LIKE ? "
            "ORDER BY n", (scope, parts[0], f"{parent}/%=%"))
            if keys.span("call", key).parts == parts]

    def _variant_clash(self, got: Keyed) -> str:
        """Why a variant cannot join the variants its call already has in its scope, or empty:
        they select on one register, and no value picks two."""
        if got.kind != "call" or (mine := keys.span("call", got.key).selector) is None:
            return ""
        parent = got.key.rpartition("/")[0]
        for other in self.variants(got.scope, parent):
            theirs = keys.span("call", other.key).selector
            assert theirs is not None
            if other.id == got.id:
                continue
            if theirs.register != mine.register:
                return (f"selects on {mine.register}, and the other variants of {parent} select "
                        f"on {theirs.register}")
            if mine.overlaps(theirs):
                return f"overlaps {other.id}, which a register value cannot tell apart"
        return ""

    def _one(self, where: str, args: Sequence[object]) -> E | None:
        row = self._db.execute(f"SELECT {self._columns} FROM entry WHERE {where}",
                               args).fetchone()
        return self._entry(row) if row else None

    def _of(self, n: int) -> E:
        found = self._one("n = ?", (n,))
        assert found is not None
        return found

    def _many(self, numbers: Sequence[int]) -> list[E]:
        """The entries of `numbers`, in that order, in one read."""
        if not numbers:
            return []
        marks = ",".join("?" * len(numbers))
        built = {row[0]: self._entry(row) for row in self._db.execute(
            f"SELECT {self._columns} FROM entry WHERE n IN ({marks})", numbers)}
        return [built[n] for n in numbers]

    def faults(self) -> list[str]:
        """Every fault of the files and the entries, one line each."""
        return [*self.file_faults, *self.entry_faults, *self.load_faults]

    def __len__(self) -> int:
        return self._count

    def entries(self) -> Iterator[E]:
        for row in self._db.execute(f"SELECT {self._columns} FROM entry ORDER BY n"):
            yield self._entry(row)

    def ids(self) -> list[str]:
        """Every id served, in load order."""
        return [i for (i,) in self._db.execute("SELECT id FROM entry ORDER BY n")]

    def scopes(self, kind: str = "") -> list[str]:
        """The scopes that hold entries (of `kind` when given), sorted."""
        return [s for (s,) in self._db.execute(
            "SELECT DISTINCT scope FROM entry WHERE ? = '' OR kind = ? ORDER BY scope",
            (kind, kind))]

    def kinds(self, scope: str = "") -> list[str]:
        """The kinds that have entries (in `scope` when given), in the order of `keys.KINDS`."""
        held = {k for (k,) in self._db.execute(
            "SELECT DISTINCT kind FROM entry WHERE ? = '' OR scope = ?", (scope, scope))}
        return [k for k in keys.KINDS if k in held]

    def by_id(self, id: str) -> E | None:
        return self._one("id = ?", (id,))

    def get(self, kind: str, key: str, scope: str, access: str = "") -> E | None:
        """The entry of `kind` and `key` (in the canonical spelling) in `scope`."""
        return self._one("kind = ? AND key = ? AND scope = ? AND access = ?",
                         (kind, key, scope, access))

    def at(self, address: int, scope: str = "") -> tuple[E, int] | None:
        """The entry that sits at `address` (a vector's slot, a memory area) in `scope` (any when
        empty), and how many bytes in it is: the narrowest area, the first of equals."""
        found = self._one("n = (SELECT n FROM entry WHERE a_lo <= ? AND a_hi >= ? AND "
                          "(? = '' OR scope = ?) ORDER BY a_hi - a_lo, n LIMIT 1)",
                          (address, address, scope, scope))
        if found is None:
            return None
        assert found.a_lo is not None
        return found, address - found.a_lo

    def by_alias(self, word: str) -> list[E]:
        rows = self._db.execute("SELECT n FROM alias WHERE alias = ? ORDER BY n",
                                (word.casefold(),)).fetchall()
        return [self._of(n) for (n,) in rows]

    def _devices(self, key: str) -> list[E]:
        """The device entries named `key`, in load order."""
        return [self._of(n) for (n,) in self._db.execute(
            "SELECT n FROM entry WHERE kind = 'device' AND key = ? ORDER BY n", (key,))]

    def device_entry(self, scope: str, key: str) -> E | None:
        """The device `key`, as seen from `scope`: that scope's own, else the shared `chip` one,
        else the only one of the name."""
        held = self._db.execute("SELECT n, scope FROM entry WHERE kind = 'device' AND key = ? "
                                "ORDER BY n", (key,)).fetchall()
        for wanted in (scope, "chip"):
            for n, of in held:
                if of == wanted:
                    return self._of(n)
        return self._of(held[0][0]) if len(held) == 1 else None

    def device_keys(self) -> list[str]:
        return [k for (k,) in self._db.execute(
            "SELECT DISTINCT key FROM entry WHERE kind = 'device' ORDER BY key")]

    def _closure(self, key: str) -> set[str]:
        seen, todo = set(), [key]
        while todo:
            at = todo.pop()
            if at in seen:
                continue
            seen.add(at)
            for e in self._devices(at):
                todo.extend(e.contains)
        return seen

    def search(self, kind: str = "", key: str = "", words: str = "", device: str = "",
               scopes: Iterable[str] = (), limit: int = 10) -> Found[E]:
        """The entries that answer every filter given: `kind`; `key` (a number or a range read
        by number, an interrupt's functions, an input's or a device's name); `words` (every word,
        `*` for a prefix); `device` (its own entry first, then its ports, lines, registers and
        commands, and those of the devices it holds); `scopes`. A `KeyFault` says a `key` is no
        key of its kind."""
        where, args = _base_filters(kind, tuple(scopes))
        examined = self._db.execute(f"SELECT COUNT(*) FROM entry WHERE {where}", args).fetchone()[0]
        clauses, more = [where], list(args)
        number = _key_clause(kind, key, clauses, more) if key else None
        if device:
            keep = sorted(self._closure(device))
            marks = ",".join("?" * len(keep))
            clauses.append(f"(device IN ({marks}) OR (kind IN ('register','command') "
                           f"AND scope IN ({marks})) OR (kind = 'device' AND key = ?))")
            more += [*keep, *keep, device]
        asked = text.terms(words) if words else []
        if words and not asked:
            return Found(examined=examined)
        tiers = self._tiers(asked) if asked else {}
        first = "(kind = 'device' AND key = ?) DESC, " if device else ""
        rows = [(n, k, row_key) for n, k, row_key in self._db.execute(
            f"SELECT n, kind, key FROM entry WHERE {' AND '.join(clauses)} "
            f"ORDER BY {first}{_ORDER}", [*more, *([device] if device else [])])
            if (not asked or n in tiers) and (
                number is None or _prefix_of(kind, key, k, row_key))]
        if asked:
            rows.sort(key=lambda r: (not (device and r[1] == "device" and r[2] == device),
                                     tiers[r[0]]))
        found = Found(self._many([n for n, _, _ in rows[:limit]]), len(rows), examined)
        if not rows:
            found.nearest = self._nearest(where, args, number, asked,
                                          keys.call_bounds(kind, key) if key else None,
                                          keys.call_selector(kind, key) is not None)
        return found

    def _tiers(self, asked: list[text.Term]) -> dict[int, int]:
        """The entries that hold every word asked, each with the tier of its best field."""
        if self._fallback is not None:
            return self._fallback.tiers(asked)
        found: dict[int, int] = {}
        for tier in range(len(self.FIELDS) - 1, -1, -1):
            query = " AND ".join(t.fts(self.FIELDS[:tier + 1]) for t in asked)
            for (n,) in self._db.execute(
                    "SELECT rowid FROM entry_text WHERE entry_text MATCH ?", (query,)):
                found[n] = tier
        return found

    def _nearest(self, where: str, args: list[object], number: keys.Span | None,
                 asked: list[text.Term], bounds: tuple[tuple[int, ...], tuple[int, ...]] | None,
                 selected: bool) -> list[E]:
        if bounds is not None:
            first, last = bounds
            calls = [(keys.span("call", row_key).parts, n) for n, row_key in self._db.execute(
                f"SELECT n, key FROM entry WHERE {where} AND kind = 'call' ORDER BY n", args)]
            if selected and (of_it := [self._of(n) for parts, n in calls if parts == first]):
                return sorted(of_it, key=order)[:5]
            below = [c for c in calls if c[0][:len(first)] < first]
            above = [c for c in calls if c[0][:len(last)] > last]
            return [self._of(x[1]) for x in (max(below, key=lambda c: c[0], default=None),
                                             min(above, key=lambda c: c[0], default=None)) if x]
        if number is not None and number.lo is not None:
            below_row = self._db.execute(
                f"SELECT n FROM entry WHERE {where} AND hi < ? ORDER BY hi DESC, n LIMIT 1",
                [*args, number.lo]).fetchone()
            above_row = self._db.execute(
                f"SELECT n FROM entry WHERE {where} AND lo > ? ORDER BY lo, n LIMIT 1",
                [*args, number.hi]).fetchone()
            return [self._of(r[0]) for r in (below_row, above_row) if r]
        if asked:
            start = asked[0].word[:3]
            near = [self._of(n) for n, name in self._db.execute(
                f"SELECT n, name FROM entry WHERE {where}", args)
                if any(w.startswith(start) for w in text.words(name))]
            return sorted(near, key=order)[:5]
        return []


def _base_filters(kind: str, scopes: tuple[str, ...]) -> tuple[str, list[object]]:
    clauses: list[str] = ["1 = 1"]
    args: list[object] = []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if scopes:
        clauses.append(f"scope IN ({','.join('?' * len(scopes))})")
        args.extend(scopes)
    return " AND ".join(clauses), args


def _key_clause(kind: str, key: str, clauses: list[str], args: list[object]) -> keys.Span | None:
    """Adds the clause of a `key` and returns the numbers it asks for, None for a name."""
    bounds = keys.call_bounds(kind, key)
    if bounds is not None:
        first, last = bounds
        clauses.append("kind = 'call' AND lo <= ? AND hi >= ?")
        args.extend((last[0], first[0]))
        return keys.Span(first[0], last[0], first)
    if kind:
        canon, asked = keys.query(kind, key)
        if asked.lo is None:
            clauses.append("key = ?")
            args.append(canon)
            return None
        clauses.append("lo <= ? AND hi >= ?")
        args.extend((asked.hi, asked.lo))
        return asked
    loose = _loose(key)
    if loose is None:
        clauses.append("key = ?")
        args.append(key)
        return None
    clauses.append("(kind != 'call' AND lo <= ? AND hi >= ?)")
    args.extend((loose.hi, loose.lo))
    return loose


def _prefix_of(kind: str, key: str, row_kind: str, row_key: str) -> bool:
    """A call is asked by its leading parts, or by a range of them: `0x21` is every function of
    INT 21h, `0x21/0x4C` that function and what it takes in AL."""
    bounds = keys.call_bounds(kind, key)
    if row_kind != "call" or bounds is None:
        return True
    first, last = bounds
    row_span = keys.span("call", row_key)
    mine = row_span.parts
    if not (first <= mine[:len(first)] and mine[:len(last)] <= last):
        return False
    picked = keys.call_selector(kind, key)
    return picked is None or (row_span.selector is not None and mine == first
                              and row_span.selector.overlaps(picked))


def order(e: Keyed) -> tuple[str, str, bool, int, str, str]:
    """`_ORDER` in Python, for the lists the database does not sort."""
    return e.scope, e.kind, e.lo is None, e.lo or 0, e.key, e.access


def _loose(text_: str) -> keys.Span | None:
    """A key typed with no kind: a number (`0x21`, `5`), a range of them or a `SEG:OFF`; None
    when it is a name."""
    text_ = text_.strip()
    try:
        if ":" in text_:
            return keys.query("memory", text_)[1]
        if ".." in text_:
            first, _, last = text_.partition("..")
            if ".." in last:
                return None
            lo = _loose(first)
            hi = _loose(last)
            if lo is None or hi is None or lo.lo is None or hi.lo is None or hi.lo < lo.lo:
                return None
            return keys.Span(lo.lo, hi.lo)
        number = (int(text_[2:], 16) if text_[:2].lower() == "0x" and len(text_) <= 14
                  else keys.decimal(text_, "a number"))
    except (ValueError, keys.KeyFault):
        return None
    return keys.Span(number, number, (number,)) if keys.fits(number) else None
