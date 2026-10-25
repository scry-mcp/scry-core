"""An emulator dies with its server and at its wall-clock `deadline` (epoch seconds, 0 for none).

A SIGKILLed server runs no `finally`, and DOSBox-X's `-time-limit` never advances while stopped.
On POSIX a watcher process does it; on Windows a job object the server holds, which the OS closes
when the server ends however it ends, ending the emulator with it. The deadline is POSIX's.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from typing import Protocol

POLL_S = 1.0

STOP_GRACE_S = 5.0

#: Whether the guardian is a watcher process (POSIX) rather than a job (Windows, whose `os.kill`
#: terminates for any signal and whose processes keep no parent to watch).
WATCHER = sys.platform != "win32"
#: Windows has no SIGKILL, and there `os.kill` terminates for any signal.
KILL: int = getattr(signal, "SIGKILL", signal.SIGTERM)

#: The Windows half (`JOBOBJECT_BASIC_LIMIT_INFORMATION`, `SetInformationJobObject`, `OpenProcess`).
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE, PROCESS_SET_QUOTA = 0x0001, 0x0100

#: Kills are by pid, so only a real child is watched.
_POPEN = subprocess.Popen


def name_of(server: str) -> str:
    """The guardian's name in the process list."""
    return f"{server}-guardian"


class Guard(Protocol):
    """What `stop` ends: the watcher process, or the job."""

    def poll(self) -> int | None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class Job:
    """A Windows job object that ends its process when its last handle closes."""

    def __init__(self, handle: int) -> None:
        self.handle: int | None = handle

    def poll(self) -> int | None:
        return None if self.handle is not None else 0

    def kill(self) -> None:
        if self.handle is not None:
            _close_handle(self.handle)
            self.handle = None

    def wait(self, timeout: float | None = None) -> int:
        return 0


def spawn(child: object, server: str, deadline: float = 0.0) -> Guard | None:
    """The guardian for `child`: a watcher on POSIX, a job on Windows; None for a non-child."""
    if not isinstance(child, _POPEN):
        return None
    if sys.platform == "win32":
        return _job(child.pid)
    else:
        return _POPEN(
            # `-I` keeps a stray cwd `scry_core` out and drops PYTHONPATH, so `program` carries
            # the path.
            [sys.executable, "-I", "-c", program(sys.path), str(os.getpid()), str(child.pid),
             str(POLL_S), repr(deadline), name_of(server)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)


def stop(guard: Guard | None) -> None:
    """End a guardian once its emulator is gone."""
    if guard is None:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        guard.kill()
        guard.wait(timeout=STOP_GRACE_S)


def started(pid: int, proc: str = "/proc") -> str | None:
    """Start time of `pid`; "" if no such process, None if unknowable."""
    try:
        with open(f"{proc}/{pid}/stat", encoding="ascii", errors="replace") as f:
            stat = f.read()
    except FileNotFoundError:
        if os.path.isdir(proc):
            return ""                     # a host with /proc and no such process
    except OSError:
        pass
    else:
        fields = stat.rpartition(")")[2].split()
        return fields[19] if len(fields) > 19 else None
    try:
        run = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                             text=True, check=False, env={"TZ": "UTC", "LC_ALL": "C",
                                                          "PATH": os.environ.get("PATH", "")})
    except OSError:
        return None
    if run.returncode == 0 and run.stdout.strip():
        return run.stdout.strip()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ""
    except PermissionError:
        pass
    return None


def watch(server: int, child: int, poll_s: float, deadline: float) -> None:
    """Kill the child when the parent goes or the deadline passes."""
    born = started(child)
    while True:
        try:
            os.kill(child, 0)
        except (ProcessLookupError, PermissionError):
            return
        if os.getppid() != server or (deadline and time.time() >= deadline):
            # Pids are reused: kill only if the start time matches; with none, by pid.
            if born is None or (born and started(child) == born):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(child, KILL)
            return
        time.sleep(poll_s)


def main(argv: list[str]) -> None:
    """Name the process, then watch."""
    server, child, poll_s, deadline, name = argv
    with contextlib.suppress(Exception):
        from scry_core import process_name
        process_name.set_title(name)
    watch(int(server), int(child), float(poll_s), float(deadline))


def program(path: list[str]) -> str:

    entries = [p for p in path if p and os.path.isdir(p)]
    return (f"import sys; sys.path[:0] = {entries!r}; "
            "from scry_core.guardian import main; main(sys.argv[1:])")


def _job(pid: int) -> Job:
    """`pid` placed in a new job that kills it on close; `OSError` if Windows refuses a step."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        try:
            if not (process and k32.SetInformationJobObject(
                    wintypes.HANDLE(job), JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    ctypes.byref(info), ctypes.sizeof(info))
                    and k32.AssignProcessToJobObject(wintypes.HANDLE(job),
                                                     wintypes.HANDLE(process))):
                error = ctypes.WinError(ctypes.get_last_error())
                _close_handle(job)
                raise error
        finally:
            if process:
                _close_handle(process)
        return Job(job)
    else:
        raise OSError("a job object is Windows'")


def _close_handle(handle: int) -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(handle))
