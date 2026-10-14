"""The prefix of a server's texts that the MCP client delivers: every `instructions` and tool
description has to fit it, or the model never reads what is past the cut.

The client compares a JavaScript `.length`, so the unit is the UTF-16 code unit, not the
character or the byte. This is the one place the cap's value lives; each server's suite calls
`over_the_cap` on its own servers and fails on any line it returns.
"""

from __future__ import annotations

import asyncio
from typing import Any

CLIENT_TEXT_CAP = 2048
PAST_THE_CUT_SHOWN = 60


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def past_the_cut(text: str) -> str:
    """What the model loses, from the first unit past the cap, measured in the client's unit and
    folded onto one line so each offending text stays one line of the report."""
    lost = text.encode("utf-16-le")[2 * CLIENT_TEXT_CAP:].decode("utf-16-le", errors="replace")
    return " ".join(lost[:PAST_THE_CUT_SHOWN].split())


def over_the_cap(server: str, mcp: Any) -> list[str]:
    """One line per text of `mcp` (an MCP server object) over the cap, naming it and what is lost.

    A server that declares no instructions or lists no tools raises `AssertionError`: a load that
    examined nothing is not a pass, since an empty server has no text over any cap."""
    instructions = mcp.instructions or ""
    tools = list(asyncio.run(mcp.list_tools()))
    assert instructions, f"{server} declares no instructions, so there is nothing to measure"
    assert tools, f"{server} lists no tools, so there is nothing to measure"
    texts = [("instructions", instructions)] + [(t.name, t.description or "") for t in tools]
    return [f'{server} {name} {utf16_units(text)} > {CLIENT_TEXT_CAP}: "{past_the_cut(text)}"'
            for name, text in texts if utf16_units(text) > CLIENT_TEXT_CAP]
