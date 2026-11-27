"""The format `scry-knowledge/2`: an entry as rows that carry their evidence, and the command
`rows` (`python -m scry_core.knowledge.rows`) that stamps, lists, checks, reads and indexes
them.

A dictionary file holds a header (its source, the official documents and the lines of them that
are the programming model, what it covers, the code that answers its keys, what the build defines,
the engine functions it does not cover) and its entries. An entry is its `key`, `name` and
`aliases`, the `regions` that answer it (the official source's and each emulator's code), its
`rows` and the items it `closed`. A `doc` row states what the official source says; a row of an
emulator is a note beside it (`vs`). A quote is a location and a digest
(`scry_core.knowledge.quote`), so no file here holds source text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from scry_core.knowledge import keys
from scry_core.knowledge.callees import Callees
from scry_core.knowledge.callees import parse as parse_callees
from scry_core.knowledge.entry import (
    ACCESS,
    ALIAS_MAX,
    ALIASES_MAX,
    NAME_MAX,
    WITH_ACCESS,
    entry_id,
)
from scry_core.knowledge.quote import (
    BODY_LINES,
    PARTY,
    QUOTE_LINES,
    Datasheet,
    Invalid,
    Quote,
    Sources,
    span,
    split_ref,
    table_for,
)

FORMAT = "scry-knowledge/2"
PARTIES = ("doc", "dosbox-x", "mame")
EMULATORS = ("dosbox-x", "mame")
SOURCES = ("official", "emulator")
VERDICTS = ("differs", "absent")
VS = (*VERDICTS, "extra", "place")
#: The places a dictionary of an `emulator` source says it looked for an official document.
SEARCH_PLACES = ("mame-header", "maker", "bitsavers", "archive-org", "index")
SEARCH_WORDS = 30
TEXT_WORDS, QUOTES_PER_ROW, LINKS_PER_ROW, UNSEEN_WORDS = 30, 6, 4, 16
CLOSED_AS = ("log", "structure", "decode", "key", "build", "dead", "see-also", "version",
             "unseen", "preamble", "parent", "agrees", "unfollowed", "layout", "electrical",
             "elsewhere")
#: The closures that are an emulator's verdict on a `doc` row: it does what the row says, or the
#: row's behaviour goes through code the callee table does not follow.
VERDICT_CLOSURES = ("agrees", "unfollowed")
TITLE_WORDS = 10
OWNED = ("preamble", "parent", "elsewhere")
#: Reasons that close a line of an official document, and the one that closes an emulator's.
OFFICIAL_ONLY = ("layout", "electrical", "elsewhere")
DOCUMENT_REASONS = ("key", "see-also", "version", *OFFICIAL_ONLY)
PLACEMENT = ("address", "length", "device", "ports", "irq", "dma", "contains", "classes",
             "handlers")
#: Words a row's lines rarely support and a reader must look at (question 1 of the reader).
SWEEPING = ("always", "never", "only", "every")
STATES = ("undetermined",)

_HEADER_FIELDS = {"format", "dictionary", "title", "kind", "scope", "covers", "source", "documents",
                  "official", "searched", "closed", "handlers", "defines", "engine",
                  "entries"}
_ENTRY_FIELDS = {"key", "name", "aliases", "access", "source", "searched", "regions", "rows",
                 "closed", *PLACEMENT}
_ROW_FIELDS = {"n", "on", "of", "vs", "row", "variant", "text", "quotes", "state", "links"}
_REGION_FIELDS = {"ref", "function", "case", "value", "preamble", "lines"}
_CLOSED_FIELDS = {"ref", "lines", "as", "reason", "owner", "row", "nothing"}
_LABEL = re.compile(r"[A-Za-z0-9]{1,6}")
_BITS = r"bits \d+-\d+(?: = \S+)?|bit \d+|value \S+"
SUBJECTS: dict[str, str] = {
    "call": r"is|place|when|does|in \S+|out \S+",
    "register": rf"is|place|when|read|write|reset|order|{_BITS}",
    "command": rf"is|place|when|write|order|{_BITS}",
    "device": r"is|place|when|order|reset|detect|type \S+",
    "port": rf"is|place|read|write|{_BITS}",
    "vector": r"is|when|does|place",
    "irq": r"is|place|when",
    "memory": rf"is|place|{_BITS}",
    "error": r"is|place",
    "input": r"is|place|value \S+",
}
#: Subjects an entry of the kind must have a row on, each a set of which one is enough.
REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "call": (("is",), ("out",)),
    "register": (("is",), ("read", "write")),
    "command": (("is",), ("write",)),
    "device": (("is",), ("reset",)),
    "port": (("is",), ("place",)),
    "vector": (("is",),),
    "irq": (("is",),),
    "memory": (("is",), ("place",)),
    "error": (("is",),),
    "input": (("is",),),
}


@dataclass(frozen=True)
class Row:
    n: str
    on: str
    of: str
    text: str
    quotes: tuple[Quote, ...]
    vs: str = ""
    row: str = ""
    variant: str = ""
    state: str = ""
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class Region:
    """Code that answers a key: a function (the path of `case` labels to this key, the `value`
    the key takes in it, or just its statements before the dispatch) or a section of a list."""

    ref: str
    function: str = ""
    case: tuple[str, ...] = ()
    value: str = ""
    preamble: bool = False
    lines: str = ""


@dataclass(frozen=True)
class Closure:
    ref: str
    lines: str
    reason: str
    why: str = ""
    owner: str = ""
    row: str = ""
    #: An `agrees` whose whole body does nothing to what the row names: an early exit, an empty
    #: case, for a row that says something is left unchanged or nothing is returned.
    nothing: bool = False

    @property
    def party(self) -> str:
        return PARTY[split_ref(self.ref)[0]]

    @property
    def first(self) -> int:
        return span(self.lines)[0]

    @property
    def last(self) -> int:
        return span(self.lines)[1]


@dataclass(frozen=True)
class Entry:
    id: str
    key: str
    name: str
    aliases: tuple[str, ...]
    regions: tuple[Region, ...]
    rows: tuple[Row, ...]
    closed: tuple[Closure, ...]
    placed: bool = False
    source: str = ""
    searched: tuple[Search, ...] = ()


@dataclass(frozen=True)
class Document:
    """A row of the repository's document table that a dictionary relies on, and the part
    (`variant`) of the family it describes."""

    name: str
    variant: str


@dataclass(frozen=True)
class Search:
    """One place looked in for an official document, and what it gave."""

    where: str
    gave: str


@dataclass(frozen=True)
class Header:
    dictionary: str
    title: str
    kind: str
    scope: str
    covers: str
    source: str
    documents: tuple[Document, ...]
    official: Mapping[str, tuple[str, ...]]
    searched: tuple[Search, ...]
    closed: tuple[Closure, ...]
    handlers: tuple[Region, ...]
    defines: Mapping[str, tuple[str, ...]]
    engine: tuple[str, ...]


@dataclass(frozen=True)
class Dictionary:
    header: Header
    entries: tuple[Entry, ...]

    @property
    def emulators(self) -> tuple[str, ...]:
        """The emulators the dictionary has code of, in the header's handlers or in an entry's
        regions: each owes a verdict on every official row an entry states."""
        refs = [r.ref for r in self.header.handlers]
        refs += [r.ref for e in self.entries for r in e.regions]
        found = {PARTY[split_ref(ref)[0]] for ref in refs}
        return tuple(p for p in EMULATORS if p in found)

    def source_of(self, entry: Entry) -> str:
        return entry.source or self.header.source

    def regions(self, entry: Entry) -> tuple[Region, ...]:
        """The code that answers `entry`: the header's handlers, each with the key's own value
        in it, unless the entry names a region of that function, then the entry's own."""
        own = {(r.ref, r.function) for r in entry.regions}
        got = []
        for handler in self.header.handlers:
            if (handler.ref, handler.function) in own:
                continue
            value = ""
            if handler.value:
                numbers = keys.span(self.header.kind, entry.key)
                if numbers.lo is not None and numbers.hi is not None:
                    value = f"{handler.value}={numbers.lo}..{numbers.hi}"
            got.append(replace(handler, value=value))
        return (*got, *entry.regions)


