"""What a reader sealed of an entry written as rows, and the two acts that write it: `seal` and
`reopen` (`rows seal`, `rows reopen`).

An entry has one part per party: its official part (`doc`: its key, name, aliases, source, its
`doc` rows, the closures of the document's lines and its official regions) and one part per
emulator the dictionary has code of (that emulator's notes, its closures and its regions). A
reader who did not write a part seals it: the lock keeps, per part, its seal, who read it, who
wrote it and, per row, the row's digest and who judged it. An entry is served when every part is
sealed at the seal it gives now, so a row reworded after its seal holds the entry back until a
reader judges it again. A reopening names the rows at fault and lifts the part's seal; when the
part is sealed again, only the rows whose digest changed are judged anew, and never by the reader
whose judgement was overturned.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scry_core.knowledge.quote import PARTY, split_ref
from scry_core.knowledge.rows import Dictionary, Entry, Row
from scry_core.knowledge.rows import read as read_dictionary

LOCK_FORMAT = "scry-knowledge-rows-lock/1"
OFFICIAL = "doc"

SERVED = "sealed"
UNSEALED = "unsealed"
CHANGED = "changed since it was sealed"


def _sha(value: object) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_digest(row: Row) -> str:
    """What a reader judged of a row: everything it says and each quote's file and digest, not
    the quote's `lines`, so a pin that only moves the text breaks no seal."""
    return _sha({"on": row.on, "of": row.of, "vs": row.vs, "row": row.row, "variant": row.variant,
                 "state": row.state, "text": row.text, "links": list(row.links),
                 "quotes": [[q.ref, q.sha] for q in row.quotes]})


def parts(dictionary: Dictionary) -> tuple[str, ...]:
    """The parts each entry of `dictionary` is sealed in: the official one, then each emulator's."""
    return (OFFICIAL, *dictionary.emulators)


def _party(ref: str) -> str:
    return PARTY[split_ref(ref)[0]]


def rows_of(entry: Entry, part: str) -> dict[str, str]:
    """The digest of each row of `part`, by label."""
    return {r.n: row_digest(r) for r in entry.rows if r.of == part}


def seal_of(dictionary: Dictionary, entry: Entry, part: str) -> str:
    """The seal of one part of `entry`: what a reader of that part judged. An emulator's part
    holds the digest of each `doc` row its notes and verdicts name, since a verdict is a judgement
    of what that row says."""
    closed = [c for c in entry.closed if c.party == part]
    named = {r.row for r in entry.rows if r.of == part and r.row} | {c.row for c in closed if c.row}
    body: dict[str, Any] = {
        "id": entry.id, "part": part, "rows": rows_of(entry, part),
        "closed": [asdict(c) for c in closed],
        "regions": [asdict(r) for r in dictionary.regions(entry) if _party(r.ref) == part]}
    if part != OFFICIAL:
        docs = rows_of(entry, OFFICIAL)
        body["judges"] = {n: docs.get(n, "") for n in sorted(named)}
    if part == OFFICIAL:
        body.update(key=entry.key, name=entry.name, aliases=list(entry.aliases),
                    source=dictionary.source_of(entry),
                    searched=[asdict(s) for s in entry.searched or dictionary.header.searched])
    return _sha(body)


@dataclass(frozen=True)
class Judged:
    digest: str
    by: str


@dataclass(frozen=True)
class Part:
    """A sealed part: its seal, its reader, its writer, and each row as it was judged."""

    seal: str
    by: str
    writer: str
    rows: Mapping[str, Judged]


@dataclass(frozen=True)
class Reopened:
    """A part whose seal was lifted: the rows at fault, who reopened it and why, and the part as
    it was sealed, so its unchanged rows keep their judgement and the overturned ones are not
    judged again by their reader."""

    id: str
    part: str
    rows: tuple[str, ...]
    by: str
    why: str
    was: Part


@dataclass(frozen=True)
class Lock:
    sealed: Mapping[str, Mapping[str, Part]]
    reopened: tuple[Reopened, ...] = ()

    def standing(self, dictionary: Dictionary, entry: Entry) -> str:
        """`SERVED`, or why `entry` is held back."""
        held = self.sealed.get(entry.id, {})
        for part in parts(dictionary):
            got = held.get(part)
            if got is None:
                return f"{UNSEALED} ({part})"
            if got.seal != seal_of(dictionary, entry, part):
                return f"{CHANGED} ({part})"
        return SERVED

    def last_reopened(self, id: str, part: str) -> Reopened | None:
        return next((r for r in reversed(self.reopened) if (r.id, r.part) == (id, part)), None)

    def document(self) -> dict[str, Any]:
        def part(p: Part) -> dict[str, Any]:
            return {"seal": p.seal, "by": p.by, "writer": p.writer,
                    "rows": {n: {"digest": j.digest, "by": j.by}
                             for n, j in sorted(p.rows.items())}}
        doc: dict[str, Any] = {"format": LOCK_FORMAT, "sealed": {
            id_: {name: part(p) for name, p in sorted(held.items())}
            for id_, held in sorted(self.sealed.items())}}
        if self.reopened:
            doc["reopened"] = [{"id": r.id, "part": r.part, "rows": list(r.rows), "by": r.by,
                                "why": r.why, "was": part(r.was)} for r in self.reopened]
        return doc


