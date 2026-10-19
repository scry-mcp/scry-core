"""HOW A COUNT IS SAID in a summary, a note or a refusal, on every Scry server: the one plural
rule, and the verb that agrees with it.

THE RULE IS GRAMMATICAL, never `(s)`: `1 byte`, `48 bytes`, `0 lines`. `(s)` prints `48 byte(s)`
where English says `48 bytes`, and a plural written bare beside a count prints `1 bytes`.
"""

from __future__ import annotations


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """`n` with its noun in the number it has. `plural` where adding `s` is not English
    (`entries`, `matches`)."""
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


def agrees(n: int, one: str, many: str) -> str:
    """The verb (or pronoun) a count of `n` takes: `agrees(1, "was", "were")`."""
    return one if n == 1 else many
