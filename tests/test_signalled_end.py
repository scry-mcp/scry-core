"""A signalled end closes under the lock or past its wait, cleans up, and leaves whatever failed."""

from __future__ import annotations

import signal
import threading
import time
from typing import Any

import pytest

from scry_core import signalled_end

LOCK = threading.RLock()


def _end(closes: list[str], fails: bool = False) -> tuple[signalled_end.SignalledEnd, list[int],
                                                          threading.Event]:
    left: list[int] = []
    gone = threading.Event()

    def close() -> None:
        closes.append("closed")
        if fails:
            raise OSError("not reaped")

    end = signalled_end.SignalledEnd(LOCK, close, lambda: closes.append("clean"), "test server")

    def leave(code: int) -> None:
        left.append(code)
        gone.set()
    end.leave = leave
    return end, left, gone


@pytest.fixture
def handlers() -> Any:
    saved = {s: signal.getsignal(s) for s in signalled_end.EXIT_SIGNALS}
    yield
    for s, handler in saved.items():
        signal.signal(s, handler if handler is not None else signal.SIG_DFL)


def test_a_signal_closes_cleans_and_leaves_and_the_next_signals_are_ignored(handlers: None) -> None:
    closes: list[str] = []
    end, left, gone = _end(closes)
    end.install()
    assert all(signal.getsignal(s) == end.on_signal for s in signalled_end.EXIT_SIGNALS)
    end.on_signal(signal.SIGTERM, None)
    assert gone.wait(5.0) and left == [128 + signal.SIGTERM] and closes == ["closed", "clean"]
    assert all(signal.getsignal(s) == signal.SIG_IGN for s in signalled_end.EXIT_SIGNALS)


def test_a_held_lock_is_waited_for_only_so_long(handlers: None) -> None:
    closes: list[str] = []
    end, left, gone = _end(closes)
    end.lock_wait_s = 0.2
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with LOCK:
            held.set()
            release.wait(10.0)
    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(5.0)
    began = time.monotonic()
    end.on_signal(signal.SIGTERM, None)
    try:
        assert gone.wait(5.0) and time.monotonic() - began < 3.0 and closes == ["closed", "clean"]
    finally:
        release.set()
        holder.join()


def test_a_tool_holding_the_lock_finishes_before_the_close(handlers: None) -> None:
    closes: list[str] = []
    end, left, gone = _end(closes)
    held = threading.Event()

    def hold() -> None:
        with LOCK:
            held.set()
            time.sleep(0.3)
            closes.append("tool done")
    holder = threading.Thread(target=hold)
    holder.start()
    held.wait(5.0)
    end.on_signal(signal.SIGTERM, None)
    assert gone.wait(5.0) and closes == ["tool done", "closed", "clean"], closes
    holder.join()


def test_a_close_that_fails_is_said_and_the_end_still_cleans_and_leaves(
        capfd: pytest.CaptureFixture[str]) -> None:
    closes: list[str] = []
    end, left, _gone = _end(closes, fails=True)
    end.end(143)
    assert left == [143] and closes == ["closed", "clean"]
    assert "test server: the session could not be closed on the way out" in capfd.readouterr().err
