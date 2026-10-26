"""The identity every listed declaration carries, built once so both servers read alike."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from scry_core import vocabulary as vocab
from scry_core.reply_contract import or_unavailable

UNDATED_WHY = "the row carries no date with an offset"
NO_ORIGIN_WHY = ("the row names no session it was declared in: clear it by its ref, or declare it "
                 "again to adopt it")
#: A comment is adopted by commenting it again, never by declaring it.
NO_ORIGIN_COMMENT_WHY = ("the row names no session it was commented in: delete it by its ref, or "
                         "comment it again here to adopt it")


def chosen_kinds(kind: str, kinds: Sequence[str]) -> tuple[str, ...]:
    """The kinds `declaration_list` reads: `kind`, or every one when it is empty."""
    vocab.one_of("kind", kind, ("", *kinds))
    return (kind,) if kind else tuple(kinds)


def age_s(stamp: str | None, now: datetime) -> int | None:
    """Floored seconds from `stamp` to `now`; None when undated, since 0 would claim "just now"."""
    try:
        then = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None
    if then is None or then.utcoffset() is None:
        return None
    return int((now - then).total_seconds() // 1)


def row(*, kind: str, ref: str, by: str, cpu: str | None, cpu_why: str, created_at: str | None,
        origin: str | None, own_origin: str | None, now: datetime) -> dict[str, Any]:
    """A list row's identity. `inherited` is needed because no reply names this session's own
    origin."""
    return {"ref": ref, "by": by, "cpu": or_unavailable(cpu, cpu_why),
            "created_at": or_unavailable(created_at, UNDATED_WHY),
            "origin": or_unavailable(origin, NO_ORIGIN_COMMENT_WHY if kind == "comment"
                                     else NO_ORIGIN_WHY),
            "inherited": origin != own_origin,
            "age_s": or_unavailable(age_s(created_at, now), UNDATED_WHY)}


def merged(listed: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge each kind's list reply; `foreign` is keyed by kind since their numbering differs.

    The first reply that is not `ok` is returned as the answer.
    """
    out: dict[str, Any] = {"status": "ok"}
    foreign: dict[str, Any] = {}
    rest: dict[str, Any] = {}
    for key, reply in listed.items():
        if reply.get("status") != "ok":
            return reply
        out[key] = reply[key]
        if held := reply.get("foreign"):
            foreign[key] = held
        rest.update({f: v for f, v in reply.items() if f not in ("status", key, "foreign")})
    return {**out, "foreign": foreign, **rest}
