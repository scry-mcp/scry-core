"""Run a live tier's independent jobs as parallel child processes, and merge what each declares.

Each job is a child process of the caller's own script; it writes a SUMMARY, a JSON document in
the format this module writes and reads, and the parent merges the summaries:

    jobs = [live_pool.Job("A", [sys.executable, script], env={"X_LIVE_SECTIONS": "A"},
                          planned=labels_of_a)]
    result = live_pool.run_pool(jobs, live_pool.default_workers(), out_dir, "X_LIVE_SUMMARY")

The summary is the interface, never the child's printed lines. A job whose child leaves no
readable summary, or could not be started, FAILS every label it planned; a summary that plans
other labels than its job's makes the result INVALID and that job's labels FAIL. The exit code is
reported beside the summary and judged by the caller.

Interrupted, every child is sent SIGINT (terminated outright on Windows, where anything it
launched is left for its owner) and killed after `STOP_GRACE_S`, or at once on a second
interrupt. Each child runs in its own process group, so a Ctrl-C at the terminal reaches the
parent alone and the child gets exactly one interrupt; the price is that a parent killed outright
does not reach its children.
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
# A bare lock wait on Windows lets no Ctrl-C through, a timed one does.
POLL_INTERVAL_S = 0.5
STOP_GRACE_S = 10.0
# A job name is a file stem, so never a path; compared case-folded like macOS and Windows names.
_JOB_NAME = re.compile(r"[A-Za-z0-9_-]+")
# Unbuffered so a stopped child keeps its last log lines; UTF-8 so a label prints under a Windows
# code page.
_CHILD_ENV = {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
_OWN_GROUP: dict[str, Any] = (
    {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    if sys.platform == "win32" else {"process_group": 0})
# A background pool has SIGINT ignored, and ignored signals and blocked masks survive exec, so a
# Python child would never install its cleanup handler. On POSIX each child starts through this
# isolated (`-I`) trampoline, which restores SIGINT, SIGPIPE and SIGXFSZ (a Python ignores the
# last two at startup) and unblocks SIGINT. A `preexec_fn` is unsafe beside the pool's threads.
_RESTORE_SIGNALS: tuple[str, ...] = () if sys.platform == "win32" else (
    sys.executable, "-I", "-c",
    "import os, signal, sys\n"
    "for name in ('SIGINT', 'SIGPIPE', 'SIGXFSZ'):\n"
    "    signal.signal(getattr(signal, name), signal.SIG_DFL)\n"
    "signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})\n"
    "os.execvp(sys.argv[1], sys.argv[1:])")


def default_workers() -> int:
    """Half the CPUs available (affinity-aware where Python has it), at least one."""
    count = getattr(os, "process_cpu_count", os.cpu_count)()
    return max(1, (count or 1) // 2)


#: The line a plan prints for a cell its selection can never judge.
CANNOT_BE_JUDGED = "cannot be judged in this selection"


def cannot_be_judged(spanning: Sequence[tuple[str, Sequence[str], bool]]) -> list[tuple[str, str]]:
    """The cells a selection plans and can never judge, as `(label, why)`: those of each spanning
    section `(name, labels, has_company)` whose verdict judges what the other sections do, when
    `has_company` (decided by the caller, whose sections it is) says none is chosen beside it."""
    return [(label, f"[{name}] judges what the other sections do, and none is chosen")
            for name, labels, has_company in spanning if not has_company for label in labels]


def cannot_be_judged_line(label: str, why: str) -> str:
    """The plan's line for one such cell."""
    return f"{CANNOT_BE_JUDGED}: {label}: {why}"


@dataclass(frozen=True)
class Summary:
    """What one job ran: its planned labels, each one's outcome and reason, and its transcript."""
    planned: tuple[str, ...]
    outcomes: Mapping[str, Outcome]
    reasons: Mapping[str, str]
    transcript: str
    elapsed_s: float


def write_summary(path: Path, summary: Summary) -> None:
    """Write the summary beside and rename it over, so a parent never reads half a document."""
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
    """Read a summary, or raise ValueError naming what is wrong with it."""
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
    """One job: its name, its argv, its added environment and the labels it must judge."""
    name: str
    argv: Sequence[str]
    planned: tuple[str, ...] = field(kw_only=True)
    env: Mapping[str, str] = field(default_factory=dict, kw_only=True)


@dataclass
class JobResult:
    job: Job
    rc: int | None
    log: Path
    elapsed_s: float
    summary: Summary | None
    #: Why this job's labels FAIL whatever its summary says; empty when they stand.
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
    results: list[JobResult]
    #: Why the merge cannot be believed.
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
    """The live children and the stop that ends them; once stopping, none starts."""

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
                # The trampoline's exec would fail here; tell "not executable" from "no program".
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
            # A second interrupt inside the grace: nobody waits for a clean end any more.
            for proc in live:
                proc.kill()
            raise


def _run_job(job: Job, out_dir: Path, summary_var: str, children: _Children) -> JobResult:
    log, summary_path = out_dir / f"{job.name}.log", out_dir / f"{job.name}.json"
    # A summary left by an earlier run would be read as this child's.
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
    """Run `jobs`, at most `workers` at once; each child finds its summary path in `summary_var`.

    `on_done` sees each result from a worker thread, one call at a time; if it raises, the pool
    stops as if interrupted. Raises ValueError before anything starts on a bad job set.
    """
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
        # As a set, not in order: else a raised report hides behind a slower job.
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
