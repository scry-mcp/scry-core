"""A reference's table of how a cancelled call ends, held against `Boundary.declared_ends`."""

from __future__ import annotations

import re
from collections.abc import Mapping

from scry_core import cancel

SECTION = "### A long wait, and a cancelled call"
_ROW = re.compile(r"^\| `(\w+)` \|.*\| (.*) \|\s*$", re.MULTILINE)


def unlike(reference: str, declared: Mapping[str, cancel.OnCancel]
           ) -> dict[str, dict[str, list[str]]]:
    """Per end, `table_only` and `declared_only` tools; empty when they agree. A missing section,
    table or a duplicated end raises `ValueError`."""
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
        by_end.setdefault(end, set()).add(tool)
    apart = {end: {"table_only": sorted(rows.get(end, set()) - by_end.get(end, set())),
                   "declared_only": sorted(by_end.get(end, set()) - rows.get(end, set()))}
             for end in rows.keys() | by_end.keys()}
    return {end: sides for end, sides in apart.items() if any(sides.values())}
