"""The words of a search, and the order of its answer, which is ours and not FTS5's: both paths
only say which entries hold every word, so a host with no FTS5 answers the same rows."""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass

#: Best first: a hit in the name outranks one in the aliases, and so on.
FIELDS = ("name", "aliases", "description", "behaviour")
_WORD = re.compile(r"[^\W_]+")


def words(text: str) -> list[str]:
    """The words of `text`: lower case, accents removed."""
    if not text.isascii():
        text = "".join(c for c in unicodedata.normalize("NFKD", text)
                       if not unicodedata.combining(c))
    return _WORD.findall(text.casefold())


@dataclass(frozen=True)
class Term:
    """One word a caller asked for, and whether it is a prefix (it ended with `*`)."""

    word: str
    prefix: bool

    def held_by(self, tokens: set[str]) -> bool:
        return any(t.startswith(self.word) for t in tokens) if self.prefix else self.word in tokens

    def fts(self) -> str:
        return f'"{self.word}"' + ("*" if self.prefix else "")


def terms(query: str) -> list[Term]:
    """The words asked for; one ending in `*` is a prefix. Anything else is a separator."""
    out: list[Term] = []
    for raw in query.split():
        found = words(raw)
        out.extend(Term(w, raw.endswith("*") and i == len(found) - 1)
                   for i, w in enumerate(found))
    return out


def tier(asked: list[Term], fields: dict[str, set[str]]) -> int:
    """0 when the name holds every word, 1 with the aliases, 2 with the description, 3 else."""
    seen: set[str] = set()
    for i, name in enumerate(FIELDS):
        seen |= fields[name]
        if all(t.held_by(seen) for t in asked):
            return i
    return len(FIELDS)


class Fallback:
    """Word to the entries that hold it, for a host with no FTS5."""

    def __init__(self) -> None:
        self._held: dict[str, set[int]] = {}
        self._sorted: list[str] = []

    def add(self, n: int, fields: dict[str, set[str]]) -> None:
        for tokens in fields.values():
            for word in tokens:
                self._held.setdefault(word, set()).add(n)

    def freeze(self) -> None:
        self._sorted = sorted(self._held)

    def find(self, asked: list[Term]) -> set[int]:
        found: set[int] | None = None
        for term in asked:
            if term.prefix:
                at = bisect.bisect_left(self._sorted, term.word)
                have: set[int] = set()
                while at < len(self._sorted) and self._sorted[at].startswith(term.word):
                    have |= self._held[self._sorted[at]]
                    at += 1
            else:
                have = self._held.get(term.word, set())
            found = set(have) if found is None else found & have
            if not found:
                return set()
        return found or set()
