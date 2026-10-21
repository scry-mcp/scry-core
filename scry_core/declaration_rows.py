"""The identity every listed declaration carries on both servers: its ref, how it was declared,
which cpu it acts on, when and in which session it was declared, whether that session is this
one, and how old it is. One builder, because a row another session left must read the same on
either machine: the owner's shape is age and origin, never an expiry, and deleting stays with the
`*_clear` tools.

Each server hands in its own clock, so a test can fix it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scry_core.reply_contract import or_unavailable

UNDATED_WHY = "the row carries no date with an offset"
NO_ORIGIN_WHY = ("the row names no session it was declared in: clear it by its ref, or declare it "
                 "again to adopt it")


def age_s(stamp: str | None, now: datetime) -> int | None:
    """Whole seconds from `stamp` (an ISO date with an offset) to `now`, floored, negative for a
    stamp ahead of the clock; None when the row carries no date, or one that names no instant. A
    zero would read as "declared just now", which is the one thing an undated row cannot claim."""
    try:
        then = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None
    if then is None or then.utcoffset() is None:
        return None
    return int((now - then).total_seconds() // 1)


def row(*, ref: str, by: str, cpu: str | None, cpu_why: str, created_at: str | None,
        origin: str | None, own_origin: str | None, now: datetime) -> dict[str, Any]:
    """A list row's identity. `cpu_why` is why a row names no cpu, which is the server's to say.
    `inherited` is the half a caller cannot work out from `origin`, because no reply names this
    session's own: a declaration the store brought back reads otherwise exactly like one made
    here. `age_s` tells an old row from a recent one in a store sessions share."""
    return {"ref": ref, "by": by, "cpu": or_unavailable(cpu, cpu_why),
            "created_at": or_unavailable(created_at, UNDATED_WHY),
            "origin": or_unavailable(origin, NO_ORIGIN_WHY),
            "inherited": origin != own_origin,
            "age_s": or_unavailable(age_s(created_at, now), UNDATED_WHY)}
