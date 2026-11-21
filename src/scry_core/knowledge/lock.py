"""The lock of a repository's checked entries: the file format, and reading it.

A checked entry holds a seal over its text and its check (`entry.digest`). The lock is the
repository's own list of every checked entry, by id, with the seal it was locked at: a check that
is deleted, an entry that is removed, or a text and a seal that were both rewritten by hand all
show up as a difference from the committed lock. `scry_core.knowledge.seal` is the command that
writes it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_FORMAT = "scry-knowledge-lock/1"
COMMAND = "python -m scry_core.knowledge.seal"


@dataclass(frozen=True)
class Lock:
    """The checked entries of a repository: each id with the seal it was locked at."""

    checked: Mapping[str, str]


def dumps(doc: Any) -> str:
    """A document as the files here are written: two-space indent, keys as given, one final
    newline. The command rewrites only a file that already reads this way."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def parse_lock(text: str, where: str = "lock") -> Lock:
    """The lock a command wrote, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    held = doc.get("checked") if isinstance(doc, dict) else None
    if (not isinstance(doc, dict) or doc.get("format") != LOCK_FORMAT or set(doc) != {
            "format", "checked"} or not isinstance(held, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in held.items())):
        raise ValueError(f"{where} is not a `{LOCK_FORMAT}` document: `format` and `checked`, "
                         "each id with its seal")
    return Lock(dict(held))


def read_lock(path: Path) -> Lock:
    return parse_lock(path.read_text(encoding="utf-8"), path.name)
