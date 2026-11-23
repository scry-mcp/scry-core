"""The script half of the check of an entry (`rows check`): every quote is in the pinned source
and gives its digest, every row quotes only its own party, the entry has an official region (or
says it has no official source), and every item the coverage lister reads from the entry's
regions is closed by a row, the key, a closure with a reason of the fixed set, or the callee
table. An item left over is open, as a key with no entry is; an item both claimed by a note and
closed is a fault unless the closure is a verdict or `structure`, since one statement may do what
several rows say; a call to a callee that `writes` is owed as a store is; a `local` or an `input`
is shown by a verdict and owed nothing. A line another entry owns, through a closure or the
callee table, whose owner is not written is counted as owed under `--partial` and a fault
without it. The verdict each emulator
owes on each official row is `verdict`'s, what the lines of a verdict must show is `cited`'s, the
lines of the declared official ranges are `official`'s.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from scry_core.knowledge import cited, cover, official, reach, verdict
from scry_core.knowledge.callees import Callees, Decision, last_name
from scry_core.knowledge.quote import BODY_LINES, PARTY, QUOTE_LINES, Sources, span, split_ref
from scry_core.knowledge.rows import OWNED, VERDICT_CLOSURES, Closure, Dictionary, Entry, Region

OPEN = "OPEN"
#: What a callee that writes the guest's state is closed by: a row or a closure, as a store is.
WRITES = "callee: writes"
#: The closures that may lie over a line a note claims: what one statement does may be the note's
#: and the verdict of another row, and a `structure` closes the lines around a note's.
BESIDE_A_NOTE = (*VERDICT_CLOSURES, "structure")
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
    got = cover.list_function(
        "\n".join(held), region.function, case=region.case, preamble=region.preamble,
        key=cover.parse_key(region.value) if region.value else None,
        defined=header.defines.get(party, ()))
    got.items += reach.state(got.text, got.start, got.region, got.tree, (got.first, got.last))
    got.items += reach.lookup(got.text, got.region)
    return got


def _reached(listings: list[tuple[Region, cover.Listing]]) -> None:
    """Drops what a region reaches that the entry's own regions hold: a `state` line inside one
    of them is the entry's own code. An item two regions reach is listed once."""
    seen: set[tuple[str, str, str]] = set()
    for region, listing in listings:
        spans = [(lg.first, lg.last) for r, lg in listings if r.ref == region.ref]
        kept = []
        for item in listing.items:
            if item.kind in ("state", "lookup"):
                key = (region.ref, item.kind,
                       f"{item.text} {item.lines}" if item.kind == "state" else str(item.line))
                outside = tuple(x for x in item.lines if item.kind == "lookup"
                                or not any(a <= x <= b for a, b in spans))
                if key in seen or not outside:
                    continue
                seen.add(key)
                item = cover.Item(outside[0], item.kind, item.text, outside)
            kept.append(item)
        listing.items = kept


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
            report.faults += [f"{where}: {f}"
                              for f in sources.faults(q, BODY_LINES if row.vs == "absent"
                                                      else QUOTE_LINES)]
            if q.party != row.of:
                report.faults.append(f"{where} speaks for {row.of} and quotes {q.party}: a row "
                                     "quotes its own party only")
        for link in row.links:
            if not _LINK.fullmatch(link):
                report.faults.append(f"{where}: link {link!r} is an entry id")
            elif link.startswith(f"{scope}:{kind}:") and link not in known:
                report.faults.append(f"{where}: link {link} names no entry of this dictionary")


def _callee(dictionary: Dictionary, entry: Entry, known: Mapping[str, Entry],
            homes: Mapping[str, Dictionary], region: Region, item: cover.Item,
            how: Decision | None, report: Report, partial: bool) -> tuple[str, Decision | None]:
    """What closes a call, and the decision it has in this entry: an `open` callee whose body is
    another entry's region is that entry's, as a `shared` one is."""
    scheme = split_ref(region.ref)[0]
    name = last_name(item.text)
    if how is None:
        return OPEN, how
    if how.kind == "none":
        return f"callee: none:{how.detail}", how
    if how.kind in ("virtual", "writes"):
        return f"callee: {how.kind}", how
    if how.kind == "engine":
        if name not in dictionary.header.engine:
            return OPEN, how
        report.owed += 1
        return "callee: engine", how
    if how.kind == "open":
        body = (scheme, last_name(how.detail or name))
        if body in _regions_of(dictionary, entry):
            return "callee: open", how
        owner = next((e.id for e in known.values()
                      if body in _regions_of(homes.get(e.id, dictionary), e)), "")
        return (f"callee: shared:{owner}", Decision("shared", owner)) if owner else (OPEN, how)
    owner_entry = known.get(how.detail)
    if owner_entry is None and not partial:
        report.faults.append(f"{region.ref}:{item.line} calls {item.text}, which the callee table "
                             f"gives to {how.detail}, no entry of the dictionary or beside it: "
                             "write it, or check with --partial while it is not written")
        return f"callee: shared:{how.detail}", how
    if owner_entry is None:
        report.owed += 1
        return f"callee: shared:{how.detail}", how
    return (f"callee: shared:{how.detail}" if (scheme, name) in _regions_of(
        homes.get(owner_entry.id, dictionary), owner_entry) else OPEN), how


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