def _listed(raw: dict[str, Any], name: str, where: str, faults: list[str]) -> list[Any]:
    got = raw.get(name, [])
    if not isinstance(got, list):
        faults.append(f"{where}: `{name}` is a list")
        return []
    return got


def _region(raw: object, where: str, faults: list[str]) -> Region | None:
    if not (isinstance(raw, dict) and isinstance(raw.get("ref"), str) and raw["ref"]
            and set(raw) <= _REGION_FIELDS):
        faults.append(f"{where} is `ref` with `function` (and `case`, `value`, `preamble`) or "
                      "`lines`")
        return None
    try:
        split_ref(raw["ref"])
        if "lines" in raw:
            span(raw["lines"])
    except (ValueError, TypeError) as bad:
        faults.append(f"{where}: {bad}")
        return None
    if ("lines" in raw) == ("function" in raw):
        faults.append(f"{where} is a function or a section of a list, one of the two")
        return None
    case = raw.get("case", [])
    if not (isinstance(case, list) and all(isinstance(c, str) and c for c in case)):
        faults.append(f"{where}: `case` is a list of labels")
        return None
    function, value = raw.get("function", ""), raw.get("value", "")
    if not (isinstance(function, str) and isinstance(value, str)):
        faults.append(f"{where}: `function` and `value` are text")
        return None
    preamble = raw.get("preamble", False)
    if not isinstance(preamble, bool):
        faults.append(f"{where}: `preamble` is true or false")
        return None
    return Region(raw["ref"], function, tuple(case), value, preamble, str(raw.get("lines", "")))


def _quote(raw: object, where: str, faults: list[str], limit: int = QUOTE_LINES) -> Quote | None:
    if not (isinstance(raw, dict) and set(raw) <= {"ref", "lines", "sha"}
            and isinstance(raw.get("ref"), str) and isinstance(raw.get("lines"), str)):
        faults.append(f"{where} is `ref`, `lines` and `sha`")
        return None
    try:
        split_ref(raw["ref"])
        first, last = span(raw["lines"])
    except ValueError as bad:
        faults.append(f"{where}: {bad}")
        return None
    if last - first + 1 > limit:
        faults.append(f"{where}: {raw['lines']} is {last - first + 1} lines, over {limit}")
    return Quote(raw["ref"], raw["lines"], str(raw.get("sha", "")))


