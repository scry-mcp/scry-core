"""A listed declaration's identity, one builder for both servers: its age from a fixed clock in two
offsets, a dateless or naive row unavailable rather than zero, a stamp ahead of the clock negative,
and `inherited` telling this session's row from another's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from scry_core import declaration_rows as rows
from scry_core.reply_contract import Invalid

NOW = datetime(2026, 1, 1, 0, 1, 40, 900000, tzinfo=UTC)


def test_a_known_stamp_gives_its_age_in_any_offset_floored() -> None:
    assert rows.age_s("2026-01-01T00:00:00+00:00", NOW) == 100
    assert rows.age_s("2026-01-01T02:00:00+02:00", NOW) == 100


def test_no_date_a_naive_date_and_a_non_date_have_no_age() -> None:
    for stamp in (None, "", "2026-01-01T00:00:00", "yesterday"):
        assert rows.age_s(stamp, NOW) is None, stamp


def test_a_stamp_ahead_of_the_clock_is_negative_never_clamped() -> None:
    ahead = (NOW + timedelta(seconds=5)).astimezone(timezone(timedelta(hours=-3)))
    assert rows.age_s(ahead.isoformat(), NOW) == -5
    part = NOW + timedelta(seconds=4.1)
    assert rows.age_s(part.isoformat(), NOW) == -5, "floored, never truncated toward zero"


def _row(origin: str | None, cpu: str | None = ":maincpu",
         created_at: str | None = "2026-01-01T00:00:00+00:00") -> dict[str, object]:
    return rows.row(ref="0x10", by="address", cpu=cpu, cpu_why="no cpu here",
                    created_at=created_at, origin=origin, own_origin="mine", now=NOW)


def test_a_row_names_every_field_and_tells_this_sessions_own() -> None:
    assert _row("mine") == {"ref": "0x10", "by": "address", "cpu": ":maincpu",
                            "created_at": "2026-01-01T00:00:00+00:00", "origin": "mine",
                            "inherited": False, "age_s": 100}
    assert _row("theirs")["inherited"] is True


def test_what_a_row_lacks_is_unavailable_with_its_reason() -> None:
    bare = _row(None, cpu=None, created_at=None)
    assert bare["cpu"] == {"available": False, "why": "no cpu here"}
    assert bare["created_at"] == bare["age_s"] == {"available": False, "why": rows.UNDATED_WHY}
    assert bare["origin"] == {"available": False, "why": rows.NO_ORIGIN_WHY}
    assert bare["inherited"] is True


def test_the_lists_of_several_kinds_merge_with_their_foreign_rows_kept_apart() -> None:
    from scry_core.declaration_rows import merged

    got = merged({"breakpoints": {"status": "ok", "breakpoints": [1], "foreign": ["a"],
                                  "cpu": "x"},
                  "watches": {"status": "ok", "watches": [], "foreign": [], "cpu": "x"}})
    assert got == {"status": "ok", "breakpoints": [1], "watches": [],
                   "foreign": {"breakpoints": ["a"]}, "cpu": "x"}
    refused = {"status": "INVALID", "code": "no_channel", "message": "m"}
    assert merged({"breakpoints": {"status": "ok", "breakpoints": []},
                   "watches": refused}) is refused


def test_the_kinds_listed_are_the_one_named_or_every_one_and_no_other() -> None:
    assert rows.chosen_kinds("watch", ("breakpoint", "watch")) == ("watch",)
    assert rows.chosen_kinds("", ("breakpoint", "watch")) == ("breakpoint", "watch")
    with pytest.raises(Invalid, match="kind is one of"):
        rows.chosen_kinds("comment", ("breakpoint", "watch"))