def _text(raw: Mapping[str, Any], *names: str) -> bool:
    return all(isinstance(raw.get(n), str) and raw[n] for n in names)


def _part(raw: object) -> Part:
    if not (isinstance(raw, dict) and set(raw) == {"seal", "by", "writer", "rows"}
            and _text(raw, "seal", "by", "writer") and isinstance(raw["rows"], dict)):
        raise ValueError("a part is `seal`, `by`, `writer` and `rows`")
    judged = {}
    for n, j in raw["rows"].items():
        if not (isinstance(j, dict) and set(j) == {"digest", "by"} and _text(j, "digest", "by")):
            raise ValueError(f"row {n} is `digest` and `by`")
        judged[n] = Judged(j["digest"], j["by"])
    return Part(raw["seal"], raw["by"], raw["writer"], judged)


def parse_lock(text: str, where: str = "lock") -> Lock:
    """The lock the commands wrote, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
        if not (isinstance(doc, dict) and doc.get("format") == LOCK_FORMAT
                and {"format", "sealed"} <= set(doc) <= {"format", "sealed", "reopened"}
                and isinstance(doc["sealed"], dict)):
            raise ValueError(f"`format` {LOCK_FORMAT}, `sealed` and optionally `reopened`")
        sealed = {}
        for id_, held in doc["sealed"].items():
            if not isinstance(held, dict):
                raise ValueError(f"{id_} maps each part to its seal")
            sealed[id_] = {name: _part(p) for name, p in held.items()}
        again = []
        listed = doc.get("reopened", [])
        if not isinstance(listed, list):
            raise ValueError("`reopened` is a list")
        for raw in listed:
            if not (isinstance(raw, dict) and set(raw) == {"id", "part", "rows", "by", "why", "was"}
                    and _text(raw, "id", "part", "by", "why") and isinstance(raw["rows"], list)
                    and all(isinstance(n, str) for n in raw["rows"])):
                raise ValueError("a reopening is `id`, `part`, `rows`, `by`, `why` and `was`")
            again.append(Reopened(raw["id"], raw["part"], tuple(raw["rows"]), raw["by"],
                                  raw["why"], _part(raw["was"])))
    except (json.JSONDecodeError, ValueError) as bad:
        raise ValueError(f"{where} is not a `{LOCK_FORMAT}` document: {bad}") from bad
    return Lock(sealed, tuple(again))


def read_lock(path: Path) -> Lock:
    return parse_lock(path.read_text(encoding="utf-8"), path.name)


def frozen(dictionary: Dictionary, lock: Lock) -> list[str]:
    """What changed in a sealed part since its seal, row by row: a sealed entry is never touched
    (decisions 37 and 39) except through `reopen`."""
    out: list[str] = []
    for entry in dictionary.entries:
        for part, got in lock.sealed.get(entry.id, {}).items():
            if part not in parts(dictionary):
                out.append(f"{entry.id}: the lock seals a part {part} the dictionary has no "
                           "code of")
                continue
            if got.by == got.writer:
                out.append(f"{entry.id} ({part}): read by its own writer {got.by!r}")
            if got.seal == seal_of(dictionary, entry, part):
                continue
            now = rows_of(entry, part)
            moved = sorted(n for n in {*now, *got.rows}
                           if now.get(n) != (got.rows[n].digest if n in got.rows else None))
            what = (f"rows {', '.join(moved)}" if moved
                    else "its closures, regions, names or the `doc` rows it judges")
            out.append(f"{entry.id} ({part}): {what} changed since {got.by!r} sealed it: "
                       f"reopen the part with `rows reopen <dictionary> {entry.id} --part {part}`"
                       ", with `--row <n>` for each row at fault")
    return out


def _judged(entry: Entry, part: str, by: str, before: Part | None, again: Reopened | None,
            faults: list[str]) -> dict[str, Judged]:
    """Each row of `part` with its judgement: the one it had when its digest is unchanged, else
    `by`'s, which may not be the reader whose judgement of that row was overturned."""
    out: dict[str, Judged] = {}
    at_fault = set(again.rows) if again else set()
    for n, digest in rows_of(entry, part).items():
        held = before.rows.get(n) if before else None
        if held is not None and held.digest == digest:
            if n in at_fault:
                faults.append(f"{entry.id} ({part}): row {n} was reopened and is unchanged: "
                              "rewrite it first")
            out[n] = held
            continue
        out[n] = Judged(digest, by)
    return out


def _overturned(again: Reopened) -> set[str]:
    """Who judged what a reopening named: each row's reader, or the part's when it named none."""
    return {again.was.rows[n].by for n in again.rows if n in again.was.rows} or {again.was.by}


def _dictionary(file: Path) -> Dictionary | list[str]:
    try:
        dictionary, faults = read_dictionary(file)
    except OSError as bad:
        return [f"{file.name}: {bad}"]
    if dictionary is None or faults:
        return [f"{file.name}: {f}" for f in faults] + ["`rows check` it before it is sealed"]
    return dictionary


