"""`scry_core.progress`: the Ticker's edges held on a clock this file moves by hand, the
rebasing that keeps one call's line rising, the line's length, and the bridge from a worker
thread to the request, which sends nothing once the call is cancelled."""

from __future__ import annotations

import asyncio
import time

import anyio
import anyio.to_thread
import pytest

from scry_core import cancel, progress
from scry_core.client_cap import utf16_units


class _Clock:
    """`time.monotonic` as a number the case sets."""

    def __init__(self, at: float = 100.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr("scry_core.progress.time.monotonic", c)
    return c


def test_a_bound_expires_at_its_deadline_and_leaves_nothing_after_it(clock: _Clock) -> None:
    t = progress.Ticker(5.0, progress.no_progress)
    clock.at += 4.0
    assert t.expired() is False and t.left() == 1.0
    clock.at += 1.0
    assert t.expired() is True and t.left() == 0.0, "the deadline itself is expired, 0 left"
    clock.at += 3.0
    assert t.expired() is True and t.left() == 0.0, "past it, never a negative wait"


def test_elapsed_is_rounded_to_a_millisecond_unless_asked(clock: _Clock) -> None:
    t = progress.Ticker(5.0, progress.no_progress)
    clock.at += 1.23456
    assert t.elapsed() == 1.235 and t.elapsed(1) == 1.2


def test_a_report_is_due_once_per_period_and_never_at_once(clock: _Clock) -> None:
    said: list[tuple[float, float | None, str]] = []
    t = progress.Ticker(10.0, lambda e, s, m: said.append((e, s, m)))
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert said == [], "no report before a period has passed"
    clock.at += progress.PROGRESS_EVERY_S
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert [m for _, _, m in said] == ["1.0s"], "due exactly one period in"
    clock.at += progress.PROGRESS_EVERY_S / 2
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert len(said) == 1, "and not again inside the next period"
    clock.at += progress.PROGRESS_EVERY_S / 2
    t.expired()
    t.tick("{elapsed:.1f}s")
    assert [m for _, _, m in said] == ["1.0s", "2.0s"] and said[-1][0] == 2.0
    assert all(total is None for _, total, _ in said), said


def test_a_work_report_carries_its_pair_on_the_same_period(clock: _Clock) -> None:
    said: list[tuple[float, float | None, str]] = []
    t = progress.Ticker(10.0, lambda p, total, m: said.append((p, total, m)))
    t.expired()
    t.report(0, 4, "frame {frame}", frame=10)
    assert said == [], "no report before a period has passed"
    clock.at += progress.PROGRESS_EVERY_S
    t.expired()
    t.report(3, 4, "frame {frame}, {elapsed:.0f}s", frame=13)
    t.report(4, 4, "frame {frame}, {elapsed:.0f}s", frame=14)
    assert said == [(3, 4, "frame 13, 1s")], "once per period, whatever the work did meanwhile"
    clock.at += progress.PROGRESS_EVERY_S
    t.expired()
    t.report(-2, 4, "behind the start")
    clock.at += progress.PROGRESS_EVERY_S
    t.expired()
    t.report(9, 4, "past the end")
    assert [p for p, _, _ in said[1:]] == [0, 4], "clamped into [0, total]"


def test_a_finish_is_sent_at_once_at_its_total() -> None:
    said: list[tuple[float, float | None, str]] = []
    t = progress.Ticker(10.0, lambda p, total, m: said.append((p, total, m)))
    t.finish(4, "frame {frame}, done", frame=14)
    assert said == [(4, 4, "frame 14, done")], "never held back by the period"


def _rebased() -> tuple[progress.RebasedProgress, list[tuple[float, float | None, str]]]:
    sent: list[tuple[float, float | None, str]] = []
    return progress.RebasedProgress(lambda p, t, m: sent.append((p, t, m))), sent


def test_a_rebased_progress_passes_an_increasing_sequence_through_unchanged() -> None:
    report, sent = _rebased()
    report(1.0, None, "a")
    report(2.5, None, "b")
    report(3.0, 8.0, "c")
    assert sent == [(1.0, None, "a"), (2.5, None, "b"), (3.0, 8.0, "c")]


def test_a_restart_inside_one_call_continues_from_the_last_value_sent() -> None:
    """A retry after a wait, or a second Ticker in one call, begins again at its own zero: the
    client is told a value above everything it was told before, never a smaller one."""
    report, sent = _rebased()
    for elapsed in (1.0, 2.0, 3.0):
        report(elapsed, None, f"waiting {elapsed:g}s")
    report(1, 3, "retry 1 of 3")              # start's retry: a count, below the last raw
    report(1.0, None, "again 1s")             # the new Ticker's first: not above what was sent
    report(2.0, None, "again 2s")
    assert sent == [(1.0, None, "waiting 1s"), (2.0, None, "waiting 2s"),
                    (3.0, None, "waiting 3s"), (4.0, 6.0, "retry 1 of 3"),
                    (5.0, None, "again 2s")], sent
    values = [p for p, _, _ in sent]
    assert all(b > a for a, b in zip(values, values[1:], strict=False))


class _RecordingCtx:
    def __init__(self) -> None:
        self.got: list[tuple[float, float | None, str | None]] = []

    async def report_progress(self, p: float, total: float | None = None,
                              message: str | None = None) -> None:
        self.got.append((p, total, message))


class _TimedCtx(_RecordingCtx):
    """A context that also keeps when each line reached it."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[float] = []

    async def report_progress(self, p: float, total: float | None = None,
                              message: str | None = None) -> None:
        self.sent.append(time.monotonic())
        await super().report_progress(p, total, message)




def test_the_bridge_reaches_the_context_from_a_worker_thread_and_none_paints_nothing() -> None:
    assert progress.bridge(None) is progress.no_progress
    ctx = _RecordingCtx()

    async def main() -> None:
        report = progress.bridge(ctx)  # type: ignore[arg-type]
        for p in (1.0, 2.0, 1.0):
            await anyio.to_thread.run_sync(report, p, None, f"{p:g}")

    anyio.run(main)
    assert ctx.got == [(1.0, None, "1"), (2.0, None, "2"), (3.0, None, "1")]


def test_a_line_is_cut_to_the_bound_in_the_clients_unit_with_an_ellipsis() -> None:
    assert progress.line("short") == "short"
    cut = progress.line("\U0001f3ae" * 200)      # two units each, so the cut counts units
    assert utf16_units(cut) <= progress.MESSAGE_MAX_UNITS and cut.endswith("\u2026")
    exact = "x" * progress.MESSAGE_MAX_UNITS
    assert progress.line(exact) == exact


def test_a_ticker_polls_for_a_cancellation_at_every_iteration(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def cancelled() -> None:
        calls.append(1)
        if len(calls) == 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(cancel, "check", cancelled)
    t = progress.Ticker(60.0, progress.no_progress)
    with pytest.raises(asyncio.CancelledError):
        while not t.expired():
            pass
    assert len(calls) == 3


#: Half a report period past the first, so a line is due before the cancel.
CANCEL_AFTER_S = 1.5 * progress.PROGRESS_EVERY_S


def test_a_cancelled_call_sends_no_progress_and_its_wait_ends_at_the_next_poll() -> None:
    """The bridge and the Ticker on a real worker thread whose request is cancelled: the wait
    unwinds at its next poll, a line reached the context before the cancellation (a bridge that
    never sends would pass the rest), and none after it."""
    ctx = _TimedCtx()
    polls: list[float] = []
    began: list[float] = []

    def wait() -> None:
        t = progress.Ticker(30.0, progress.bridge(ctx))  # type: ignore[arg-type]
        while not t.expired():
            polls.append(t.now)
            t.tick("waiting {elapsed:.0f}s")
            time.sleep(0.05)

    async def main() -> None:
        began.append(time.monotonic())
        with anyio.move_on_after(CANCEL_AFTER_S):
            await anyio.to_thread.run_sync(wait)

    anyio.run(main)
    cancelled_at = began[0] + CANCEL_AFTER_S
    assert polls and polls[-1] - polls[0] < 2.0, "the wait ran on past its cancellation"
    assert ctx.sent, "no line reached the context in the second before the cancel"
    assert all(when < cancelled_at for when in ctx.sent), (ctx.sent, cancelled_at)


def test_check_is_a_no_op_outside_a_worker_thread() -> None:
    cancel.check()


def test_a_shielded_end_neither_polls_for_the_cancellation_nor_reports(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def cancelled() -> None:
        raise asyncio.CancelledError
    monkeypatch.setattr(anyio.from_thread, "check_cancelled", cancelled)
    ctx = _RecordingCtx()
    report = progress.bridge(ctx)  # type: ignore[arg-type]
    with pytest.raises(asyncio.CancelledError):
        cancel.check()
    with cancel.shielded():
        cancel.check()
        with cancel.shielded():
            assert cancel.shielding()
        assert cancel.shielding(), "an inner shield ended the outer one"
        report(1.0, None, "the end of a cancelled call")
    assert not cancel.shielding() and ctx.got == []


def test_a_long_message_is_cut_at_once_and_a_line_holds_no_line_break() -> None:
    began = time.monotonic()
    cut = progress.line("x" * 200_000)
    assert time.monotonic() - began < 0.1, "the cut walked the message a character at a time"
    assert utf16_units(cut) <= progress.MESSAGE_MAX_UNITS
    assert progress.line("lua: error\nin chunk\r\nat 3") == "lua: error in chunk at 3"


class _FailingCtx:
    async def report_progress(self, p: float, total: float | None = None,
                              message: str | None = None) -> None:
        raise anyio.BrokenResourceError


def test_a_notification_that_cannot_be_sent_never_ends_the_wait_it_reports() -> None:
    async def main() -> None:
        report = progress.bridge(_FailingCtx())  # type: ignore[arg-type]
        await anyio.to_thread.run_sync(report, 1.0, None, "tick")

    anyio.run(main)


def test_nothing_is_sent_once_the_call_is_cancelled() -> None:
    """The bridge is asked to report after the cancellation, on the cancelled worker itself."""
    ctx = _RecordingCtx()
    raised: list[str] = []

    def work() -> None:
        report = progress.bridge(ctx)  # type: ignore[arg-type]
        report(1.0, None, "before")
        time.sleep(0.4)                     # the scope is cancelled meanwhile
        try:
            report(2.0, None, "after")
        except asyncio.CancelledError:
            raised.append("cancelled")
            raise

    async def main() -> None:
        with anyio.move_on_after(0.2):
            await anyio.to_thread.run_sync(work)

    anyio.run(main)
    assert [m for _, _, m in ctx.got] == ["before"] and raised == ["cancelled"], ctx.got


def test_finish_reports_the_time_it_finished_at(clock: _Clock) -> None:
    said: list[tuple[float, float | None, str]] = []
    t = progress.Ticker(10.0, lambda p, total, m: said.append((p, total, m)))
    t.expired()
    clock.at += 3.0                          # a last step after the last poll
    t.finish(4, "done in {elapsed:.1f}s")
    assert said == [(4, 4, "done in 3.0s")], said


def test_a_step_reports_through_the_sequence_it_runs_in_under_its_prefix() -> None:
    """A tool called as a step of a sequence has no request of its own (`bridge(None)`): inside
    `within` it reports through the sequence's line, prefixed with which step it is."""
    said: list[tuple[float, float | None, str]] = []
    outer = progress.RebasedProgress(lambda p, t, m: said.append((p, t, m)))
    assert progress.bridge(None) is progress.no_progress
    with progress.within(outer, "perform step 2 of 3 (run_for)"):
        inner = progress.bridge(None)
        inner(1.0, 4.0, "run_for 4 frames: frame 1 of 4")
        with progress.within(outer, "perform step 3 of 3 (resume)"):
            progress.bridge(None)(1.0, None, "resume: running 1s of 5s")
        inner(2.0, 4.0, "run_for 4 frames: frame 2 of 4")
    assert progress.bridge(None) is progress.no_progress
    assert [m for _, _, m in said] == [
        "perform step 2 of 3 (run_for): run_for 4 frames: frame 1 of 4",
        "perform step 3 of 3 (resume): resume: running 1s of 5s",
        "perform step 2 of 3 (run_for): run_for 4 frames: frame 2 of 4"]
    values = [p for p, _, _ in said]
    assert all(b > a for a, b in zip(values, values[1:], strict=False)), values



def test_a_second_restart_is_based_on_the_value_sent_not_on_the_raw_one() -> None:
    """After one rebase the value sent and the raw one differ, and only the value sent keeps the
    line rising: based on the raw one, the third segment would fall below what was sent."""
    report, sent = _rebased()
    for raw in (1.0, 2.0, 3.0):
        report(raw, None, "first")
    report(1.0, 3.0, "second")                # sent 4.0 of 6.0
    report(0.5, None, "third")
    assert sent[-2:] == [(4.0, 6.0, "second"), (4.5, None, "third")], sent



def test_a_value_not_above_the_last_one_sent_is_not_sent_nor_its_message() -> None:
    report, sent = _rebased()
    report(2.0, 4.0, "two")
    report(2.0, 4.0, "two again")
    assert sent == [(2.0, 4.0, "two")]
