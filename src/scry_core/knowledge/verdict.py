"""The verdict each emulator owes on each official row of an entry (`rows check`): for every `doc`
row whose subject is not `is`, and for each emulator the dictionary has code of, exactly one of a
note `differs` or `absent` that names the row, or a closure `agrees` that names it. None says
nobody looked; two say the entry contradicts itself.
"""

from __future__ import annotations

from scry_core.knowledge.rows import VERDICTS, Dictionary, Entry, Row


def faults(dictionary: Dictionary, entry: Entry) -> list[str]:
    docs = {r.n: r for r in entry.rows if r.of == "doc"}
    out: list[str] = []
    for r in entry.rows:
        if r.vs in VERDICTS and r.of not in dictionary.emulators and r.row not in docs:
            out.append(f"{r.of} note {r.n} names row {r.row}, which is no `doc` row of the entry")
    for emulator in dictionary.emulators:
        said: dict[str, list[str]] = {n: [] for n in docs}
        for r in entry.rows:
            if r.of == emulator and r.vs in VERDICTS:
                _record(said, docs, f"note {r.n}", r.row, emulator, out)
        for c in entry.closed:
            if c.reason == "agrees" and c.party == emulator:
                _record(said, docs, f"closure {c.ref}:{c.lines}", c.row, emulator, out)
        for n, row in docs.items():
            if row.on == "is":
                continue
            if not said[n]:
                out.append(f"row {n} has no verdict of {emulator}: a note `differs` or `absent` "
                           "or a closure `agrees` names it")
            elif len(said[n]) > 1:
                out.append(f"row {n} has {len(said[n])} verdicts of {emulator} "
                           f"({', '.join(said[n])}): exactly one")
    return out


def _record(said: dict[str, list[str]], docs: dict[str, Row], by: str, named: str,
            emulator: str, out: list[str]) -> None:
    if named not in docs:
        out.append(f"{emulator} {by} names row {named}, which is no `doc` row of the entry")
    else:
        said[named].append(by)
