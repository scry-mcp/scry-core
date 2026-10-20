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
leaves when the two differ; a pid it may not signal is somebody else's too.

POSIX ONLY. Windows has no reparenting for `getppid` to see, and its `os.kill` terminates a
process for any signal but the console's two, so the poll itself would kill the emulator: there
`spawn` returns None, and a server says so where it reports its backstops.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

from scry_core import process_name

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


def spawn(child: object, name: str, deadline: float = 0.0) -> subprocess.Popen[bytes] | None:
    """The guardian for `child`, a process this server spawned, named `name` in the host's
    process list, in a session of its own; None for a process this server did not spawn itself,
    or on a host with no guardian (`SUPPORTED`)."""
    if not SUPPORTED or not isinstance(child, _POPEN):
        return None
    return _POPEN(
        # ISOLATED (`-I`): a `scry_core` in whatever directory the server runs from cannot stand in
        # for the real one.
        [sys.executable, "-I", "-c", _PROGRAM, str(os.getpid()), str(child.pid), str(POLL_S),
         repr(deadline), name],
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


def started(pid: int) -> str:
    """When `pid` started, as `ps` tells it, or "" for a pid with no process."""
    run = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                         check=False)
    return run.stdout.strip() if run.returncode == 0 else ""


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
            if born and started(child) == born:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.kill(child, signal.SIGKILL)
            return
        time.sleep(poll_s)


def main(argv: list[str]) -> None:
    """The guardian's program, over `spawn`'s arguments: named, then watching. A name the host
    refuses costs the name, never the watch."""
    server, child, poll_s, deadline, name = argv
    with contextlib.suppress(Exception):
        process_name.set_title(name)
    watch(int(server), int(child), float(poll_s), float(deadline))


#: What the guardian's interpreter runs: `main` over its arguments.
_PROGRAM = "import sys; from scry_core.guardian import main; main(sys.argv[1:])"
