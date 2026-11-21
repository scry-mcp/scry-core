"""The lock of a repository's checked entries, by id with the seal each was locked at and who
checked it against which lines, and the entries whose seal was lifted; written by
`scry_core.knowledge.seal` and `scry_core.knowledge.reopen`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_FORMAT = "scry-knowledge-lock/2"
COMMAND = "python -m scry_core.knowledge.seal"
REOPEN_COMMAND = "python -m scry_core.knowledge.reopen"


@dataclass(frozen=True)
class Locked:
    """What a check left in the lock: the seal, who checked, and the lines of each source it
    compared (`ref`, `line`), so a re-check can be told from a reword."""

    digest: str
    by: str
    against: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Reopened:
    """An entry whose seal was lifted: the id, the seal it had, who lifted it and why, and who had
    checked it against which lines, so the rewrite cannot be checked the same way again."""

    id: str
    digest: str
    by: str
    why: str
    checked_by: str
    against: tuple[tuple[str, str], ...]

    def was(self) -> Locked:
        """The lock row this reopening removed."""
        return Locked(self.digest, self.checked_by, self.against)


@dataclass(frozen=True)
class Lock:
    """The checked entries of a repository, each id with what its last check left, and the
    reopenings in the order they happened."""

    checked: Mapping[str, Locked]
    reopened: tuple[Reopened, ...] = ()

    def document(self) -> dict[str, Any]:
        """The lock as the commands write it: the ids sorted, `reopened` only when it has rows."""
        doc: dict[str, Any] = {"format": LOCK_FORMAT, "checked": {
            id_: {"digest": got.digest, "by": got.by,
                  "against": [{"ref": r, "line": line} for r, line in got.against]}
            for id_, got in sorted(self.checked.items())}}
        if self.reopened:
            doc["reopened"] = [
                {"id": r.id, "digest": r.digest, "by": r.by, "why": r.why,
                 "checked_by": r.checked_by,
                 "against": [{"ref": ref, "line": line} for ref, line in r.against]}
                for r in self.reopened]
        return doc


def dumps(doc: Any) -> str:
    """A document as the files here are written; the command rewrites only a file that reads so."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _locked(raw: object) -> Locked | None:
    if not (isinstance(raw, dict) and set(raw) == {"digest", "by", "against"}
            and isinstance(raw["digest"], str) and isinstance(raw["by"], str)
            and isinstance(raw["against"], list)):
        return None
    lines = [(a.get("ref"), a.get("line")) for a in raw["against"]
             if isinstance(a, dict) and set(a) == {"ref", "line"}]
    if len(lines) != len(raw["against"]) or not all(
            isinstance(r, str) and isinstance(line, str) for r, line in lines):
        return None
    return Locked(raw["digest"], raw["by"], tuple(lines))  # type: ignore[arg-type]


def _reopened(raw: object) -> Reopened | None:
    if not (isinstance(raw, dict)
            and set(raw) == {"id", "digest", "by", "why", "checked_by", "against"}):
        return None
    was = _locked({"digest": raw["digest"], "by": raw["checked_by"], "against": raw["against"]})
    if was is None or not all(isinstance(raw[k], str) for k in ("id", "by", "why")):
        return None
    return Reopened(raw["id"], was.digest, raw["by"], raw["why"], was.by, was.against)


def parse_lock(text: str, where: str = "lock") -> Lock:
    """The lock a command wrote, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    held = doc.get("checked") if isinstance(doc, dict) else None
    got = {k: _locked(v) for k, v in held.items()} if isinstance(held, dict) else {}
    said = doc.get("reopened", []) if isinstance(doc, dict) else []
    again = [_reopened(r) for r in said] if isinstance(said, list) else [None]
    if (not isinstance(doc, dict) or doc.get("format") != LOCK_FORMAT or not (
            {"format", "checked"} <= set(doc) <= {"format", "checked", "reopened"})
            or not isinstance(held, dict) or None in got.values() or None in again):
        raise ValueError(f"{where} is not a `{LOCK_FORMAT}` document: `format` and `checked`, "
                         "each id with its `digest`, `by` and `against`, and optionally "
                         "`reopened`, each with its `id`, `digest`, `by`, `why`, "
                         "`checked_by` and `against`")
    return Lock({k: v for k, v in got.items() if v is not None},
                tuple(r for r in again if r is not None))


def read_lock(path: Path) -> Lock:
    return parse_lock(path.read_text(encoding="utf-8"), path.name)
