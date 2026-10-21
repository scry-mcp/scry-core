"""The prefix of a server's texts that the MCP client delivers: every `instructions` and tool
description has to fit it, or the model never reads what is past the cut.

The client compares a JavaScript `.length`, so the unit is the UTF-16 code unit, not the
character or the byte. This is the one place the cap's value lives: each server's suite fails on
any line `over_the_cap` returns for its servers (through `probe_checks.over_cap`) and prints the
`margins` of the texts nearest it on every run, and the probe shows its model only what
`delivered` keeps.
"""

from __future__ import annotations

import asyncio
from typing import Any

from scry_core.verdict import Invalid

CLIENT_TEXT_CAP = 2048
PAST_THE_CUT_SHOWN = 60


def _utf16(text: str) -> bytes:
    # A lone surrogate is one unit to the client's `.length`, so it is encoded, never refused.
    return text.encode("utf-16-le", errors="surrogatepass")


def utf16_units(text: str) -> int:
    return len(_utf16(text)) // 2


def delivered(text: str) -> str:
    """The text as the client delivers it: its first `CLIENT_TEXT_CAP` units. A character outside
    the BMP that straddles the cut is dropped whole, since half a surrogate pair is no character
    a model could read. The probe shows the model this, so what it measures is what is delivered."""
    return _utf16(text)[:2 * CLIENT_TEXT_CAP].decode("utf-16-le", errors="ignore")


def past_the_cut(text: str) -> str:
    """What the model loses, from the first unit past the cap, measured in the client's unit and
    folded onto one line so each offending text stays one line of the report."""
    lost = _utf16(text)[2 * CLIENT_TEXT_CAP:].decode("utf-16-le", errors="replace")
    return " ".join(lost[:PAST_THE_CUT_SHOWN].split())


def _texts(server: str, mcp: Any) -> list[tuple[str, str]]:
    """Every text of `mcp` (an MCP server object) the client delivers, by name. A server that
    declares no instructions or lists no tools is `Invalid`: a load that examined nothing is not
    a pass, since an empty server has no text over any cap."""
    instructions = mcp.instructions or ""
    tools = list(asyncio.run(mcp.list_tools()))
    if not instructions:
        raise Invalid(f"{server} declares no instructions, so there is nothing to measure")
    if not tools:
        raise Invalid(f"{server} lists no tools, so there is nothing to measure")
    return [("instructions", instructions)] + [(t.name, t.description or "") for t in tools]


def over_the_cap(server: str, mcp: Any) -> list[str]:
    """One line per text of `mcp` over the cap, naming it and what is lost."""
    return [f'{server} {name} {utf16_units(text)} > {CLIENT_TEXT_CAP}: "{past_the_cut(text)}"'
            for name, text in _texts(server, mcp) if utf16_units(text) > CLIENT_TEXT_CAP]


def margins(server: str, mcp: Any, shown: int | None = None) -> list[str]:
    """One line per text of `mcp`, its length and the units left under the cap, nearest the cap
    first (a text over it has a negative margin); the first `shown`, or every one. A text one
    sentence under the cap breaks on the next edit, which a list of breaches alone never says."""
    rows = sorted((CLIENT_TEXT_CAP - utf16_units(text), name) for name, text in _texts(server, mcp))
    return [f"{server} {name} {CLIENT_TEXT_CAP - left} units, margin {left}"
            for left, name in rows[:shown]]
