"""The progress line of a bounded wait: monotonic, at most one a second, one short line."""

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

# `total` is None for a wait in time: a bar filling towards the bound reads as progress to failure.
Progress = Callable[[float, float | None, str], None]


PROGRESS_EVERY_S = 1.0


def no_progress(progress: float, total: float | None, message: str) -> None:
    """The callback of a call with no client to paint for."""


class Ticker:
    """The progress line of one bounded wait; where each loop ticks stays its own (`run_to` ticks
    before its poll)."""

    def __init__(self, seconds: float, progress: Progress) -> None:
        self.began = time.monotonic()
        self.now = self.began
        self.deadline = self.began + seconds
        self._progress = progress
        self._next = self.began + PROGRESS_EVERY_S

    def elapsed(self, digits: int = 3) -> float:
        return round(self.seconds(), digits)

    def seconds(self) -> float:
        return time.monotonic() - self.began

    def expired(self) -> bool:
        """One clock read per iteration; also where a cancelled call ends."""
        cancel.check()
        self.now = time.monotonic()
        return self.now >= self.deadline

    def left(self) -> float:
        return max(0.0, self.deadline - self.now)

    def tick(self, template: str, **fields: Any) -> None:
        """Report elapsed time when due; `template` is formatted only then."""
        self._send_if_due(None, None, template, fields)

    def report(self, done: float, total: float, template: str, /, **fields: Any) -> None:
        """Report work done, clamped into [0, total], when due."""
        self._send_if_due(min(max(done, 0), total), total, template, fields)

    def finish(self, total: float, template: str, /, **fields: Any) -> None:
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
    """One call's progress, never going backwards: a raw drop starts a new segment."""

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


#: UTF-16 units, the client's own unit.
MESSAGE_MAX_UNITS = 160


def line(message: str) -> str:
    """`message` as one line of at most `MESSAGE_MAX_UNITS`, an ellipsis where cut."""
    message = " ".join(message[:4 * MESSAGE_MAX_UNITS].split())
    if utf16_units(message) <= MESSAGE_MAX_UNITS:
        return message
    message = message[:MESSAGE_MAX_UNITS]          # a character is at least one unit
    while utf16_units(message) > MESSAGE_MAX_UNITS - 1:
        message = message[:-1]
    return message + "\u2026"


# A sequence's step has no request of its own, so `bridge(None)` would report to no one.
_steps = threading.local()


@contextlib.contextmanager
def within(report: Progress, prefix: str, began: float | None = None) -> Iterator[None]:
    """Make `bridge(None)` on this thread report through `report` under `prefix`."""
    stack: list[tuple[Progress, str, float]] = _steps.__dict__.setdefault("stack", [])
    stack.append((report, prefix, time.monotonic() if began is None else began))
    try:
        yield
    finally:
        stack.pop()


def _stepped() -> Progress:
    stack: list[tuple[Progress, str, float]] = getattr(_steps, "stack", [])
    if not stack:
        return no_progress
    report, prefix, began = stack[-1]

    def step(progress: float, total: float | None, message: str) -> None:
        report(time.monotonic() - began, None, f"{prefix}: {message}")
    return step


def bridge(ctx: Context[Any, Any] | None) -> Progress:
    """The progress of one call, from the worker thread to the request's `Context`.

    A failed send is dropped: cancellation ends a wait, never a lost notification.
    """
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
