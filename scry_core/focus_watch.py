"""Whether a run took the owner's focus: the frontmost application, sampled while the run goes.

A live tier is only bearable beside somebody working if nothing it launches comes to the front,
and nothing in the run can say that it did: an emulator activated behind the run's back answers
every tool normally. So the question is put from outside, on a clock:

    with focus_watch.FocusWatch(tsv) as watch:
        ...                                   # the run
    v = focus_watch.judge(watch.samples, {"dosbox-x"}, start_ms=t0, end_ms=t1)

`v.status` is `CLEAN` (no sample had one of `names` in front, and no display's Space moved),
`TOOK_FOCUS` (`v.sample` is the first that had one in front), `SPACE_CHANGED` (`v.sample` is the
first whose displays' current Spaces differ from the window's first sample's) or `INVALID`:
the window holds no sample, a stretch of it went unsampled for longer than `MAX_GAP_MS`, or a
sample could not be taken. The focus taken, or a Space moved, is reported over a sample that
failed, a stretch unsampled or a later change of displays; short of one, an instrument that was
blind for part of the run clears nothing. A stay in front shorter than one sampling period can
fall between two samples, so this sees an emulator that took the focus and kept it, not a
flicker; the same holds for a Space that moves and comes back inside one period. A Space move
is not tied to any process, so the caller reads SPACE_CHANGED as a move nobody can be named for
(the owner may have made it), never as a theft proven; a change in the number of displays,
short of a move before it, makes the window INVALID.

THE INSTRUMENT IS SYSTEM EVENTS, asked through `osascript` on every sample, a separate process
each time, rather than `NSWorkspace` inside this one, whose answer was observed to stay at
whatever was in front when the process started. It needs the Automation permission for System
Events, and without it every sample is an ERROR. Each sample also records the host pointer,
for whoever reads a failed run's TSV, and never judges it: the owner's own hand moves it. And
each records the current Space of every display (CoreGraphics' managed-display list, the one
reading the system has of it), because a run can move the owner to another Space without
anything of its own coming to the front; a reading that fails is an ERROR sample.

`exclude` takes the stretches a run takes the focus BY DESIGN (a menu clicked through the
emulator's window), so a section that has to come to the front is named, not hidden.

THE CONTROL is `control`, taken in the same harness as the run: one start that must be judged
`TOOK_FOCUS` over its own window, one that must be `CLEAN`, and the owner's Space moved and put
back by `move_space`, which must be `SPACE_CHANGED`. Only then does `verdict` judge the run, and
a window it cannot judge is BLOCKED, never green and never the server's FAIL. The Space control
presses keys, so it also needs the Accessibility permission.

The samples go to a TSV as they are taken, `epoch_ms<TAB>app<TAB>pid<TAB>x,y<TAB>space,space`
or `epoch_ms<TAB>ERROR<TAB><why>`, so a run that dies keeps its record. macOS only: anywhere else
every sample is an ERROR, so every verdict is INVALID.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import functools
import plistlib
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol, TextIO

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

Status = Literal["CLEAN", "TOOK_FOCUS", "SPACE_CHANGED", "INVALID"]


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
    # The current Space of each display, in the system's display order.
    spaces: tuple[int, ...] = ()

    def line(self) -> str:
        if self.error:
            return f"{self.epoch_ms}\tERROR\t{_field(self.error)}"
        pid = "" if self.pid is None else str(self.pid)
        where = "" if self.pointer is None else f"{self.pointer[0]},{self.pointer[1]}"
        spaces = ",".join(str(n) for n in self.spaces)
        return f"{self.epoch_ms}\t{_field(self.app)}\t{pid}\t{where}\t{spaces}"


def parse(line: str) -> Sample:
    """One TSV line back into its sample, a record with no Spaces field included (one written
    before Spaces were read); a line in none of those shapes is ValueError."""
    fields = line.rstrip("\n").split("\t")
    epoch_ms = int(fields[0])
    if len(fields) == 3 and fields[1] == "ERROR":
        return Sample(epoch_ms, error=fields[2])
    if len(fields) not in (4, 5):
        raise ValueError(f"not a focus_watch sample: {line!r}")
    pointer = None
    if fields[3]:
        x, y = fields[3].split(",")
        pointer = (int(x), int(y))
    spaces = tuple(int(n) for n in fields[4].split(",")) if len(fields) == 5 and fields[4] else ()
    return Sample(epoch_ms, fields[1], int(fields[2]) if fields[2] else None, pointer,
                  spaces=spaces)


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
    cg.CGSMainConnectionID.restype = ctypes.c_int
    cg.CGSCopyManagedDisplaySpaces.restype = ctypes.c_void_p
    cg.CGSCopyManagedDisplaySpaces.argtypes = [ctypes.c_int]
    cf.CFPropertyListCreateData.restype = ctypes.c_void_p
    cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                            ctypes.c_long, ctypes.c_void_p]
    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
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


# CFPropertyListCreateData's format for a binary plist, which `plistlib` reads.
_BINARY_PLIST = 200


def _spaces() -> tuple[int, ...] | None:
    """The current Space of every display, or None where it cannot be read. The list is the
    window server's own (`CGSCopyManagedDisplaySpaces`, private but the one reading there is),
    serialised to a plist so no CoreFoundation type has to be walked by hand."""
    libs = _graphics()
    if libs is None:
        return None
    cg, cf = libs
    managed = cg.CGSCopyManagedDisplaySpaces(cg.CGSMainConnectionID())
    if not managed:
        return None
    try:
        data = cf.CFPropertyListCreateData(None, managed, _BINARY_PLIST, 0, None)
        if not data:
            return None
        try:
            raw = ctypes.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))
        finally:
            cf.CFRelease(data)
    finally:
        cf.CFRelease(managed)
    try:
        return tuple(int(d["Current Space"]["ManagedSpaceID"]) for d in plistlib.loads(raw))
    except (plistlib.InvalidFileException, KeyError, TypeError, ValueError):
        return None


def now_ms() -> int:
    """The epoch in milliseconds, the clock every sample and window here is stamped on."""
    return int(time.time() * 1000)


#: Whether this host is macOS, read once into a name: a type checker narrows `sys.platform` and
#: would call the macOS half unreachable on any other host.
_MACOS = sys.platform == "darwin"


def sample_host() -> Sample:
    """One sample of this host: who is in front, and where the pointer is. STAMPED AT THE
    MIDDLE of the System Events call, the instant its answer is closest to describing, so a
    window's edge does not take a sample that saw the moment after it."""
    if not _MACOS:
        return Sample(now_ms(), error=f"the frontmost application is read on macOS only, not "
                                       f"{sys.platform}")
    asked = now_ms()
    try:
        run = subprocess.run(["osascript", *FRONT_SCRIPT], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=OSASCRIPT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Sample(now_ms(), error=f"osascript did not answer: {e}")
    stamp = (asked + now_ms()) // 2
    app, _, pid = run.stdout.strip().partition("\t")
    if run.returncode != 0 or not pid.isdigit():
        why = run.stderr.strip() or run.stdout.strip() or f"rc {run.returncode}"
        return Sample(stamp, error=f"System Events did not name the frontmost process: {why}")
    spaces = _spaces()
    if not spaces:
        return Sample(stamp, error="the displays' current Spaces could not be read")
    return Sample(stamp, app, int(pid), _pointer(), spaces=spaces)


# THE SPACE CONTROL'S KEYS: Mission Control's Ctrl+Right and Ctrl+Left, as key codes.
KEY_RIGHT, KEY_LEFT = 124, 123
SPACE_KEYS = (KEY_RIGHT, KEY_LEFT)
SPACE_SETTLE_S = 1.5


def _press(key: int) -> str:
    """One Mission Control shortcut through System Events: "" when it went, else why not."""
    try:
        run = subprocess.run(["osascript", "-e", f'tell application "System Events" to key code '
                              f"{key} using control down"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=OSASCRIPT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"osascript did not answer: {e}"
    if run.returncode != 0:
        return f"System Events refused the keystroke: {run.stderr.strip() or run.returncode}"
    return ""


def move_space(settle_s: float = SPACE_SETTLE_S) -> tuple[int, int, str]:
    """The owner's Space moved one along and back, by System Events, for a CONTROL that must see
    SPACE_CHANGED over the window returned (epoch ms). Right then Left, or Left then Right when
    there is no Space to the right. Whether a key moved the owner is read off the Spaces, never
    off the keystroke's own answer, since one that timed out may still have acted; so the way
    back is pressed whenever the owner moved, and the owner is checked to end where they began.
    The third value is "" when all of that held, else what did not (Spaces that cannot be read,
    which presses nothing; a keystroke refused, which needs Accessibility for this process; no
    Space to move to; the owner left elsewhere): the control then fails saying so, which is its
    job, and never passes for a watch that cannot see."""
    began = now_ms()
    before = _spaces()
    if not before:
        return began, now_ms(), "the displays' Spaces could not be read, so no key was pressed"
    whys: list[str] = []
    back = None
    for go, ret in (SPACE_KEYS, SPACE_KEYS[::-1]):
        whys.append(_press(go))
        time.sleep(settle_s)
        now = _spaces()
        if now is None:
            whys.append("the displays' Spaces could not be read after a key")
            break
        if now != before:
            back = ret
            break
        if whys[-1]:
            break
    if back is not None:
        whys.append(_press(back))
        time.sleep(settle_s)
    elif not any(whys):
        whys.append("no other Space to move to")
    after = _spaces()
    if after != before:
        whys.append(f"the owner was left on {after}, not {before}")
    return began, now_ms(), "; ".join(w for w in whys if w)


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
            return Sample(now_ms(), error=f"the sampler raised {type(e).__name__}: {e}")

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
    # The sample that decided: the first theft (TOOK_FOCUS), the first move (SPACE_CHANGED), the
    # one the instrument could not take or whose displays changed (INVALID), or None.
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
    read = [s for s in chosen if not s.error]
    # A move between readings of the same displays, reported over any blindness after it.
    moved = next((s for s in read if len(s.spaces) == len(read[0].spaces)
                  and s.spaces != read[0].spaces), None)
    if moved is not None:
        return Verdict("SPACE_CHANGED", len(chosen),
                       f"the displays' Spaces went from {list(read[0].spaces)} to "
                       f"{list(moved.spaces)} at {moved.epoch_ms}", moved, pointers)
    if any(not s.spaces for s in read) and any(s.spaces for s in read):
        return Verdict("INVALID", len(chosen), "some samples carry no Space reading, so a move "
                       "between them cannot be judged", None, pointers)
    resized = next((s for s in read if len(s.spaces) != len(read[0].spaces)), None)
    if resized is not None:
        return Verdict("INVALID", len(chosen), f"the displays changed from {len(read[0].spaces)} "
                       f"to {len(resized.spaces)} at {resized.epoch_ms}, so a Space move cannot "
                       f"be judged across it", resized, pointers)
    broken = next((s for s in chosen if s.error), None)
    if broken is not None:
        return Verdict("INVALID", len(chosen), f"a sample could not be taken: {broken.error}",
                       broken, pointers)
    gap = _gap(chosen, start_ms, end_ms, exclude)
    if gap:
        return Verdict("INVALID", len(chosen), f"the window was not watched throughout: {gap}",
                       None, pointers)
    unread = "" if read and read[0].spaces else " (no Space was recorded)"
    return Verdict("CLEAN", len(chosen), f"none of {sorted(wanted)} was in front in "
                                         f"{len(chosen)} samples{unread}", None, pointers)


# THE CONTROL AND THE VERDICT a live section takes the watch through, the same flow on every
# server: a control proves the watch sees what it must (a start in front, none behind, a Space
# moved on purpose) before its samples may clear anything, and the verdict judges the run after
# it. Each outcome is a cell's: PASS, FAIL, or BLOCKED when the window could not be judged at all.
#: How long each control start is held in front, or behind, for the watch to sample it.
HOLD_S = 4.0
#: Shorter than this, a judged window says too little about a run to be its verdict.
MIN_WINDOW_MS = 60_000

Outcome = Literal["PASS", "FAIL", "BLOCKED"]


class Watched(Protocol):
    """What the flow reads off a watch: its samples, its record, and its end."""

    samples: list[Sample]
    path: Path

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None: ...


@dataclass(frozen=True)
class Judged:
    status: Outcome
    reason: str


@dataclass(frozen=True)
class Control:
    front: Judged
    behind: Judged
    space: Judged
    # The end of the control, where the judged window opens; None when it did not hold.
    since: int | None


def control(watch: Watched, names: Collection[str],
            hold: Callable[[bool], tuple[int, int]]) -> Control:
    """The control over `watch`: `hold(background)` launches one start as asked and returns its
    window (epoch ms); then the owner's Space is moved and put back (`move_space`)."""
    front_w, behind_w = hold(False), hold(True)
    seen = judge(watch.samples, names, start_ms=front_w[0], end_ms=front_w[1])
    front = Judged("PASS" if seen.status == "TOOK_FOCUS" else "FAIL", seen.reason)
    clean = judge(watch.samples, names, start_ms=behind_w[0], end_ms=behind_w[1])
    # A Space move names nobody (`verdict` says why), here as there.
    behind = Judged("BLOCKED" if clean.status == "SPACE_CHANGED"
                    else "PASS" if clean.status == "CLEAN" else "FAIL", clean.reason)
    began, ended, why = move_space()
    moved = judge(watch.samples, names, start_ms=began, end_ms=ended)
    space = Judged("PASS" if moved.status == "SPACE_CHANGED" and not why else "FAIL",
                   f"{why}; {moved.reason}" if why else moved.reason)
    held = all(o.status == "PASS" for o in (front, behind, space))
    return Control(front, behind, space, ended if held else None)


def verdict(watch: Watched, names: Collection[str], since: int | None, end_ms: int) -> Judged:
    """The run's verdict, the watch ended first: judged only after a control that held
    (`since`), over a window of at least `MIN_WINDOW_MS`."""
    watch.__exit__(None, None, None)
    record = f"record {watch.path}"
    if since is None:
        return Judged("BLOCKED", f"the control did not hold, so the watch clears nothing; {record}")
    if end_ms - since < MIN_WINDOW_MS:
        return Judged("BLOCKED", f"{end_ms - since} ms ran after the control, too little to "
                                 f"judge; {record}")
    v = judge(watch.samples, names, start_ms=since, end_ms=end_ms)
    if v.status == "INVALID":
        # THE INSTRUMENT, not the server: a sample it could not take, or a stretch unsampled.
        return Judged("BLOCKED", f"the watch cannot judge the run: {v.reason}; {record}")
    if v.status == "SPACE_CHANGED":
        # A SPACE MOVE NAMES NOBODY: the owner may have made it. Never green, never the
        # server's FAIL on that alone: the record is there to read.
        return Judged("BLOCKED", f"a Space moved and nothing names who moved it: {v.reason}; "
                                 f"{record}")
    return Judged("PASS" if v.status == "CLEAN" else "FAIL", f"{v.status}: {v.reason}; {record}")
