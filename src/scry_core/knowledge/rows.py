"""The format `scry-knowledge/2`: an entry as rows that carry their evidence, and the command
`rows` (`python -m scry_core.knowledge.rows`) that stamps, lists, checks and reads them.

A dictionary file holds a header (what it covers, the code that answers its keys, what the build
defines, the engine functions it does not cover) and its entries. An entry is its `key`, `name`
and `aliases`, the `regions` of code that answer it, its `rows` and the items it `closed`. A row
is one fact, of named parties, with the lines that say it; a quote is a location and a digest
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
from scry_core.knowledge.entry import ALIAS_MAX, ALIASES_MAX, NAME_MAX, entry_id
from scry_core.knowledge.quote import QUOTE_LINES, Invalid, Quote, Sources, span, split_ref

FORMAT = "scry-knowledge/2"
PARTIES = ("doc", "dosbox-x", "mame")
TEXT_WORDS, QUOTES_PER_ROW, LINKS_PER_ROW, UNSEEN_WORDS = 30, 6, 4, 16
CLOSED_AS = ("log", "structure", "decode", "key", "build", "dead", "see-also", "version",
             "unseen", "preamble", "parent")
OWNED = ("preamble", "parent")
PLACEMENT = ("address", "length", "device", "ports", "irq", "dma", "contains", "classes",
             "handlers")
#: Words a row's lines rarely support and a reader must look at (question 1 of the reader).
SWEEPING = ("always", "never", "only", "every")
STATES = ("undetermined",)

_HEADER_FIELDS = {"format", "dictionary", "kind", "scope", "covers", "handlers", "defines",
                  "stores", "engine", "entries"}
_ENTRY_FIELDS = {"key", "name", "aliases", "access", "regions", "rows", "closed", *PLACEMENT}
_ROW_FIELDS = {"n", "on", "of", "text", "quotes", "state", "links"}
_REGION_FIELDS = {"ref", "function", "case", "value", "preamble", "lines"}
_CLOSED_FIELDS = {"ref", "lines", "as", "reason", "owner"}
_LABEL = re.compile(r"[A-Za-z0-9]{1,6}")
_BITS = r"bits \d+-\d+(?: = \S+)?|bit \d+|value \S+"
_PLACE = r"is|place|when|order"
SUBJECTS: dict[str, str] = {
    "call": r"is|when|does|in \S+|out \S+",
    "register": rf"is|when|read|write|reset|order|{_BITS}",
    "command": rf"is|when|write|order|{_BITS}",
    "device": rf"{_PLACE}|reset|detect|type \S+",
    "port": rf"is|place|read|write|{_BITS}",
    "vector": r"is|when|does|place",
    "irq": r"is|place|when",
    "memory": rf"is|place|{_BITS}",
    "error": r"is",
    "input": r"is|value \S+",
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
    of: tuple[str, ...]
    text: str
    quotes: tuple[Quote, ...]
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


@dataclass(frozen=True)
class Header:
    dictionary: str
    kind: str
    scope: str
    covers: str
    handlers: tuple[Region, ...]
    defines: Mapping[str, tuple[str, ...]]
    stores: Mapping[str, str]
    engine: tuple[str, ...]


@dataclass(frozen=True)
class Dictionary:
    header: Header
    entries: tuple[Entry, ...]

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
    return Region(raw["ref"], str(raw.get("function", "")), tuple(case), str(raw.get("value", "")),
                  bool(raw.get("preamble", False)), str(raw.get("lines", "")))


def _quote(raw: object, where: str, faults: list[str]) -> Quote | None:
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
    if last - first + 1 > QUOTE_LINES:
        faults.append(f"{where}: {raw['lines']} is {last - first + 1} lines, over {QUOTE_LINES}")
    return Quote(raw["ref"], raw["lines"], str(raw.get("sha", "")))


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
    if not (isinstance(of, list) and of and all(isinstance(p, str) and p in PARTIES for p in of)
            and len(set(of)) == len(of)):
        faults.append(f"{where}: `of` is one to three of {', '.join(PARTIES)}")
        of = []
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
        got = (_quote(q, f"{where}, quote {i + 1}", faults) for i, q in enumerate(raw_quotes))
        quotes = [q for q in got if q]
    if len(faults) != mine:
        return None
    return Row(str(n), str(on), tuple(of), str(text), tuple(quotes), str(state), tuple(links))


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
    why, owner = raw.get("reason", ""), raw.get("owner", "")
    if reason == "unseen" and not (isinstance(why, str) and 0 < len(why.split()) <= UNSEEN_WORDS):
        faults.append(f"{where}: `unseen` needs a `reason` of at most {UNSEEN_WORDS} words")
        return None
    if reason in OWNED and not (isinstance(owner, str) and owner):
        faults.append(f"{where}: `{reason}` names the entry that owns the line, as `owner`")
        return None
    return Closure(raw["ref"], raw["lines"], reason, str(why), str(owner))


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
    ident = entry_id(header.scope, header.kind, key, access if isinstance(access, str) else "")
    where = ident
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
    if placed and not re.fullmatch(SUBJECTS[header.kind], "place"):
        faults.append(f"{where}: a {header.kind} has no placement field "
                      f"({', '.join(f for f in PLACEMENT if f in raw)})")
    _required(made, header.kind, ident, placed, faults)
    return Entry(ident, key, str(name), tuple(aliases), tuple(r for r in regions if r),
                 tuple(made), tuple(c for c in closed if c), placed)


def _required(rows: list[Row], kind: str, ident: str, placed: bool,
              faults: list[str]) -> None:
    subjects = {r.on.split(" ")[0] for r in rows}
    wanted = list(REQUIRED[kind])
    if placed and ("place",) not in wanted and re.fullmatch(SUBJECTS[kind], "place"):
        wanted.append(("place",))
    for options in wanted:
        if not subjects & set(options):
            faults.append(f"{ident}: a {kind} needs a row on {' or '.join(options)}")


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
    handlers = [_region(h, f"handler {i + 1}", faults)
                for i, h in enumerate(_listed(doc, "handlers", "header", faults))]
    defines, stores = doc.get("defines", {}), doc.get("stores", {})
    engine = doc.get("engine", [])
    if not (isinstance(defines, dict) and set(defines) <= set(PARTIES)
            and all(isinstance(v, list) for v in defines.values())):
        faults.append("`defines` maps a party to the names its build defines")
        defines = {}
    if not (isinstance(stores, dict) and set(stores) <= set(PARTIES)):
        faults.append("`stores` maps a party to a pattern of the calls that write")
        stores = {}
    for who, pattern in list(stores.items()):
        try:
            re.compile(pattern)
        except (re.error, TypeError) as bad:
            faults.append(f"`stores` of {who} is no pattern: {bad}")
            del stores[who]
    if not (isinstance(engine, list) and all(isinstance(e, str) for e in engine)):
        faults.append("`engine` is a list of function names")
        engine = []
    return Header(doc["dictionary"], kind, scope, doc["covers"],
                  tuple(h for h in handlers if h),
                  {k: tuple(v) for k, v in defines.items()}, dict(stores), tuple(engine))


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
    if not got.callees:
        return Callees()
    return parse_callees(got.callees.read_text(encoding="utf-8"), got.callees.name)


def _sources(got: argparse.Namespace) -> Sources:
    return Sources(mame=got.mame, dosbox=got.dosbox, rbil=got.rbil, datasheets=got.datasheets)


def _chosen(dictionary: Dictionary, wanted: Sequence[str]) -> list[Entry]:
    if not wanted:
        return list(dictionary.entries)
    by_id = {e.id: e for e in dictionary.entries}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        raise Invalid(f"no entry {', '.join(missing)} in the dictionary")
    return [by_id[w] for w in wanted]


def _stamp_file(path: Path, sources: Sources) -> tuple[int, int]:
    """Writes the digest into every quote of `path` that has none; returns how many it stamped
    and how many already held one."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    stamped = held = 0
    for entry in doc.get("entries", []):
        for row in entry.get("rows", []):
            for q in row.get("quotes", []):
                if q.get("sha"):
                    held += 1
                    continue
                q["sha"] = sources.stamped(q["ref"], q["lines"]).sha
                stamped += 1
    if stamped:
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
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
    known = {e.id: e for e in dictionary.entries}
    code = 1 if faults else 0
    chosen = _chosen(dictionary, got.entries)
    if not chosen:
        raise Invalid("nothing was examined: the dictionary holds no entry")
    for fault in faults:
        print(f"- {fault}")
    for entry in chosen:
        report = closure.check(dictionary, entry, sources, table, known)
        print(closure.listing(report))
        code = code or (1 if report.faults else 0)
    return code