def _judging(closures: list[Closure], ref: str, line: int) -> list[int]:
    """Every verdict closure over the line: one statement of an emulator may do what several
    official rows say, so each of them is used by it."""
    return [k for k, c in enumerate(closures)
            if c.reason in VERDICT_CLOSURES and c.ref == ref and c.first <= line <= c.last]


def _settled(closures: list[Closure], claims: dict[str, dict[int, list[str]]], ref: str,
             line: int, used: set[int], report: Report, effect: bool) -> str:
    """What closes an item a row or a closure must: a note's claim, with a verdict or a
    `structure` beside it at most, or one closure. An `agrees` marked `nothing` closes no
    `effect`: what its body stores of something else is still owed."""
    over = [k for k, c in enumerate(closures) if c.ref == ref and c.first <= line <= c.last
            and not (effect and c.nothing)]
    used.update(over)
    if line in claims.get(ref, {}):
        by = "row " + ", ".join(claims[ref][line])
        for k in over:
            if closures[k].reason not in BESIDE_A_NOTE:
                report.faults.append(f"{ref}:{line} is claimed by {by} and closed as "
                                     f"{closures[k].reason}: one of the two")
        return by
    return f"closed: {closures[over[0]].reason}" if over else OPEN


def check(dictionary: Dictionary, entry: Entry, sources: Sources, callees: Callees,
          known: Mapping[str, Entry], *, partial: bool = False,
          homes: Mapping[str, Dictionary] | None = None) -> Report:
    """The report of one entry. `known` are the entries an owner may be, `homes` the dictionary
    of each that is not this one; `partial` when the dictionary is still being written.
    `Invalid` when a source or a function cannot be read."""
    homes = homes or {}
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
    listings = [(r, _listing(r, dictionary, sources)) for r in dictionary.regions(entry)]
    _reached(listings)
    for region, listing in listings:
        scheme, file = split_ref(region.ref)
        spans.append((region, listing.first, listing.last))
        for item in listing.items:
            how = callees.of(scheme, file, item.text) if item.kind == "call" else None
            by = ""
            if item.kind == "call":
                by, how = _callee(dictionary, entry, known, homes, region, item, how, report,
                                  partial)
            listed.append(cited.Listed(region.ref, item, region.function, how))
            if item.kind in cover.NOT_OWED:
                continue
            if item.kind == "key":
                by = "the key"
            elif item.lines:
                settled = [_settled(closures, claims, region.ref, line, used, report, True)
                           for line in item.lines]
                by = next((got for got in settled if got != OPEN), OPEN)
            elif by == "callee: virtual":
                by = _judged(closures, claims, region.ref, item.line)
            elif item.kind != "call" or by == WRITES:
                by = _settled(closures, claims, region.ref, item.line, used, report,
                              item.kind == "store" or by == WRITES)
            used.update(_judging(closures, region.ref, item.line))
            report.results.append(Result(region, item, by))
            if by == OPEN:
                report.faults.append(f"OPEN {region.ref}:{item.line} {item.kind} {item.text}")
    proof = cited.prove(dictionary, entry, sources, callees, listed, spans)
    report.faults += proof.faults
    used |= proof.used
    for k, c in enumerate(closures):
        if k not in used:
            report.faults.append(f"closed {c.ref}:{c.lines} closes no listed item")
        elif c.owner:
            _owned(c, known, report, partial)
    return report


def _owned(closure: Closure, known: Mapping[str, Entry], report: Report, partial: bool) -> None:
    owner = known.get(closure.owner)
    if owner is not None and owner.id == report.entry.id:
        report.faults.append(f"closed {closure.ref}:{closure.lines} as {closure.reason} for the "
                             "entry itself: an owner is another entry")
        return
    if owner is None and partial:
        report.owed += 1
        return
    if owner is None:
        report.faults.append(f"closed {closure.ref}:{closure.lines} as {closure.reason} for "
                             f"{closure.owner}, which is no entry of the dictionary: write it, "
                             "or check with --partial while the dictionary is not whole")
        return
    first, last = span(closure.lines)
    held = _claims(owner).get(closure.ref, {})
    if not any(n in held for n in range(first, last + 1)) and not any(
            c.ref == closure.ref and c.first <= last and first <= c.last
            and c.reason not in OWNED for c in owner.closed):
        report.faults.append(f"closed {closure.ref}:{closure.lines}: {closure.owner} has no "
                             "row on those lines and closes none of them itself")


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