def _note(where: str, of: str, on: str, vs: object, about: object, variant: object,
          faults: list[str]) -> None:
    """What `vs`, `row` and `variant` are on a row of `of`."""
    if of == "doc":
        if vs != "":
            faults.append(f"{where}: a `doc` row has no `vs`: only a note of an emulator has one")
        if on == "place":
            faults.append(f"{where}: `place` is how an emulator reaches the thing; what the "
                          "document says of it is `is`")
        if not isinstance(variant, str):
            faults.append(f"{where}: `variant` is text")
    elif variant != "":
        faults.append(f"{where}: only a `doc` row has a `variant`")
    if of in EMULATORS:
        if vs not in VS:
            faults.append(f"{where}: a note of an emulator has `vs`, one of {', '.join(VS)}")
        elif vs == "place" and on != "place":
            faults.append(f"{where}: `vs` place is on `place`")
    if vs in VERDICTS:
        if not (isinstance(about, str) and about):
            faults.append(f"{where}: `{vs}` names the `doc` row it is about, as `row`")
    elif about != "":
        faults.append(f"{where}: `row` goes with `differs` or `absent`, not with {vs or 'a doc'}")


def _row(raw: object, kind: str, where: str, faults: list[str]) -> Row | None:
    if not (isinstance(raw, dict) and set(raw) <= _ROW_FIELDS):
        faults.append(f"{where} is an object of {', '.join(sorted(_ROW_FIELDS))}")
        return None
    n, on, text = raw.get("n"), raw.get("on"), raw.get("text")
    mine = len(faults)
    if not (isinstance(n, str) and _LABEL.fullmatch(n)):
        faults.append(f"{where}: `n` is 1 to 6 letters or digits")
    if not (isinstance(on, str) and re.fullmatch(SUBJECTS[kind], on)):
        faults.append(f"{where}: `on` {on!r} is not a subject of a {kind}: {SUBJECTS[kind]}")
    if not (isinstance(text, str) and text.strip() == text and text and text.isascii()
            and text.isprintable()):
        faults.append(f"{where}: `text` is printable ASCII with no space around it")
    elif len(text.split()) > TEXT_WORDS:
        faults.append(f"{where}: `text` is {len(text.split())} words, over {TEXT_WORDS}")
    of = raw.get("of")
    if not (isinstance(of, str) and of in PARTIES):
        faults.append(f"{where}: `of` is one party of {', '.join(PARTIES)}")
        of = ""
    vs, about, variant = raw.get("vs", ""), raw.get("row", ""), raw.get("variant", "")
    _note(where, of, str(on), vs, about, variant, faults)
    state = raw.get("state", "")
    if state not in ("", *STATES):
        faults.append(f"{where}: `state` is absent or one of {', '.join(STATES)}")
    links = raw.get("links", [])
    if not (isinstance(links, list) and len(links) <= LINKS_PER_ROW
            and all(isinstance(x, str) and x for x in links)):
        faults.append(f"{where}: `links` is at most {LINKS_PER_ROW} entry ids")
        links = []
    raw_quotes = raw.get("quotes")
    quotes: list[Quote] = []
    if not (isinstance(raw_quotes, list) and 1 <= len(raw_quotes) <= QUOTES_PER_ROW):
        faults.append(f"{where}: 1 to {QUOTES_PER_ROW} `quotes`")
    else:
        limit = BODY_LINES if vs == "absent" else QUOTE_LINES
        got = (_quote(q, f"{where}, quote {i + 1}", faults, limit)
               for i, q in enumerate(raw_quotes))
        quotes = [q for q in got if q]
    if len(faults) != mine:
        return None
    return Row(str(n), str(on), str(of), str(text), tuple(quotes), str(vs), str(about),
               str(variant), str(state), tuple(links))


def _closure(raw: object, where: str, faults: list[str]) -> Closure | None:
    if not (isinstance(raw, dict) and set(raw) <= _CLOSED_FIELDS
            and isinstance(raw.get("ref"), str) and isinstance(raw.get("lines"), str)):
        faults.append(f"{where} is `ref`, `lines`, `as` and, where it needs one, `reason` or "
                      "`owner`")
        return None
    reason = raw.get("as")
    try:
        split_ref(raw["ref"])
        span(raw["lines"])
    except ValueError as bad:
        faults.append(f"{where}: {bad}")
        return None
    if reason not in CLOSED_AS:
        faults.append(f"{where}: `as` {reason!r} is no reason of the set: "
                      f"{', '.join(CLOSED_AS)}")
        return None
    why, owner, row = raw.get("reason", ""), raw.get("owner", ""), raw.get("row", "")
    party = PARTY[split_ref(raw["ref"])[0]]
    if reason in VERDICT_CLOSURES and not (party in EMULATORS and isinstance(row, str) and row):
        faults.append(f"{where}: `{reason}` closes lines of an emulator and names the `doc` row "
                      "they are a verdict on, as `row`")
        return None
    if reason not in VERDICT_CLOSURES and row != "":
        faults.append(f"{where}: `row` goes with `agrees` or `unfollowed` only")
        return None
    nothing = raw.get("nothing", False)
    if nothing is not False and not (nothing is True and reason == "agrees"):
        faults.append(f"{where}: `nothing` is `true` on an `agrees`, or absent")
        return None
    if party == "doc" and reason not in DOCUMENT_REASONS:
        faults.append(f"{where}: `{reason}` is about an emulator's code; a line of an official "
                      f"document is closed as {', '.join(DOCUMENT_REASONS)}")
        return None
    if reason in OFFICIAL_ONLY and party != "doc":
        faults.append(f"{where}: `{reason}` closes a line of an official document")
        return None
    if reason == "unseen" and not (isinstance(why, str) and 0 < len(why.split()) <= UNSEEN_WORDS):
        faults.append(f"{where}: `unseen` needs a `reason` of at most {UNSEEN_WORDS} words")
        return None
    if reason in OWNED and not (isinstance(owner, str) and owner):
        faults.append(f"{where}: `{reason}` names the entry that owns the line, as `owner`")
        return None
    return Closure(raw["ref"], raw["lines"], reason, str(why), str(owner), str(row), nothing)


