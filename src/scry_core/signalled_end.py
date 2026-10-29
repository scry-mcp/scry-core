"""A server's end on SIGTERM, SIGHUP or Ctrl-C: the default action skips its `finally`, and an
emulator in a process session of its own would outlive it."""

from __future__ import annotations

import os
import signal
import sys
import threading
from collections.abc import Callable
from typing import Protocol

EXIT_SIGNALS: tuple[signal.Signals, ...] = tuple(
    getattr(signal, name) for name in ("SIGTERM", "SIGHUP", "SIGINT") if hasattr(signal, name))
#: How long a tool may hold the machine before the emulator is closed anyway.
LOCK_WAIT_S = 10.0


class Lock(Protocol):
    def acquire(self, blocking: bool = ..., timeout: float = ...) -> bool: ...
    def release(self) -> None: ...


class SignalledEnd:
    """`close` under `lock` (or past `lock_wait_s`), `cleanup`, then `leave` at once: the
    transport's reader is blocked on a stdin nobody closed."""

    def __init__(self, lock: Lock, close: Callable[[], object], cleanup: Callable[[], object],
                 name: str) -> None:
        self.lock, self.close, self.cleanup, self.name = lock, close, cleanup, name
        self.lock_wait_s = LOCK_WAIT_S
        self.leave: Callable[[int], object] = os._exit

    def install(self) -> None:
        for sig in EXIT_SIGNALS:
            signal.signal(sig, self.on_signal)

    def on_signal(self, signum: int, _frame: object) -> None:
        """The end on a thread of its own (raised in the event loop's frame, a task group would
        swallow it); later signals are ignored, so none cuts it short."""
        for sig in EXIT_SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        threading.Thread(target=self.end, args=(128 + signum,), name="signalled-end",
                         daemon=True).start()

    def end(self, code: int) -> None:
        try:
            took = self.lock.acquire(timeout=self.lock_wait_s)
            try:
                self.close()
            except Exception as e:  # noqa: BLE001
                print(f"{self.name}: the session could not be closed on the way out ({e!r})",
                      file=sys.stderr, flush=True)
            finally:
                if took:
                    self.lock.release()
            self.cleanup()
        finally:
            self.leave(code)
