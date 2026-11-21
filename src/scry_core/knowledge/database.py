"""The base: every dictionary a server ships, loaded once into an SQLite database in memory.

The files are text in git and the only copy; nothing is written to disk and nothing is rebuilt by
hand. A lookup is an indexed read (by id, by key, by range of numbers or addresses, by alias, by
device) and a text search asks FTS5 when the host's SQLite has it, else an index kept in Python.
`faults` lists what a file or an entry got wrong: a run is lenient (the bad entry is skipped and
counted) and the tests are strict (`faults()` must be empty).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from scry_core.knowledge import entry as fmt
from scry_core.knowledge import keys, text

#: A package's dictionaries sit in its `knowledge` directory, subdirectories included.
DIRECTORY = "knowledge"
_SCHEMA = """
CREATE TABLE entry (
  n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, kind TEXT NOT NULL,
  key TEXT NOT NULL, access TEXT NOT NULL, lo INTEGER, hi INTEGER,
  a_lo INTEGER, a_hi INTEGER, name TEXT NOT NULL, device TEXT NOT NULL, dictionary TEXT NOT NULL);
CREATE TABLE alias (alias TEXT NOT NULL, n INTEGER NOT NULL);
CREATE TABLE relation (n INTEGER NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL,
                       PRIMARY KEY (n, rel, target)) WITHOUT ROWID;
