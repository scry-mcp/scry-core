"""The prefix of a server's texts the MCP client delivers, in UTF-16 code units."""

from __future__ import annotations

import asyncio
from typing import Any

from scry_core.verdict import Invalid

#: Claude Code's MCP docs, *Tool search for MCP server authors*.
CLIENT_TEXT_CAP = 4096
PAST_THE_CUT_SHOWN = 60


def _utf16(text: str) -> bytes:
    # A lone surrogate is one unit to the client's `.length`: encode, never refuse.
    return text.encode("utf-16-le", errors="surrogatepass")


def utf16_units(text: str) -> int:
    return len(_utf16(text)) // 2


def delivered(text: str) -> str:
    """The first `CLIENT_TEXT_CAP` units; a character straddling the cut is dropped."""
    return _utf16(text)[:2 * CLIENT_TEXT_CAP].decode("utf-16-le", errors="ignore")


def _lost(text: str) -> str:
    return _utf16(text)[2 * CLIENT_TEXT_CAP:].decode("utf-16-le", errors="replace")


def past_the_cut(text: str) -> str:
    return " ".join(_lost(text).split())[:PAST_THE_CUT_SHOWN]


def _texts(server: str, mcp: Any) -> list[tuple[str, str]]:
    """Every (name, text) of `mcp`; `Invalid` when there is nothing to measure."""
    instructions = mcp.instructions or ""
    tools = list(asyncio.run(mcp.list_tools()))
    if not instructions:
        raise Invalid(f"{server} declares no instructions, so there is nothing to measure")
    if not tools:
        raise Invalid(f"{server} lists no tools, so there is nothing to measure")
    return [("instructions", instructions)] + [(t.name, t.description or "") for t in tools]


def over_the_cap(server: str, mcp: Any) -> list[str]:
    """One line per text over the cap."""
    return [f"{server} {name} {utf16_units(text)} > {CLIENT_TEXT_CAP}, the client drops: "
            + (f'"{past_the_cut(text)}"' if _lost(text).strip() else "whitespace only")
            for name, text in _texts(server, mcp) if utf16_units(text) > CLIENT_TEXT_CAP]


def margins(server: str, mcp: Any, shown: int | None = None) -> list[str]:
    """One line per text, nearest the cap first; the first `shown`."""
    rows = sorted((CLIENT_TEXT_CAP - utf16_units(text), name) for name, text in _texts(server, mcp))
    return [f"{server} {name} {CLIENT_TEXT_CAP - left} units, margin {left}"
            for left, name in rows[:shown]]
