"""The host a server's live tier runs on: whether it can start the emulator at all, which
emulators a run launched and whether any outlived it, and the run's scratch, left as its verdict
says.

    run = live_host.LiveRun.for_process("mame-live-matrix-", job=bool(summary))
    if why := run.begin(canary_argv, "MAME"):     # before the first start
        ...                                        # INVALID, nothing launched
    ...
    if line := run.close(on_end):                  # the machine closed, the emulators proved gone
        ...                                        # a FAIL beside the verdict
    run.finished = True
    run.leave(kept=red)

A HOST WHOSE INPUT LAYER STOPPED ANSWERING BLOCKS EVERY SDL PROGRAM AT ITS INIT, deaf to
signals, and a run that went on into it would fail every cell on the code and leave an emulator
behind per start. So a run launches the emulator once first, in a form that ends by itself, and
refuses the host when it does not (`canary`). And an emulator is never evidence: a run proves at
its end that every one its sessions launched is gone (`EmulatorLedger`), killing and naming any
that is not.

A RUN'S JOBS LIVE INSIDE IT. A pooled job is handed a scratch under its parent's
(`LiveRun.job_env`), so what the parent removes or keeps it removes or keeps whole, and a job
that died before declaring anything leaves nothing anonymous behind. The ledger is the parent's
too: every launch of every job, and of every server a run spawns, is recorded in the one file
the parent named in the environment, at the server's own launch point, so a start that then
failed is recorded as well.

POSIX only, as the live tiers are: the end check reads `ps` and signals process groups.
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

#: macOS makes a newly launched app with a window the frontmost one, which takes the person's
#: focus and can move them to another Space; SDL reads this hint before its init and keeps the
#: app behind. Every unwatched launch sets it, the canary always.
BACKGROUND_VAR = "SDL_MAC_BACKGROUND_APP"
#: A healthy host starts and ends either emulator's canary in a few seconds; a blocked one never
#: returns, so the bound only has to tell those apart.
CANARY_S = 20.0
#: Where a live run's ledger of launched emulators is, for its jobs and the servers it spawns.
LEDGER_VAR = "SCRY_LIVE_LEDGER"
#: The ledger's name inside the run's scratch.
LEDGER_NAME = "emulators.tsv"
#: Where a pooled job's scratch is, inside its parent's; set by the parent, never by hand.
SCRATCH_VAR = "SCRY_LIVE_SCRATCH"
#: How long a leftover emulator is given to leave on SIGTERM before SIGKILL, and then to vanish.
LEAVE_S = 5.0
#: How much of a command name Linux's `ps` keeps: a longer name is matched by its prefix.
COMM_MAX = 15
#: WINDOWS HAS NO PROCESS GROUPS AND NO `ps -A`: its processes are listed by `tasklist` and ended
#: one pid at a time (both signals are `TerminateProcess` there), so the guards that remain are
#: the program's name and the run's own ledger.
WINDOWS = os.name == "nt"


def canary(argv: Sequence[str]) -> str:
    """Empty when the emulator `argv` names started and ended by itself (rc 0) within `CANARY_S`,
    otherwise why not, for the run to print as INVALID before it launches anything else.

    `argv` initialises SDL as the run's first start does and ENDS BY ITSELF on a healthy host. It
    runs launched behind, in its own process group and in a working directory of its own that is
    removed after it (an emulator writes its configuration where it runs), and its group is
    killed on any way out but a clean end, an interrupt included."""
    cwd = tempfile.mkdtemp(prefix="scry-canary-")
    name = Path(argv[0]).name
    try:
        try:
            proc = subprocess.Popen(list(argv), env={**os.environ, BACKGROUND_VAR: "1"},
                                    cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return f"{name} could not be launched: {e}"
        # NOT `with proc`: its exit waits for the process, and one stuck in the kernel never ends.
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
    """SIGKILL to the group `proc` leads (on Windows, `proc` itself), then whether it is still
    there."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if WINDOWS:
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(LEAVE_S)
    return bool(_alive({proc.pid}, 0.0))


def _processes() -> dict[int, tuple[int, str, str]]:
    """Every process on the host, `pid -> (pgid, state, command)`, from one `ps` listing; on
    Windows from one `tasklist` listing (`_tasklist`)."""
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
    """Every process on a Windows host as `_processes` answers it: each its own group (there are
    none) and running (no state is listed)."""
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
    """The processes of `pids` still alive after waiting up to `within_s` for them to leave."""
    deadline = time.monotonic() + within_s
    while True:
        # A ZOMBIE IS GONE: it ended and only waits for its parent (the run, for an emulator it
        # launched in process) to read its exit status.
        alive = {p for p, (_, state, _) in _processes().items()
                 if p in pids and not state.startswith("Z")}
        if not alive or time.monotonic() >= deadline:
            return alive
        time.sleep(0.1)


