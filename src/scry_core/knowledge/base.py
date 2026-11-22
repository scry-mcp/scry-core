"""The base a server serves: its dictionaries written as rows (`scry-knowledge/2`), loaded once
into the database of `scry_core.knowledge.index`, the sealed entries only.

An entry is served when every part of it is sealed at the seal it gives now
(`scry_core.knowledge.sealed`); one held back keeps only its id, kind, key and device, to say it
exists. A served entry's rows live in their own table, in the order a reply shows them (the `doc`
rows, then each emulator's notes), with the verdict each emulator gave on each `doc` row, and the
full-text index holds the rows' text beside the names. No Python object is kept per entry: an
entry and its rows are built from the database when one is asked for.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Required, cast

from typing_extensions import TypedDict

from scry_core.knowledge import callees, keys, quote, rows, sealed, shared
from scry_core.knowledge.index import Found, Index, files
from scry_core.knowledge.sources import SCHEMES

__all__ = ["DIRECTORY", "Base", "dictionaries", "Cite", "EntryReply", "Found", "RowReply", "Served"]

#: A package's dictionaries of rows sit in its `knowledge_rows` directory.
DIRECTORY = "knowledge_rows"
#: The rows a whole entry shows; past it the reply is cut, the notes before the `doc` rows.
ROWS_SHOWN = 24
#: What a reply calls each verdict an emulator gives on a `doc` row.
VERDICT_WORDS = {"agrees": "as documented", "differs": "differs", "absent": "absent",
                 "unfollowed": "unfollowed"}
_EMULATOR_NAMES = {"dosbox-x": "DOSBox-X", "mame": "MAME"}
_RBIL = "Ralf Brown's Interrupt List"
_TABLES = """
CREATE TABLE row (e INTEGER NOT NULL, pos INTEGER NOT NULL, n TEXT NOT NULL, subject TEXT NOT NULL,
                  party TEXT NOT NULL, vs TEXT NOT NULL, about TEXT NOT NULL,
                  variant TEXT NOT NULL, state TEXT NOT NULL, text TEXT NOT NULL,
                  cites TEXT NOT NULL, PRIMARY KEY (e, pos)) WITHOUT ROWID;
CREATE TABLE verdict (e INTEGER NOT NULL, row TEXT NOT NULL, emulator TEXT NOT NULL,
                      class TEXT NOT NULL, PRIMARY KEY (e, row, emulator)) WITHOUT ROWID;
"""


class Cite(TypedDict, total=False):
    """Where a row's lines are: a `document` (its title) or an emulator's `file`, the `lines`,
    and in a row asked by its id the `url` that opens them. Never the text."""

    document: str
    file: str
    lines: Required[str]
    url: str


class RowReply(TypedDict, total=False):
    """One row as `knowledge_find` shows it: `vs` and `row` on a note, `verdicts` (emulator to
    `VERDICT_WORDS`) on a `doc` row an emulator judged."""

    n: Required[str]
    on: Required[str]
    of: Required[str]
    vs: str
    row: str
    variant: str
    state: str
    text: Required[str]
    cites: Required[list[Cite]]
    verdicts: dict[str, str]


class EntryReply(TypedDict, total=False):
    """An entry as `knowledge_find` answers it whole, or with the one row its id names:
    `source` only for an entry no official document answers, `rows_total` when the rows are cut,
    `sources` (each place once, with its `url`) on the whole entry."""

    id: Required[str]
    kind: Required[str]
    key: Required[str]
    name: Required[str]
    scope: Required[str]
    aliases: list[str]
    access: str
    source: str
    rows: Required[list[RowReply]]
    rows_total: int
    sources: list[dict[str, str]]


@dataclass(frozen=True)
class Served:
    """One entry as the base serves it; `h` is its dictionary's place in `Base.dictionaries`."""

    n: int
    id: str
    scope: str
    kind: str
    key: str
    access: str
    name: str
    aliases: tuple[str, ...]
    source: str
    h: int
    lo: int | None = None
    hi: int | None = None
    a_lo: int | None = None
    device: str = ""
    contains: tuple[str, ...] = ()

    def short(self) -> dict[str, Any]:
        """The row a list shows: `id`, `kind`, `key`, `name` and `scope`."""
        return {"id": self.id, "kind": self.kind, "key": self.key, "name": self.name,
                "scope": self.scope}


def _access(entry: rows.Entry, header: rows.Header) -> str:
    return entry.id.removeprefix(f"{header.scope}:{header.kind}:{entry.key}").lstrip(":")


def _shown(entry: rows.Entry, emulators: Sequence[str]) -> list[rows.Row]:
    """The rows in the order a reply shows them: the `doc` rows, then each emulator's notes."""
    return [r for party in ("doc", *emulators) for r in entry.rows if r.of == party]


