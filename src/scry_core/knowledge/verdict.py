"""The verdict each emulator owes on each official row of an entry (`rows check`): for every `doc`
row whose subject is not `is`, and for each emulator the dictionary has code of, a verdict of one
class: `agrees` closures that together show the row done, `unfollowed` closures, or notes `differs`
or `absent` (one per part that departs). None says nobody looked; two classes on one row, an `is`
row included, say the entry contradicts itself.
"""

from __future__ import annotations

from scry_core.knowledge.rows import VERDICTS, Dictionary, Entry, Row

#: The class of verdict a note or a closure gives.
NOTES = "notes"


def faults(dictionary: Dictionary, entry: Entry) -> list[str]:
    docs = {r.n: r for r in entry.rows if r.of == "doc"}
    out: list[str] = []
    for r in entry.rows:
        if r.vs in VERDICTS and r.of not in dictionary.emulators and r.row not in docs:
            out.append(f"{r.of} note {r.n} names row {r.row}, which is no `doc` row of the entry")
    for emulator in dictionary.emulators:
        said: dict[str, list[tuple[str, str]]] = {n: [] for n in docs}
        for r in entry.rows:
            if r.of == emulator and r.vs in VERDICTS:
                _record(said, docs, NOTES, f"note {r.n}", r.row, emulator, out)
        for c in entry.closed:
            if c.reason in ("agrees", "unfollowed") and c.party == emulator:
                _record(said, docs, c.reason, f"{c.reason} {c.ref}:{c.lines}", c.row, emulator,
                        out)
        for n, row in docs.items():
            classes = sorted({what for what, _ in said[n]})
            if not said[n] and row.on != "is":
                out.append(f"row {n} has no verdict of {emulator}: a note `differs` or `absent` "
                           "or a closure `agrees` or `unfollowed` names it")
            elif len(classes) > 1:
                out.append(f"row {n} has verdicts of {emulator} of {len(classes)} classes "
                           f"({', '.join(by for _, by in said[n])}): `agrees`, `unfollowed` and "
                           "the notes do not mix on one row")
    return out


def _record(said: dict[str, list[tuple[str, str]]], docs: dict[str, Row], what: str, by: str,
            named: str, emulator: str, out: list[str]) -> None:
    if named not in docs:
        out.append(f"{emulator} {by} names row {named}, which is no `doc` row of the entry")
    else:
        said[named].append((what, by))
