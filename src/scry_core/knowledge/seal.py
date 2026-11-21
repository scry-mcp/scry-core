"""The command that seals a check: it stamps the seal into the dictionary file and writes the
entry's id and seal to the repository's lock (`scry_core.knowledge.lock`). It is run when an entry
has been checked, and again when a correction has been checked anew:

    python -m scry_core.knowledge.seal <dictionary.json> <entry id>... --lock <lock.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scry_core.knowledge import entry as fmt
from scry_core.knowledge import keys
from scry_core.knowledge.lock import COMMAND, Lock, Locked, dumps, read_lock


def find(doc: Mapping[str, Any], header: fmt.Header, wanted: str) -> dict[str, Any] | None:
    for raw in doc["entries"]:
        if not (isinstance(raw, dict) and isinstance(raw.get("key"), str)):
            continue
        try:
            key = keys.canonical(header.kind, raw["key"])
        except keys.KeyFault:
            continue
        access = raw.get("access", "")
        if isinstance(access, str) and fmt.entry_id(header.scope, header.kind, key,
                                                    access) == wanted:
            return raw
    return None


def _again(locked: Locked | None, now: fmt.Check, seal_: str) -> str:
    """Why `now` is no new check of an entry already locked, or last locked before it was
    reopened, or nothing: its seal moved (the text or the record changed) and the checker and the
    lines compared are those."""
    if locked is None or locked.digest == seal_ or locked.by != now.by or (
            sorted(locked.against) != sorted(now.against)):
        return ""
    return (f"checked by {now.by!r} against the lines already locked, and the entry changed since: "
            "a correction is checked again by another session, or against other lines, and "
            "that check is what `checked` records")


def read_both(file: Path, lock_file: Path) -> tuple[dict[str, Any], fmt.Header, Lock] | list[str]:
    """A dictionary and the lock beside it as the commands read them, or the faults that refuse
    both: the lock's folder is missing, a file does not read, or the dictionary is not written the
    way the commands write it."""
    if not lock_file.parent.is_dir():
        return [f"the lock goes in {lock_file.parent}, which is no directory"]
    try:
        text = file.read_text(encoding="utf-8")
        doc = json.loads(text)
        lock = read_lock(lock_file) if lock_file.exists() else Lock({})
    except (OSError, ValueError) as bad:
        return [f"{file.name}: {bad}"]
    if text != dumps(doc):
        return [f"{file.name} is not written the way this command writes it (`json.dumps` with "
                "`indent=2`, `ensure_ascii=False` and a final newline), and writing it would "
                "reformat it: rewrite it that way in its own commit first"]
    header, faults = fmt.parse_header(doc, file.name)
    return faults if header is None else (doc, header, lock)


def write_both(file: Path, doc: Mapping[str, Any], lock_file: Path, lock: Lock) -> list[str]:
    """Writes the dictionary and the lock, or says the pair may be half written."""
    try:
        with file.open("w", encoding="utf-8", newline="\n") as out:
            out.write(dumps(doc))
        with lock_file.open("w", encoding="utf-8", newline="\n") as out:
            out.write(dumps(lock.document()))
    except OSError as bad:
        return [f"{bad}: the dictionary or the lock may be half written; run the command again"]
    return []


def seal(file: Path, ids: Sequence[str], lock_file: Path) -> list[str]:
    """Stamps the seal of each entry `ids` into `file` and writes them to the lock at
    `lock_file`. Both files are written, or neither and the faults come back. Each entry already
    carries its `checked` record (`by`, `writer`, `against`; any `digest` is replaced)."""
    read = read_both(file, lock_file)
    if isinstance(read, list):
        return read
    doc, header, lock = read
    faults: list[str] = []
    sealed = dict(lock.checked)
    for wanted in ids:
        raw = find(doc, header, wanted)
        if raw is None:
            faults.append(f"{wanted} is no entry of {file.name}")
            continue
        record = raw.get("checked")
        if not isinstance(record, dict) or not {"by", "writer", "against"} <= set(record):
            faults.append(f"{wanted} has no `checked` record with `by`, `writer` and `against`: "
                          "add it first")
            continue
        record["digest"] = ""
        record["digest"] = fmt.digest(header.scope, header.kind, raw, header.reached)
        got, problems = fmt.parse_entry(raw, header)
        if got is None:
            faults.extend(f"{wanted}: {f}" for f in problems)
            continue
        assert got.checked is not None
        before = sealed.get(got.id) or next(
            (r.was() for r in reversed(lock.reopened) if r.id == got.id), None)
        again = _again(before, got.checked, record["digest"])
        if again:
            faults.append(f"{wanted}: {again}")
            continue
        sealed[got.id] = Locked(record["digest"], got.checked.by, got.checked.against)
    if faults:
        return faults
    return write_both(file, doc, lock_file, Lock(sealed, lock.reopened))


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(
        prog=COMMAND, description="Seal the check of entries and write it to the lock: run it "
        "when an entry has been checked, and again after a correction that was checked anew. "
        "Exit 0 when sealed, 2 when refused (nothing is written).")
    ask.add_argument("dictionary", type=Path, help="the dictionary file the entries are in")
    ask.add_argument("ids", nargs="+", help="the ids of the entries, as `knowledge_find` gives "
                     "them (`ibm-pc:port:0x3C8`)")
    ask.add_argument("--lock", type=Path, required=True, help="the repository's lock file")
    got = ask.parse_args(argv)
    faults = seal(got.dictionary, got.ids, got.lock)
    for fault in faults:
        print(fault, file=sys.stderr)
    if not faults:
        print(f"sealed {len(got.ids)} in {got.dictionary.name} and {got.lock.name}")
    return 2 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