#: The last signal: Windows has no SIGKILL, and its SIGTERM already ends a process outright.
_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def _signal(pid: int, pgid: int, sig: signal.Signals) -> None:
    """`sig` to the group `pid` leads, or to `pid` alone when it lives in somebody else's group:
    MAME runs in its server's, which in process is the run's own."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if pgid == pid and not WINDOWS:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)


def _started(pid: int) -> str:
    """When `pid` started, as `ps` says it (`lstart`), or empty when it cannot say: with the
    name, what tells the emulator a run launched from a later process the system gave its pid."""
    try:
        done = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                              text=True, check=False)
    except Exception:  # noqa: BLE001 -- it sharpens the guard and never fails the launch
        return ""
    return " ".join(done.stdout.split()) if done.returncode == 0 else ""


def _same_program(recorded: str, comm: str) -> bool:
    """Whether `ps`'s command `comm` is the program recorded under `recorded`: macOS lists the
    path, Linux the name cut to `COMM_MAX`."""
    shown = Path(comm).name
    if WINDOWS:     # `tasklist` names the image, `mamed.exe`, which a launch may have named bare
        return Path(shown).stem.lower() == Path(recorded).stem.lower()
    return shown == recorded or (len(recorded) > COMM_MAX and shown == recorded[:COMM_MAX])


@dataclass(frozen=True)
class Leftovers:
    """What a run found alive of the emulators it launched: how many it recorded, how many were
    still alive, and the ones still there after SIGKILL, each `(pid, state)`."""
    recorded: int = 0
    found: int = 0
    survived: tuple[tuple[int, str], ...] = ()

    def line(self) -> str:
        """The FAIL line a run prints beside its verdict, empty when nothing outlived it."""
        if not self.found:
            return ""
        stuck = ", ".join(f"pid {p} state {s}" for p, s in self.survived)
        return (f"FAIL  {self.found} emulator(s) outlived the run that launched them and were "
                f"killed" + (f"; still alive after SIGKILL: {stuck}" if stuck else ""))


class EmulatorLedger:
    """The emulators a live run launched, one `<pid>\\t<name>\\t<started>` line each, and the end
    check that proves them gone. The name and the start time guard a pid the system gave another
    process after the emulator left: the same program, launched by somebody else, included."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_environment(cls) -> EmulatorLedger | None:
        """The ledger the live run this process belongs to named, or None outside one."""
        named = os.environ.get(LEDGER_VAR)
        return cls(Path(named)) if named else None

    def record(self, pid: int, program: str) -> None:
        """One launch, called by a server right after its emulator's process exists, before
        anything that could fail; a ledger that cannot be written never fails the launch, and
        the run's end reports how many it recorded."""
        started = _started(pid)
        with contextlib.suppress(OSError), self.path.open("a", encoding="utf-8") as out:
            out.write(f"{pid}\t{Path(program).name}\t{started}\n")

    def recorded(self) -> dict[int, str]:
        """The program each recorded pid was launched as."""
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
        """Every recorded emulator still alive under its own name, sent SIGTERM, then SIGKILL
        after `LEAVE_S`, and what survived both."""
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
    """One live run's life on its host: its scratch (named now, made on first use), the canary
    and the ledger at its start, the proof at its end, and what it leaves.

    `job`: a pooled job, whose parent ran the canary, reaps for it and owns its scratch."""
    scratch: Path
    job: bool
    say: Callable[[str], None] = print
    #: Whether the run has ended, by its verdict or by `unfinished`: it ends once.
    finished: bool = False
    ledger: EmulatorLedger | None = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    @classmethod
    def for_process(cls, prefix: str, job: bool) -> LiveRun:
        """This process's run: in a pooled job the scratch its parent handed it, else a new one
        named `<prefix><random>` directly under the host's temporary directory."""
        handed = os.environ.get(SCRATCH_VAR) if job else None
        return cls(Path(handed) if handed else
                   Path(tempfile.gettempdir()) / f"{prefix}{uuid.uuid4().hex[:12]}", job)

    def made(self) -> Path:
        self.scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.scratch

    def job_env(self, name: str) -> dict[str, str]:
        """What a pooled job named `name` is started with: its scratch, inside this run's."""
        return {SCRATCH_VAR: str(self.made() / "jobs-scratch" / name)}

    def begin(self, canary_argv: Sequence[str] | None, emulator: str) -> str:
        """Before the run's first start, outside a job: the canary, then the ledger every launch
        is recorded in. Answers why the host is refused (nothing made, nothing launched), or
        empty. `canary_argv` None: no `emulator` resolves on this host."""
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
        """Once: the machine this process holds closed (`on_end`), then every emulator the run
        launched proved gone. Answers the FAIL line for the verdict, empty when nothing outlived
        the run; a check that could not read the host is a FAIL too, never a pass."""
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
            # NOTHING RECORDED IS NOT NOTHING LEFT: a server that never wrote the ledger (one
            # pinned to a core without it, or spawned before the run named it) leaves this same
            # empty file, and an end check that examined nothing is no verdict.
            return ("INVALID  the ledger recorded no emulator launch, so the end check examined "
                    "nothing: a run that launched one has a server that did not record it")
        if not left.found:
            self.say(f"emulators launched: {left.recorded}, none left alive")
        return left.line()

    def leave(self, kept: bool) -> None:
        """A RUN LEAVES WHAT IT SAYS IT KEEPS AND NOTHING ELSE: green, its scratch is removed with
        everything in it (its jobs' and its transcript too); red, INVALID or broken, it is kept
        and named. A job leaves its own to its parent."""
        if self.job or not self.scratch.exists():
            return
        if kept:
            self.say(f"kept: {self.scratch}")
            return
        shutil.rmtree(self.scratch, ignore_errors=True)
        self.say("scratch removed, the transcript with it")

    def unfinished(self, on_end: Callable[[], object]) -> None:
        """The end of a run that never reached its verdict (an INVALID, an uncaught exception, a
        signal made an exit): its machine closed, its emulators proved gone, its scratch kept."""
        if self.finished:
            return
        self.finished = True
        if line := self.close(on_end):
            self.say(line)
        self.leave(kept=True)
