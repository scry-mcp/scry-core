"""The official source of an entry and of a dictionary (`rows check`).

An entry of an `official` source has an official region, a section of the list or the lines of a
document's capture, and every line of it is claimed by a `doc` row or closed. A dictionary
declares, per document, the lines of its capture that are the programming model; each non-blank
line of them is in exactly one entry's region or in a closure of the dictionary. A line no entry
owns is red once the dictionary is whole, and only counted while it is `--partial`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from scry_core.knowledge.quote import Invalid, Sources, span, split_ref
from scry_core.knowledge.rows import Dictionary, Entry, Region

DOCUMENT = "datasheet"


def _of_documents(dictionary: Dictionary, entry: Entry) -> list[Region]:
    return [r for r in dictionary.regions(entry) if split_ref(r.ref)[0] in (DOCUMENT, "rbil61")]


def _through(lines: str) -> tuple[int, int]:
    first, last = span(lines)
    return first, last + 1


def _lines(ranges: Iterable[str]) -> set[int]:
    return {n for r in ranges for n in range(span(r)[0], span(r)[1] + 1)}


def entry_faults(dictionary: Dictionary, entry: Entry) -> list[str]:
    """What is wrong with the entry's official side: a region of an official source it has none
    of, a document its dictionary does not name, lines outside the declared programming model, a
    quote outside the entry's official region (its own or the header's), a variant no document
    describes."""
    out: list[str] = []
    header = dictionary.header
    named = {d.name for d in header.documents}
    regions = _of_documents(dictionary, entry)
    if dictionary.source_of(entry) == "official" and not regions:
        out.append("an `official` entry has an official region: it names a section of the list "
                   "or lines of a document, and has none")
    for r in regions:
        scheme, file = split_ref(r.ref)
        if scheme != DOCUMENT:
            continue
        if file not in named:
            out.append(f"region {r.ref} is a document the dictionary does not name")
        elif r.lines and not _lines([r.lines]) <= _lines(header.official.get(file, ())):
            out.append(f"region {r.ref}:{r.lines} is outside the lines of {file} declared as "
                       "its programming model")
    variants = {(d.name, d.variant) for d in header.documents}
    held = {(r.ref, n) for r in regions if r.lines for n in range(*_through(r.lines))}
    for row in entry.rows:
        for q in row.quotes:
            if row.of == "doc" and not all((q.ref, n) in held
                                           for n in range(q.first, q.last + 1)):
                out.append(f"row {row.n} quotes {q.ref}:{q.lines}, outside the entry's official "
                           "region: a row states what its own region says")
            scheme, file = split_ref(q.ref)
            if scheme == DOCUMENT and file not in named:
                out.append(f"row {row.n} quotes {q.ref}, a document the dictionary does not name")
            elif scheme == DOCUMENT and row.variant and (file, row.variant) not in variants:
                out.append(f"row {row.n} is of the {row.variant} and quotes {file}, which the "
                           "dictionary names for another variant")
        if row.variant and row.variant not in {d.variant for d in header.documents}:
            out.append(f"row {row.n}: variant {row.variant} is none of the dictionary's")
    return out


@dataclass
class Report:
    """The lines of the declared official ranges of a dictionary and who holds them."""

    faults: list[str] = field(default_factory=list)
    lines: int = 0
    owned: int = 0
    closed: int = 0
    unowned: int = 0
    owed: int = 0

    def summary(self) -> str:
        return (f"official lines {self.lines}, owned by an entry {self.owned}, closed in the "
                f"dictionary {self.closed}, owned by an entry of another file {self.owed}, owned "
                f"by none {self.unowned}")


def check(dictionary: Dictionary, sources: Sources, *, partial: bool = False) -> Report:
    """Rule 1 over the whole dictionary. `Invalid` when a capture cannot be read."""
    report = Report()
    header = dictionary.header
    owners: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    elsewhere: dict[str, set[int]] = defaultdict(set)
    for entry in dictionary.entries:
        gone = {(c.ref, n) for c in entry.closed if c.reason == "elsewhere"
                for n in range(c.first, c.last + 1)}
        for r in _of_documents(dictionary, entry):
            if r.lines and split_ref(r.ref)[0] == DOCUMENT:
                for n in range(span(r.lines)[0], span(r.lines)[1] + 1):
                    if (r.ref, n) in gone:
                        elsewhere[r.ref].add(n)
                    else:
                        owners[r.ref][n].append(entry.id)
    ids = {e.id for e in dictionary.entries}
    for entry in dictionary.entries:
        for c in entry.closed:
            if c.reason == "elsewhere" and c.owner in ids:
                lacking = [n for n in range(c.first, c.last + 1)
                           if c.owner not in owners[c.ref].get(n, [])
                           and n in elsewhere[c.ref]]
                report.faults += [f"{c.ref}:{n} is closed elsewhere for {c.owner}, whose region "
                                  "does not hold it" for n in lacking]
    held_by_dictionary: dict[str, set[int]] = defaultdict(set)
    for c in header.closed:
        held_by_dictionary[c.ref] |= set(range(c.first, c.last + 1))
    for name, ranges in header.official.items():
        ref = f"{DOCUMENT}:{name}"
        if name not in sources.table:
            report.faults.append(f"document {name} is not in the document table")
            continue
        held = sources.lines(ref)
        if any(span(r)[1] > len(held) for r in ranges):
            raise Invalid(f"`official` of {name} runs past its capture, which has {len(held)} "
                          "lines")
        declared = {n for n in _lines(ranges) if held[n - 1].strip()}
        _classify(report, ref, declared, owners[ref], elsewhere[ref], held_by_dictionary[ref],
                  partial)
    for c in header.closed:
        declared = _lines(header.official.get(split_ref(c.ref)[1], ()))
        if not declared & set(range(c.first, c.last + 1)):
            report.faults.append(f"header closed {c.ref}:{c.lines} closes no line of a declared "
                                 "range")
    return report


def _classify(report: Report, ref: str, declared: set[int], owners: dict[int, list[str]],
              elsewhere: set[int], closed: set[int], partial: bool) -> None:
    for n in sorted(declared):
        report.lines += 1
        held = owners.get(n, [])
        if len(held) > 1:
            report.faults.append(f"{ref}:{n} is in the regions of {len(held)} entries "
                                 f"({', '.join(held)}): one owns a line, the others link to it")
        if held and n in closed:
            report.faults.append(f"{ref}:{n} is in a region and closed by the dictionary")
        if held:
            report.owned += 1
        elif n in closed:
            report.closed += 1
        elif n in elsewhere:
            report.owed += 1
        else:
            report.unowned += 1
            if not partial:
                report.faults.append(f"{ref}:{n} is a line of the declared programming model that "
                                     "no entry and no closure holds")