def _entry(raw: object, header: Header, where: str, faults: list[str]) -> Entry | None:
    if not isinstance(raw, dict):
        faults.append(f"{where} is an object")
        return None
    extra = sorted(set(raw) - _ENTRY_FIELDS)
    if extra:
        faults.append(f"{where}: no field {', '.join(extra)}")
    try:
        key = keys.canonical(header.kind, raw.get("key", ""))
    except keys.KeyFault as bad:
        faults.append(f"{where}: {bad}")
        return None
    if key != raw["key"]:
        faults.append(f"{where}: the key is written {key}")
    access = raw.get("access", "")
    judged = isinstance(access, str) and (
        not access or (access in ACCESS and header.kind in WITH_ACCESS))
    ident = entry_id(header.scope, header.kind, key, access if judged else "")
    where = ident
    if not judged:
        faults.append(f"{where}: `access` is `read` or `write`, and only for a port, a register "
                      "or a command")
    name, aliases = raw.get("name"), raw.get("aliases", [])
    if not (isinstance(name, str) and name and len(name) <= NAME_MAX and name.isascii()
            and name.isprintable()):
        faults.append(f"{where}: `name` is printable ASCII, at most {NAME_MAX} characters")
    if not (isinstance(aliases, list) and len(aliases) <= ALIASES_MAX and all(
            isinstance(a, str) and a and len(a) <= ALIAS_MAX for a in aliases)):
        faults.append(f"{where}: `aliases` is at most {ALIASES_MAX} names of at most "
                      f"{ALIAS_MAX} characters")
        aliases = []
    regions = [_region(r, f"{where}, region {i + 1}", faults)
               for i, r in enumerate(_listed(raw, "regions", where, faults))]
    closed = [_closure(c, f"{where}, closed {i + 1}", faults)
              for i, c in enumerate(_listed(raw, "closed", where, faults))]
    listed = raw.get("rows")
    rows: list[Row | None] = []
    if not (isinstance(listed, list) and listed):
        faults.append(f"{where}: `rows` is a list with at least one row")
    else:
        rows = [_row(r, header.kind, f"{where}, row {i + 1}", faults)
                for i, r in enumerate(listed)]
    made = [r for r in rows if r]
    labels = [r.n for r in made]
    if len(set(labels)) != len(labels):
        faults.append(f"{where}: two rows share a label")
    placed = any(f in raw for f in PLACEMENT)
    source = raw.get("source", "")
    if source not in ("", *SOURCES):
        faults.append(f"{where}: `source` is one of {', '.join(SOURCES)}")
        source = ""
    searched = _searched(raw, where, faults)
    effective = source or header.source
    if effective == "emulator":
        _emulator_entry(made, where, faults)
        if not (searched or header.searched):
            faults.append(f"{where}: an `emulator` source says where it searched, as `searched`")
    elif searched:
        faults.append(f"{where}: `searched` goes with an `emulator` source")
    _required(made, header.kind, ident, placed, effective, faults)
    return Entry(ident, key, str(name), tuple(aliases), tuple(r for r in regions if r),
                 tuple(made), tuple(c for c in closed if c), placed, str(source), searched)


def _emulator_entry(rows: list[Row], where: str, faults: list[str]) -> None:
    """An entry no official document answers has the emulator's rows only, as notes of what it
    does where the document is silent."""
    for r in rows:
        if r.of == "doc":
            faults.append(f"{where}, row {r.n}: an `emulator` source has no `doc` row")
        elif r.vs not in ("extra", "place"):
            faults.append(f"{where}, row {r.n}: with no official document a note is `extra` or "
                          "`place`")


def _required(rows: list[Row], kind: str, ident: str, placed: bool, source: str,
              faults: list[str]) -> None:
    """The subjects a row of the entry is on: what the document says, or in an `emulator` entry
    what the emulator does; a `place` is the emulator's in either."""
    stated = [r for r in rows if r.of == "doc" or source == "emulator"]
    subjects = {r.on.split(" ")[0] for r in stated}
    places = {r.on for r in rows}
    wanted = list(REQUIRED[kind])
    if placed and ("place",) not in wanted:
        wanted.append(("place",))
    for options in wanted:
        if not (subjects | (places if "place" in options else set())) & set(options):
            faults.append(f"{ident}: a {kind} needs a row on {' or '.join(options)}")


