"""Ending a launched process with everything it started, and asking whether a pid lives."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from typing import Any

SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x102
ERROR_ACCESS_DENIED = 5


def end_tree(proc: subprocess.Popen[Any], *, ran_out: bool = True, wait_s: float = 5.0) -> None:
    """End `proc`'s group (on Windows its tree, by parent pid) and reap it within `wait_s`.

    The Windows tree is followed by pid, so it is ended only while `ran_out` says `proc` still
    runs: a freed pid can be another program's."""
    if sys.platform == "win32":
        if ran_out:
            with contextlib.suppress(subprocess.TimeoutExpired):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, check=False, timeout=wait_s)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=wait_s)


def pid_alive(pid: int) -> bool:
    """Whether `pid` runs, a zombie awaiting its parent excluded. A `ps` that fails is an error,
    never a process that is gone."""
    if sys.platform == "win32":
        return _win_alive(pid)
    else:   # an `else`, so mypy skips this branch on win32 instead of calling it unreachable
        done = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                              text=True, check=False)
        if done.returncode not in (0, 1):
            raise OSError(f"ps answered rc={done.returncode}: {done.stderr.strip()}")
        stat = done.stdout.strip()
        return bool(stat) and not stat.startswith("Z")


def _win_alive(pid: int) -> bool:
    """A process object still unsignalled; one the user may not open exists all the same."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return bool(ctypes.get_last_error() == ERROR_ACCESS_DENIED)
        try:
            return bool(k32.WaitForSingleObject(wintypes.HANDLE(handle), 0) == WAIT_TIMEOUT)
        finally:
            k32.CloseHandle(wintypes.HANDLE(handle))
    else:
        raise OSError("a Windows probe")
