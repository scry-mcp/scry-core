from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REFUSAL_CHARS_SHOWN = 120


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """`n` with its noun, grammatically plural (never `(s)`)."""
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


def agrees(n: int, one: str, many: str) -> str:
    """The verb form a count of `n` takes."""
    return one if n == 1 else many


def clipped(text: str, limit: int = REFUSAL_CHARS_SHOWN) -> str:
    """Cut `text` at a word; the rest is in `message`."""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit + 1)
    return text[:cut if cut > 0 else limit] + "..."


def refusal(name: str, reply: Mapping[str, Any]) -> str:
    """The summary line for an INVALID reply."""
    return f"{name}: INVALID ({reply.get('code')}), {clipped(str(reply.get('message', '')))}"
