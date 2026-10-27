"""`perform(until_frame=F)`: the list repeated until a stop reads frame F, on a server whose stop
replies carry `frame`, a count since the machine started."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from scry_core import progress as mprogress
from scry_core import prose, sequence
from scry_core import reply_contract as contract
from scry_core import sequence_account as account
from scry_core import vocabulary as vocab
from scry_core.reply_contract import Invalid, or_unavailable

# `run_for` walks through a watch's stop and carries on at the next step; `run_to` and `step`
# end at the first one.
UNTIL_OP = "run_for"
# A frame counter that never arrives must end somewhere, in steps and in time: the whole cycle
# holds the server's one lock.
UNTIL_STEPS_MAX = 5000
UNTIL_SECONDS_MAX = vocab.WAIT_MAX_S


def check_arguments(until_frame: int, summaries: bool) -> None:
    """`until_frame`'s machine-independent half: a frame number, with `summaries`, because a
    window is hundreds of steps."""
    if isinstance(until_frame, bool) or not isinstance(until_frame, int) or until_frame < 0:
        raise Invalid("bad_argument", f"until_frame={until_frame!r} is a frame number, 0 for none")
    if until_frame and not summaries:
        raise Invalid("bad_argument",
                      "until_frame needs summaries=True: a window of frames is hundreds of "
                      "steps, and their full replies would not fit one reply")


def check_until(steps: list[Any], until_frame: int, here: int | None, running: bool) -> None:
    """A list run `until_frame` must advance the machine, and the frame must be ahead of `here`,
    the last stop's; a running machine's frame is judged at its first stop instead."""
    if not until_frame:
        return
    if not any(isinstance(s, dict) and s.get("op") == UNTIL_OP for s in steps):
        raise Invalid("bad_argument",
                      f"until_frame repeats the list until a stop reaches the frame, so the "
                      f"list needs a `{UNTIL_OP}` step (`frames: 1` walks a window one frame "
                      f"at a time)")
    if here is not None and here >= until_frame and not running:
        raise Invalid("bad_argument",
                      f"until_frame={until_frame} is not ahead of the machine, which stands at "
                      f"frame {here}: the frame is absolute, the one the window ends at")


def frame_of(reply: dict[str, Any]) -> int | None:
    """The newest frame a reply's stops carry."""
    known = [f for s in account.stops_in(reply) if isinstance(f := s.get("frame"), int)]
    return max(known) if known else None


def reached(frame: int | None) -> int | dict[str, Any]:
    """`until_frame`'s `frame_reached`, or why there is none."""
    return or_unavailable(frame, "no stop of the list read a frame")


def _no_line() -> None:
    """The last line of a list that has none to send."""


class Window(sequence.Cycle):
    """A list repeated until a stop reply carries a `frame` at or past `until`.

    The steps a window takes are its frames plus the stops inside it, which no caller can size
    beforehand. The run ends right after the first step whose stop reads the frame, even
    mid-list; `UNTIL_STEPS_MAX` and `UNTIL_SECONDS_MAX` bound it, and a stop with no frame ends
    it, since nothing then says whether the window is over. `start` is the frame the machine
    stands at, None when it was running (`blind`): its first stop starts the window."""

    def __init__(self, until: int, start: int | None, blind: bool,
                 progress: mprogress.Progress) -> None:
        self.limit = UNTIL_STEPS_MAX
        self.until = until
        self.blind = blind
        self.start = None if blind else start
        self.reached: int | None = None
        self.clock = mprogress.Ticker(UNTIL_SECONDS_MAX, progress)
        self.last_line: Callable[[], None] = _no_line

    def expired(self) -> bool:
        return self.clock.expired()

    def after(self, reply: dict[str, Any], steps_completed: int,
              step: str) -> sequence.Stop | bool:
        if not account.stops_in(reply):
            return False
        frame = frame_of(reply)
        if frame is None:
            return sequence.Stop("unexpected_answer",
                                 f"{step} stopped with no frame read, so "
                                 f"nothing says whether frame {self.until} was reached: the "
                                 "list ends here")
        if self.blind and self.reached is None and frame >= self.until:
            self.reached = frame
            return sequence.Stop("bad_argument",
                                 f"the machine was running when the list began and its first "
                                 f"stop already reads frame {frame}, at or past "
                                 f"until_frame={self.until}: nothing of the window was walked")
        self.reached = frame
        template = "perform until frame {until}: frame {frame}, {steps}"
        said = {"until": self.until, "frame": frame,
                "steps": prose.counted(steps_completed, "step")}
        if frame >= self.until:
            if self.start is not None:
                self.last_line = functools.partial(self.clock.finish, self.until - self.start,
                                                   template, **said)
            return True
        if self.start is None:
            self.clock.tick(template, **said)
        else:
            self.clock.report(frame - self.start, self.until - self.start, template, **said)
        return False

    def short(self, steps_completed: int) -> sequence.Stop | None:
        if self.reached is not None and self.reached >= self.until:
            return None
        return sequence.Stop(None, "", {
            "verdict": contract.TIMEOUT,
            "note": f"until_frame={self.until} was not reached in "
                    f"{prose.counted(steps_completed, 'step')} and {self.clock.elapsed():.0f} s "
                    f"(the bounds are {UNTIL_STEPS_MAX} steps and {UNTIL_SECONDS_MAX:g} s): "
                    f"the last frame read was {self.reached}"})

    def fields(self) -> dict[str, Any]:
        return {"until_frame": self.until, "frame_reached": reached(self.reached)}
