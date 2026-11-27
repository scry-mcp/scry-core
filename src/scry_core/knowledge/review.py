"""What `rows review` prints for a reader, in the order a reply shows an entry: the `doc` rows as
the entry, then per emulator its notes with their `vs` and the row each names, then each verdict
closed on a row (`agrees`, every place it cites together, an `agrees` whose whole body does nothing
of what the row names, or `unfollowed`) with the emulator's lines
beside the row's text and quoted lines, then the entry's official region
whole for the notes that are `extra`; and what the reader's other questions need (the closures,
the callee decisions the entry used).
"""

from __future__ import annotations

import re
from collections import defaultdict

from scry_core.knowledge.closure import Report
from scry_core.knowledge.quote import Quote, Sources, split_ref
from scry_core.knowledge.rows import (
    EMULATORS,
    SWEEPING,
    VERDICT_CLOSURES,
    Closure,
    Dictionary,
    Entry,
    Row,
)

_WIDTH = 110


def _lines(quote: Quote, sources: Sources) -> list[str]:
    held = sources.read(quote)
    return [f"        {n:>6} | {line.strip()[:_WIDTH]}"
            for n, line in zip(range(quote.first, quote.last + 1), held, strict=True)]


def _row(row: Row, sources: Sources) -> list[str]:
    words = re.findall(r"[a-z]+", row.text.lower())
    flags = [w for w in SWEEPING if w in words]
    if row.state:
        flags.append(row.state)
    if row.vs == "absent":
        flags.append("absent: nothing observable may happen in its place")
    named = f" {row.vs}" + (f" row {row.row}" if row.row else "") if row.vs else ""
    variant = f"  variant {row.variant}" if row.variant else ""
    out = [f"  row {row.n}  {row.on}  of {row.of}{named}{variant}"
           + (f"   [{', '.join(flags)}]" if flags else ""), f"      {row.text}"]
    for q in row.quotes:
        out.append(f"      {q.ref} {q.lines}")
        out += _lines(q, sources)
    return out


def _source(dictionary: Dictionary, entry: Entry) -> list[str]:
    if dictionary.source_of(entry) == "official":
        return []
    out = ["  according to the emulator's source; no official document found"]
    for s in entry.searched or dictionary.header.searched:
        out.append(f"    searched {s.where}: {s.gave}")
    return out


def entry_text(dictionary: Dictionary, entry: Entry, report: Report, sources: Sources) -> str:
    out = [f"{entry.id}   name: {entry.name}", *_source(dictionary, entry)]
    docs = [r for r in entry.rows if r.of == "doc"]
    if docs:
        out.append("official rows (the entry)")
        for r in docs:
            out += _row(r, sources)
    for emulator in EMULATORS:
        notes = [r for r in entry.rows if r.of == emulator]
        if notes:
            out.append(f"notes of {emulator}")
            for r in notes:
                out += _row(r, sources)
    by_row = {r.n: r for r in docs}
    verdicts: dict[tuple[str, str, str], list[Closure]] = defaultdict(list)
    for c in entry.closed:
        if c.reason in VERDICT_CLOSURES:
            verdicts[(c.party, c.row, "nothing" if c.nothing else c.reason)].append(c)
    for (party, n, reason), places in verdicts.items():
        said = {"agrees": f"{party} agrees with row {n}, as documented",
                "nothing": f"{party} agrees with row {n} by doing nothing: the whole body below "
                           "stores nothing of what the row names",
                "unfollowed": f"{party} leaves row {n} unfollowed: what it does there was not "
                              "established"}[reason]
        out.append(f"{said} ({len(places)} place{'s' if len(places) > 1 else ''})")
        for c in places:
            out.append(f"      {c.ref} {c.lines}")
            out += _lines(Quote(c.ref, c.lines), sources)
        if n in by_row:
            out += _row(by_row[n], sources)
    extras = [r for r in entry.rows if r.vs == "extra"]
    official = [g for g in dictionary.regions(entry)
                if g.lines and split_ref(g.ref)[0] in ("datasheet", "rbil61")]
    if extras and official:
        out.append("official region whole, to read for each extra note "
                   f"({', '.join(f'{r.of} {r.n}' for r in extras)}): does any line speak of it?")
        for region in official:
            out.append(f"      {region.ref} {region.lines}")
            out += _lines(Quote(region.ref, region.lines), sources)
    by_subject: dict[str, list[Row]] = defaultdict(list)
    for r in entry.rows:
        if r.of != "doc" and not r.row:
            by_subject[r.on].append(r)
    for subject, together in by_subject.items():
        if len({r.of for r in together}) > 1:
            out.append(f"notes of several emulators on {subject}, together")
            out += [f"      {r.of} {r.n} {r.vs}: {r.text}" for r in together]
    for c in entry.closed:
        if c.reason in VERDICT_CLOSURES:
            continue
        out.append(f"  closed {c.ref} {c.lines} as {c.reason}"
                   + (f" ({c.why})" if c.why else "") + (f" owner {c.owner}" if c.owner else ""))
        out += _lines(Quote(c.ref, c.lines), sources)
    decided = sorted({f"{r.item.text} {r.by.removeprefix('callee: ')}"
                      for r in report.results if r.by.startswith("callee")})
    if decided:
        out.append("  callee decisions used: " + ", ".join(decided))
    out.append(f"  items {len(report.results)}, open {report.open}, owed elsewhere {report.owed}")
    return "\n".join(out)
