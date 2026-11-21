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

    def fts(self, fields: tuple[str, ...] = ()) -> str:
        match = f'"{self.word}"' + ("*" if self.prefix else "")
        return f"{{{' '.join(fields)}}} : {match}" if fields else match


def terms(query: str) -> list[Term]:
    """The words asked for; one ending in `*` is a prefix. Anything else is a separator."""
    out: list[Term] = []
    for raw in query.split():
        found = words(raw)
        out.extend(Term(w, raw.endswith("*") and i == len(found) - 1)
                   for i, w in enumerate(found))
    return out


class Fallback:
    """Word to the entries that hold it, per field, for a host with no FTS5."""

    def __init__(self) -> None:
        self._held: dict[str, dict[str, set[int]]] = {f: {} for f in FIELDS}
        self._sorted: dict[str, list[str]] = {}

    def add(self, n: int, fields: dict[str, set[str]]) -> None:
        for field, tokens in fields.items():
            held = self._held[field]
            for word in tokens:
                held.setdefault(word, set()).add(n)

    def freeze(self) -> None:
        self._sorted = {f: sorted(held) for f, held in self._held.items()}

    def _in(self, field: str, term: Term) -> set[int]:
        held = self._held[field]
        if not term.prefix:
            return held.get(term.word, set())
        words = self._sorted[field]
        at = bisect.bisect_left(words, term.word)
        have: set[int] = set()
        while at < len(words) and words[at].startswith(term.word):
            have |= held[words[at]]
            at += 1
        return have

    def tiers(self, asked: list[Term]) -> dict[int, int]:
        """The entries holding every word of `asked`, each with its tier (an index of `FIELDS`)."""
        so_far: list[set[int]] = [set() for _ in asked]
        found: dict[int, int] = {}
        for tier, field in enumerate(FIELDS):
            for have, term in zip(so_far, asked, strict=True):
                have |= self._in(field, term)
            for n in set.intersection(*so_far):
                found.setdefault(n, tier)
        return found
