"""Host checks for a live tier: SDL canary, ledger of launched emulators, run scratch.

A host whose input layer stopped answering blocks every SDL program at its init, deaf to signals,
so a run first launches an emulator that ends by itself and refuses the host when it does not.
Pooled jobs record into the parent's ledger and scratch. POSIX only (`ps`, process groups).
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, cast

#: SDL hint that keeps a newly launched app from taking focus (macOS makes it frontmost).
BACKGROUND_VAR = "SDL_MAC_BACKGROUND_APP"
#: A healthy host ends the canary in seconds; a blocked one never returns.
CANARY_S = 20.0
LEDGER_VAR = "SCRY_LIVE_LEDGER"
LEDGER_NAME = "emulators.tsv"
#: Set by the parent run: a pooled job's scratch, inside its own.
SCRATCH_VAR = "SCRY_LIVE_SCRATCH"
#: Seconds a leftover emulator is given to leave after each signal.
LEAVE_S = 5.0
#: Linux's `ps` cuts a command name to this; a longer one is matched by prefix.
COMM_MAX = 15
#: Windows has no process groups or `ps -A`; both signals are `TerminateProcess`.
WINDOWS = os.name == "nt"


def canary(argv: Sequence[str]) -> str:
    """Empty when `argv` (an emulator that ends by itself) exits 0 within `CANARY_S`, else why.

    Runs in its own process group and a throwaway cwd; the group is killed on any unclean exit."""
    cwd = tempfile.mkdtemp(prefix="scry-canary-")
    name = Path(argv[0]).name
    try:
        try:
            proc = subprocess.Popen(list(argv), env={**os.environ, BACKGROUND_VAR: "1"},
                                    cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return f"{name} could not be launched: {e}"
        # Not `with proc`: its exit waits, and a kernel-stuck process never ends.
        try:
            out, _ = proc.communicate(timeout=CANARY_S)
        except subprocess.TimeoutExpired:
            stuck = _end_group(proc)
            return (f"{name} (pid {proc.pid}) did not return within {CANARY_S:g} s: SDL did "
                    f"not return from its init; the host cannot start this emulator"
                    + (f", and it survived SIGKILL (state U: read it with `sample {proc.pid}`)"
                       if stuck else ""))
        except BaseException:
            _end_group(proc)
            raise
        finally:
            cast(IO[bytes], proc.stdout).close()
        if proc.returncode != 0:
            tail = out[-300:].decode(errors="replace").strip()
            return (f"{name} ended rc={proc.returncode}, so it proved nothing about this "
                    f"host: {tail}")
        return ""
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def _end_group(proc: subprocess.Popen[bytes]) -> bool:
    """SIGKILL the group `proc` leads (on Windows `proc`); whether it is still alive."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if WINDOWS:
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(LEAVE_S)
    return bool(_alive({proc.pid}, 0.0))


def _processes() -> dict[int, tuple[int, str, str]]:
    """Every process on the host, `pid -> (pgid, state, command)`."""
    if WINDOWS:
        return _tasklist()
    done = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,stat=,comm="], capture_output=True,
                          text=True, check=False)
    if done.returncode != 0:
        raise OSError(f"ps answered rc={done.returncode}: {done.stderr.strip()}")
    found: dict[int, tuple[int, str, str]] = {}
    for line in done.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
            found[int(parts[0])] = (int(parts[1]), parts[2], parts[3])
    return found


def _tasklist() -> dict[int, tuple[int, str, str]]:
    done = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                          errors="replace", check=False)
    if done.returncode != 0:
        raise OSError(f"tasklist answered rc={done.returncode}: {done.stderr.strip()}")
    return _tasklist_rows(done.stdout)


def _tasklist_rows(text: str) -> dict[int, tuple[int, str, str]]:
    found: dict[int, tuple[int, str, str]] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[1].isdigit():
            found[int(row[1])] = (int(row[1]), "R", row[0])
    return found


def _alive(pids: set[int], within_s: float) -> set[int]:
    deadline = time.monotonic() + within_s
    while True:
        # A zombie is gone: it ended and only awaits its parent's wait().
        alive = {p for p, (_, state, _) in _processes().items()
                 if p in pids and not state.startswith("Z")}
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.1)


#: Windows has no SIGKILL; its SIGTERM already ends a process outright.
_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _signal(pid: int, pgid: int, sig: signal.Signals) -> None:
    """`sig` to the group `pid` leads, else to `pid` alone."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if pgid == pid and not WINDOWS:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)


def _started(pid: int) -> str:
    """`pid`'s `ps` start time, or empty; tells an emulator from a later holder of its pid."""
    try:
        done = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                              text=True, check=False)
    except Exception:  # noqa: BLE001 -- it sharpens the guard and never fails the launch
        return ""
    return " ".join(done.stdout.split()) if done.returncode == 0 else ""


def _same_program(recorded: str, comm: str) -> bool:
    """Whether `ps`'s `comm` is the program recorded as `recorded` (macOS lists the path)."""
    shown = Path(comm).name
    if WINDOWS:     # `tasklist` names the image (`mamed.exe`)
        return Path(shown).stem.lower() == Path(recorded).stem.lower()
    return shown == recorded or (len(recorded) > COMM_MAX and shown == recorded[:COMM_MAX])


