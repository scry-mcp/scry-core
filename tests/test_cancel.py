"""`scry_core.cancel`: the shield a cancelled call's end runs under, what counts as the call
being cancelled, and the record the next reply carries."""

from __future__ import annotations

import asyncio
import time
from typing import get_args

import anyio
import anyio.to_thread
import pytest

from scry_core import cancel


def test_a_shield_comes_off_when_its_end_raises() -> None:
    with pytest.raises(ValueError), cancel.shielded():
        raise ValueError
    assert not cancel.shielding()


def test_shields_left_out_of_order_leave_no_thread_shielded_for_ever() -> None:
    first, second = cancel.shielded(), cancel.shielded()
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    second.__exit__(None, None, None)
    assert not cancel.shielding()


def test_a_cancelled_error_is_a_cancellation_only_where_the_call_was_cancelled() -> None:
    """Outside a worker the type is all there is; on a worker the request itself is asked, so an
    `asyncio.CancelledError` a tool body let escape from a loop of its own is not taken for one."""
    assert cancel.is_cancellation(asyncio.CancelledError())
    assert not cancel.is_cancellation(RuntimeError())
    seen: dict[str, bool] = {}

    def on_a_live_request() -> None:
        seen["live"] = cancel.is_cancellation(asyncio.CancelledError())

    def on_a_cancelled_one() -> None:
        time.sleep(0.3)
        seen["cancelled"] = cancel.is_cancellation(asyncio.CancelledError())

    async def main() -> None:
        await anyio.to_thread.run_sync(on_a_live_request)
        with anyio.move_on_after(0.1):
            await anyio.to_thread.run_sync(on_a_cancelled_one)

    anyio.run(main)
    assert seen == {"live": False, "cancelled": True}, seen


def test_the_ends_a_tool_declares_are_the_literal_s_own() -> None:
    assert get_args(cancel.OnCancel) == cancel.ON_CANCEL


def test_the_record_says_which_tool_how_long_and_what_it_left() -> None:
    c = cancel.Cancelled("run_for", 2.04, "stopped")
    assert c.note() == {"tool": "run_for", "after_s": 2.0, "left": "stopped"}
    assert c.summary("status: alive") == "after a cancelled run_for (stopped): status: alive"


def test_a_record_kept_over_an_unreported_one_names_the_calls_before_it() -> None:
    first = cancel.recorded(None, "run_to", 1.0, "stopped")
    assert first == cancel.Cancelled("run_to", 1.0, "stopped")
    second = cancel.recorded(first, "run_for", 2.0, "stopped")
    third = cancel.recorded(second, "log_wait", 0.5, "running")
    assert third.earlier == ("run_to", "run_for")
    assert third.note() == {"tool": "log_wait", "after_s": 0.5, "left": "running",
                            "earlier": ["run_to", "run_for"]}
    assert third.summary("status: alive") == (
        "after a cancelled log_wait (running), and run_to, run_for before it: status: alive")
