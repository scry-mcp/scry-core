"""What a reply may serve. An entry is confirmed when its lock holds it sealed at the digest it
has now and the second check recorded that same digest; anything else is held back.

The second check is one file format for every repository:
`{"format": "scry-knowledge-second-check/1", "confirmed": [{"id", "by", "digest"}, ...]}`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from scry_core.knowledge.entry import Entry
from scry_core.knowledge.lock import Lock

SECOND_FORMAT = "scry-knowledge-second-check/1"

CONFIRMED = "confirmed"
UNSEALED = "unsealed"
REOPENED = "reopened"
SEALED_ONCE = "sealed once"
CHANGED = "changed since it was sealed"
ANOTHER_DIGEST = "confirmed under another digest"

_DIGEST = re.compile(r"[0-9a-f]{64}")
_ROW = {"id", "by", "digest"}


@dataclass(frozen=True)
class Recorded:
    """What the second check left for one entry: who confirmed it, and at which seal."""

    by: str
    digest: str


@dataclass(frozen=True)
class SecondCheck:
    """The entries a second check confirmed, by id."""

    confirmed: Mapping[str, Recorded]


def parse_second_check(text: str, where: str = "second check") -> SecondCheck:
    """The second check a file holds, or `ValueError` naming what is wrong. The older shape (a
    `checked` mapping of id to `by` and `digest`) is refused by name, never read as empty."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    if not isinstance(doc, dict) or doc.get("format") != SECOND_FORMAT:
        raise ValueError(f"{where} is not a `{SECOND_FORMAT}` document")
    if "checked" in doc:
        raise ValueError(f"{where} is the older shape (`checked`, each id with its `by` and "
                         f"`digest`): the format is `confirmed`, a list of rows with `id`, `by` "
                         "and `digest`")
    rows = doc.get("confirmed")
    if set(doc) != {"format", "confirmed"} or not isinstance(rows, list):
        raise ValueError(f"{where} is `format` and `confirmed`, a list of rows")
    got: dict[str, Recorded] = {}
    for row in rows:
        if not (isinstance(row, dict) and set(row) == _ROW
                and all(isinstance(v, str) for v in row.values())):
            raise ValueError(f"{where}: a row is `id`, `by` and `digest`, all text")
        if not _DIGEST.fullmatch(row["digest"]):
            raise ValueError(f"{where}: {row['id']}: `digest` is 64 hex digits, lower case")
        if row["id"] in got:
            raise ValueError(f"{where}: {row['id']} is recorded twice")
        got[row["id"]] = Recorded(row["by"], row["digest"])
    return SecondCheck(got)


def read_second_check(path: Path) -> SecondCheck:
    return parse_second_check(path.read_text(encoding="utf-8"), path.name)


@dataclass(frozen=True)
class Confirmation:
    """The lock and the second check of a base, reduced to what the filter reads: the seal each
    sealed id holds, the ids whose seal was lifted, and the seal the second check recorded."""

    sealed: Mapping[str, str]
    reopened: frozenset[str]
    recorded: Mapping[str, str]

    @classmethod
    def of(cls, locks: Iterable[Lock], seconds: Iterable[SecondCheck]) -> Confirmation:
        """Every lock and every second check a base answers to (the shared ones and its own)."""
        sealed: dict[str, str] = {}
        reopened: set[str] = set()
        recorded: dict[str, str] = {}
        for lock in locks:
            sealed.update({i: held.digest for i, held in lock.checked.items()})
            reopened.update(r.id for r in lock.reopened)
        for second in seconds:
            recorded.update({i: row.digest for i, row in second.confirmed.items()})
        return cls(sealed, frozenset(reopened), recorded)

    def standing(self, e: Entry) -> str:
        """`CONFIRMED`, or why `e` is held back."""
        seal = self.sealed.get(e.id)
        if seal is None:
            return REOPENED if e.id in self.reopened else UNSEALED
        if seal != e.digest or e.checked is None or e.checked.digest != e.digest:
            return CHANGED
        got = self.recorded.get(e.id)
        if got is None:
            return SEALED_ONCE
        return CONFIRMED if got == e.digest else ANOTHER_DIGEST

    def confirms(self, e: Entry) -> bool:
        return self.standing(e) == CONFIRMED
