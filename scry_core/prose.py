"""HOW A COUNT IS SAID in a summary, a note or a refusal, on every Scry server: the one plural
rule, and the verb that agrees with it; and the one line every tool answers for a refusal.

THE RULE IS GRAMMATICAL, never `(s)`: `1 byte`, `48 bytes`, `0 lines`. `(s)` prints `48 byte(s)`
where English says `48 bytes`, and a plural written bare beside a count prints `1 bytes`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Where a refusal's prose is cut for its summary line: the whole of it is in `message`.
REFUSAL_CHARS_SHOWN = 120


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """`n` with its noun in the number it has. `plural` where adding `s` is not English
    (`entries`, `matches`)."""
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


def agrees(n: int, one: str, many: str) -> str:
    """The verb (or pronoun) a count of `n` takes: `agrees(1, "was", "were")`."""
    return one if n == 1 else many


def clipped(text: str, limit: int = REFUSAL_CHARS_SHOWN) -> str:
    """A long refusal cut for the summary line: at a word, with a mark saying the rest is in
    `message`. A cut inside a word reads as a word that does not exist."""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit + 1)
    return text[:cut if cut > 0 else limit] + "..."


def refusal(name: str, reply: Mapping[str, Any]) -> str:
    """Every tool's line for an INVALID reply: the code, and the prose cut at a word."""
    return f"{name}: INVALID ({reply.get('code')}), {clipped(str(reply.get('message', '')))}"
