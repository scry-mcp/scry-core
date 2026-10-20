"""`scry_core.session_block`: the alarms on every reply, the fixed half where it is asked for."""

from __future__ import annotations

import json

import pytest

from scry_core import client_cap, session_block


def test_the_short_block_keeps_the_alarms_and_names_the_fixed_half_it_left_out() -> None:
    alarms, fixed = {"alive": True, "running": False, "altered": False}, {"conf": "/c", "pid": 4}
    assert session_block.block(alarms, fixed, whole=True) == {**alarms, **fixed}
    short = session_block.block(alarms, fixed, whole=False)
    assert short == {**alarms, "omitted": ["conf", "pid"], "how": session_block.HOW}
    assert "`status`" in session_block.HOW


def test_a_fact_that_is_both_an_alarm_and_fixed_is_refused() -> None:
    with pytest.raises(ValueError, match="both an alarm and a fixed fact"):
        session_block.block({"alive": True}, {"alive": True}, whole=True)


def test_a_block_with_nothing_fixed_omits_nothing() -> None:
    assert session_block.block({"alive": False}, {}, whole=False) == {"alive": False}


def test_start_and_status_answer_the_whole_block() -> None:
    assert session_block.whole_for("start") and session_block.whole_for("status")
    assert not session_block.whole_for("run_for")


def test_naming_what_was_left_out_never_costs_more_than_leaving_it_in() -> None:
    """The short block exists to cut a reply, so the smallest fixed half a server carries (MAME's
    two zero counts) must not come out larger short than whole, in the client's own unit."""
    alarms = {"alive": True, "running": False, "altered": False}
    fixed = {"altering_writes": 0, "console": {"thread_errors": 0, "reruns": 0, "lost": 0}}
    whole, short = (session_block.block(alarms, fixed, whole=w) for w in (True, False))
    units = [client_cap.utf16_units(json.dumps(b, ensure_ascii=False, separators=(",", ":")))
             for b in (whole, short)]
    assert units[1] <= units[0], units
