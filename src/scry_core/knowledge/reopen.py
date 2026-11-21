"""The command that lifts the seal of a checked entry so a writer can correct it: it removes the
entry's `checked` record from the dictionary and its row from the lock, and records the reopening
in the lock (the id, the seal it had, who reopened it, why). It is run when a check or a reading
shows a sealed entry wrong or incomplete; the entry is then rewritten, checked by another session
and sealed again with `scry_core.knowledge.seal`:

    python -m scry_core.knowledge.reopen <dictionary.json> <entry id>... --lock <lock.json> \\
        --by <who reopens> --why <what is wrong>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scry_core.knowledge.lock import REOPEN_COMMAND, Lock, Reopened
from scry_core.knowledge.seal import find, read_both, write_both


def reopen(file: Path, ids: Sequence[str], lock_file: Path, by: str, why: str) -> list[str]:
    """Lifts the seal of each entry `ids` of `file` and records it in the lock at `lock_file`.
    Both files are written, or neither and the faults come back. An entry is reopened only while
    it is locked."""
    if not by.strip() or not why.strip():
        return ["say who reopens the entry and why: the lock keeps both"]
    read = read_both(file, lock_file)
    if isinstance(read, list):
        return read
    doc, header, lock = read
    held = dict(lock.checked)
    said = list(lock.reopened)
    faults: list[str] = []
    for wanted in ids:
        raw = find(doc, header, wanted)
        if raw is None:
            faults.append(f"{wanted} is no entry of {file.name}")
        elif wanted not in held:
            faults.append(f"{wanted} is not locked: only a sealed entry is reopened")
        else:
            raw.pop("checked", None)
            was = held.pop(wanted)
            said.append(Reopened(wanted, was.digest, by.strip(), why.strip(), was.by,
                                 was.against))
    if faults:
        return faults
    return write_both(file, doc, lock_file, Lock(held, tuple(said)))


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(
        prog=REOPEN_COMMAND, description="Lift the seal of checked entries so they can be "
        "rewritten: removes their `checked` record and lock row and records who reopened them "
        "and why. Exit 0 when reopened, 2 when refused (nothing is written).")
    ask.add_argument("dictionary", type=Path, help="the dictionary file the entries are in")
    ask.add_argument("ids", nargs="+", help="the ids of the entries, as `knowledge_find` gives "
                     "them (`ibm-pc:port:0x3C8`)")
    ask.add_argument("--lock", type=Path, required=True, help="the repository's lock file")
    ask.add_argument("--by", required=True, help="who reopens them")
    ask.add_argument("--why", required=True, help="what is wrong with them")
    got = ask.parse_args(argv)
    faults = reopen(got.dictionary, got.ids, got.lock, got.by, got.why)
    for fault in faults:
        print(fault, file=sys.stderr)
    if not faults:
        print(f"reopened {len(got.ids)} in {got.dictionary.name} and {got.lock.name}")
    return 2 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
