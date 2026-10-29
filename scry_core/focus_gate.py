"""The focus-watch flow shared by every server: a control proves the watch sees what it must, then
the verdict judges the run.

`move_space` is an actuator, so it lives here and not beside the instrument. The control's two
cells that take the owner's desk (a start forced in front, the Space moved) run only when
`OPT_IN_VAR` is set to 1.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from scry_core import focus_watch
from scry_core.live_pool import Outcome

#: Set to 1 to let the control take the desk: a start forced in front and the Space moved.
OPT_IN_VAR = "SCRY_FOCUS_CONTROL"
#: How long each control start is held in front, or behind, for the watch to sample it.
HOLD_S = 4.0
#: Shorter than this, a judged window is too little to be a verdict.
MIN_WINDOW_MS = 60_000

# Mission Control's Ctrl+Right and Ctrl+Left key codes.
KEY_RIGHT, KEY_LEFT = 124, 123
SPACE_KEYS = (KEY_RIGHT, KEY_LEFT)
SPACE_SETTLE_S = 1.5
NO_OTHER_SPACE = "no other Space to move to"
SHORTCUTS_OFF = ("the shortcuts moved nothing though a display holds {} Spaces: Mission "
                 "Control's \"Move left a space\" and \"Move right a space\" may be off")


def _opted_in() -> bool:
    return os.environ.get(OPT_IN_VAR) == "1"


def _needs_the_desk(what: str) -> str:
    return (f"{what} takes the owner's desk and runs only when asked: set {OPT_IN_VAR}=1 on an "
            f"idle machine")


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
    """What `move_space` did; `taken` False means the control could not be taken, not that it
    failed."""

    began: int
    ended: int
    why: str = ""
    taken: bool = True


def move_space(settle_s: float = SPACE_SETTLE_S) -> Moved:
    """Move the owner's Space along and back (epoch-ms window returned); `why` is "" when it all
    held.

    A key's effect is read off the Spaces, never its answer: a timed-out one may still have acted.
    Not `taken` (BLOCKED, never a FAIL): Spaces unreadable, keystroke refused, no other Space, or
    shortcuts that moved nothing."""
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
    elif any(whys):
        taken = False                       # keystroke refused: never moved
    else:
        most = max(focus_watch.space_counts() or (1,))
        whys.append(SHORTCUTS_OFF.format(most) if most > 1 else NO_OTHER_SPACE)
        taken = False
    after = focus_watch.spaces()
    if not after or not focus_watch.same_spaces(after, before):
        whys.append(f"the owner was left on {after}, not {before}")
        taken = True
    return Moved(began, focus_watch.now_ms(), "; ".join(w for w in whys if w), taken)


class Watched(Protocol):
    """What the flow reads off a watch."""

    samples: list[focus_watch.Sample]
    path: Path

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None: ...


@dataclass(frozen=True)
class Judged:
    """One cell's outcome and its reason."""

    status: Outcome
    reason: str


@dataclass(frozen=True)
class Control:
    """The control's three cells."""

    front: Judged
    behind: Judged
    space: Judged
    # Where the judged window opens; None when the control did not hold.
    since: int | None


def control(watch: Watched, names: Collection[str],
            hold: Callable[[bool], tuple[int, int]]) -> Control:
    """Run the control over `watch`; `hold(background)` launches one start and returns its
    window."""
    asked = _opted_in()
    front_w = hold(False) if asked else None
    behind_w = hold(True)
    # A window the watch could not cover says nothing about the start, so it is BLOCKED.
    if front_w is None:
        front = Judged("BLOCKED", _needs_the_desk("forcing a start in front"))
    else:
        seen = focus_watch.judge(watch.samples, names, start_ms=front_w[0], end_ms=front_w[1])
        front = Judged("BLOCKED" if seen.status == "INVALID"
                       else "OK" if seen.status == "TOOK_FOCUS" else "FAIL", seen.reason)
    clean = focus_watch.judge(watch.samples, names, start_ms=behind_w[0], end_ms=behind_w[1])
    behind = Judged("BLOCKED" if clean.status in ("SPACE_CHANGED", "INVALID")
                    else "OK" if clean.status == "CLEAN" else "FAIL", clean.reason)
    if not asked:
        space = Judged("BLOCKED", _needs_the_desk("moving the Space"))
        return Control(front, behind, space, None)
    m = move_space()
    moved = focus_watch.judge(watch.samples, names, start_ms=m.began, end_ms=m.ended)
    space = Judged("BLOCKED" if not m.taken or moved.status == "INVALID"
                   else "OK" if moved.status == "SPACE_CHANGED" and not m.why else "FAIL",
                   m.why if not m.taken else f"{m.why}; {moved.reason}" if m.why
                   else moved.reason)
    held = all(o.status == "OK" for o in (front, behind, space))
    return Control(front, behind, space, m.ended if held else None)


def _unproven(watch: Watched, names: Collection[str], end_ms: int, record: str) -> Judged:
    """The whole run judged with no control behind it: a stolen focus is still a FAIL, a clean run
    proves nothing."""
    if not watch.samples:
        return Judged("BLOCKED", f"the watch took no sample; {record}")
    v = focus_watch.judge(watch.samples, names, start_ms=watch.samples[0].epoch_ms, end_ms=end_ms)
    if v.status == "TOOK_FOCUS":
        return Judged("FAIL", f"{v.status}: {v.reason}; {record}")
    return Judged("BLOCKED", f"unproven: the control was not taken, so a clean watch clears "
                             f"nothing (set {OPT_IN_VAR}=1 on an idle machine); {record}")


def verdict(watch: Watched, names: Collection[str], since: int | None, end_ms: int) -> Judged:
    """End the watch, then judge the run, only after a held control and a window of
    `MIN_WINDOW_MS`."""
    record = f"record {watch.path}"
    try:
        watch.__exit__(None, None, None)
    except Exception as e:  # a record not written
        return Judged("BLOCKED", f"the watch failed ({type(e).__name__}: {e}), so the run "
                                 f"cannot be judged; {record}")
    if since is None and not _opted_in():
        return _unproven(watch, names, end_ms, record)
    if since is None:
        return Judged("BLOCKED", f"the control did not hold, so the watch clears nothing; {record}")
    if end_ms - since < MIN_WINDOW_MS:
        return Judged("BLOCKED", f"{end_ms - since} ms ran after the control, too little to "
                                 f"judge; {record}")
    v = focus_watch.judge(watch.samples, names, start_ms=since, end_ms=end_ms)
    if v.status == "INVALID":
        return Judged("BLOCKED", f"the watch cannot judge the run: {v.reason}; {record}")
    if v.status == "SPACE_CHANGED":
        # A Space move names nobody (the owner may have made it): never green, never FAIL.
        return Judged("BLOCKED", f"a Space moved and nothing names who moved it: {v.reason}; "
                                 f"{record}")
    return Judged("OK" if v.status == "CLEAN" else "FAIL", f"{v.status}: {v.reason}; {record}")
