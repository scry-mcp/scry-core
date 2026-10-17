"""A CANCELLED CALL, as every Scry server ends it: at once, the way its own bound would have ended
it, and said in the next reply.

The protocol cancels a request by notification (`notifications/cancelled`), and the SDK answers
it by cancelling the request's scope and sending no response. A tool body here is synchronous and
runs on a worker thread the SDK does not stop, so a wait would run on to its bound and hold the
next call behind it. `check` is the poll point every bounded wait calls (`progress.Ticker` calls
it at each poll): past a cancellation it raises the event loop's own `CancelledError`, which
unwinds the tool to the server's boundary, where the end the tool declared (`OnCancel`) is applied
and the `Cancelled` record is kept for the next reply, because the cancelled call has none.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, get_args

import anyio.from_thread

#: How a tool ends when its call is cancelled, declared where it is registered: `stop` for one
#: that comes back with the machine STOPPED, `kill` for one whose failure path ends the emulator
#: (`start`), `none` for one that leaves the machine as it was.
OnCancel = Literal["stop", "kill", "none"]
ON_CANCEL: tuple[OnCancel, ...] = get_args(OnCancel)
#: What the machine was left as, in the record.
Left = Literal["stopped", "running", "closed", "as it was", "unknown"]


# THE END OF A CANCELLED CALL RUNS SHIELDED: the request stays cancelled while the server stops
# the machine it left, and that stop may wait on a bounded poll of its own, whose `check` would
# raise again and abandon the very cleanup the cancellation asked for.
_shield = threading.local()


def check() -> None:
    """Raise the event loop's `CancelledError` if this call was cancelled; a no-op outside an
    AnyIO worker thread (a test, a direct call), where no request can be cancelled, and inside
    `shielded`."""
    if shielding():
        return
    try:
        anyio.from_thread.check_cancelled()
    except RuntimeError:       # anyio's `NoEventLoopError`: no worker thread, no request
        return


@contextlib.contextmanager
def shielded() -> Iterator[None]:
    """Run the end of a cancelled call with `check` silenced, on this thread only."""
    _shield.depth = getattr(_shield, "depth", 0) + 1
    try:
        yield
    finally:
        _shield.depth -= 1


def shielding() -> bool:
    """Whether this thread is ending a cancelled call (`shielded`)."""
    return getattr(_shield, "depth", 0) > 0


def is_cancellation(e: BaseException) -> bool:
    """Whether `e` is a cancelled call unwinding, never a tool's own error: the event loop's
    `CancelledError`, and on a worker thread the request itself asked, so one a tool body let
    escape from a loop of its own is not taken for the call's. Outside a worker the type is all
    there is to go on."""
    if not isinstance(e, asyncio.CancelledError):
        return False
    try:
        anyio.from_thread.check_cancelled()
    except asyncio.CancelledError:
        return True
    except RuntimeError:       # no worker thread: a test or a direct call raised it
        return True
    return False


@dataclass(frozen=True)
class Cancelled:
    """A call that was cancelled: which tool, how long it had run, and what it left."""

    tool: str
    after_s: float
    left: Left

    def note(self) -> dict[str, Any]:
        return {"tool": self.tool, "after_s": round(self.after_s, 1), "left": self.left}

    def summary(self, summary: str) -> str:
        """The next reply's summary, saying first what the cancelled call left."""
        return f"after a cancelled {self.tool} ({self.left}): {summary}"

