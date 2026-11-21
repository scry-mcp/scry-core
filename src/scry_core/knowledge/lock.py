"""The lock of a repository's checked entries, by id with the seal each was locked at and who
checked it against which lines; written by `scry_core.knowledge.seal`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_FORMAT = "scry-knowledge-lock/2"
COMMAND = "python -m scry_core.knowledge.seal"


@dataclass(frozen=True)
class Locked:
    """What a check left in the lock: the seal, who checked, and the lines of each source it
    compared (`ref`, `line`), so a re-check can be told from a reword."""

    digest: str
    by: str
    against: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Lock:
    """The checked entries of a repository, each id with what its last check left."""

    checked: Mapping[str, Locked]

    def document(self) -> dict[str, Any]:
        """The lock as the command writes it: the ids sorted."""
        return {"format": LOCK_FORMAT, "checked": {
            id_: {"digest": got.digest, "by": got.by,
                  "against": [{"ref": r, "line": line} for r, line in got.against]}
            for id_, got in sorted(self.checked.items())}}


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


def parse_lock(text: str, where: str = "lock") -> Lock:
    """The lock a command wrote, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    held = doc.get("checked") if isinstance(doc, dict) else None
    got = {k: _locked(v) for k, v in held.items()} if isinstance(held, dict) else {}
    if (not isinstance(doc, dict) or doc.get("format") != LOCK_FORMAT or set(doc) != {
            "format", "checked"} or not isinstance(held, dict) or None in got.values()):
        raise ValueError(f"{where} is not a `{LOCK_FORMAT}` document: `format` and `checked`, "
                         "each id with its `digest`, `by` and `against`")
    return Lock({k: v for k, v in got.items() if v is not None})


def read_lock(path: Path) -> Lock:
    return parse_lock(path.read_text(encoding="utf-8"), path.name)
