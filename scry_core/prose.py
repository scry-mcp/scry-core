from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REFUSAL_CHARS_SHOWN = 120
HEX_BYTES_SHOWN = 64


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """`n` with its noun, grammatically plural (never `(s)`)."""
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


def agrees(n: int, one: str, many: str) -> str:
    """The verb form a count of `n` takes."""
    return one if n == 1 else many


def ended_by(code: int) -> str:
    """A negative exit code is a signal."""
    return f"died by signal {-code}" if code < 0 else f"exited with code {code}"


def clipped(text: str, limit: int = REFUSAL_CHARS_SHOWN) -> str:
    """Cut `text` at a word; the rest is in `message`."""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit + 1)
    return text[:cut if cut > 0 else limit] + "..."


def refusal(name: str, reply: Mapping[str, Any]) -> str:
    """The summary line for an INVALID reply."""
    return f"{name}: INVALID ({reply.get('code')}), {clipped(str(reply.get('message', '')))}"


def hex_clipped(hex_text: str) -> str:
    """A read's bytes for its summary, the rest counted, never cut mid-byte into a shorter value."""
    shown = hex_text[:HEX_BYTES_SHOWN * 2]
    rest = (len(hex_text) - len(shown)) // 2
    return shown + (f"... ({rest} more bytes in `hex`)" if rest else "")
