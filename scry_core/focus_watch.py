"""Whether a run took the owner's focus: the frontmost application, sampled while the run goes.

A live tier is only bearable beside somebody working if nothing it launches comes to the front,
and nothing in the run can say that it did: an emulator activated behind the run's back answers
every tool normally. So the question is put from outside, on a clock:

    with focus_watch.FocusWatch(tsv) as watch:
        ...                                   # the run
    v = focus_watch.judge(watch.samples, {"dosbox-x"}, start_ms=t0, end_ms=t1)

`v.status` is `CLEAN` (no sample had one of `names` in front), `TOOK_FOCUS` (`v.sample` is the
first that did) or `INVALID`: the window holds no sample, a stretch of it went unsampled for
longer than `MAX_GAP_MS`, or a sample could not be taken. A theft seen is reported over any
blindness elsewhere in the window; short of one, an instrument that was blind for part of the
run clears nothing. A stay in front shorter than one sampling period can fall between two
samples, so this sees an emulator that took the focus and kept it, not a flicker.

THE INSTRUMENT IS SYSTEM EVENTS, asked through `osascript` on every sample, a separate process
each time, rather than `NSWorkspace` inside this one, whose answer was observed to stay at
whatever was in front when the process started. It needs the Automation permission for System
Events, and without it every sample is an ERROR. Each sample also records the host pointer,
for whoever reads a failed run's TSV, and never judges it: the owner's own hand moves it.

`exclude` takes the stretches a run takes the focus BY DESIGN (a menu clicked through the
emulator's window), so a section that has to come to the front is named, not hidden.

THE CONTROL IS THE CALLER'S, in the same harness: one start that must be judged `TOOK_FOCUS`
over its own window and one that must be `CLEAN`, before the run's own verdict is believed.

The samples go to a TSV as they are taken, `epoch_ms<TAB>app<TAB>pid<TAB>x,y` or
`epoch_ms<TAB>ERROR<TAB><why>`, so a run that dies keeps its record. macOS only: anywhere else
every sample is an ERROR, so every verdict is INVALID.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, TextIO

# The pause between samples; each one also spends an osascript call, so the period is longer.
INTERVAL_S = 0.25
# A System Events that has not answered in this long is a sample that failed, not a slow one.
OSASCRIPT_TIMEOUT_S = 5.0
# Longer than this between two samples, or between a window's edge and its nearest sample, and
# the stretch was not watched: several periods, so a slow osascript call is not blindness.
MAX_GAP_MS = 2500
FRONT_SCRIPT = [
    "-e", 'tell application "System Events" to set p to first process whose frontmost is true',
    "-e", 'tell application "System Events" to return (name of p) & tab & (unix id of p)']
_FIELD_BREAKS = re.compile(r"[\t\r\n\v\f\x1c-\x1e\x85  ]")

Status = Literal["CLEAN", "TOOK_FOCUS", "INVALID"]


def _field(text: str) -> str:
    """A TSV field: no tab, and nothing `splitlines` would break a record on."""
    return _FIELD_BREAKS.sub(" ", text)


@dataclass(frozen=True)
class Sample:
    epoch_ms: int
    app: str = ""
    pid: int | None = None
    pointer: tuple[int, int] | None = None
    error: str = ""

    def line(self) -> str:
        if self.error:
            return f"{self.epoch_ms}\tERROR\t{_field(self.error)}"
        pid = "" if self.pid is None else str(self.pid)
        where = "" if self.pointer is None else f"{self.pointer[0]},{self.pointer[1]}"
        return f"{self.epoch_ms}\t{_field(self.app)}\t{pid}\t{where}"


def parse(line: str) -> Sample:
    """One TSV line back into its sample; a line in neither shape is ValueError."""
    fields = line.rstrip("\n").split("\t")
    epoch_ms = int(fields[0])
    if len(fields) == 3 and fields[1] == "ERROR":
        return Sample(epoch_ms, error=fields[2])
    if len(fields) != 4:
        raise ValueError(f"not a focus_watch sample: {line!r}")
    pointer = None
    if fields[3]:
        x, y = fields[3].split(",")
        pointer = (int(x), int(y))
    return Sample(epoch_ms, fields[1], int(fields[2]) if fields[2] else None, pointer)


def load(path: Path) -> list[Sample]:
    return [parse(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


@functools.cache
def _graphics() -> tuple[ctypes.CDLL, ctypes.CDLL] | None:
    """CoreGraphics and CoreFoundation, typed once, or None where they are not there."""
    graphics = ctypes.util.find_library("CoreGraphics")
    foundation = ctypes.util.find_library("CoreFoundation")
    if graphics is None or foundation is None:
        return None
    cg, cf = ctypes.CDLL(graphics), ctypes.CDLL(foundation)
    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = _Point
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    return cg, cf


def _pointer() -> tuple[int, int] | None:
    """The host pointer, read off a fresh event, or None where it cannot be asked."""
    libs = _graphics()
    if libs is None:
        return None
    cg, cf = libs
    event = cg.CGEventCreate(None)
    if not event:
        return None
    try:
        at = cg.CGEventGetLocation(event)
    finally:
        cf.CFRelease(event)
    return round(at.x), round(at.y)


def _now_ms() -> int:
    return int(time.time() * 1000)


def sample_host() -> Sample:
    """One sample of this host: who is in front, and where the pointer is. STAMPED AT THE
    MIDDLE of the System Events call, the instant its answer is closest to describing, so a
    window's edge does not take a sample that saw the moment after it."""
    if sys.platform != "darwin":
        return Sample(_now_ms(), error=f"the frontmost application is read on macOS only, not "
                                       f"{sys.platform}")
    asked = _now_ms()
    try:
        run = subprocess.run(["osascript", *FRONT_SCRIPT], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=OSASCRIPT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Sample(_now_ms(), error=f"osascript did not answer: {e}")
    stamp = (asked + _now_ms()) // 2
    app, _, pid = run.stdout.strip().partition("\t")
    if run.returncode != 0 or not pid.isdigit():
        why = run.stderr.strip() or run.stdout.strip() or f"rc {run.returncode}"
        return Sample(stamp, error=f"System Events did not name the frontmost process: {why}")
    return Sample(stamp, app, int(pid), _pointer())


class FocusWatch:
    """Samples on a thread of its own from `__enter__` to `__exit__`, each one appended to
    `samples` and written to `path` as it is taken. `sample` is the seam a test hands its own
    sampler through. A sampler that RAISES is recorded as an ERROR sample and sampling goes
    on, so the verdict says INVALID rather than judging the samples before it; a record that
    cannot be written stops the thread and re-raises at `__exit__`."""

    def __init__(self, path: Path, *, interval_s: float = INTERVAL_S,
                 sample: Callable[[], Sample] = sample_host) -> None:
        self.path = path
        self.samples: list[Sample] = []
        self._interval_s = interval_s
        self._sample = sample
        self._stop = threading.Event()
        self._failure: BaseException | None = None

    def _take(self) -> Sample:
        try:
            return self._sample()
        except Exception as e:  # any failure of the instrument is a sample it could not take
            return Sample(_now_ms(), error=f"the sampler raised {type(e).__name__}: {e}")

    def _run(self, out: TextIO) -> None:
        try:
            while True:
                taken = self._take()
                self.samples.append(taken)
                out.write(taken.line() + "\n")
                out.flush()
                if self._stop.wait(self._interval_s):
                    return
        except BaseException as e:
            self._failure = e

    def __enter__(self) -> FocusWatch:
        # OPENED HERE, not on the thread: a path that cannot be written refuses the run
        # before it starts.
        self._out = self.path.open("w", encoding="utf-8")
        self._thread = threading.Thread(target=self._run, args=(self._out,),
                                        name="focus_watch", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self._stop.set()
        self._thread.join()
        self._out.close()
        if self._failure is not None and exc is None:
            raise self._failure


@dataclass(frozen=True)
class Verdict:
    status: Status
    examined: int
    reason: str
    # The sample that decided: the first theft (TOOK_FOCUS), the one the instrument could not
    # take (INVALID), or None.
    sample: Sample | None = None
    distinct_pointers: int = 0


def _gap(chosen: list[Sample], start_ms: int | None, end_ms: int | None,
         exclude: Collection[tuple[int, int]]) -> str:
    """Where the judged window went unwatched for longer than `MAX_GAP_MS`, or "" if nowhere.
    An excluded stretch is not judged, so its edges count as watched and its inside as no gap."""
    edges = sorted({s.epoch_ms for s in chosen}
                   | ({start_ms} if start_ms is not None else set())
                   | ({end_ms} if end_ms is not None else set())
                   | {edge for window in exclude for edge in window
                      if (start_ms is None or edge >= start_ms)
                      and (end_ms is None or edge <= end_ms)})
    for a, b in zip(edges, edges[1:], strict=False):
        skipped = any(ea <= a and b <= eb for ea, eb in exclude)
        if not skipped and b - a > MAX_GAP_MS:
            return f"no sample between {a} and {b} ({b - a} ms, over {MAX_GAP_MS})"
    return ""


def judge(samples: list[Sample], names: Collection[str], *, start_ms: int | None = None,
          end_ms: int | None = None, exclude: Collection[tuple[int, int]] = ()) -> Verdict:
    """Judge the samples inside `[start_ms, end_ms]` and outside every `exclude` window: was any
    application in `names` in front? `names` is a collection of names, never one string, and
    never empty: either would match nothing and read as CLEAN (ValueError)."""
    if isinstance(names, str) or not names:
        raise ValueError(f"names is a non-empty collection of application names; got {names!r}")
    wanted = set(names)

    def inside(s: Sample) -> bool:
        return ((start_ms is None or s.epoch_ms >= start_ms)
                and (end_ms is None or s.epoch_ms <= end_ms)
                and not any(a <= s.epoch_ms <= b for a, b in exclude))
    chosen = [s for s in samples if inside(s)]
    if not chosen:
        return Verdict("INVALID", 0, "no sample was taken inside the window, so nothing was "
                                     "examined")
    pointers = len({s.pointer for s in chosen if not s.error})
    took = next((s for s in chosen if not s.error and s.app in wanted), None)
    if took is not None:
        hits = sum(not s.error and s.app in wanted for s in chosen)
        return Verdict("TOOK_FOCUS", len(chosen),
                       f"{took.app} (pid {took.pid}) was in front in {hits} of {len(chosen)} "
                       f"samples, first at {took.epoch_ms}", took, pointers)
    broken = next((s for s in chosen if s.error), None)
    if broken is not None:
        return Verdict("INVALID", len(chosen), f"a sample could not be taken: {broken.error}",
                       broken, pointers)
    gap = _gap(chosen, start_ms, end_ms, exclude)
    if gap:
        return Verdict("INVALID", len(chosen), f"the window was not watched throughout: {gap}",
                       None, pointers)
    return Verdict("CLEAN", len(chosen), f"none of {sorted(wanted)} was in front in "
                                         f"{len(chosen)} samples", None, pointers)