def _searched(raw: dict[str, Any], where: str, faults: list[str]) -> tuple[Search, ...]:
    """Each place of the fixed list with what it gave, or no `searched` at all."""
    got = raw.get("searched")
    if got is None:
        return ()
    ok = isinstance(got, list) and all(
        isinstance(g, dict) and set(g) == {"where", "gave"} and isinstance(g["where"], str)
        and isinstance(g["gave"], str) for g in got)
    if not ok:
        faults.append(f"{where}: `searched` lists `where` and `gave`")
        return ()
    made = tuple(Search(g["where"], g["gave"]) for g in got)
    if sorted(m.where for m in made) != sorted(SEARCH_PLACES):
        faults.append(f"{where}: `searched` has each place once: {', '.join(SEARCH_PLACES)}")
    for m in made:
        if not (0 < len(m.gave.split()) <= SEARCH_WORDS and m.gave.isascii()
                and m.gave.isprintable()):
            faults.append(f"{where}: what `{m.where}` gave is printable ASCII of 1 to "
                          f"{SEARCH_WORDS} words")
    return made


def _documents(doc: dict[str, Any], faults: list[str]) -> tuple[Document, ...]:
    listed = _listed(doc, "documents", "header", faults)
    made = []
    for i, raw in enumerate(listed):
        if not (isinstance(raw, dict) and set(raw) == {"name", "variant"}
                and all(isinstance(v, str) and v for v in raw.values())):
            faults.append(f"documents {i + 1} is `name` and `variant`")
        else:
            made.append(Document(raw["name"], raw["variant"]))
    if len(set(made)) != len(made):
        faults.append("`documents` names a document and variant twice")
    return tuple(made)


def _official(doc: dict[str, Any], documents: tuple[Document, ...],
              faults: list[str]) -> dict[str, tuple[str, ...]]:
    """The lines of each document's capture that are the programming model."""
    got = doc.get("official", {})
    if not isinstance(got, dict):
        faults.append("`official` maps a document to the line ranges of its programming model")
        return {}
    made: dict[str, tuple[str, ...]] = {}
    named = {d.name for d in documents}
    for name, ranges in got.items():
        try:
            if not (isinstance(ranges, list) and ranges):
                raise ValueError("a list of ranges")
            held = sorted(span(r) for r in ranges)
        except (ValueError, TypeError):
            faults.append(f"`official` of {name} is a list of `a-b` ranges")
            continue
        if any(b[0] <= a[1] for a, b in zip(held, held[1:], strict=False)):
            faults.append(f"`official` of {name} has ranges that overlap")
        if name not in named:
            faults.append(f"`official` names {name}, which `documents` does not")
        made[name] = tuple(ranges)
    for name in sorted(named - set(made)):
        faults.append(f"`documents` names {name} and `official` gives it no range")
    return made


def _header(doc: dict[str, Any], faults: list[str]) -> Header | None:
    extra = sorted(set(doc) - _HEADER_FIELDS)
    if extra:
        faults.append(f"no header field {', '.join(extra)}")
    kind, scope = doc.get("kind"), doc.get("scope")
    if kind not in keys.KINDS or kind not in SUBJECTS:
        faults.append(f"`kind` is one of {', '.join(SUBJECTS)}")
        return None
    if not (isinstance(scope, str) and scope and isinstance(doc.get("dictionary"), str)
            and isinstance(doc.get("covers"), str)):
        faults.append("`dictionary`, `scope` and `covers` are text")
        return None
    title = doc.get("title")
    if not (isinstance(title, str) and title.strip() == title and title.isascii()
            and title.isprintable() and 0 < len(title.split()) <= TITLE_WORDS):
        faults.append(f"`title` names what the dictionary covers in 1 to {TITLE_WORDS} words of "
                      "printable ASCII")
        title = ""
    source = doc.get("source")
    if source not in SOURCES:
        faults.append(f"`source` is one of {', '.join(SOURCES)}")
        source = "official"
    documents = _documents(doc, faults)
    official = _official(doc, documents, faults)
    searched = _searched(doc, "header", faults)
    closed = tuple(c for i, raw in enumerate(_listed(doc, "closed", "header", faults))
                   if (c := _closure(raw, f"header, closed {i + 1}", faults)))
    for c in closed:
        if c.party != "doc":
            faults.append(f"header, closed {c.ref}:{c.lines}: a dictionary closes lines of an "
                          "official document")
    handlers = [_region(h, f"handler {i + 1}", faults)
                for i, h in enumerate(_listed(doc, "handlers", "header", faults))]
    defines = doc.get("defines", {})
    engine = doc.get("engine", [])
    if not (isinstance(defines, dict) and set(defines) <= set(PARTIES)
            and all(isinstance(v, list) for v in defines.values())):
        faults.append("`defines` maps a party to the names its build defines")
        defines = {}
    if not (isinstance(engine, list) and all(isinstance(e, str) for e in engine)):
        faults.append("`engine` is a list of function names")
        engine = []
    return Header(doc["dictionary"], str(title), kind, scope, doc["covers"], source, documents,
                  official, searched, closed, tuple(h for h in handlers if h),
                  {k: tuple(v) for k, v in defines.items()}, tuple(engine))


