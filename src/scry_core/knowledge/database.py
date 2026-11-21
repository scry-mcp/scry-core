"""The base: every dictionary a server ships, loaded once into an SQLite database in memory.

The files are text in git and the only copy; nothing is written to disk and nothing is rebuilt by
hand. The database is the only copy in memory too: an `Entry` is built from its row when it is
asked for, so what a server holds is the rows and no Python object per entry. A lookup is an
indexed read (by id, by key, by range of numbers or addresses, by alias, by device) and a text
search asks FTS5 when the host's SQLite has it, else an index kept in Python that only such a host
builds. `faults` lists what a file or an entry got wrong: a run is lenient (the bad entry is
skipped and counted) and the tests are strict (`faults()` must be empty).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from scry_core.knowledge import entry as fmt
from scry_core.knowledge import keys, text

#: A package's dictionaries sit in its `knowledge` directory, subdirectories included.
DIRECTORY = "knowledge"
_SCHEMA = """
CREATE TABLE entry (
  n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, scope TEXT NOT NULL, kind TEXT NOT NULL,
  key TEXT NOT NULL, access TEXT NOT NULL, lo INTEGER, hi INTEGER,
  a_lo INTEGER, a_hi INTEGER, name TEXT NOT NULL, device TEXT NOT NULL, h INTEGER NOT NULL,
  body TEXT NOT NULL);
CREATE TABLE alias (alias TEXT NOT NULL, n INTEGER NOT NULL);
CREATE TABLE relation (n INTEGER NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL,
                       PRIMARY KEY (n, rel, target)) WITHOUT ROWID;
