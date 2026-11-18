from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REFUSAL_CHARS_SHOWN = 120
HEX_BYTES_SHOWN = 64


def counted(n: int, noun: str, plural: str | None = None) -> str:
    """`n` with its noun, grammatically plural (never `(s)`)."""
    return f"{n} {noun if n == 1 else plural or noun + 's'}"


def left(n: int) -> str:
    """A scan's count after a filter, as every summary says it."""
    return f"{n} left"


def reaction(verify: Mapping[str, Any]) -> str:
    """What an input's check (`verify`) found, as every summary says it."""
    if verify.get("available") is False:
        return "reaction could not be checked"
    if verify.get("seen"):
        return "reaction seen"
    if "verdict" in verify:
        return f"no reaction seen ({verify['verdict']})"
    return "no reaction seen" if verify.get("checked") else "sent, reaction not checked"


def ambiguous_name(name: str, addresses: Sequence[str], where: str) -> str:
    """The refusal of a name the table gives more than once, naming each address in file order."""
    return (f"{name!r} names {counted(len(addresses), 'symbol')} in {where} "
            f"({', '.join(addresses)}), so taking one would be a guess at the wrong address: "
            "use the address of the one meant")


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


def picture(reply: Mapping[str, Any]) -> str:
    """The picture's half of a view's line: its size, its scale and whether it is attached."""
    image = reply.get("image") or {}
    shown = "inline" if image.get("inline") else "not inlined"
    return f"{image.get('width')}x{image.get('height')} PNG x{image.get('scale')}, {shown}"
