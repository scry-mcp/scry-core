"""THE GUARDIAN: an emulator a server spawned dies with it, however the server ends, and never
outlives the wall-clock bound its session declared.

An emulator has no reason of its own to exit when its server goes (end-of-file on a console
only stops the console, a dropped debugger connection leaves the machine running), and a server
that is SIGKILLed or crashes runs no `finally`, so its emulator would run on under init. Nor does
an emulator's own time limit bound a session that sits in its debugger: DOSBox-X's `-time-limit`
counts emulated time, which a stopped machine never advances. The guardian is a small process
beside every emulator, in a session of its own so a signal to the server's process group does
not take it down with the server. It polls its parent: within a poll of being reparented, the
server gone, it SIGKILLs the emulator; past `deadline` (epoch seconds, 0 for none) it does the
same. The server stops it at every close, so it outlives no session it watches.

IT KILLS ONLY THE PROCESS IT WAS GIVEN. A pid is reused once the server has reaped its emulator,
so the guardian reads the child's start time when it begins and again before it kills, and
leaves when the two differ; a pid it may not signal is somebody else's too. The start time is the
kernel's own count where the host has `/proc`, and `ps` asked in UTC and the C locale elsewhere,
so the same process reads the same both times.

POSIX ONLY. Windows has no reparenting for `getppid` to see, and its `os.kill` terminates a
process for any signal but the console's two, so the poll itself would kill the emulator: there
`spawn` returns None, and nothing but the server watches its emulator.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

#: How often the guardian looks: a second, against an emulator that would otherwise run until
#: reboot.
POLL_S = 1.0

#: How long `stop` waits for the SIGKILLed guardian to be reaped.
STOP_GRACE_S = 5.0

#: Whether this host can have a guardian, read once into a name (a type checker narrows
#: `sys.platform` and would call the other half unreachable).
SUPPORTED = sys.platform != "win32"

#: `Popen` as this module found it. The guardian kills BY PID, so it watches only a process that
#: is this server's own child: anything else (a stand-in whose pid may be anybody's) gets none.
_POPEN = subprocess.Popen


def name_of(server: str) -> str:
    """What the guardian of the server named `server` is called in the host's process list."""
    return f"{server}-guardian"


def spawn(child: object, server: str, deadline: float = 0.0) -> subprocess.Popen[bytes] | None:
    """The guardian for `child`, a process this server spawned, named after `server` in the
    host's process list (`name_of`), in a session of its own; None for a process this server did
    not spawn itself, or on a host with no guardian (`SUPPORTED`)."""
    if not SUPPORTED or not isinstance(child, _POPEN):
        return None
    return _POPEN(
        # ISOLATED (`-I`): a `scry_core` in whatever directory the server runs from cannot stand in
        # for the real one. The server's own import path goes in the program instead, since `-I`
        # also drops PYTHONPATH and the user's site, where this server may have found it.
        [sys.executable, "-I", "-c", program(sys.path), str(os.getpid()), str(child.pid),
         str(POLL_S), repr(deadline), name_of(server)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def stop(guard: subprocess.Popen[bytes] | None) -> None:
    """End a guardian, once the emulator it watches is ended or given up on: stopped before, a
    server dying in between would leave that emulator with nothing watching it."""
    if guard is None:
        return
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        guard.kill()
        guard.wait(timeout=STOP_GRACE_S)


def started(pid: int, proc: str = "/proc") -> str | None:
    """When `pid` started: "" for a pid with no process, None when the host cannot say, so the
    identity cannot be checked at all."""
    try:
        with open(f"{proc}/{pid}/stat", encoding="ascii", errors="replace") as f:
            stat = f.read()
    except FileNotFoundError:
        if os.path.isdir(proc):
            return ""                     # a host with /proc and no such process
    except OSError:
        pass
    else:
        # The start time is field 22, counted after the name, which may hold spaces and ")".
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
    # `ps` said nothing: the process gone, or a `ps` that cannot answer for one that is there.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ""
    except PermissionError:
        pass
    return None


def watch(server: int, child: int, poll_s: float, deadline: float) -> None:
    """The guardian's loop: leave when the child does, kill it if the parent goes or the
    deadline passes. `os.getppid` changing is the test, never `kill(server, 0)`, because a dead
    server's pid can be reused and a reparented process cannot be un-reparented."""
    born = started(child)
    while True:
        try:
            os.kill(child, 0)
        except (ProcessLookupError, PermissionError):
            return
        if os.getppid() != server or (deadline and time.time() >= deadline):
            # A HOST THAT CANNOT SAY WHEN THE CHILD STARTED kills by the pid alone: an emulator
            # left running is the worse of the two.
            if born is None or (born and started(child) == born):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(child, signal.SIGKILL)
            return
        time.sleep(poll_s)


def main(argv: list[str]) -> None:
    """The guardian's program, over `spawn`'s arguments: named, then watching. A name the host
    refuses costs the name, never the watch."""
    server, child, poll_s, deadline, name = argv
    # IMPORTED HERE, so a naming that cannot even import costs the name and never the watch.
    with contextlib.suppress(Exception):
        from scry_core import process_name
        process_name.set_title(name)
    watch(int(server), int(child), float(poll_s), float(deadline))


def program(path: list[str]) -> str:
    """What the guardian's interpreter runs: `main` over its arguments, importing from `path`,
    the server's import path, less the current directory."""
    entries = [p for p in path if p and os.path.isdir(p)]
    return (f"import sys; sys.path[:0] = {entries!r}; "
            "from scry_core.guardian import main; main(sys.argv[1:])")
