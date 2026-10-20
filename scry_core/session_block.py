"""THE `session` BLOCK, the field that closes every reply of both servers: its ALARMS on every
reply, its FIXED half where a caller asks what the session is.

A fact rides where it is asked for. What a caller must never miss rides on every reply: whether
the machine is alive, running and written to, and each alarm while it holds. What is fixed for the
life of a session, or only counts, rides on `start` and `status` (`WHOLE_ON`), and the short block
names what it left out (`scry_core.narrowing`). Which fact is an alarm and which is fixed is each
server's to say; how the block is put together is held here.
"""

from __future__ import annotations

from typing import Any

from scry_core import narrowing

#: The tools whose replies carry the whole block.
WHOLE_ON = frozenset({"start", "status"})
#: What the short block says about the half it left out.
HOW = "`status` answers the whole block: what is fixed for this session as well as its alarms"


def block(alarms: dict[str, Any], fixed: dict[str, Any], whole: bool) -> dict[str, Any]:
    """The block: `alarms` always; `fixed` whole, or named in `omitted` beside `how`. A key in
    both is the server's bug, a `ValueError`: the short block would omit what it carries."""
    if both := alarms.keys() & fixed.keys():
        raise ValueError(f"{sorted(both)} are both an alarm and a fixed fact")
    if whole:
        return {**alarms, **fixed}
    return {**alarms, **narrowing.omission(list(fixed), HOW)}


def whole_for(tool: str) -> bool:
    """Whether `tool`'s replies carry the whole block."""
    return tool in WHOLE_ON
