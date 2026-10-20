"""THE FOCUS GATE a live section takes `scry_core.focus_watch` through, the same flow on every
server: a control proves the watch sees what it must (a start in front, none behind, the owner's
Space moved on purpose) before its samples may clear anything, and the verdict judges the run
after it. Each outcome is a cell's, in `live_pool`'s words: `OK`, `FAIL`, or `BLOCKED` when the
window could not be judged at all, or the control could not be taken.

THE SPACE CONTROL IS AN ACTUATOR, so it lives here and not beside the instrument: `move_space`
presses Mission Control's shortcuts through System Events (it needs the Accessibility permission)
and reads the result back through the instrument's own `spaces`. On a host where every display
holds one Space there is nothing to move to, and on one without the private CoreGraphics
symbols nothing to read: in both the control could not be taken, which is BLOCKED, never the
watch's FAIL.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from scry_core import focus_watch
from scry_core.live_pool import Outcome

#: How long each control start is held in front, or behind, for the watch to sample it (the
#: servers' `hold` callbacks wait it out).
HOLD_S = 4.0
#: Shorter than this, a judged window says too little about a run to be its verdict.
MIN_WINDOW_MS = 60_000

# THE SPACE CONTROL'S KEYS: Mission Control's Ctrl+Right and Ctrl+Left, as key codes.
KEY_RIGHT, KEY_LEFT = 124, 123
SPACE_KEYS = (KEY_RIGHT, KEY_LEFT)
SPACE_SETTLE_S = 1.5
#: What `move_space` says when every display holds one Space.
NO_OTHER_SPACE = "no other Space to move to"


def _press(key: int) -> str:
    """One Mission Control shortcut through System Events: "" when it went, else why not."""
    run = focus_watch.osascript(f'tell application "System Events" to key code {key} using '
                                f"control down")
    if isinstance(run, str):
        return run
    if run.returncode != 0:
        return f"System Events refused the keystroke: {run.stderr.strip() or run.returncode}"
    return ""


@dataclass(frozen=True)
class Moved:
    """What `move_space` did: its window (epoch ms), "" or what did not hold, and whether the
    control could be taken at all (`taken`): one that could not is not one that failed."""

    began: int
    ended: int
    why: str = ""
    taken: bool = True


def move_space(settle_s: float = SPACE_SETTLE_S) -> Moved:
    """The owner's Space moved one along and back, by System Events, for a CONTROL that must see
    SPACE_CHANGED over the window returned. Right then Left, or Left then Right when there is no
    Space to the right. Whether a key moved the owner is read off the Spaces, never off the
    keystroke's own answer, since one that timed out may still have acted; so the way back is
    pressed whenever the owner moved, and the owner is checked to end where they began. `why` is
    "" when all of that held, else what did not (a keystroke refused, which needs Accessibility
    for this process; the owner left elsewhere); a host whose Spaces cannot be read, which
    presses nothing, or one with no other Space to move to, is not `taken`."""
    began = focus_watch.now_ms()
    if missing := focus_watch.spaces_missing():
        return Moved(began, focus_watch.now_ms(),
                     f"this host's CoreGraphics has no {missing}, so no Space can be read",
                     taken=False)
    before = focus_watch.spaces()
    if not before:
        return Moved(began, focus_watch.now_ms(),
                     "the displays' Spaces could not be read, so no key was pressed", taken=False)
    whys: list[str] = []
    back = None
    for go, ret in (SPACE_KEYS, SPACE_KEYS[::-1]):
        whys.append(_press(go))
        time.sleep(settle_s)
        now = focus_watch.spaces()
        if not now:
            whys.append("the displays' Spaces could not be read after a key")
            break
        if not focus_watch.same_spaces(now, before):
            back = ret
            break
        if whys[-1]:
            break
    taken = True
    if back is not None:
        whys.append(_press(back))
        time.sleep(settle_s)
    elif not any(whys):
        whys.append(NO_OTHER_SPACE)
        taken = False
    after = focus_watch.spaces()
    if not after or not focus_watch.same_spaces(after, before):
        whys.append(f"the owner was left on {after}, not {before}")
        taken = True
    return Moved(began, focus_watch.now_ms(), "; ".join(w for w in whys if w), taken)


class Watched(Protocol):
    """What the flow reads off a watch: its samples, its record, and its end."""

    samples: list[focus_watch.Sample]
    path: Path

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None: ...


@dataclass(frozen=True)
class Judged:
    """One cell's outcome and the reason it reads."""

    status: Outcome
    reason: str


@dataclass(frozen=True)
class Control:
    """The control's three cells, and where the judged window opens."""

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
    # A WINDOW THE WATCH COULD NOT COVER (no sample it could take, a stretch unsampled) is
    # BLOCKED here as in `verdict`: it says nothing about the start, nor about a Space moved. A
    # Space move names nobody (`verdict` says why).
    seen = focus_watch.judge(watch.samples, names, start_ms=front_w[0], end_ms=front_w[1])
    front = Judged("BLOCKED" if seen.status == "INVALID"
                   else "OK" if seen.status == "TOOK_FOCUS" else "FAIL", seen.reason)
    clean = focus_watch.judge(watch.samples, names, start_ms=behind_w[0], end_ms=behind_w[1])
    behind = Judged("BLOCKED" if clean.status in ("SPACE_CHANGED", "INVALID")
                    else "OK" if clean.status == "CLEAN" else "FAIL", clean.reason)
    m = move_space()
    moved = focus_watch.judge(watch.samples, names, start_ms=m.began, end_ms=m.ended)
    space = Judged("BLOCKED" if not m.taken or moved.status == "INVALID"
                   else "OK" if moved.status == "SPACE_CHANGED" and not m.why else "FAIL",
                   m.why if not m.taken else f"{m.why}; {moved.reason}" if m.why
                   else moved.reason)
    held = all(o.status == "OK" for o in (front, behind, space))
    return Control(front, behind, space, m.ended if held else None)


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
    v = focus_watch.judge(watch.samples, names, start_ms=since, end_ms=end_ms)
    if v.status == "INVALID":
        # THE INSTRUMENT, not the server: no sample it could take, or a stretch unsampled.
        return Judged("BLOCKED", f"the watch cannot judge the run: {v.reason}; {record}")
    if v.status == "SPACE_CHANGED":
        # A SPACE MOVE NAMES NOBODY: the owner may have made it. Never green, never the
        # server's FAIL on that alone: the record is there to read.
        return Judged("BLOCKED", f"a Space moved and nothing names who moved it: {v.reason}; "
                                 f"{record}")
    return Judged("OK" if v.status == "CLEAN" else "FAIL", f"{v.status}: {v.reason}; {record}")