def _run_check(got: argparse.Namespace) -> int:
    from scry_core.knowledge import closure
    dictionary, faults = _with_dictionary(got)
    sources, table = _sources(got), _callees(got)
    known = {e.id: e for e in dictionary.entries}
    reports = [closure.check(dictionary, e, sources, table, known)
               for e in _chosen(dictionary, got.entries)]
    for fault in faults:
        print(f"- {fault}")
    for report in reports:
        print(closure.summary(report))
    items = sum(len(r.results) for r in reports)
    if not items:
        raise Invalid("nothing was examined: no item was listed for the entries chosen")
    open_ = sum(r.open for r in reports)
    bad = len(faults) + sum(len(r.faults) for r in reports)
    print(f"TOTAL entries {len(reports)}, items {items}, open {open_}, faults {bad}")
    return 1 if bad else 0


def _run_review(got: argparse.Namespace) -> int:
    from scry_core.knowledge import closure, review
    dictionary, faults = _with_dictionary(got)
    sources, table = _sources(got), _callees(got)
    known = {e.id: e for e in dictionary.entries}
    chosen = _chosen(dictionary, got.entries)
    if not chosen:
        raise Invalid("nothing was examined: the dictionary holds no entry")
    for fault in faults:
        print(f"- {fault}")
    for entry in chosen:
        report = closure.check(dictionary, entry, sources, table, known)
        print(review.entry_text(entry, report, sources))
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


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(
        prog="rows", description="Stamp, list, check and read the rows of a dictionary "
        f"({FORMAT}).",
        epilog="Exit 0 done, 1 a fault or an item left open, 2 a bad option, 3 a source, "
               "function or run that could not be read or examined nothing (INVALID).")
    ask.add_argument("--mame", type=Path, help="tree of MAME files at the pinned tag")
    ask.add_argument("--dosbox", type=Path, help="DOSBox-X checkout that holds the pin")
    ask.add_argument("--rbil", type=Path, help="folder of Ralf Brown's list files or archives")
    ask.add_argument("--datasheets", type=Path, help="folder of the datasheet captures")
    ask.add_argument("--callees", type=Path, help="the callee table, `scry-knowledge-callees/1`")
    commands = ask.add_subparsers(dest="command", required=True)
    quote = commands.add_parser("quote", help="print the lines of a ref with their digest, or "
                                "stamp the quotes of a dictionary that have none")
    quote.add_argument("ref", nargs="?")
    quote.add_argument("lines", nargs="?")
    quote.add_argument("--stamp", type=Path, help="a dictionary: write the missing digests")
    quote.add_argument("--json", action="store_true", help="print the quote as JSON")
    for name, text in (("cover", "list what the entries owe, and what closes each item"),
                       ("check", "prove the quotes and the closure of every item"),
                       ("review", "print each row with the text of its lines"),
                       ("migrate", "draft rows from an old-shape entry and its evidence")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("dictionary", type=Path)
        sub.add_argument("entries", nargs="*", help="entry ids; all of them when none is given")
        if name == "migrate":
            sub.add_argument("--evidence", type=Path, required=True)
            sub.add_argument("--out", type=Path)
    got = ask.parse_args(argv)
    run = {"quote": _run_quote, "cover": _run_cover, "check": _run_check,
           "review": _run_review, "migrate": _run_migrate}[got.command]
    try:
        return run(got)
    except (Invalid, ValueError, OSError) as bad:
        print(f"INVALID: {bad}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