def _read(file: Path, lock_file: Path) -> tuple[Dictionary, Lock] | list[str]:
    if not lock_file.parent.is_dir():
        return [f"the lock goes in {lock_file.parent}, which is no directory"]
    dictionary = _dictionary(file)
    if isinstance(dictionary, list):
        return dictionary
    try:
        lock = read_lock(lock_file) if lock_file.exists() else Lock({})
    except (OSError, ValueError) as bad:
        return [str(bad)]
    return dictionary, lock


def _write(lock_file: Path, lock: Lock) -> list[str]:
    try:
        with lock_file.open("w", encoding="utf-8", newline="\n") as out:
            out.write(json.dumps(lock.document(), indent=1, ensure_ascii=False) + "\n")
    except OSError as bad:
        return [f"{bad}: the lock may be half written; run the command again"]
    return []


def _entries(dictionary: Dictionary, ids: Sequence[str], part: str,
             faults: list[str]) -> list[Entry]:
    if part not in parts(dictionary):
        faults.append(f"{part} is no part of {dictionary.header.dictionary}: "
                      f"{', '.join(parts(dictionary))}")
        return []
    by_id = {e.id: e for e in dictionary.entries}
    faults.extend(f"{i} is no entry of {dictionary.header.dictionary}" for i in ids
                  if i not in by_id)
    return [by_id[i] for i in ids if i in by_id]


def seal(file: Path, ids: Sequence[str], lock_file: Path, part: str, by: str,
         writer: str) -> list[str]:
    """Seals `part` of each entry `ids` of `file` as read by `by` and written by `writer`, in the
    lock at `lock_file`; the lock is written, or nothing and the faults come back."""
    if not by.strip() or not writer.strip():
        return ["say who read the part and who wrote it: the lock keeps both"]
    if by.strip() == writer.strip():
        return [f"{by!r} wrote the part: a reader who did not write it seals it"]
    read = _read(file, lock_file)
    if isinstance(read, list):
        return read
    dictionary, lock = read
    faults: list[str] = []
    sealed = {i: dict(held) for i, held in lock.sealed.items()}
    for entry in _entries(dictionary, ids, part, faults):
        now = seal_of(dictionary, entry, part)
        before = sealed.get(entry.id, {}).get(part)
        if before is not None:
            if before.seal != now:
                faults.append(f"{entry.id} ({part}) changed since {before.by!r} sealed it: "
                              "reopen the rows at fault first")
            continue
        again = lock.last_reopened(entry.id, part)
        if again and by.strip() in _overturned(again):
            what = f"row {', '.join(again.rows)}" if again.rows else "the part"
            faults.append(f"{entry.id} ({part}): {by.strip()!r} judged what was reopened "
                          f"({what}), so another reader seals the rewrite")
            continue
        unstamped = [r.n for r in entry.rows if r.of == part and any(not q.sha for q in r.quotes)]
        if unstamped:
            faults.append(f"{entry.id} ({part}): row {', '.join(unstamped)} has a quote with no "
                          "digest: `rows quote --stamp` it first")
            continue
        rows = _judged(entry, part, by.strip(), again.was if again else None, again, faults)
        sealed.setdefault(entry.id, {})[part] = Part(now, by.strip(), writer.strip(), rows)
    if faults:
        return faults
    return _write(lock_file, Lock(sealed, lock.reopened))


def reopen(file: Path, ids: Sequence[str], lock_file: Path, part: str, rows: Sequence[str],
           by: str, why: str) -> list[str]:
    """Lifts the seal of `part` of each entry `ids`, naming the `rows` at fault (none when the
    fault is in the part's closures, regions or names), and records who reopened it and why."""
    if not by.strip() or not why.strip():
        return ["say who reopens the part and why: the lock keeps both"]
    read = _read(file, lock_file)
    if isinstance(read, list):
        return read
    dictionary, lock = read
    faults: list[str] = []
    sealed = {i: dict(held) for i, held in lock.sealed.items()}
    again = list(lock.reopened)
    for entry in _entries(dictionary, ids, part, faults):
        held = sealed.get(entry.id, {})
        was = held.get(part)
        if was is None:
            faults.append(f"{entry.id} ({part}) is not sealed: only a sealed part is reopened")
            continue
        named = tuple(rows)
        unknown = [n for n in named if n not in was.rows]
        if unknown:
            faults.append(f"{entry.id} ({part}): no sealed row {', '.join(unknown)}")
            continue
        del held[part]
        if not held:
            del sealed[entry.id]
        again.append(Reopened(entry.id, part, named, by.strip(), why.strip(), was))
    if faults:
        return faults
    return _write(lock_file, Lock(sealed, tuple(again)))


__all__ = ["CHANGED", "LOCK_FORMAT", "OFFICIAL", "SERVED", "UNSEALED", "Judged",
           "Lock", "Part", "Reopened", "frozen", "parse_lock", "parts", "read_lock",
           "reopen", "row_digest", "rows_of", "seal", "seal_of"]