CREATE INDEX entry_exact ON entry (kind, key, scope);
CREATE INDEX entry_range ON entry (kind, scope, lo, hi);
CREATE INDEX entry_address ON entry (scope, a_lo, a_hi);
CREATE INDEX entry_device ON entry (device, kind, lo);
CREATE INDEX alias_exact ON alias (alias);
CREATE INDEX relation_target ON relation (rel, target);
"""
_FTS = ("CREATE VIRTUAL TABLE entry_text USING fts5 (name, aliases, description, behaviour, "
        "content='', tokenize='unicode61 remove_diacritics 2')")
_ORDER = "scope, kind, lo IS NULL, lo, key, access"


@dataclass
class Found:
    """What `search` answers: the first `limit` entries, how many matched, how many entries of that
    kind and scope were searched, and, when nothing matched, the nearest ones."""

    entries: list[fmt.Entry] = field(default_factory=list)
    total: int = 0
    examined: int = 0
    nearest: list[fmt.Entry] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.total > len(self.entries)


@dataclass(frozen=True)
class Relations:
    """What ties an entry to its hardware: its device, what a device holds, who uses it, and the
    ports a register is reached through."""

    device: fmt.Entry | None
    contains: tuple[fmt.Entry, ...]
    used_by: tuple[fmt.Entry, ...]
    reached: Mapping[str, tuple[str, ...]]


def _walk(folder: Traversable) -> Iterator[tuple[str, str]]:
    for item in sorted(folder.iterdir(), key=lambda i: i.name):
        if item.is_dir():
            yield from _walk(item)
        elif item.name.endswith(".json"):
            yield item.name, item.read_text(encoding="utf-8")


def _files(source: str | Path) -> Iterator[tuple[str, str]]:
    if isinstance(source, Path):
        if not source.is_dir():
            raise FileNotFoundError(f"no such directory: {source.name}")
        for path in sorted(source.rglob("*.json")):
            yield str(path.relative_to(source)), path.read_text(encoding="utf-8")
    else:
        yield from _walk(resources.files(source) / DIRECTORY)


class Base:
    """The dictionaries of `sources` (a package name, whose `knowledge` directory is read, or a
    directory), in the database. `fts5` is None to use FTS5 where the host has it, False to force
    the index of our own. `pins` are the commit or tag each source scheme is pinned to."""

    def __init__(self, sources: Sequence[str | Path] = (), fts5: bool | None = None,
                 pins: Mapping[str, str] | None = None) -> None:
        self.pins: Mapping[str, str] = dict(pins or {})
        self.dictionaries: list[fmt.Header] = []
        self.file_faults: list[str] = []
        self.entry_faults: list[str] = []
        self.load_faults: list[str] = []
        self._entries: list[fmt.Entry] = []
        self._tokens: list[dict[str, set[str]]] = []
        self._n: dict[str, int] = {}
        self._devices: dict[str, list[fmt.Entry]] = {}
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._fallback = text.Fallback()
        self.uses_fts5 = False
        self.raw: dict[str, dict[str, object]] = {}
        for source in sources:
            self._read(source)
        self._index(fts5 is not False)
        self._db.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        """Release the database; a base that is dropped is closed the same way."""
        self._db.close()

    def __del__(self) -> None:
        if hasattr(self, "_db"):
            self.close()

    @classmethod
    def load(cls, *sources: str | Path, fts5: bool | None = None,
             pins: Mapping[str, str] | None = None) -> Base:
        return cls(sources, fts5, pins)

    def _read(self, source: str | Path) -> None:
        try:
            files = list(_files(source))
        except (OSError, ModuleNotFoundError) as bad:
            self.file_faults.append(f"{source}: no dictionaries could be read: {bad}")
            return
        for name, body in files:
            label = f"{source}/{name}" if isinstance(source, str) else name
            try:
                doc = json.loads(body)
            except json.JSONDecodeError as bad:
                self.file_faults.append(f"{label}: not JSON: {bad}")
                continue
            header, bad_header = fmt.parse_header(doc, label)
            self.file_faults.extend(bad_header)
            if header is None:
                continue
            self.dictionaries.append(header)
            for raw in doc["entries"]:
                self._add(header, raw)

    def _add(self, header: fmt.Header, raw: object) -> None:
        got, faults = fmt.parse_entry(raw, header)
        where = f"{header.dictionary} {raw.get('key', '?') if isinstance(raw, dict) else '?'}"
        self.entry_faults.extend(f"{where}: {f}" for f in faults)
        if got is None:
            return
        if got.id in self.raw:
            self.load_faults.append(f"{where}: the id {got.id} is already an entry; the "
                                    "second is skipped")
            return
        assert isinstance(raw, dict)
        self.raw[got.id] = raw
        self._entries.append(got)

    def _index(self, want_fts5: bool) -> None:
        rows: list[tuple[object, ...]] = []
        aliases: list[tuple[str, int]] = []
        relations: list[tuple[int, str, str]] = []
        for n, e in enumerate(self._entries, 1):
            self._n[e.id] = n
            fields = {"name": e.name, "aliases": " ".join(e.aliases),
                      "description": e.description, "behaviour": e.behaviour}
            self._tokens.append({k: set(text.words(v)) for k, v in fields.items()})
            self._fallback.add(n, self._tokens[-1])
            rows.append((n, e.id, e.scope, e.kind, e.key, e.access, e.lo, e.hi, e.a_lo,
                         e.a_hi, e.name, e.device, e.dictionary))
            aliases.extend((a.casefold(), n) for a in (e.name, *e.aliases))
            relations.extend((n, rel, str(t)) for rel, ts in (
                ("contains", e.contains), ("irq", e.irq), ("dma", e.dma)) for t in ts)
            if e.kind == "device":
                self._devices.setdefault(e.key, []).append(e)
        self._fallback.freeze()
        self._db.executemany("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self._db.executemany("INSERT INTO alias VALUES (?,?)", aliases)
        self._db.executemany("INSERT OR IGNORE INTO relation VALUES (?,?,?)", relations)
        if want_fts5:
            try:
                self._db.execute(_FTS)
            except sqlite3.OperationalError:
                return
            self._db.executemany(
                "INSERT INTO entry_text (rowid, name, aliases, description, behaviour) "
                "VALUES (?,?,?,?,?)",
                [(n, e.name, " ".join(e.aliases), e.description, e.behaviour)
                 for n, e in enumerate(self._entries, 1)])
            self.uses_fts5 = True

    def faults(self) -> list[str]:
        """Every fault of the files and the entries, one line each."""
        return [*self.file_faults, *self.entry_faults, *self.load_faults]

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> Iterator[fmt.Entry]:
        return iter(self._entries)

    def scopes(self, kind: str = "") -> list[str]:
        """The scopes that hold entries (of `kind` when given), sorted."""
        return sorted({e.scope for e in self._entries if not kind or e.kind == kind})

    def kinds(self, scope: str = "") -> list[str]:
        """The kinds that have entries (in `scope` when given), in the order of `keys.KINDS`."""
        held = {e.kind for e in self._entries if not scope or e.scope == scope}
        return [k for k in keys.KINDS if k in held]

    def _of(self, n: int) -> fmt.Entry:
        return self._entries[n - 1]

    def by_id(self, id: str) -> fmt.Entry | None:
        row = self._db.execute("SELECT n FROM entry WHERE id = ?", (id,)).fetchone()
        return self._of(row[0]) if row else None

    def get(self, kind: str, key: str, scope: str, access: str = "") -> fmt.Entry | None:
        """The entry of `kind` and `key` (in the canonical spelling) in `scope`."""
        row = self._db.execute("SELECT n FROM entry WHERE kind = ? AND key = ? AND scope = ? "
                               "AND access = ?", (kind, key, scope, access)).fetchone()
        return self._of(row[0]) if row else None

    def at(self, address: int, scope: str = "") -> tuple[fmt.Entry, int] | None:
        """The entry that sits at `address` (a vector's slot, a memory area) in `scope` (any when
        empty), and how many bytes in it is: the narrowest area, the first of equals."""
        rows = self._db.execute(
            "SELECT n FROM entry WHERE a_lo <= ? AND a_hi >= ? AND (? = '' OR scope = ?) "
            "ORDER BY a_hi - a_lo, n LIMIT 1", (address, address, scope, scope)).fetchall()
        if not rows:
            return None
        found = self._of(rows[0][0])
        assert found.a_lo is not None
        return found, address - found.a_lo

    def by_alias(self, word: str) -> list[fmt.Entry]:
        rows = self._db.execute("SELECT n FROM alias WHERE alias = ? ORDER BY n",
                                (word.casefold(),)).fetchall()
        return [self._of(n) for (n,) in rows]

    def device_entry(self, scope: str, key: str) -> fmt.Entry | None:
        """The device `key`, as seen from `scope`: that scope's own, else the shared `chip` one,
        else the only one of the name."""
        held = self._devices.get(key, [])
        for wanted in (scope, "chip"):
            for e in held:
                if e.scope == wanted:
                    return e
        return held[0] if len(held) == 1 else None

    def device_keys(self) -> list[str]:
        return sorted(self._devices)

    def _closure(self, key: str) -> set[str]:
        seen, todo = set(), [key]
        while todo:
            at = todo.pop()
            if at in seen:
                continue
            seen.add(at)
            for e in self._devices.get(at, []):
                todo.extend(e.contains)
        return seen

    def search(self, kind: str = "", key: str = "", words: str = "", device: str = "",
               scopes: Iterable[str] = (), limit: int = 10) -> Found:
        """The entries that answer every filter given: `kind`; `key` (a number or a range read
        by number, an interrupt's functions, an input's or a device's name); `words` (every word,
        `*` for a prefix); `device` (its ports, lines, registers and commands, and those of the
        devices it holds); `scopes`. A `KeyFault` says a `key` is no key of its kind."""
        where, args = self._base_filters(kind, tuple(scopes))
        examined = self._db.execute(f"SELECT COUNT(*) FROM entry WHERE {where}", args).fetchone()[0]
        clauses, more = [where], list(args)
        number = self._key_clause(kind, key, clauses, more) if key else None
        if device:
            keep = sorted(self._closure(device))
            marks = ",".join("?" * len(keep))
            clauses.append(f"(device IN ({marks}) OR (kind IN ('register','command') "
                           f"AND scope IN ({marks})))")
            more += keep + keep
        asked = text.terms(words) if words else []
        if words and not asked:
            return Found(examined=examined)
        if asked and len(clauses) == 1 and not args:
            held = self._matching(asked)
            rows = sorted((self._of(n) for n in held), key=_order)
        else:
            rows = [self._of(n) for (n,) in self._db.execute(
                f"SELECT n FROM entry WHERE {' AND '.join(clauses)} ORDER BY {_ORDER}", more)]
            held = self._matching(asked) if asked else set()
            rows = [e for e in rows if self._n[e.id] in held] if asked else rows
        if number is not None:
            rows = [e for e in rows if self._prefix_of(kind, key, e)]
        if asked:
            rows.sort(key=lambda e: text.tier(asked, self._tokens[self._n[e.id] - 1]))
        found = Found(rows[:limit], len(rows), examined)
        if not rows:
            found.nearest = self._nearest(where, args, number, asked,
                                          keys.call_bounds(kind, key) if key else None)
        return found

    def _base_filters(self, kind: str, scopes: tuple[str, ...]) -> tuple[str, list[object]]:
        clauses: list[str] = ["1 = 1"]
        args: list[object] = []
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if scopes:
            clauses.append(f"scope IN ({','.join('?' * len(scopes))})")
            args.extend(scopes)
        return " AND ".join(clauses), args

    def _key_clause(self, kind: str, key: str, clauses: list[str],
                    args: list[object]) -> keys.Span | None:
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

    def _prefix_of(self, kind: str, key: str, e: fmt.Entry) -> bool:
        """A call is asked by its leading parts, or by a range of them: `0x21` is every function
        of INT 21h, `0x21/0x4C` that function and what it takes in AL."""
        bounds = keys.call_bounds(kind, key)
        if e.kind != "call" or bounds is None:
            return True
        first, last = bounds
        mine = keys.span("call", e.key).parts
        return first <= mine[:len(first)] and mine[:len(last)] <= last

    def _matching(self, asked: list[text.Term]) -> set[int]:
        if self.uses_fts5:
            query = " ".join(t.fts() for t in asked)
            return {n for (n,) in self._db.execute(
                "SELECT rowid FROM entry_text WHERE entry_text MATCH ?", (query,))}
        return self._fallback.find(asked)

    def _nearest(self, where: str, args: list[object], number: keys.Span | None,
                 asked: list[text.Term], bounds: tuple[tuple[int, ...], tuple[int, ...]] | None
                 ) -> list[fmt.Entry]:
        if bounds is not None:
            first, last = bounds
            calls = [(keys.span("call", e.key).parts, e) for e in (
                self._of(n) for (n,) in self._db.execute(
                    f"SELECT n FROM entry WHERE {where} AND kind = 'call'", args))]
            below = [c for c in calls if c[0][:len(first)] < first]
            above = [c for c in calls if c[0][:len(last)] > last]
            return [x[1] for x in (max(below, key=lambda c: c[0], default=None),
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
            near = [e for e in (self._of(n) for (n,) in self._db.execute(
                f"SELECT n FROM entry WHERE {where}", args))
                if any(w.startswith(start) for w in self._tokens[self._n[e.id] - 1]["name"])]
            return sorted(near, key=_order)[:5]
        return []

    def related(self, e: fmt.Entry) -> Relations:
        """The device of `e`, what it holds, who uses it, and the ports its registers go by."""
        device = None
        if e.device:
            device = self.device_entry(e.scope, e.device)
        elif e.kind in ("register", "command"):
            device = self.device_entry("", e.scope)
        contains = tuple(d for k in e.contains if (d := self.device_entry(e.scope, k)))
        used: list[fmt.Entry] = []
        if e.kind == "device":
            used = [x for x in self._entries if x.device == e.key]
        elif e.kind in ("irq", "port"):
            used = [d for d in self._entries if d.kind == "device" and (
                (e.kind == "irq" and e.lo in d.irq)
                or (e.kind == "port" and e.lo is not None and any(
                    b <= e.lo < b + n for b, n in d.ports)))]
        reached: dict[str, tuple[str, ...]] = {}
        for way, value in (e.reached or {}).items():
            names = [value] if isinstance(value, str) else list(value)
            reached[way] = tuple(self._port_id(device, n) for n in names)
        return Relations(device, contains, tuple(sorted(used, key=_order)), reached)

    def _port_id(self, device: fmt.Entry | None, name: str) -> str:
        """The id of the port entry a `reached` word names, else the word (a handler's name)."""
        if not name.lower().startswith("0x"):
            return name
        try:
            wanted = f"0x{int(name, 16):02X}"
        except ValueError:
            return name
        hits = [x for x in self._entries if x.kind == "port" and x.key == wanted]
        mine = [x for x in hits if device is not None and x.device == device.key]
        chosen = mine or hits
        return chosen[0].id if chosen else name


def _order(e: fmt.Entry) -> tuple[str, str, bool, int, str, str]:
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
