"""An emulator dies with its server and at its wall-clock `deadline` (epoch seconds, 0 for none).

A SIGKILLed server runs no `finally`, and DOSBox-X's `-time-limit` never advances while stopped.
POSIX only: on Windows `os.kill` terminates for any signal.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

POLL_S = 1.0

STOP_GRACE_S = 5.0

SUPPORTED = sys.platform != "win32"
#: Windows has no SIGKILL, and there `os.kill` terminates for any signal.
KILL: int = getattr(signal, "SIGKILL", signal.SIGTERM)

#: Kills are by pid, so only a real child is watched.
_POPEN = subprocess.Popen


def name_of(server: str) -> str:
    """The guardian's name in the process list."""
    return f"{server}-guardian"


def spawn(child: object, server: str, deadline: float = 0.0) -> subprocess.Popen[bytes] | None:
    """The guardian for `child`; None for a non-child or on Windows."""
    if not SUPPORTED or not isinstance(child, _POPEN):
        return None
    return _POPEN(
        # `-I` keeps a stray cwd `scry_core` out and drops PYTHONPATH, so `program` carries the
        # path.
        [sys.executable, "-I", "-c", program(sys.path), str(os.getpid()), str(child.pid),
         str(POLL_S), repr(deadline), name_of(server)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def stop(guard: subprocess.Popen[bytes] | None) -> None:
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