def _verdicts(entry: rows.Entry, emulators: Sequence[str]) -> list[tuple[str, str, str]]:
    """(row, emulator, class) for each `doc` row an emulator gave a verdict on: several closures
    `agrees` on one row are one verdict."""
    docs = {r.n for r in entry.rows if r.of == "doc"}
    got: dict[tuple[str, str], str] = {}
    for r in entry.rows:
        if r.of in emulators and r.vs in rows.VERDICTS and r.row in docs:
            got.setdefault((r.row, r.of), r.vs)
    for c in entry.closed:
        if c.reason in rows.VERDICT_CLOSURES and c.party in emulators and c.row in docs:
            got.setdefault((c.row, c.party), c.reason)
    return [(n, emulator, what) for (n, emulator), what in sorted(got.items())]


def _documents(source: str | Path) -> dict[str, quote.Datasheet]:
    """The document table a source's quotes name: scry-core's and the source package's own."""
    if isinstance(source, Path):
        return quote.table_for(source / "dictionary.json")
    table = quote.default_datasheets()
    beside = resources.files(source) / "knowledge_index" / "datasheets.json"
    if beside.is_file():
        table.update(quote.parse_datasheets(beside.read_text(encoding="utf-8"),
                                            f"{source}/knowledge_index/datasheets.json"))
    return table


def dictionaries(source: str | Path) -> Iterator[tuple[str, rows.Dictionary | None, list[str]]]:
    """Each dictionary of rows of a source, with its label and its faults; the callee table that
    sits beside them is not one."""
    for name, body in files(source, DIRECTORY):
        if f'"{callees.FORMAT}"' in body:
            continue
        label = f"{source}/{name}" if isinstance(source, str) else name
        yield label, *rows.parse(body, label)


