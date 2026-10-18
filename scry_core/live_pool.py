"""Run a live tier's independent jobs as parallel child processes, and merge what each declares.

A live run spends most of its time waiting on emulators, so the jobs that share nothing (a
matrix's sections, a suite's files) can wait side by side. Each job is a child process of the
caller's own script; it writes a SUMMARY, a JSON document in the format this module writes and
reads, and the parent merges the summaries:

    jobs = [live_pool.Job("A", [sys.executable, script], env={"X_LIVE_SECTIONS": "A"},
                          planned=labels_of_a)]
    result = live_pool.run_pool(jobs, live_pool.default_workers(), out_dir, "X_LIVE_SUMMARY")

THE SUMMARY IS THE INTERFACE, never the child's printed lines: a merge that picked numbers out of
a recap would read whatever column it landed on. A job whose child leaves no readable summary,
or could not be started, FAILS every label it planned, with the reason, because a job that died
is a failure, never a shorter green. A summary that plans other labels than the parent gave its
job makes the result INVALID, and that job's labels FAIL rather than merge a plan nobody
declared. The exit code is reported beside the summary and judged by the caller, who knows what
its children's codes mean.

INTERRUPTED, every child is sent the interrupt itself (SIGINT on POSIX, so a Python child unwinds
through its own cleanup and closes what it launched) and killed if it is still there after
`STOP_GRACE_S`, or at once on a second interrupt. Windows has no SIGINT to send to one process,
so there the child is terminated outright, and anything it launched is left for its owner to
reap. Each child runs in a process group of its own, so a Ctrl-C at the terminal reaches the
parent alone and the stop is the one interrupt a child gets: a second one is what makes a
Python child abandon its cleanup. The price is that a signal sent to the parent's group, or a
parent killed outright, does not reach the children; the parent's stop is what ends them.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Literal, TypeGuard, cast, get_args

SUMMARY_FORMAT = "scry-live-summary"
SUMMARY_VERSION = 1
Outcome = Literal["OK", "FAIL", "BLOCKED"]
OUTCOMES: frozenset[str] = frozenset(get_args(Outcome))
# How often the parent looks up from waiting on its children: a bare lock wait on Windows lets
# no Ctrl-C through, a timed one does.
POLL_INTERVAL_S = 0.5
# How long an interrupted child is given to unwind before it is killed.
STOP_GRACE_S = 10.0
# A job's name is the stem of its log and summary files: one plain word, so it is never a path,
# and compared case-folded, because macOS and Windows file names are.
_JOB_NAME = re.compile(r"[A-Za-z0-9_-]+")
# What every child is started with before its job's own environment: its output unbuffered, so
# a child that is stopped keeps its last lines in the log, and Python's UTF-8 mode, so a child's
# print of a label is not refused by a Windows code page.
_CHILD_ENV = {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
# Each child in a process group of its own (the module docstring says why).
_OWN_GROUP: dict[str, Any] = (
    {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    if sys.platform == "win32" else {"process_group": 0})
# A CHILD UNWINDS ON THE POOL'S INTERRUPT WHATEVER ITS LAUNCHER IGNORED: a pool started as a
# background job of a non-interactive shell has SIGINT ignored, an ignored signal survives exec,
# and a Python child born so never installs the handler its cleanup runs under. So on POSIX each
# child starts through this trampoline, which execs the job's own argv with SIGINT at its default,
# and SIGPIPE and SIGXFSZ too: the trampoline is itself a Python, which ignores those two at
# startup, undoing what `Popen`'s `restore_signals` did. SIGINT is UNBLOCKED as well: a mask
# survives exec like a disposition does, and a blocked SIGINT is never delivered, only kept
# pending. Only SIGINT: it is the pool's stop, and a block of any other signal is the launcher's.
# Isolated (`-I`), so neither a module in the pool's directory nor the job's `PYTHON*` variables
# reach it. A `preexec_fn` would do it in the parent's fork, which is unsafe beside the threads
# the pool starts children from.
_RESTORE_SIGNALS: tuple[str, ...] = () if sys.platform == "win32" else (
    sys.executable, "-I", "-c",
    "import os, signal, sys\n"
    "for name in ('SIGINT', 'SIGPIPE', 'SIGXFSZ'):\n"
    "    signal.signal(getattr(signal, name), signal.SIG_DFL)\n"
    "signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})\n"
    "os.execvp(sys.argv[1], sys.argv[1:])")


def default_workers() -> int:
    """Half the CPUs available, at least one, so the person at the machine keeps the other half:
    `os.process_cpu_count` where Python has it (3.13+, which honours the process's affinity),
    else `os.cpu_count`, the machine's."""
    count = getattr(os, "process_cpu_count", os.cpu_count)()
    return max(1, (count or 1) // 2)


@dataclass(frozen=True)
class Summary:
    """What one job ran: every label it planned, each label's outcome, a reason for any of them,
    its transcript and how long it took by its own clock."""
    planned: tuple[str, ...]
    outcomes: Mapping[str, Outcome]
    reasons: Mapping[str, str]
    transcript: str
    elapsed_s: float


def write_summary(path: Path, summary: Summary) -> None:
    """The summary as the child's last act. Written beside and renamed over, so a parent never
    reads half a document."""
    doc = {"format": SUMMARY_FORMAT, "version": SUMMARY_VERSION,
           "planned": list(summary.planned), "outcomes": dict(summary.outcomes),
           "reasons": dict(summary.reasons), "transcript": summary.transcript,
           "elapsed_s": summary.elapsed_s}
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(part, path)


def _strings(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _string_map(value: object) -> TypeGuard[dict[str, str]]:
    return isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def read_summary(path: Path) -> Summary:
    """A summary, or ValueError naming what is wrong with it: not JSON, another format or
    version, a field missing or of the wrong type, an outcome or a reason for a label nobody
    planned, a planned label with no outcome, or an outcome outside OK, FAIL and BLOCKED."""
    doc: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != SUMMARY_FORMAT:
        raise ValueError(f"{path} is not a {SUMMARY_FORMAT} document")
    if doc.get("version") != SUMMARY_VERSION:
        raise ValueError(f"{path} is version {doc.get('version')!r}, this reads {SUMMARY_VERSION}")
    planned, outcomes, reasons = doc.get("planned"), doc.get("outcomes"), doc.get("reasons")
    elapsed = doc.get("elapsed_s")
    if not (_strings(planned) and _string_map(outcomes) and _string_map(reasons)
            and isinstance(doc.get("transcript"), str)
            and isinstance(elapsed, int | float) and not isinstance(elapsed, bool)
            and math.isfinite(elapsed)):
        raise ValueError(f"{path} has a field missing or of the wrong type")
    if set(outcomes) != set(planned):
        raise ValueError(f"{path} judges {sorted(set(outcomes) ^ set(planned))} against its plan")
    if stray := sorted(set(reasons) - set(planned)):
        raise ValueError(f"{path} gives reasons for {stray}, which it never planned")
    if bad := sorted({v for v in outcomes.values() if v not in OUTCOMES}):
        raise ValueError(f"{path} carries outcomes {bad}")
    return Summary(tuple(planned), cast(dict[str, Outcome], outcomes), dict(reasons),
                   doc["transcript"],
                   float(elapsed))


@dataclass(frozen=True)
class Job:
    """One job: its name (the stem of its log and summary files), the argv that runs it, what
    it adds to the environment, and the labels the parent expects it to judge."""
    name: str
    argv: Sequence[str]
    planned: tuple[str, ...] = field(kw_only=True)
    env: Mapping[str, str] = field(default_factory=dict, kw_only=True)


@dataclass
class JobResult:
    job: Job
    #: None when the child was never started.
    rc: int | None
    log: Path
    #: By the parent's clock, from the start to the exit.
    elapsed_s: float
    summary: Summary | None
    #: Why this job's labels FAIL whatever its summary says; empty when they stand as declared.
    failed_why: str = ""

    def outcomes(self) -> dict[str, Outcome]:
        if self.failed_why or self.summary is None:
            return {label: "FAIL" for label in self.job.planned}
        return dict(self.summary.outcomes)

    def reasons(self) -> dict[str, str]:
        if self.failed_why or self.summary is None:
            return {label: self.failed_why for label in self.job.planned}
        return dict(self.summary.reasons)


@dataclass
class PoolResult:
    #: In the jobs' declared order, whatever order they ended in.
    results: list[JobResult]
    #: Why the merge cannot be believed; empty when it can.
    invalid: str = ""
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)


def _check_jobs(jobs: Sequence[Job], workers: int) -> None:
    if not jobs:
        raise ValueError("no job to run")
    if workers < 1:
        raise ValueError(f"workers is {workers}; at least one runs the jobs")
    if bad := [j.name for j in jobs if not _JOB_NAME.fullmatch(j.name)]:
        raise ValueError(f"job names must be one plain word of letters, digits, _ and -: {bad}")
    folded = [j.name.casefold() for j in jobs]
    if len(set(folded)) != len(folded):
        raise ValueError(f"two jobs share a name, case aside: "
                         f"{sorted(j.name for j in jobs if folded.count(j.name.casefold()) > 1)}")
    if empty := [j.name for j in jobs if not j.planned]:
        raise ValueError(f"jobs that plan no label could never fail: {empty}")
    labels = [label for j in jobs for label in j.planned]
    if len(set(labels)) != len(labels):
        raise ValueError(f"labels planned twice: "
                         f"{sorted({x for x in labels if labels.count(x) > 1})}")


class _Children:
    """The children alive now, and the stop that ends them: once stopping, no new one starts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: set[subprocess.Popen[bytes]] = set()
        self._stopping = False

    def start(self, argv: Sequence[str], env: dict[str, str],
              out: IO[bytes]) -> subprocess.Popen[bytes] | None:
        with self._lock:
            if self._stopping:
                return None
            if _RESTORE_SIGNALS and shutil.which(argv[0], path=env.get("PATH")) is None:
                # What the trampoline's exec would fail on, refused here before it, and told apart
                # by what is on disk: a path that is there and may not be run is not "no program".
                if os.sep in argv[0] and os.path.lexists(argv[0]):
                    raise PermissionError(f"{argv[0]!r} is not executable")
                raise FileNotFoundError(f"no program {argv[0]!r}")
            proc = subprocess.Popen([*_RESTORE_SIGNALS, *argv], env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=subprocess.STDOUT, **_OWN_GROUP)
            self._live.add(proc)
            return proc

    def ended(self, proc: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._live.discard(proc)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            live = list(self._live)
        for proc in live:
            if sys.platform == "win32":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGINT)
        deadline = time.monotonic() + STOP_GRACE_S
        try:
            for proc in live:
                try:
                    proc.wait(max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()
        except BaseException:
            # A SECOND INTERRUPT INSIDE THE GRACE: nobody is waiting for a clean end any more.
            for proc in live:
                proc.kill()
            raise


def _run_job(job: Job, out_dir: Path, summary_var: str, children: _Children) -> JobResult:
    log, summary_path = out_dir / f"{job.name}.log", out_dir / f"{job.name}.json"
    # A SUMMARY LEFT BY AN EARLIER RUN in the same directory would be read as this child's.
    summary_path.unlink(missing_ok=True)
    summary_path.with_name(summary_path.name + ".part").unlink(missing_ok=True)
    env = {**os.environ, **_CHILD_ENV, **job.env, summary_var: str(summary_path)}
    began = time.monotonic()
    with log.open("wb") as out:
        try:
            proc = children.start(job.argv, env, out)
        except OSError as e:
            return JobResult(job, None, log, 0.0, None, f"could not start {job.argv[0]!r}: {e}")
        if proc is None:
            return JobResult(job, None, log, 0.0, None, "not started: the pool was stopping")
        try:
            rc = proc.wait()
        finally:
            children.ended(proc)
    elapsed = time.monotonic() - began
    try:
        summary = read_summary(summary_path)
    except (OSError, ValueError) as e:
        return JobResult(job, rc, log, elapsed, None,
                         f"child exited rc={rc} without its summary ({e}): {log}")
    if (planned := set(summary.planned)) != set(job.planned):
        return JobResult(job, rc, log, elapsed, summary,
                         f"its summary planned {sorted(planned - set(job.planned))} and not "
                         f"{sorted(set(job.planned) - planned)}: {log}")
    return JobResult(job, rc, log, elapsed, summary)


def run_pool(jobs: Sequence[Job], workers: int, out_dir: Path, summary_var: str,
             on_done: Callable[[JobResult], None] | None = None) -> PoolResult:
    """Run `jobs`, at most `workers` at once, taken in declared order; each child finds the path
    its summary goes to in `summary_var`. `on_done` sees each result as its job ends, from a
    worker thread, one call at a time; if it raises, the pool stops as if interrupted. Refused
    with ValueError before anything starts: no job, `workers` below one, a name that is not one
    plain word or that two jobs share case aside, a job planning no label, or a label planned
    twice."""
    _check_jobs(jobs, workers)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    children, report = _Children(), threading.Lock()

    def run_and_report(job: Job) -> JobResult:
        result = _run_job(job, out_dir, summary_var, children)
        if on_done is not None:
            with report:
                on_done(result)
        return result

    pool = ThreadPoolExecutor(max_workers=workers)
    futures: list[Future[JobResult]] = []
    try:
        futures = [pool.submit(run_and_report, job) for job in jobs]
        # WAITED ON AS A SET, not in declared order: in order, a job whose report raised would
        # sit unseen behind a slow one still running.
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=POLL_INTERVAL_S, return_when=FIRST_EXCEPTION)
            for f in done:
                if (e := f.exception()) is not None:
                    raise e
        results = [f.result() for f in futures]
    except BaseException:
        for f in futures:
            f.cancel()
        children.stop()
        raise
    finally:
        pool.shutdown(wait=True)
    merged = PoolResult(results)
    for r in results:
        if r.summary is not None and r.failed_why:
            merged.invalid += f"{'; ' if merged.invalid else ''}job {r.job.name} {r.failed_why}"
        merged.outcomes.update(r.outcomes())
        merged.reasons.update(r.reasons())
    return merged
