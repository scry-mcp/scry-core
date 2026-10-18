"""A server reference's table of how a cancelled call ends, held against what its tools declare
(`scry_core.boundary.Boundary.declared_ends`): the table is a promise to a caller, and a promise
nobody compares with the code drifts the day a tool changes its end.

The table sits under `SECTION` and has a row per end, the end and the tools in backticks, what
the end leaves between them:

    | `stop` | the machine stopped ... | `run_to`, `run_for` |
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from scry_core import cancel

SECTION = "### A long wait, and a cancelled call"
_ROW = re.compile(r"^\| `(\w+)` \|.*\| (.*) \|\s*$", re.MULTILINE)


def unlike(reference: str, declared: Mapping[str, cancel.OnCancel | None]
           ) -> dict[str, dict[str, list[str]]]:
    """Where the table and the declarations disagree, per end: `table_only` (named in its row,
    declared otherwise) and `declared_only`; empty when they agree. A reference with no section,
    no table in it, or one end in two rows is a `ValueError`, never an agreement."""
    start = reference.find(SECTION)
    if start < 0:
        raise ValueError(f"the reference has no section {SECTION!r}")
    section = reference[start:]
    heading = re.search(r"^#", section[len(SECTION):], re.MULTILINE)
    if heading is not None:
        section = section[:len(SECTION) + heading.start()]
    rows: dict[str, set[str]] = {}
    for end, tools in _ROW.findall(section):
        if end not in cancel.ON_CANCEL:
            continue
        if end in rows:
            raise ValueError(f"the table of ends has two rows for `{end}`")
        rows[end] = set(re.findall(r"`(\w+)`", tools))
    if not rows:
        raise ValueError(f"the section {SECTION!r} holds no table of ends")
    by_end: dict[str, set[str]] = {}
    for tool, end in declared.items():
        if end is not None:
            by_end.setdefault(end, set()).add(tool)
    apart = {end: {"table_only": sorted(rows.get(end, set()) - by_end.get(end, set())),
                   "declared_only": sorted(by_end.get(end, set()) - rows.get(end, set()))}
             for end in rows.keys() | by_end.keys()}
    return {end: sides for end, sides in apart.items() if any(sides.values())}
