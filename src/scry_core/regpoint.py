"""A registerpoint stop's `regpoint_hit`, whose note says what its own emulator does."""

from __future__ import annotations

from typing import Any

STILL_ARMED = ("still armed: a registerpoint stops at every instruction where its condition "
               "holds, so the next advance stops again; `declaration_clear(kind=\"regpoint\")` "
               "removes it")

WAITS_WHILE_HELD = ("still armed: a registerpoint stops as its condition comes true and waits "
                    "while it already holds, so a resumed machine does not stop again at once; "
                    "`declaration_clear(kind=\"regpoint\")` removes it")


def hit(ref: str, condition: str, pc: str, *, note: str, **own: Any) -> dict[str, Any]:
    """The `regpoint_hit`; `note` is the caller's and `own` its extra fields."""
    return {"ref": ref, "condition": condition, "pc": pc, "note": note, **own}