CREATE TABLE device_port (n INTEGER NOT NULL, lo INTEGER NOT NULL, hi INTEGER NOT NULL);
CREATE INDEX entry_exact ON entry (kind, key, scope);
CREATE INDEX entry_range ON entry (kind, scope, lo, hi);
CREATE INDEX entry_address ON entry (scope, a_lo, a_hi);
CREATE INDEX entry_device ON entry (device, kind, lo);
CREATE INDEX alias_exact ON alias (alias);
CREATE INDEX relation_target ON relation (rel, target);
CREATE INDEX device_port_range ON device_port (lo, hi);
"""
_COLUMNS = "n, id, scope, kind, key, access, lo, hi, a_lo, a_hi, name, device, h, body"
_FTS = ("CREATE VIRTUAL TABLE entry_text USING fts5 (name, aliases, description, behaviour, "
        "content='', tokenize='unicode61 remove_diacritics 2', detail=column)")
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


def _body(e: fmt.Entry) -> str:
    """The fields of `e` no query reads, as compact JSON: the part of the row `_entry` reverses."""
    body: dict[str, Any] = {"description": e.description, "behaviour": e.behaviour,
                            "digest": e.digest,
                            "sources": [[s.role, s.ref, s.cites] for s in e.sources]}
    for name in ("aliases", "differs", "address", "length", "ports", "irq", "dma", "contains",
                 "classes"):
        value = getattr(e, name)
        if value not in ((), "", None):
            body[name] = value
    if e.handlers is not None:
        body["handlers"] = dict(e.handlers)
    if e.checked is not None:
        body["checked"] = [e.checked.by, e.checked.writer, e.checked.digest,
                           [list(a) for a in e.checked.against]]
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


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
        self._count = 0
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self.uses_fts5 = fts5 is not False and self._create_fts()
        self._fallback = None if self.uses_fts5 else text.Fallback()
        for source in sources:
            self._read(source)
        if self._fallback is not None:
            self._fallback.freeze()
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

    def _create_fts(self) -> bool:
        try:
            self._db.execute(_FTS)
        except sqlite3.OperationalError:
            return False
        return True

    def _read(self, source: str | Path) -> None:
        try:
            for name, body in _files(source):
                self._read_file(f"{source}/{name}" if isinstance(source, str) else name, body)
        except (OSError, ModuleNotFoundError) as bad:
            self.file_faults.append(f"{source}: no dictionaries could be read: {bad}")

    def _read_file(self, label: str, body: str) -> None:
        try:
            doc = json.loads(body)
        except json.JSONDecodeError as bad:
            self.file_faults.append(f"{label}: not JSON: {bad}")
            return
        header, bad_header = fmt.parse_header(doc, label)
        self.file_faults.extend(bad_header)
        if header is None:
            return
        self.dictionaries.append(header)
        for raw in doc["entries"]:
            self._add(header, len(self.dictionaries) - 1, raw)

    def _add(self, header: fmt.Header, h: int, raw: object) -> None:
        got, faults = fmt.parse_entry(raw, header)
        where = f"{header.dictionary} {raw.get('key', '?') if isinstance(raw, dict) else '?'}"
        self.entry_faults.extend(f"{where}: {f}" for f in faults)
        if got is None:
            return
        clash = self._overlap(got, h)
        if clash:
            self.load_faults.append(f"{where}: {got.id} overlaps {clash} in its dictionary and "
                                    "access does not tell them apart; the second is skipped")
            return
        added = self._db.execute(
            f"INSERT OR IGNORE INTO entry ({_COLUMNS}) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (got.id, got.scope, got.kind, got.key, got.access, got.lo, got.hi, got.a_lo, got.a_hi,
             got.name, got.device, h, _body(got)))
        if not added.rowcount:
            self.load_faults.append(f"{where}: the id {got.id} is already an entry; the "
                                    "second is skipped")
            return
        n = added.lastrowid
        assert n is not None
        self._count += 1
        self._db.executemany("INSERT INTO alias VALUES (?,?)",
                             [(a, n) for a in sorted({a.casefold() for a in
                                                     (got.name, *got.aliases)})])
        self._db.executemany("INSERT OR IGNORE INTO relation VALUES (?,?,?)", [
            (n, rel, str(t)) for rel, ts in (("contains", got.contains), ("irq", got.irq),
                                             ("dma", got.dma)) for t in ts])
        self._db.executemany("INSERT INTO device_port VALUES (?,?,?)",
                             [(n, b, b + length - 1) for b, length in got.ports])
        fields = {"name": got.name, "aliases": " ".join(got.aliases),
                  "description": got.description, "behaviour": got.behaviour}
        words = {k: text.words(v) for k, v in fields.items()}
        if self._fallback is None:
            self._db.execute("INSERT INTO entry_text (rowid, name, aliases, description, "
                             "behaviour) VALUES (?,?,?,?,?)",
                             (n, *(" ".join(w) for w in words.values())))
        else:
            self._fallback.add(n, {k: set(w) for k, w in words.items()})

    def _overlap(self, got: fmt.Entry, h: int) -> str:
        """The id of an entry already loaded from the same dictionary whose numbers overlap `got`'s
        and whose access does not differ from its own: only registers and commands, whose banks
        must name one entry for a number (a memory area may hold another)."""
        if got.kind not in ("register", "command"):
            return ""
        for id_, access in self._db.execute(
                "SELECT id, access FROM entry WHERE kind = ? AND scope = ? AND h = ? "
                "AND lo <= ? AND hi >= ? ORDER BY n", (got.kind, got.scope, h, got.hi, got.lo)):
            if id_ != got.id and not (access and got.access and access != got.access):
                return str(id_)
        return ""

    def _entry(self, row: Sequence[Any]) -> fmt.Entry:
        """The entry of one row of `_COLUMNS`."""
        n, id_, scope, kind, key, access, lo, hi, a_lo, a_hi, name, device, h, body = row
        got = json.loads(body)
        header = self.dictionaries[h]
        check = got.get("checked")
        return fmt.Entry(
            id=id_, scope=scope, kind=kind, key=key, name=name, description=got["description"],
            behaviour=got["behaviour"],
            sources=tuple(fmt.Source(*s) for s in got["sources"]), dictionary=header.dictionary,
            digest=got["digest"], aliases=tuple(got.get("aliases", ())),
            differs=got.get("differs", ""), address=got.get("address"),
            length=got.get("length"), access=access, device=device,
            ports=tuple((b, length) for b, length in got.get("ports", ())),
            irq=tuple(got.get("irq", ())), dma=tuple(got.get("dma", ())),
            contains=tuple(got.get("contains", ())), classes=tuple(got.get("classes", ())),
            handlers=got.get("handlers"), reached=header.reached,
            checked=fmt.Check(check[0], check[1], tuple((r, line) for r, line in check[3]),
                              check[2]) if check else None, lo=lo, hi=hi, a_lo=a_lo, a_hi=a_hi)

    def _one(self, where: str, args: Sequence[object]) -> fmt.Entry | None:
        row = self._db.execute(f"SELECT {_COLUMNS} FROM entry WHERE {where}", args).fetchone()
        return self._entry(row) if row else None

    def _of(self, n: int) -> fmt.Entry:
        found = self._one("n = ?", (n,))
        assert found is not None
        return found

    def _many(self, numbers: Sequence[int]) -> list[fmt.Entry]:
        """The entries of `numbers`, in that order, in one read."""
        if not numbers:
            return []
        marks = ",".join("?" * len(numbers))
        built = {row[0]: self._entry(row) for row in self._db.execute(
            f"SELECT {_COLUMNS} FROM entry WHERE n IN ({marks})", numbers)}
        return [built[n] for n in numbers]

    def faults(self) -> list[str]:
        """Every fault of the files and the entries, one line each."""
        return [*self.file_faults, *self.entry_faults, *self.load_faults]

    def __len__(self) -> int:
        return self._count

    def entries(self) -> Iterator[fmt.Entry]:
        for row in self._db.execute(f"SELECT {_COLUMNS} FROM entry ORDER BY n"):
            yield self._entry(row)

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

    def by_id(self, id: str) -> fmt.Entry | None:
        return self._one("id = ?", (id,))

    def get(self, kind: str, key: str, scope: str, access: str = "") -> fmt.Entry | None:
        """The entry of `kind` and `key` (in the canonical spelling) in `scope`."""
        return self._one("kind = ? AND key = ? AND scope = ? AND access = ?",
                         (kind, key, scope, access))

    def at(self, address: int, scope: str = "") -> tuple[fmt.Entry, int] | None:
        """The entry that sits at `address` (a vector's slot, a memory area) in `scope` (any when
        empty), and how many bytes in it is: the narrowest area, the first of equals."""
        found = self._one("n = (SELECT n FROM entry WHERE a_lo <= ? AND a_hi >= ? AND "
                          "(? = '' OR scope = ?) ORDER BY a_hi - a_lo, n LIMIT 1)",
                          (address, address, scope, scope))
        if found is None:
            return None
        assert found.a_lo is not None
        return found, address - found.a_lo

    def by_alias(self, word: str) -> list[fmt.Entry]:
        rows = self._db.execute("SELECT n FROM alias WHERE alias = ? ORDER BY n",
                                (word.casefold(),)).fetchall()
        return [self._of(n) for (n,) in rows]

    def _devices(self, key: str) -> list[fmt.Entry]:
        """The device entries named `key`, in load order."""
        return [self._of(n) for (n,) in self._db.execute(
            "SELECT n FROM entry WHERE kind = 'device' AND key = ? ORDER BY n", (key,))]

    def device_entry(self, scope: str, key: str) -> fmt.Entry | None:
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
        tiers = self._tiers(asked) if asked else {}
        rows = [(n, k, row_key) for n, k, row_key in self._db.execute(
            f"SELECT n, kind, key FROM entry WHERE {' AND '.join(clauses)} ORDER BY {_ORDER}", more)
            if (not asked or n in tiers) and (
                number is None or self._prefix_of(kind, key, k, row_key))]
        if asked:
            rows.sort(key=lambda r: tiers[r[0]])
        found = Found(self._many([n for n, _, _ in rows[:limit]]), len(rows), examined)
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

    def _prefix_of(self, kind: str, key: str, row_kind: str, row_key: str) -> bool:
        """A call is asked by its leading parts, or by a range of them: `0x21` is every function
        of INT 21h, `0x21/0x4C` that function and what it takes in AL."""
        bounds = keys.call_bounds(kind, key)
        if row_kind != "call" or bounds is None:
            return True
        first, last = bounds
        mine = keys.span("call", row_key).parts
        return first <= mine[:len(first)] and mine[:len(last)] <= last

    def _tiers(self, asked: list[text.Term]) -> dict[int, int]:
        """The entries that hold every word asked, each with the tier of its best field: the
        name, then the aliases, the description, the behaviour (`text.FIELDS`)."""
        if self._fallback is not None:
            return self._fallback.tiers(asked)
        found: dict[int, int] = {}
        for tier in range(len(text.FIELDS) - 1, -1, -1):
            query = " AND ".join(t.fts(text.FIELDS[:tier + 1]) for t in asked)
            for (n,) in self._db.execute(
                    "SELECT rowid FROM entry_text WHERE entry_text MATCH ?", (query,)):
                found[n] = tier
        return found

    def _nearest(self, where: str, args: list[object], number: keys.Span | None,
                 asked: list[text.Term], bounds: tuple[tuple[int, ...], tuple[int, ...]] | None
                 ) -> list[fmt.Entry]:
        if bounds is not None:
            first, last = bounds
            calls = [(keys.span("call", row_key).parts, n) for n, row_key in self._db.execute(
                f"SELECT n, key FROM entry WHERE {where} AND kind = 'call' ORDER BY n", args)]
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
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT n FROM entry WHERE device = ?", (e.key,))]
        elif e.kind == "irq" and e.lo is not None:
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT n FROM relation WHERE rel = 'irq' AND target = ?", (str(e.lo),))]
        elif e.kind == "port" and e.lo is not None:
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT DISTINCT n FROM device_port WHERE lo <= ? AND hi >= ?", (e.lo, e.lo))]
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
        hits = self._db.execute("SELECT id, device FROM entry WHERE kind = 'port' AND key = ? "
                                "ORDER BY n", (wanted,)).fetchall()
        mine = [i for i, of in hits if device is not None and of == device.key]
        chosen = mine or [i for i, _ in hits]
        return chosen[0] if chosen else name


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