def parse(text: str, where: str = "dictionary") -> tuple[Dictionary | None, list[str]]:
    """The dictionary a file holds and every fault it has, so a person fixes it in one pass; the
    dictionary is None when its header is unreadable."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        return None, [f"{where} is not JSON: {bad}"]
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return None, [f"{where} is not a `{FORMAT}` document"]
    faults: list[str] = []
    header = _header(doc, faults)
    listed = doc.get("entries")
    if header is None or not isinstance(listed, list):
        return None, [*faults, *([] if isinstance(listed, list) else ["`entries` is a list"])]
    entries = [_entry(e, header, f"entry {i + 1}", faults) for i, e in enumerate(listed)]
    made = tuple(e for e in entries if e)
    ids = [e.id for e in made]
    if len(set(ids)) != len(ids):
        faults.append("two entries share an id")
    return Dictionary(header, made), faults


def read(path: Path) -> tuple[Dictionary | None, list[str]]:
    return parse(path.read_text(encoding="utf-8"), path.name)


def _callees(got: argparse.Namespace) -> Callees:
    """The table `--callees` names, or the `callees.json` beside the dictionary, or none."""
    path = got.callees or got.dictionary.parent / "callees.json"
    if not (got.callees or path.is_file()):
        return Callees()
    return parse_callees(path.read_text(encoding="utf-8"), path.name)


def _known(dictionary: Dictionary, path: Path) -> tuple[dict[str, Entry], dict[str, Dictionary]]:
    """The entries an owner may be, this dictionary's and those of the dictionaries beside it (a
    chip's registers and its device are two files), and the dictionary of each of the others."""
    known = {e.id: e for e in dictionary.entries}
    homes: dict[str, Dictionary] = {}
    for other in sorted(path.parent.glob("*.json")):
        if other.resolve() == path.resolve():
            continue
        text = other.read_text(encoding="utf-8")
        if f'"{FORMAT}"' not in text:
            continue
        beside, _ = parse(text, other.name)
        if beside is None:
            continue
        for e in beside.entries:
            if e.id not in known:
                known[e.id], homes[e.id] = e, beside
    return known, homes


def _sources(got: argparse.Namespace) -> Sources:
    """The pinned sources, and the documents of this package's table and of the table of the
    package that holds the dictionary."""
    held = getattr(got, "dictionary", None) or getattr(got, "stamp", None)
    return Sources(mame=got.mame, dosbox=got.dosbox, rbil=got.rbil, datasheets=got.datasheets,
                   table=table_for(held) if held else None)


def _chosen(dictionary: Dictionary, wanted: Sequence[str]) -> list[Entry]:
    if not wanted:
        return list(dictionary.entries)
    by_id = {e.id: e for e in dictionary.entries}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise Invalid(f"no entry {', '.join(missing)} in the dictionary")
    return [by_id[w] for w in wanted]


def _objects(value: object, name: str, path: Path) -> list[dict[str, Any]]:
    """The objects `value` holds, or `Invalid`: a file whose shape `--stamp` cannot walk is a
    bad file, not a traceback."""
    if not (isinstance(value, list) and all(isinstance(v, dict) for v in value)):
        raise Invalid(f"{path.name}: `{name}` is a list of objects")
    return value


