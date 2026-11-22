"""The script half of the check of an entry (`rows check`): every quote is in the pinned source
and gives its digest, every row speaks only for the parties it quotes, and every item the
coverage lister reads from the entry's regions is closed by a row, the key, a closure with a
reason of the fixed set, or the callee table. An item left over is open, as a key with no entry is.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from scry_core.knowledge import cover
from scry_core.knowledge.callees import Callees
from scry_core.knowledge.quote import PARTY, Sources, span, split_ref
from scry_core.knowledge.rows import Closure, Dictionary, Entry, Region

OPEN = "OPEN"
_LINK = re.compile(r"[^:\s]+:[a-z]+:\S+")


@dataclass(frozen=True)
class Result:
    region: Region
    item: cover.Item
    by: str


@dataclass
class Report:
    entry: Entry
    results: list[Result] = field(default_factory=list)
    faults: list[str] = field(default_factory=list)
    owed: int = 0
    quotes: int = 0

    @property
    def open(self) -> int:
        return sum(r.by == OPEN for r in self.results)


def _last(name: str) -> str:
    return re.split(r"::|\.|->", name)[-1]


def _listing(region: Region, dictionary: Dictionary, sources: Sources) -> cover.Listing:
    held = sources.lines(region.ref)
    if region.lines:
        return cover.list_section(held, region.lines)
    header = dictionary.header
    party = PARTY[split_ref(region.ref)[0]]
    return cover.list_function(
        "\n".join(held), region.function, case=region.case, preamble=region.preamble,
        key=cover.parse_key(region.value) if region.value else None,
        defined=header.defines.get(party, ()), stores=header.stores.get(party, ""))


def _claims(entry: Entry) -> dict[str, dict[int, list[str]]]:
    claimed: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in entry.rows:
        for q in row.quotes:
            for line in range(q.first, q.last + 1):
                if row.n not in claimed[q.ref][line]:
                    claimed[q.ref][line].append(row.n)
    return claimed


def _regions_of(dictionary: Dictionary, entry: Entry) -> set[tuple[str, str]]:
    """The functions an entry has a region of, by emulator and name."""
    return {(split_ref(r.ref)[0], _last(r.function))
            for r in dictionary.regions(entry) if r.function}


def _check_rows(entry: Entry, sources: Sources, known: Mapping[str, Entry], scope: str,
                kind: str, report: Report) -> None:
    for row in entry.rows:
        where = f"row {row.n}"
        quoted = set()
        for q in row.quotes:
            report.quotes += 1
            report.faults += [f"{where}: {f}" for f in sources.faults(q)]
            quoted.add(q.party)
        for who in sorted(set(row.of) - quoted):
            report.faults.append(f"{where} speaks for {who} and quotes nothing of it")
        for who in sorted(quoted - set(row.of)):
            report.faults.append(f"{where} quotes {who} and does not speak for it")
        for link in row.links:
            if not _LINK.fullmatch(link):
                report.faults.append(f"{where}: link {link!r} is an entry id")
            elif link.startswith(f"{scope}:{kind}:") and link not in known:
                report.faults.append(f"{where}: link {link} names no entry of this dictionary")


def _callee(dictionary: Dictionary, entry: Entry, known: Mapping[str, Entry], callees: Callees,
            region: Region, item: cover.Item, report: Report) -> str:
    scheme, file = split_ref(region.ref)
    how = callees.of(scheme, file, item.text)
    name = _last(item.text)
    if how is None:
        return OPEN
    if how.kind == "none":
        return f"callee: none:{how.detail}"
    if how.kind == "engine":
        if name not in dictionary.header.engine:
            return OPEN
        report.owed += 1
        return "callee: engine"
    if how.kind == "open":
        return "callee: open" if (scheme, _last(how.detail or name)) in _regions_of(
            dictionary, entry) else OPEN
    owner = known.get(how.detail)
    if owner is None:
        report.owed += 1
        return f"callee: shared:{how.detail}"
    return f"callee: shared:{how.detail}" if (scheme, name) in _regions_of(
        dictionary, owner) else OPEN


def _closed_by(closures: list[Closure], ref: str, line: int) -> int | None:
    for k, c in enumerate(closures):
        if c.ref == ref and c.first <= line <= c.last:
            return k
    return None


def check(dictionary: Dictionary, entry: Entry, sources: Sources, callees: Callees,
          known: Mapping[str, Entry]) -> Report:
    """The report of one entry. `Invalid` when a source or a function cannot be read."""
    report = Report(entry)
    _check_rows(entry, sources, known, dictionary.header.scope, dictionary.header.kind, report)
    if not dictionary.regions(entry):
        report.faults.append("no region answers this entry: it names none and its header's "
                             "handlers are none")
    claims = _claims(entry)
    closures = list(entry.closed)
    used: set[int] = set()
    for region in dictionary.regions(entry):
        for item in _listing(region, dictionary, sources).items:
            if item.kind == "key":
                by = "the key"
            elif item.kind == "call":
                by = _callee(dictionary, entry, known, callees, region, item, report)
            elif item.line in claims.get(region.ref, {}):
                by = "row " + ", ".join(claims[region.ref][item.line])
            elif (k := _closed_by(closures, region.ref, item.line)) is not None:
                used.add(k)
                by = f"closed: {closures[k].reason}"
            else:
                by = OPEN
            report.results.append(Result(region, item, by))
            if by == OPEN:
                report.faults.append(f"OPEN {region.ref}:{item.line} {item.kind} {item.text}")
    for k, c in enumerate(closures):
        if k not in used:
            report.faults.append(f"closed {c.ref}:{c.lines} closes no listed item")
        elif c.owner:
            _owned(c, known, report)
    return report


def _owned(closure: Closure, known: Mapping[str, Entry], report: Report) -> None:
    owner = known.get(closure.owner)
    if owner is None:
        report.owed += 1
        return
    first, last = span(closure.lines)
    held = _claims(owner).get(closure.ref, {})
    if not any(n in held for n in range(first, last + 1)):
        report.faults.append(f"closed {closure.ref}:{closure.lines}: {closure.owner} has no "
                             "row on those lines")


def summary(report: Report) -> str:
    out = [f"{report.entry.id}: rows {len(report.entry.rows)}, quotes {report.quotes}, items "
           f"{len(report.results)}, open {report.open}, owed elsewhere {report.owed}, "
           f"faults {len(report.faults)}"]
    out += [f"  - {f}" for f in report.faults]
    return "\n".join(out)


def listing(report: Report) -> str:
    """The items the entry owes, region by region, each with what closes it."""
    out = [f"# {report.entry.id}  {report.entry.name}"]
    seen: list[Region] = []
    for r in report.results:
        if r.region not in seen:
            seen.append(r.region)
            what = r.region.function or f"lines {r.region.lines}"
            out.append(f"{r.region.ref} {what} {' '.join(r.region.case)}".rstrip())
        out.append(f"  {r.item.line:>6} {r.item.kind:<7} {r.item.text[:72]:<72} <- {r.by}")
    out.append(summary(report))
    return "\n".join(out)
