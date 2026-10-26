"""The `session` block closing every reply: alarms always, the fixed half on `WHOLE_ON`."""

from __future__ import annotations

import json
from typing import Any

from scry_core import client_cap, narrowing

WHOLE_ON = frozenset({"start", "status"})
HOW = "call `status`"
#: What `close` and `status` say with no session, on both servers.
NO_SESSION_CLOSE = "close: no session"
NO_SESSION_CLOSE_NOTE = "there was no session to close"
NO_SESSION_STATUS = "status: no session"


def block(alarms: dict[str, Any], fixed: dict[str, Any], whole: bool) -> dict[str, Any]:
    """`alarms` always; `fixed` whole, or named in `omitted` when that costs fewer units."""
    if both := alarms.keys() & fixed.keys():
        raise ValueError(f"{sorted(both)} are both an alarm and a fixed fact")
    full = {**alarms, **fixed}
    if whole:
        return full
    short = {**alarms, **narrowing.omission(list(fixed), HOW)}
    return short if _units(short) < _units(full) else full


def _units(block: dict[str, Any]) -> int:
    return client_cap.utf16_units(json.dumps(block, ensure_ascii=False, separators=(",", ":")))


def whole_for(tool: str) -> bool:
    return tool in WHOLE_ON
