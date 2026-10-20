"""Whether a run took the owner's focus: the frontmost application, sampled while the run goes.

A live tier is only bearable beside somebody working if nothing it launches comes to the front,
and nothing in the run can say that it did: an emulator activated behind the run's back answers
every tool normally. So the question is put from outside, on a clock:

    with focus_watch.FocusWatch(tsv) as watch:
        ...                                   # the run
    v = focus_watch.judge(watch.samples, {"dosbox-x"}, start_ms=t0, end_ms=t1)

`v.status` is `CLEAN` (no sample had one of `names` in front, and no display's Space moved),
`TOOK_FOCUS` (`v.sample` is the first that had one in front), `SPACE_CHANGED` (`v.sample` is the
first whose displays' current Spaces differ from those of the first sample the window could
take) or `INVALID`: the window holds no sample it could take, a stretch of it went unsampled for
longer than `MAX_GAP_MS`, its samples change displays, or some carry a Space reading and others
none. A sample the instrument could not take (a process exiting under it is the common
one) is a stretch it did not see, so it counts as a gap and nothing more: one such sample among
many is a short blindness, and only a gap past the bound makes the window INVALID. The focus
taken, or a Space moved, is reported over a stretch unsampled or a later change of displays;
short of one, an instrument that was blind for part of the run clears nothing. A stay in front
shorter than one sampling period can fall between two samples, so this sees an emulator that
took the focus and kept it, not a flicker; the same holds for a Space that moves and comes back
inside one period. A Space move is not tied to any process: what a caller makes of that is
`scry_core.focus_gate`'s to say. Each display's Space is keyed by the display's own identifier,
so the same displays listed in another order are the same Spaces (`same_spaces`).

THE INSTRUMENT IS SYSTEM EVENTS, asked through `osascript` on every sample, a separate process
each time, rather than `NSWorkspace` inside this one, whose answer was observed to stay at
whatever was in front when the process started. It needs the Automation permission for System
Events, and without it every sample is an ERROR. Each sample also records the host pointer,
for whoever reads a failed run's TSV, and never judges it: the owner's own hand moves it. And
each records the current Space of every display (CoreGraphics' managed-display list, the one
reading the system has of it), because a run can move the owner to another Space without
anything of its own coming to the front; a reading that fails is an ERROR sample. The
CoreGraphics symbols that list is read through are private, so they are bound with a guard: a
host without them still gives samples, with no Space recorded, and says which symbol it lacks
(`spaces_missing`).

THE FLOW a live section takes the watch through (the control, the verdict) and the actuator that
moves the owner's Space for it are `scry_core.focus_gate`'s: this module observes and judges.

The samples go to a TSV as they are taken,
`epoch_ms<TAB>app<TAB>pid<TAB>x,y<TAB>display:space,display:space` or
`epoch_ms<TAB>ERROR<TAB><why>`, so a run that dies keeps its record. macOS only: anywhere else
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
from typing import Any, Literal, TextIO

# The pause between samples; each one also spends an osascript call, so the period is longer.
INTERVAL_S = 0.25
# A System Events that has not answered in this long is a sample that failed, not a slow one.
OSASCRIPT_TIMEOUT_S = 5.0
# Longer than this between two samples, or between a window's edge and its nearest sample, and
# the stretch was not watched: several periods, so a slow osascript call is not blindness.
MAX_GAP_MS = 2500
FRONT_SCRIPT = (
    'tell application "System Events" to set p to first process whose frontmost is true',
    'tell application "System Events" to return (name of p) & tab & (unix id of p)')
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
    # The current Space of each display, by the display's identifier, in the system's order.
    spaces: tuple[tuple[str, int], ...] = ()

    def line(self) -> str:
        if self.error:
            return f"{self.epoch_ms}\tERROR\t{_field(self.error)}"
        pid = "" if self.pid is None else str(self.pid)
        where = "" if self.pointer is None else f"{self.pointer[0]},{self.pointer[1]}"
        spaces = ",".join(f"{d}:{n}" for d, n in self.spaces)
        return f"{self.epoch_ms}\t{_field(self.app)}\t{pid}\t{where}\t{spaces}"


def _space(i: int, field: str) -> tuple[str, int]:
    """One `display:space` of a record; the bare-number form keys the display `#<position>`."""
    display, _, n = field.rpartition(":")
    return (display or f"#{i}", int(n))


def parse(line: str) -> Sample:
    """One TSV line back into its sample, a record with no Spaces field included; a line in none
    of those shapes is ValueError."""
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
    spaces = (tuple(_space(i, f) for i, f in enumerate(fields[4].split(",")))
              if len(fields) == 5 and fields[4] else ())
    return Sample(epoch_ms, fields[1], int(fields[2]) if fields[2] else None, pointer,
                  spaces=spaces)


def load(path: Path) -> list[Sample]:
    return [parse(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


#: The private CoreGraphics symbols a Space is read through.
SPACE_SYMBOLS = ("CGSMainConnectionID", "CGSCopyManagedDisplaySpaces")


def spaces_missing(cg: object | None = None) -> str:
    """The first of `SPACE_SYMBOLS` this host's CoreGraphics lacks, "" when it has them all (or
    has no CoreGraphics at all, which `spaces` answers by itself)."""
    if cg is None:
        libs = _graphics()
        if libs is None:
            return ""
        cg = libs[0]
    return next((name for name in SPACE_SYMBOLS if getattr(cg, name, None) is None), "")


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
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    # THE PRIVATE HALF, guarded: a host whose CoreGraphics lacks these is one with no Spaces to
    # read, said by `spaces_missing`, never an exception in the middle of a sample.
    if not spaces_missing(cg):
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


def plist_of(cf: ctypes.CDLL, ref: int) -> Any:
    """A CoreFoundation property list, released here, as `plistlib` reads it; None when it
    cannot be serialised or read. Serialised so no CoreFoundation type is walked by hand."""
    try:
        data = cf.CFPropertyListCreateData(None, ref, _BINARY_PLIST, 0, None)
        if not data:
            return None
        try:
            raw = ctypes.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))
        finally:
            cf.CFRelease(data)
    finally:
        cf.CFRelease(ref)
    try:
        return plistlib.loads(raw)
    except plistlib.InvalidFileException:
        return None


def windows() -> list[dict[str, Any]]:
    """Every window the window server lists, on screen or not, as CoreGraphics describes them;
    none where it cannot be asked."""
    libs = _graphics()
    if libs is None:
        return []
    cg, cf = libs
    listed = cg.CGWindowListCopyWindowInfo(0, 0)
    found = plist_of(cf, listed) if listed else None
    return found if isinstance(found, list) else []


def spaces() -> tuple[tuple[str, int], ...] | None:
    """The current Space of every display, keyed by its `Display Identifier`, or None where it
    cannot be read. The list is the window server's own (`CGSCopyManagedDisplaySpaces`, private
    but the one reading there is)."""
    listed = _managed()
    if listed is None:
        return None
    try:
        return tuple((str(d["Display Identifier"]), int(d["Current Space"]["ManagedSpaceID"]))
                     for d in listed)
    except (KeyError, TypeError, ValueError):
        return None


def _managed() -> list[Any] | None:
    """The window server's list of displays and their Spaces, or None where it cannot be read."""
    libs = _graphics()
    if libs is None or spaces_missing(libs[0]):
        return None
    cg, cf = libs
    managed = cg.CGSCopyManagedDisplaySpaces(cg.CGSMainConnectionID())
    listed = plist_of(cf, managed) if managed else None
    return listed if isinstance(listed, list) else None


