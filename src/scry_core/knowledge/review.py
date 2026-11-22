"""What `rows review` prints for a reader: each row with the text of its quoted lines, and what the
reader's other questions need beside them (the subjects several parties speak on, the closures
with their lines, the callee decisions the entry used).
"""

from __future__ import annotations

import re
from collections import defaultdict

from scry_core.knowledge.closure import Report
from scry_core.knowledge.quote import Quote, Sources
from scry_core.knowledge.rows import SWEEPING, Entry

_WIDTH = 110


def _lines(quote: Quote, sources: Sources) -> list[str]:
    held = sources.read(quote)
    return [f"        {n:>6} | {line.strip()[:_WIDTH]}"
            for n, line in zip(range(quote.first, quote.last + 1), held, strict=True)]


def entry_text(entry: Entry, report: Report, sources: Sources) -> str:
    out = [f"{entry.id}   name: {entry.name}"]
    for row in entry.rows:
        words = re.findall(r"[a-z]+", row.text.lower())
        flags = [w for w in SWEEPING if w in words]
        if row.state:
            flags.append(row.state)
        out.append(f"  row {row.n}  {row.on}  of {', '.join(row.of)}"
                   + (f"   [{', '.join(flags)}]" if flags else ""))
        out.append(f"      {row.text}")
        for q in row.quotes:
            out.append(f"      {q.ref} {q.lines}")
            out += _lines(q, sources)
    by_subject: dict[str, set[str]] = defaultdict(set)
    for row in entry.rows:
        by_subject[row.on] |= set(row.of)
    several = [s for s, parties in by_subject.items() if len(parties) > 1]
    if several:
        out.append("  subjects with several parties: " + ", ".join(several))
    for c in entry.closed:
        out.append(f"  closed {c.ref} {c.lines} as {c.reason}"
                   + (f" ({c.why})" if c.why else "") + (f" owner {c.owner}" if c.owner else ""))
        out += _lines(Quote(c.ref, c.lines), sources)
    decided = sorted({f"{r.item.text} {r.by.removeprefix('callee: ')}"
                      for r in report.results if r.by.startswith("callee")})
    if decided:
        out.append("  callee decisions used: " + ", ".join(decided))
    out.append(f"  items {len(report.results)}, open {report.open}, owed elsewhere {report.owed}")
    return "\n".join(out)
