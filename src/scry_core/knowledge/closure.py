"""The script half of the check of an entry (`rows check`): every quote is in the pinned source
and gives its digest, every row quotes only its own party, the entry has an official region (or
says it has no official source), and every item the coverage lister reads from the entry's
regions is closed by a row, the key, a closure with a reason of the fixed set, or the callee
table. An item left over is open, as a key with no entry is; an item both claimed and closed is a
fault; a `local` or an `input` is shown by a verdict and owed nothing. The verdict each emulator
owes on each official row is `verdict`'s, what the lines of a verdict must show is `cited`'s, the
lines of the declared official ranges are `official`'s.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from scry_core.knowledge import cited, cover, official, verdict
from scry_core.knowledge.callees import Callees, last_name
from scry_core.knowledge.quote import PARTY, Sources, span, split_ref
from scry_core.knowledge.rows import VERDICT_CLOSURES, Closure, Dictionary, Entry, Region

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
    """The rows over each line. An `absent` note cites the body where the thing would be, not
    what that body does, so it claims none of its lines."""
    claimed: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in entry.rows:
        if row.vs == "absent":
            continue
        for q in row.quotes:
            for line in range(q.first, q.last + 1):
                if row.n not in claimed[q.ref][line]:
                    claimed[q.ref][line].append(row.n)
    return claimed


def _regions_of(dictionary: Dictionary, entry: Entry) -> set[tuple[str, str]]:
    """The functions an entry has a region of, by emulator and name."""
    return {(split_ref(r.ref)[0], last_name(r.function))
            for r in dictionary.regions(entry) if r.function}


def _check_rows(entry: Entry, sources: Sources, known: Mapping[str, Entry], scope: str,
                kind: str, report: Report) -> None:
    for row in entry.rows:
        where = f"row {row.n}"
        for q in row.quotes:
            report.quotes += 1
            report.faults += [f"{where}: {f}" for f in sources.faults(q)]
            if q.party != row.of:
                report.faults.append(f"{where} speaks for {row.of} and quotes {q.party}: a row "
                                     "quotes its own party only")
        for link in row.links:
            if not _LINK.fullmatch(link):
                report.faults.append(f"{where}: link {link!r} is an entry id")
            elif link.startswith(f"{scope}:{kind}:") and link not in known:
                report.faults.append(f"{where}: link {link} names no entry of this dictionary")


def _callee(dictionary: Dictionary, entry: Entry, known: Mapping[str, Entry], callees: Callees,
            region: Region, item: cover.Item, report: Report) -> str:
    scheme, file = split_ref(region.ref)
    how = callees.of(scheme, file, item.text)
    name = last_name(item.text)
    if how is None:
        return OPEN
    if how.kind == "none":
        return f"callee: none:{how.detail}"
    if how.kind == "virtual":
        return "callee: virtual"
    if how.kind == "engine":
        if name not in dictionary.header.engine:
            return OPEN
        report.owed += 1
        return "callee: engine"
    if how.kind == "open":
        return "callee: open" if (scheme, last_name(how.detail or name)) in _regions_of(
            dictionary, entry) else OPEN
    owner = known.get(how.detail)
    if owner is None:
        report.owed += 1
        return f"callee: shared:{how.detail}"
    return f"callee: shared:{how.detail}" if (scheme, name) in _regions_of(
        dictionary, owner) else OPEN


def _judged(closures: list[Closure], claims: dict[str, dict[int, list[str]]], ref: str,
            line: int) -> str:
    """A call with several bodies is decided by the verdict over it or a note on it: what it
    does is each body's, so the table alone closes nothing."""
    judging = _judging(closures, ref, line)
    if judging:
        return f"closed: {closures[judging[0]].reason}"
    if line in claims.get(ref, {}):
        return "row " + ", ".join(claims[ref][line])
    return OPEN


def _closed_by(closures: list[Closure], ref: str, line: int) -> int | None:
    for k, c in enumerate(closures):
        if c.ref == ref and c.first <= line <= c.last:
            return k
    return None


def _judging(closures: list[Closure], ref: str, line: int) -> list[int]:
    """Every verdict closure over the line: one statement of an emulator may do what several
    official rows say, so each of them is used by it."""
    return [k for k, c in enumerate(closures)
            if c.reason in VERDICT_CLOSURES and c.ref == ref and c.first <= line <= c.last]


def check(dictionary: Dictionary, entry: Entry, sources: Sources, callees: Callees,
          known: Mapping[str, Entry]) -> Report:
    """The report of one entry. `Invalid` when a source or a function cannot be read."""
    report = Report(entry)
    _check_rows(entry, sources, known, dictionary.header.scope, dictionary.header.kind, report)
    if not dictionary.regions(entry):
        report.faults.append("no region answers this entry: it names none and its header's "
                             "handlers are none")
    report.faults += official.entry_faults(dictionary, entry)
    report.faults += verdict.faults(dictionary, entry)
    claims = _claims(entry)
    closures = list(entry.closed)
    used: set[int] = set()
    listed: list[cited.Listed] = []
    spans: list[tuple[Region, int, int]] = []
    for region in dictionary.regions(entry):
        scheme, file = split_ref(region.ref)
        listing = _listing(region, dictionary, sources)
        spans.append((region, listing.first, listing.last))
        for item in listing.items:
            how = callees.of(scheme, file, item.text) if item.kind == "call" else None
            listed.append(cited.Listed(region.ref, item, region.function, how))
            if item.kind in cover.NOT_OWED:
                continue
            if item.kind == "key":
                by = "the key"
            elif item.kind == "call":
                by = _callee(dictionary, entry, known, callees, region, item, report)
                if by == "callee: virtual":
                    by = _judged(closures, claims, region.ref, item.line)
            elif item.line in claims.get(region.ref, {}):
                by = "row " + ", ".join(claims[region.ref][item.line])
                if (k := _closed_by(closures, region.ref, item.line)) is not None:
                    used.add(k)
                    report.faults.append(f"{region.ref}:{item.line} is claimed by {by} and closed "
                                         f"as {closures[k].reason}: one of the two")
            elif (k := _closed_by(closures, region.ref, item.line)) is not None:
                used.add(k)
                by = f"closed: {closures[k].reason}"
            else:
                by = OPEN
            used.update(_judging(closures, region.ref, item.line))
            report.results.append(Result(region, item, by))
            if by == OPEN:
                report.faults.append(f"OPEN {region.ref}:{item.line} {item.kind} {item.text}")
    proof = cited.prove(dictionary, entry, sources, listed, spans)
    report.faults += proof.faults
    used |= proof.used
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
