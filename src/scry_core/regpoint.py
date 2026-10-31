"""A registerpoint stop's `regpoint_hit`."""

from __future__ import annotations

from typing import Any

STILL_ARMED = ("still armed: a registerpoint stops at every instruction where its condition "
               "holds, so the next advance stops again; `declaration_clear(kind=\"regpoint\")` "
               "removes it")


def hit(ref: str, condition: str, pc: str, **own: Any) -> dict[str, Any]:
    """The `regpoint_hit` object; `own` is the calling server's extra fields."""
    return {"ref": ref, "condition": condition, "pc": pc, "note": STILL_ARMED, **own}