@dataclass(frozen=True)
class Leftovers:
    """Counts recorded and found alive; `survived` holds `(pid, state)` after SIGKILL."""
    recorded: int = 0
    found: int = 0
    survived: tuple[tuple[int, str], ...] = ()

    def line(self) -> str:
        if not self.found:
            return ""
        stuck = ", ".join(f"pid {p} state {s}" for p, s in self.survived)
        return (f"FAIL  {self.found} emulator(s) outlived the run that launched them and were "
                f"killed" + (f"; still alive after SIGKILL: {stuck}" if stuck else ""))


class EmulatorLedger:
    """Launched emulators, one `<pid>\\t<name>\\t<started>` line each; name and start time guard
    against a reused pid."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_environment(cls) -> EmulatorLedger | None:
        named = os.environ.get(LEDGER_VAR)
        return cls(Path(named)) if named else None

    def record(self, pid: int, program: str) -> None:
        """One launch, right after the process exists; a write failure never fails the launch."""
        started = _started(pid)
        with contextlib.suppress(OSError), self.path.open("a", encoding="utf-8") as out:
            out.write(f"{pid}\t{Path(program).name}\t{started}\n")

    def recorded(self) -> dict[int, str]:

        return {pid: name for pid, (name, _) in self._rows().items()}

    def _rows(self) -> dict[int, tuple[str, str]]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        rows = (line.split("\t") for line in text.splitlines())
        return {int(row[0]): (row[1], row[2] if len(row) == 3 else "") for row in rows
                if len(row) in (2, 3) and row[0].isdigit() and row[1]}

    def reap(self) -> Leftovers:
        """SIGTERM then SIGKILL every recorded emulator still alive under its name; the rest."""
        mine, now = self._rows(), _processes()
        alive = {p: pgid for p, (pgid, state, comm) in now.items()
                 if p in mine and _same_program(mine[p][0], comm) and not state.startswith("Z")
                 and mine[p][1] in ("", _started(p))}
        if not alive:
            return Leftovers(len(mine))
        for p, pgid in alive.items():
            _signal(p, pgid, signal.SIGTERM)
        if left := _alive(set(alive), LEAVE_S):
            for p in left:
                _signal(p, alive[p], _KILL)
            left = _alive(left, LEAVE_S)
        states = _processes()
        return Leftovers(len(mine), len(alive), tuple(sorted(
            (p, states.get(p, (0, "?", ""))[1]) for p in left)))


@dataclass
class LiveRun:
    """One live run on its host.

    `job`: a pooled job; its parent ran the canary, reaps for it and owns its scratch."""
    scratch: Path
    job: bool
    say: Callable[[str], None] = print
    finished: bool = False
    ledger: EmulatorLedger | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    @classmethod
    def for_process(cls, prefix: str, job: bool) -> LiveRun:
        """This process's run: a job takes its parent's scratch, else a new `<prefix><random>`."""
        handed = os.environ.get(SCRATCH_VAR) if job else None
        return cls(Path(handed) if handed else
                   Path(tempfile.gettempdir()) / f"{prefix}{uuid.uuid4().hex[:12]}", job)

    def made(self) -> Path:
        self.scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.scratch

    def job_env(self, name: str) -> dict[str, str]:
        return {SCRATCH_VAR: str(self.made() / "jobs-scratch" / name)}

    def begin(self, canary_argv: Sequence[str] | None, emulator: str) -> str:
        """Outside a job: canary, then ledger. Answers why the host is refused, or empty.
        `canary_argv` None: no `emulator` resolves here."""
        if self.job:
            return ""
        if canary_argv is None:
            self.say(f"host canary: not run, no {emulator} resolves on this host")
        elif why := canary(canary_argv):
            return f"host canary: {why}"
        else:
            self.say(f"host canary: {Path(canary_argv[0]).name} started and ended by itself")
        self.ledger = EmulatorLedger(self.made() / LEDGER_NAME)
        os.environ[LEDGER_VAR] = str(self.ledger.path)
        return ""

    def close(self, on_end: Callable[[], object]) -> str:
        """Once: `on_end`, then prove every launched emulator gone. Answers the FAIL line, or
        empty; an unreadable host is a FAIL."""
        if self._closed:
            return ""
        self._closed = True
        try:
            on_end()
        except Exception as e:  # noqa: BLE001 -- the proof below still runs
            self.say(f"  (end) closing the machine raised {type(e).__name__}: {e}")
        if self.ledger is None:
            return ""
        try:
            left = self.ledger.reap()
        except OSError as e:
            return (f"FAIL  the end check could not read this host's processes ({e}), so the "
                    f"emulators this run launched may still be alive")
        if not left.recorded:
            # Nothing recorded is not nothing left: a server that never wrote the ledger leaves
            # this same empty file.
            return ("INVALID  the ledger recorded no emulator launch, so the end check examined "
                    "nothing: a run that launched one has a server that did not record it")
        if not left.found:
            self.say(f"emulators launched: {left.recorded}, none left alive")
        return left.line()

    def leave(self, kept: bool) -> None:
        """Remove the scratch when green, else keep and name it. A job leaves it to its parent."""
        if self.job or not self.scratch.exists():
            return
        if kept:
            self.say(f"kept: {self.scratch}")
            return
        shutil.rmtree(self.scratch, ignore_errors=True)
        self.say("scratch removed, the transcript with it")

    def unfinished(self, on_end: Callable[[], object]) -> None:
        """End a run that never reached its verdict: close, prove emulators gone, keep scratch."""
        if self.finished:
            return
        self.finished = True
        if line := self.close(on_end):
            self.say(line)
        self.leave(kept=True)