def _stamp_file(path: Path, sources: Sources) -> tuple[int, int]:
    """Writes the digest into every quote of `path` that has none; returns how many it stamped
    and how many already held one. The file is parsed before it is walked, so a wrong type is
    `Invalid` and never an `AttributeError`."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as bad:
        raise Invalid(f"{path.name} is not JSON: {bad}") from bad
    if not isinstance(doc, dict):
        raise Invalid(f"{path.name}: a dictionary is a JSON object")
    stamped = held = 0
    for entry in _objects(doc.get("entries", []), "entries", path):
        for row in _objects(entry.get("rows", []), "rows", path):
            for q in _objects(row.get("quotes", []), "quotes", path):
                if not (isinstance(q.get("ref"), str) and isinstance(q.get("lines"), str)):
                    raise Invalid(f"{path.name}: a quote is `ref` and `lines`, both text")
                if q.get("sha"):
                    held += 1
                    continue
                q["sha"] = sources.stamped(q["ref"], q["lines"]).sha
                stamped += 1
    if stamped:
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                        newline="\n")
    return stamped, held


def _run_quote(got: argparse.Namespace) -> int:
    sources = _sources(got)
    if got.stamp:
        stamped, held = _stamp_file(got.stamp, sources)
        if not stamped + held:
            raise Invalid(f"{got.stamp.name} holds no quote: nothing was examined")
        print(f"{got.stamp.name}: stamped {stamped} quotes, {held} already held a digest")
        return 0
    if not (got.ref and got.lines):
        raise Invalid("`rows quote` takes a ref and its lines, or --stamp FILE")
    quote = sources.stamped(got.ref, got.lines)
    if got.json:
        print(json.dumps(quote.as_json()))
        return 0
    print(f"{quote.ref} {quote.lines} sha {quote.sha}")
    for number, line in zip(range(quote.first, quote.last + 1), sources.read(quote), strict=True):
        print(f"  {number} | {line}")
    return 0


def _with_dictionary(got: argparse.Namespace) -> tuple[Dictionary, list[str]]:
    dictionary, faults = read(got.dictionary)
    if dictionary is None:
        raise Invalid("; ".join(faults))
    return dictionary, faults


def _run_cover(got: argparse.Namespace) -> int:
    from scry_core.knowledge import closure
    dictionary, faults = _with_dictionary(got)
    sources, table = _sources(got), _callees(got)
    known, homes = _known(dictionary, got.dictionary)
    code = 1 if faults else 0
    chosen = _chosen(dictionary, got.entries)
    if not chosen:
        raise Invalid("nothing was examined: the dictionary holds no entry")
    for fault in faults:
        print(f"- {fault}")
    for entry in chosen:
        report = closure.check(dictionary, entry, sources, table, known, partial=True,
                               homes=homes)
        print(closure.listing(report))
        code = code or (1 if report.faults else 0)
    return code


def _run_check(got: argparse.Namespace) -> int:
    from scry_core.knowledge import closure, official
    dictionary, faults = _with_dictionary(got)
    sources, table = _sources(got), _callees(got)
    known, homes = _known(dictionary, got.dictionary)
    reports = [closure.check(dictionary, e, sources, table, known, partial=got.partial,
                             homes=homes)
               for e in _chosen(dictionary, got.entries)]
    declared = official.check(dictionary, sources, partial=got.partial)
    for fault in faults:
        print(f"- {fault}")
    for report in reports:
        print(closure.summary(report))
    items = sum(len(r.results) for r in reports)
    if not items:
        raise Invalid("nothing was examined: no item was listed for the entries chosen")
    if dictionary.header.official:
        print(f"official: {declared.summary()}")
    for fault in declared.faults:
        print(f"  - {fault}")
    open_ = sum(r.open for r in reports)
    bad = len(faults) + sum(len(r.faults) for r in reports) + len(declared.faults)
    print(f"TOTAL entries {len(reports)}, items {items}, open {open_}, faults {bad}")
    return 1 if bad else 0


def _run_review(got: argparse.Namespace) -> int:
    from scry_core.knowledge import closure, review
    dictionary, faults = _with_dictionary(got)
    sources, table = _sources(got), _callees(got)
    known, homes = _known(dictionary, got.dictionary)
    chosen = _chosen(dictionary, got.entries)
    if not chosen:
        raise Invalid("nothing was examined: the dictionary holds no entry")
    for fault in faults:
        print(f"- {fault}")
    for entry in chosen:
        report = closure.check(dictionary, entry, sources, table, known, partial=True,
                               homes=homes)
        print(review.entry_text(dictionary, entry, report, sources))
    return 1 if faults else 0


def _run_migrate(got: argparse.Namespace) -> int:
    from scry_core.knowledge import migrate
    draft = migrate.draft(got.dictionary, got.entries[0] if got.entries else "", got.evidence,
                          _sources(got))
    text = json.dumps(draft.document, indent=1, ensure_ascii=False) + "\n"
    if got.out:
        got.out.write_text(text, encoding="utf-8")
        print(f"{got.out.name}: {draft.summary()}")
    else:
        sys.stdout.write(text)
        print(draft.summary(), file=sys.stderr)
    return 0


def _index_files(paths: Sequence[Path]) -> list[Path]:
    """The dictionary files at `paths`: each a file, or the `.json` of a folder that hold a
    dictionary (the callee table and the index beside them do not)."""
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out += [p for p in sorted(path.rglob("*.json"))
                    if f'"{FORMAT}"' in p.read_text(encoding="utf-8")]
        elif path.is_file():
            out.append(path)
        else:
            raise Invalid(f"{path} is neither a file nor a folder")
    return out


def _index_table(files: Sequence[Path]) -> dict[str, Datasheet]:
    """The documents the dictionaries may quote: scry-core's table and each package's, as
    `table_for` gives them, refused when two hold one document in two forms."""
    from scry_core.knowledge import quote
    table = quote.default_datasheets()
    for path in files:
        for name, held in quote.table_for(path).items():
            if table.setdefault(name, held) != held:
                raise Invalid(f"{name}: two packages hold the document in two forms")
    return table


def _run_index(got: argparse.Namespace) -> int:
    """Write the index of every quote's lines and the digest the source gives them."""
    from scry_core.knowledge import quote
    files = _index_files(got.dictionaries)
    if not files:
        raise Invalid("nothing was examined: no dictionary of rows was found")
    sources = Sources(mame=got.mame, dosbox=got.dosbox, rbil=got.rbil,
                      datasheets=got.datasheets, table=_index_table(files))
    held: dict[tuple[str, str], str] = {}
    faults: list[str] = []
    quotes = 0
    for path in files:
        dictionary, bad = read(path)
        faults += [f"{path.name}: {fault}" for fault in bad]
        if dictionary is None:
            continue
        for entry in dictionary.entries:
            for row in entry.rows:
                for held_quote in row.quotes:
                    quotes += 1
                    where = (f"{path.name}: {entry.id} row {row.n}: "
                             f"{held_quote.ref}:{held_quote.lines}")
                    try:
                        sha = sources.stamped(held_quote.ref, held_quote.lines).sha
                    except (Invalid, ValueError) as bad_source:
                        faults.append(f"{where}: {bad_source}")
                        continue
                    same = held.setdefault((held_quote.ref, held_quote.lines), sha)
                    if same != sha:
                        faults.append(f"{where}: the index holds {same} and the source {sha}")
    for fault in faults:
        print(f"- {fault}")
    if faults:
        return 1
    if not quotes:
        raise Invalid("nothing was examined: the dictionaries hold no quote")
    text = quote.Quotes(held).document()
    if got.out:
        got.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"{got.out.name}: {quotes} quotes, {len(held)} lines of source")
    else:
        sys.stdout.write(text)
        print(f"{quotes} quotes, {len(held)} lines of source", file=sys.stderr)
    return 0


