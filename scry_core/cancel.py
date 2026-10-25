"""A cancelled call ends at once, as its own bound would have."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, get_args

import anyio.from_thread

#: How a cancelled tool ends: `stop` the machine, `kill` the emulator, or `none`.
OnCancel = Literal["stop", "kill", "none"]
ON_CANCEL: tuple[OnCancel, ...] = get_args(OnCancel)
Left = Literal["stopped", "running", "closed", "unknown"]


# Cleanup after a cancel runs shielded, or its own polls would raise again and abandon it.
_shield = threading.local()


def check() -> None:
    """Raise `CancelledError` if this call was cancelled."""
    if shielding():
        return
    try:
        anyio.from_thread.check_cancelled()
    except RuntimeError:       # anyio's `NoEventLoopError`: no worker thread, no request
        return


@contextlib.contextmanager
def shielded() -> Iterator[None]:

    _shield.depth = getattr(_shield, "depth", 0) + 1
    try:
        yield
    finally:
        _shield.depth -= 1


def shielding() -> bool:

    return getattr(_shield, "depth", 0) > 0


def is_cancellation(e: BaseException) -> bool:
    """Whether `e` is this call's own cancellation unwinding."""
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
    """A cancelled call plus earlier unreported ones."""

    tool: str
    after_s: float
    left: Left
    earlier: tuple[str, ...] = ()

    def note(self) -> dict[str, Any]:
        note: dict[str, Any] = {"tool": self.tool, "after_s": round(self.after_s, 1),
                                "left": self.left}
        if self.earlier:
            note["earlier"] = list(self.earlier)
        return note

    def summary(self, summary: str) -> str:

        before = f", and {', '.join(self.earlier)} before it" if self.earlier else ""
        return f"after a cancelled {self.tool} ({self.left}){before}: {summary}"


def recorded(previous: Cancelled | None, tool: str, after_s: float, left: Left) -> Cancelled:
    """Record a cancelled call, keeping earlier unreported ones."""
    earlier = () if previous is None else (*previous.earlier, previous.tool)
    return Cancelled(tool, after_s, left, earlier)

