"""THE PROGRESS LINE OF A BOUNDED WAIT, the same on every Scry server, and the rules every
call's notifications keep: never going backwards, at most one a second, one short line, and none
once the call is cancelled. A module waits and reports through the callback the server hands in
(`bridge`), so the waiting module knows nothing of the protocol's `Context`, and a test hands in
a list.

THE LINE is what a person reads in the client's row for the call, never the model: the protocol
delivers progress to the client and the reply to the model. So it says which wait it is and how
far it got, `<tool> <subject>: <what it observes>, <elapsed>s of <bound>s`, and what the model
must learn stays in the reply.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import anyio.from_thread
from mcp.server.mcpserver import Context

from scry_core import cancel
from scry_core.client_cap import utf16_units

# A BOUNDED WAIT REPORTS PROGRESS WITH A MESSAGE. The arguments are the protocol's own
# (`progress`, `total`, `message`); `total` is None for a wait measured in time, because a bar
# filling towards the bound reads as progress towards failure.
Progress = Callable[[float, float | None, str], None]


# How often a bounded wait reports: a second, which is what a person watching the line reads.
PROGRESS_EVERY_S = 1.0


def no_progress(progress: float, total: float | None, message: str) -> None:
    """The callback of a call with no client to paint for (a test, a direct call)."""


class Ticker:
    """The progress line of ONE bounded wait: the clock it started on, its bound, and the
    report every `PROGRESS_EVERY_S` while the loop asks, of the time elapsed (`tick`) or of the
    work done when the work has a size (`report`, then `finish` where it ends). The arithmetic
    lives here once, while the WHERE stays each loop's (`run_to` ticks before its poll, on
    purpose): a copy per loop drifts in where the tick sits and nothing compares them. The line
    is formatted only when a report is due."""

    def __init__(self, seconds: float, progress: Progress) -> None:
        self.began = time.monotonic()
        self.now = self.began
        self.deadline = self.began + seconds
        self._progress = progress
        self._next = self.began + PROGRESS_EVERY_S

    def elapsed(self, digits: int = 3) -> float:
        return round(self.seconds(), digits)

    def seconds(self) -> float:
        """The span since the wait began, unrounded: a reply's field rounds it once
        (`st.spent_s`), where rounding an already rounded `elapsed` would round twice."""
        return time.monotonic() - self.began

    def expired(self) -> bool:
        """ONE clock read per iteration, at the loop's head: `left` and `tick` reuse it, so a
        tick is judged at most one poll late. It is also where a cancelled call ends
        (`cancel.check`), so every bounded wait polls for its cancellation at its own pace."""
        cancel.check()
        self.now = time.monotonic()
        return self.now >= self.deadline

    def left(self) -> float:
        return max(0.0, self.deadline - self.now)

    def tick(self, template: str, **fields: Any) -> None:
        """Report the time elapsed, with no total, when a report is due: `template` is
        formatted with `elapsed` and `fields` only then: a template and its fields rather than
        a closure, which would need a default-argument dance to bind a loop variable."""
        self._send_if_due(None, None, template, fields)

    def report(self, done: float, total: float, template: str, /, **fields: Any) -> None:
        """Report work done of `total`, clamped into [0, total], when a report is due, on the
        period `tick` keeps. Positional-only, so no field a template names can collide."""
        self._send_if_due(min(max(done, 0), total), total, template, fields)

    def finish(self, total: float, template: str, /, **fields: Any) -> None:
        """The work is over: report `total` of `total` at once, so the bar ends where the work
        did, whatever the period held back before it, timed now rather than at the last poll."""
        self.now = time.monotonic()
        self._send(total, total, template, fields)

    def _send_if_due(self, done: float | None, total: float | None, template: str,
                     fields: dict[str, Any]) -> None:
        if self.now >= self._next:
            self._next = self.now + PROGRESS_EVERY_S
            self._send(done, total, template, fields)

    def _send(self, done: float | None, total: float | None, template: str,
              fields: dict[str, Any]) -> None:
        elapsed = self.now - self.began
        self._progress(elapsed if done is None else done, total,
                       template.format(elapsed=elapsed, **fields))


class RebasedProgress:
    """The progress of ONE call, never going backwards, which the protocol requires of every
    notification in a request. A call may hold several waits that each count from zero (a retry
    of `start`, the waits a `perform` makes between its steps, the Lua tools' chained waits): a
    raw value below the previous raw one begins a new segment, based at the last value sent, so
    the client sees one rising line. A value not above the last one sent is dropped with its
    message rather than sent out of order."""

    def __init__(self, report: Progress) -> None:
        self._report = report
        self._last_raw: float | None = None
        self._base = 0.0
        self._sent: float | None = None

    def __call__(self, progress: float, total: float | None, message: str) -> None:
        if self._last_raw is not None and progress < self._last_raw:
            self._base = self._sent or 0.0
        self._last_raw = progress
        value = self._base + progress
        if self._sent is not None and value <= self._sent:
            return
        self._sent = value
        self._report(value, None if total is None else self._base + total, message)


#: The longest line a notification carries, in the client's own unit (UTF-16): a row of a
#: terminal, past which a client cuts it anyway.
MESSAGE_MAX_UNITS = 160


def line(message: str) -> str:
    """`message` as one line of at most `MESSAGE_MAX_UNITS`, an ellipsis where it was cut: its
    whitespace folded, since a client's row shows one line."""
    message = " ".join(message[:4 * MESSAGE_MAX_UNITS].split())
    if utf16_units(message) <= MESSAGE_MAX_UNITS:
        return message
    message = message[:MESSAGE_MAX_UNITS]          # a character is at least one unit
    while utf16_units(message) > MESSAGE_MAX_UNITS - 1:
        message = message[:-1]
    return message + "\u2026"


# A STEP OF A SEQUENCE HAS NO REQUEST OF ITS OWN: the sequence calls the tool directly, so its
# `bridge(None)` would report to no one. Inside `within` it reports through the sequence's line.
_steps = threading.local()


@contextlib.contextmanager
def within(report: Progress, prefix: str, began: float | None = None) -> Iterator[None]:
    """Make a `bridge(None)` on this thread report through `report`, each line under `prefix`,
    its value the seconds since `began` (now when not given), so a sequence's line keeps rising
    whatever count each step keeps."""
    stack: list[tuple[Progress, str, float]] = _steps.__dict__.setdefault("stack", [])
    stack.append((report, prefix, time.monotonic() if began is None else began))
    try:
        yield
    finally:
        stack.pop()


def _stepped() -> Progress:
    """The reporter of a step inside `within`, or `no_progress` outside one."""
    stack: list[tuple[Progress, str, float]] = getattr(_steps, "stack", [])
    if not stack:
        return no_progress
    report, prefix, began = stack[-1]

    def step(progress: float, total: float | None, message: str) -> None:
        report(time.monotonic() - began, None, f"{prefix}: {message}")
    return step


def bridge(ctx: Context[Any, Any] | None) -> Progress:
    """The progress of one call, from the worker thread the SDK runs a synchronous tool on to the
    request's `Context` on the event loop: rebased so it never goes back (`RebasedProgress`),
    each line cut to `MESSAGE_MAX_UNITS`, and nothing sent once the call is cancelled. A line
    the client could not be sent (it left, the stream closed) is dropped and the wait goes on:
    the cancellation is what ends a wait, never a notification that failed. With no context (a
    direct call, a test) nothing is reported, unless the call is a step of a sequence
    (`within`)."""
    if ctx is None:
        return _stepped()

    def report(progress: float, total: float | None, message: str) -> None:
        if cancel.shielding():
            return               # the end of a cancelled call reports to no one
        cancel.check()
        try:
            anyio.from_thread.run(ctx.report_progress, progress, total, line(message))
        except Exception:        # noqa: BLE001 -- a line nobody received is no reason to stop
            return

    return RebasedProgress(report)