def space_counts() -> tuple[int, ...] | None:
    """How many Spaces each display holds, or None where it cannot be read."""
    listed = _managed()
    if listed is None:
        return None
    try:
        return tuple(len(d["Spaces"]) for d in listed)
    except (KeyError, TypeError):
        return None


def same_spaces(a: tuple[tuple[str, int], ...], b: tuple[tuple[str, int], ...]) -> bool:
    """Whether two readings hold the same displays on the same Spaces, in whatever order."""
    return dict(a) == dict(b)


def osascript(*lines: str) -> subprocess.CompletedProcess[str] | str:
    """One `osascript` run of `lines` (each an `-e`), or why it did not answer: every question this
    instrument and the Space control put to System Events goes through here."""
    args = [arg for line in lines for arg in ("-e", line)]
    try:
        return subprocess.run(["osascript", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=OSASCRIPT_TIMEOUT_S,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"osascript did not answer: {e}"


def now_ms() -> int:
    """The epoch in milliseconds, the clock every sample and window here is stamped on."""
    return int(time.time() * 1000)


#: Whether this host is macOS, read once into a name: a type checker narrows `sys.platform` and
#: would call the macOS half unreachable on any other host.
_MACOS = sys.platform == "darwin"


def sample_host() -> Sample:
    """One sample of this host: who is in front, where the pointer is, and each display's Space
    (none on a host without the Space symbols). STAMPED AT THE
    MIDDLE of the System Events call, the instant its answer is closest to describing, so a
    window's edge does not take a sample that saw the moment after it."""
    if not _MACOS:
        return Sample(now_ms(), error=f"the frontmost application is read on macOS only, not "
                                       f"{sys.platform}")
    asked = now_ms()
    run = osascript(*FRONT_SCRIPT)
    if isinstance(run, str):
        return Sample(now_ms(), error=run)
    stamp = (asked + now_ms()) // 2
    app, _, pid = run.stdout.strip().partition("\t")
    if run.returncode != 0 or not pid.isdigit():
        why = run.stderr.strip() or run.stdout.strip() or f"rc {run.returncode}"
        return Sample(stamp, error=f"System Events did not name the frontmost process: {why}")
    if spaces_missing():
        return Sample(stamp, app, int(pid), _pointer())
    read = spaces()
    if not read:
        return Sample(stamp, error="the displays' current Spaces could not be read")
    return Sample(stamp, app, int(pid), _pointer(), spaces=read)


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


def _gap(seen: list[Sample], start_ms: int | None, end_ms: int | None) -> str:
    """Where the judged window went unwatched for longer than `MAX_GAP_MS`, or "" if nowhere:
    between the samples the instrument took, and from each edge to the nearest of them."""
    edges = sorted({s.epoch_ms for s in seen}
                   | ({start_ms} if start_ms is not None else set())
                   | ({end_ms} if end_ms is not None else set()))
    for a, b in zip(edges, edges[1:], strict=False):
        if b - a > MAX_GAP_MS:
            return f"no sample between {a} and {b} ({b - a} ms, over {MAX_GAP_MS})"
    return ""


def judge(samples: list[Sample], names: Collection[str], *, start_ms: int | None = None,
          end_ms: int | None = None) -> Verdict:
    """Judge the samples inside `[start_ms, end_ms]`: was any application in `names` in front,
    or did a Space move? `names` is a collection of names, never one string, and never empty:
    either would match nothing and read as CLEAN (ValueError)."""
    if isinstance(names, str) or not names:
        raise ValueError(f"names is a non-empty collection of application names; got {names!r}")
    wanted = set(names)
    chosen = [s for s in samples if (start_ms is None or s.epoch_ms >= start_ms)
              and (end_ms is None or s.epoch_ms <= end_ms)]
    if not chosen:
        return Verdict("INVALID", 0, "no sample was taken inside the window, so nothing was "
                                     "examined")
    read = [s for s in chosen if not s.error]
    if not read:
        return Verdict("INVALID", 0, f"no sample inside the window could be taken: "
                                     f"{chosen[0].error}", chosen[0])
    pointers = len({s.pointer for s in read})
    took = next((s for s in read if s.app in wanted), None)
    if took is not None:
        hits = sum(s.app in wanted for s in read)
        return Verdict("TOOK_FOCUS", len(read),
                       f"{took.app} (pid {took.pid}) was in front in {hits} of {len(read)} "
                       f"samples, first at {took.epoch_ms}", took, pointers)
    first = dict(read[0].spaces)

    def shown(sample: Sample) -> list[int]:
        return [n for _, n in sample.spaces]
    # A move between readings of the same displays, reported over any blindness after it.
    moved = next((s for s in read if dict(s.spaces).keys() == first.keys()
                  and not same_spaces(s.spaces, read[0].spaces)), None)
    if moved is not None:
        return Verdict("SPACE_CHANGED", len(read),
                       f"the displays' Spaces went from {shown(read[0])} to {shown(moved)} at "
                       f"{moved.epoch_ms}", moved, pointers)
    if any(not s.spaces for s in read) and any(s.spaces for s in read):
        return Verdict("INVALID", len(read), "some samples carry no Space reading, so a move "
                       "between them cannot be judged", None, pointers)
    resized = next((s for s in read if dict(s.spaces).keys() != first.keys()), None)
    if resized is not None:
        return Verdict("INVALID", len(read), f"the displays changed from {len(first)} to "
                       f"{len(resized.spaces)} at {resized.epoch_ms}, so a Space move cannot be "
                       f"judged across it", resized, pointers)
    gap = _gap(read, start_ms, end_ms)
    if gap:
        return Verdict("INVALID", len(read), f"the window was not watched throughout: {gap}",
                       None, pointers)
    unread = "" if first else " (no Space was recorded)"
    return Verdict("CLEAN", len(read), f"none of {sorted(wanted)} was in front in "
                                       f"{len(read)} samples{unread}", None, pointers)
