"""THE `session` BLOCK, the field that closes every reply of both servers: its ALARMS on every
reply, its FIXED half where a caller asks what the session is.

A fact rides where it is asked for. What a caller must never miss rides on every reply: whether
the machine is alive, running and written to, and each alarm while it holds. What is fixed for the
life of a session, or only counts, rides on `start` and `status` (`WHOLE_ON`), and the short block
names what it left out (`scry_core.narrowing`). Which fact is an alarm and which is fixed is each
server's to say; how the block is put together is held here.
"""

from __future__ import annotations

import json
from typing import Any

from scry_core import client_cap, narrowing

#: The tools whose replies carry the whole block.
WHOLE_ON = frozenset({"start", "status"})
#: What the short block says about the half it left out.
HOW = "call `status`"


def block(alarms: dict[str, Any], fixed: dict[str, Any], whole: bool) -> dict[str, Any]:
    """The block: `alarms` always; `fixed` whole, or named in `omitted` beside `how`. A key in
    both is the server's bug, a `ValueError`: the short block would omit what it carries.

    A FIXED HALF CHEAPER THAN ITS NAMING RIDES WHOLE: the short block exists to cut the reply, so
    when the names and the sentence would cost the client more units than the facts themselves
    (MAME's lone `altering_writes` once `console` is an alarm), the facts go instead."""
    if both := alarms.keys() & fixed.keys():
        raise ValueError(f"{sorted(both)} are both an alarm and a fixed fact")
    full = {**alarms, **fixed}
    if whole:
        return full
    short = {**alarms, **narrowing.omission(list(fixed), HOW)}
    return short if _units(short) < _units(full) else full


def _units(block: dict[str, Any]) -> int:
    """A block's cost in the client's unit, as `traffic` counts a reply."""
    return client_cap.utf16_units(json.dumps(block, ensure_ascii=False, separators=(",", ":")))


def whole_for(tool: str) -> bool:
    """Whether `tool`'s replies carry the whole block."""
    return tool in WHOLE_ON