def _run_seal(got: argparse.Namespace) -> int:
    from scry_core.knowledge import sealed
    if got.command == "seal":
        faults = sealed.seal(got.dictionary, got.entries, got.lock, got.part, got.by, got.writer)
    else:
        faults = sealed.reopen(got.dictionary, got.entries, got.lock, got.part, got.row or (),
                               got.by, got.why)
    for fault in faults:
        print(f"- {fault}")
    if not faults:
        done = "sealed" if got.command == "seal" else "reopened"
        print(f"{done} {got.part} of {len(got.entries)} in {got.lock.name}")
    return 1 if faults else 0


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(
        prog="rows", description="Stamp, list, check and read the rows of a dictionary "
        f"({FORMAT}).",
        epilog="Exit 0 done, 1 a fault, an item left open or a seal refused (nothing is "
               "written), 2 a bad option, 3 a source, "
               "function or run that could not be read or examined nothing (INVALID).")
    ask.add_argument("--mame", type=Path, help="tree of MAME files at the pinned tag")
    ask.add_argument("--dosbox", type=Path, help="DOSBox-X checkout that holds the pin")
    ask.add_argument("--rbil", type=Path, help="folder of Ralf Brown's list files or archives")
    ask.add_argument("--datasheets", type=Path, help="folder of the datasheet captures")
    ask.add_argument("--callees", type=Path, help="the callee table, `scry-knowledge-callees/1`; "
                     "the `callees.json` beside the dictionary when not given")
    commands = ask.add_subparsers(dest="command", required=True)
    quote = commands.add_parser("quote", help="print the lines of a ref with their digest, or "
                                "stamp the quotes of a dictionary that have none")
    quote.add_argument("ref", nargs="?")
    quote.add_argument("lines", nargs="?")
    quote.add_argument("--stamp", type=Path, help="a dictionary: write the missing digests")
    quote.add_argument("--json", action="store_true", help="print the quote as JSON")
    index = commands.add_parser("index", help="write the index of every quote's lines and the "
                                "digest the source gives them")
    index.add_argument("dictionaries", nargs="+", type=Path,
                       help="a dictionary file, or a folder holding some")
    index.add_argument("--out", type=Path, help="where to write the index; the standard output "
                       "when not given")
    for name, text in (("cover", "list what the entries owe, and what closes each item"),
                       ("check", "prove the quotes and the closure of every item"),
                       ("review", "print each row with the text of its lines"),
                       ("migrate", "draft rows from an old-shape entry and its evidence"),
                       ("seal", "seal a part of entries a reader judged, in the lock"),
                       ("reopen", "lift the seal of a part, naming the rows at fault")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("dictionary", type=Path)
        sub.add_argument("entries", nargs="+" if name in ("seal", "reopen") else "*",
                         help="entry ids" + ("" if name in ("seal", "reopen")
                                             else "; all of them when none is given"))
        if name == "migrate":
            sub.add_argument("--evidence", type=Path, required=True)
            sub.add_argument("--out", type=Path)
        if name in ("seal", "reopen"):
            sub.add_argument("--lock", type=Path, required=True, help="the lock of the "
                             "repository's rows, `scry-knowledge-rows-lock/1`")
            sub.add_argument("--part", required=True, help="`doc`, the official part, or the "
                             "emulator whose notes and verdicts are sealed")
            sub.add_argument("--by", required=True, help="who read the part" if name == "seal"
                             else "who reopens it")
        if name == "seal":
            sub.add_argument("--writer", required=True, help="who wrote the part: another "
                             "session than the reader")
        if name == "reopen":
            sub.add_argument("--row", action="append", help="a row at fault (repeat it); none "
                             "when the fault is in the part's closures, regions or names")
            sub.add_argument("--why", required=True, help="what is wrong with them")
        if name == "check":
            sub.add_argument("--partial", action="store_true", help="the dictionary is not "
                             "whole: count the official lines no entry holds, and the lines "
                             "closed for an owner not yet written, instead of failing on them")
    got = ask.parse_args(argv)
    run = {"quote": _run_quote, "cover": _run_cover, "check": _run_check,
           "review": _run_review, "migrate": _run_migrate, "index": _run_index,
           "seal": _run_seal, "reopen": _run_seal}[got.command]
    try:
        return run(got)
    except (Invalid, ValueError, OSError) as bad:
        print(f"INVALID: {bad}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