class Base(Index[Served]):
    """The dictionaries of rows of `sources` (a package name, whose `knowledge_rows` directory is
    read, or a directory), the entries `lock` seals. `fts5` is None to use FTS5 where the host has
    it, False to force the index of our own. `pins` are the commit or tag each emulator is read
    at, `knowledge.shared.PINS` when not given. With no `lock`, every entry is loaded: the view
    the checks of the files take (`unfiltered`), never a server's."""

    FIELDS = ("name", "aliases", "rows")
    EXTRA = ("aliases TEXT NOT NULL", "source TEXT NOT NULL")

    def __init__(self, sources: Sequence[str | Path], lock: sealed.Lock | None,
                 fts5: bool | None = None, pins: Mapping[str, str] | None = None) -> None:
        self._sources, self._fts5_asked = tuple(sources), fts5
        self.dictionaries: list[rows.Header] = []
        self.documents: dict[str, quote.Datasheet] = {}
        super().__init__(fts5, shared.PINS if pins is None else pins)
        self._db.executescript(_TABLES)
        for source in sources:
            self._read(source, lock)
        self._finish()

    @classmethod
    def load(cls, *sources: str | Path, lock: sealed.Lock, fts5: bool | None = None,
             pins: Mapping[str, str] | None = None) -> Base:
        return cls(sources, lock, fts5, pins)

    def unfiltered(self) -> Base:
        """The same dictionaries with every entry loaded, sealed or not."""
        return Base(self._sources, None, self._fts5_asked, self.pins)

    def _read(self, source: str | Path, lock: sealed.Lock | None) -> None:
        try:
            self.documents.update(_documents(source))
            for label, dictionary, faults in dictionaries(source):
                self.file_faults.extend(f"{label}: {f}" for f in faults)
                if dictionary is None:
                    continue
                self.dictionaries.append(dictionary.header)
                for entry in dictionary.entries:
                    self._add(dictionary, len(self.dictionaries) - 1, entry, lock)
        except (OSError, ModuleNotFoundError, ValueError) as bad:
            self.file_faults.append(f"{source}: no dictionaries could be read: {bad}")

    def _add(self, dictionary: rows.Dictionary, h: int, entry: rows.Entry,
             lock: sealed.Lock | None) -> None:
        header = dictionary.header
        span = keys.span(header.kind, entry.key)
        memory = header.kind == "memory"
        got = Served(0, entry.id, header.scope, header.kind, entry.key, _access(entry, header),
                     entry.name, entry.aliases, dictionary.source_of(entry), h, span.lo, span.hi,
                     span.lo if memory else None)
        if lock is not None and lock.standing(dictionary, entry) != sealed.SERVED:
            self._hold(got)
            return
        clash = self._clash(got, h)
        if clash:
            self.load_faults.append(f"{header.dictionary}: {clash}")
            return
        shown = _shown(entry, dictionary.emulators)
        n = self._insert(got, h, (json.dumps(list(entry.aliases)), got.source), entry.aliases,
                         {"name": entry.name, "aliases": " ".join(entry.aliases),
                          "rows": " ".join(r.text for r in shown)},
                         span.hi if memory else None)
        if n is None:
            self.load_faults.append(f"{header.dictionary}: the id {entry.id} is already an "
                                    "entry; the second is skipped")
            return
        self._db.executemany("INSERT INTO row VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            (n, pos, r.n, r.on, r.of, r.vs, r.row, r.variant, r.state, r.text,
             json.dumps([[q.ref, q.lines] for q in r.quotes], separators=(",", ":")))
            for pos, r in enumerate(shown)])
        self._db.executemany("INSERT INTO verdict VALUES (?,?,?,?)",
                             [(n, *v) for v in _verdicts(entry, dictionary.emulators)])

    def _entry(self, row: Sequence[Any]) -> Served:
        n, id_, scope, kind, key, access, lo, hi, a_lo, _, name, device, h, aliases, source = row
        return Served(n, id_, scope, kind, key, access, name, tuple(json.loads(aliases)), source,
                      h, lo, hi, a_lo, device)

    def _cite(self, ref: str, lines: str, whole: bool) -> Cite:
        """Where a quote is: the document's title and place, or the emulator's file and lines,
        with the URL to open; never the text."""
        scheme, file = quote.split_ref(ref)
        if scheme == "datasheet":
            held = self.documents.get(file)
            out: Cite = {"document": held.title if held else file, "lines": lines}
            url = held.url if held else ""
        elif scheme == "rbil61":
            out, url = {"document": f"{_RBIL}, {file}", "lines": lines}, SCHEMES[scheme].opens_at
        else:
            first, last = quote.span(lines)
            out = {"file": file, "lines": lines}
            pin = self.pins.get(scheme, "")
            url = (SCHEMES[scheme].opens_at.format(pin=pin, path=file)
                   + (f"#L{first}" if first == last else f"#L{first}-L{last}")) if pin else ""
        if whole and url:
            out["url"] = url
        return out

    def _rows(self, e: Served, only: str = "") -> list[RowReply]:
        verdicts: dict[str, dict[str, str]] = {}
        for n, emulator, what in self._db.execute(
                "SELECT row, emulator, class FROM verdict WHERE e = ? ORDER BY row, emulator",
                (e.n,)):
            verdicts.setdefault(n, {})[emulator] = VERDICT_WORDS[what]
        out = []
        for n, subject, party, vs, about, variant, state, said, cites in self._db.execute(
                "SELECT n, subject, party, vs, about, variant, state, text, cites FROM row "
                "WHERE e = ? AND (? = '' OR n = ?) ORDER BY pos", (e.n, only, only)):
            got: dict[str, Any] = {"n": n, "on": subject, "of": party}
            for field, value in (("vs", vs), ("row", about), ("variant", variant),
                                 ("state", state)):
                if value:
                    got[field] = value
            got["text"] = said
            got["cites"] = [self._cite(ref, lines, bool(only)) for ref, lines in json.loads(cites)]
            if n in verdicts and party == "doc":
                got["verdicts"] = verdicts[n]
            out.append(cast(RowReply, got))
        return out

    def _head(self, e: Served) -> EntryReply:
        out = cast(EntryReply, {**e.short(), "rows": []})
        if e.aliases:
            out["aliases"] = list(e.aliases)
        if e.access:
            out["access"] = e.access
        if e.source == "emulator":
            emulators = {r for (r,) in self._db.execute(
                "SELECT DISTINCT party FROM row WHERE e = ? AND party != 'doc'", (e.n,))}
            named = " and ".join(_EMULATOR_NAMES[p] for p in sorted(emulators)) or "an emulator"
            out["source"] = f"according to {named}'s source; no official document found"
        return out

    def whole(self, e: Served) -> EntryReply:
        """An entry whole: what the document says first, then each emulator's notes, each row
        with where its lines are and, on a `doc` row, each emulator's verdict; at most
        `ROWS_SHOWN` rows, the notes cut before the `doc` rows, and `sources` once each with
        the URL to open."""
        out = self._head(e)
        held = self._rows(e)
        out["rows"] = held[:ROWS_SHOWN]
        if len(held) > ROWS_SHOWN:
            out["rows_total"] = len(held)
        places: dict[str, dict[str, str]] = {}
        for ref, lines in ((c[0], c[1]) for (cites,) in self._db.execute(
                "SELECT cites FROM row WHERE e = ? ORDER BY pos", (e.n,))
                for c in json.loads(cites)):
            cited = self._cite(ref, lines, True)
            where = cited.get("document") or cited.get("file", "")
            if where not in places:
                places[where] = {"where": where, **({"url": cited["url"].split("#")[0]}
                                                    if "url" in cited else {})}
        out["sources"] = list(places.values())
        return out

    def row(self, id: str) -> EntryReply | None:
        """The row `<entry id>#<n>` with where each of its lines is, or None when there is no
        such row."""
        entry_id, mark, n = id.rpartition("#")
        e = self.by_id(entry_id) if mark and n else None
        if e is None:
            return None
        got = self._rows(e, n)
        if not got:
            return None
        out = self._head(e)
        out["rows"] = got
        return out
