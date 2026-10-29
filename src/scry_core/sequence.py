"""The sequence executor behind `perform`, `drive`'s act and `start`'s plan, for both servers.

The list was judged whole before this runs. A step that needs a stopped machine, after one that
let it run, waits for the stop (a console command sent to a running machine is swallowed). The
tail hands back the stop a running list was heading for; a list that waited earns a verdict,
`TARGET` when every wait ended at a stop.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from scry_core import progress as mprogress
from scry_core import prose, recording
from scry_core import reply_contract as contract

Ops = dict[str, Callable[..., dict[str, Any]]]
#: What a wait for a stop found: the machine stopped, still running at the bound, or gone.
Waited = Literal["stopped", "running", "gone"]

NO_FAILURE_WHY = "no step failed"


def none_failed() -> dict[str, Any]:
    """`failed_at` of a list no step of which failed."""
    return contract.unavailable(NO_FAILURE_WHY)


def where_stopped(failed_at: object) -> str:
    """Where a `drive` act stopped, counted from 1: at a step, or after its last one."""
    return f"at step {failed_at + 1}" if isinstance(failed_at, int) else "after its last step"


def refused_text(refused: list[dict[str, Any]]) -> str:
    """The message of a list refused before anything ran: every refusal by step (from 1) and op."""
    def one(e: dict[str, Any]) -> str:
        op = f" ({e['op']!r})" if isinstance(e.get("op"), str) else ""
        return f"step {e['step'] + 1}{op} {e['message']}"
    return (f"{prose.counted(len(refused), 'step')} refused before anything ran: "
            + "; ".join(one(e) for e in refused) + ". Nothing was run")


def step_op(step: object) -> str | None:
    """The step's `op` as text, or None for a step that is no mapping or names none."""
    return str(step.get("op")) if isinstance(step, dict) and "op" in step else None


def not_a_step(index: int, step: object, no_op: str) -> dict[str, Any]:
    """The refusal of a step naming no operation of the server; `no_op` says why none is named.
    The vocabulary stays out of the message (`vocabulary_named`): it is repeated per copy."""
    return {"step": index, "op": contract.or_unavailable(step_op(step), no_op),
            "code": "bad_argument",
            "message": f"is not a step ({step!r}): see `operations` for the server's own "
                       "operation names"}


def vocabulary_named(refused: list[dict[str, Any]], ops: Ops) -> dict[str, Any]:
    """`operations`, when a step named no operation of the vocabulary; else nothing."""
    unknown = any(not isinstance(e["op"], str) or e["op"] not in ops for e in refused)
    return {"operations": sorted(ops)} if unknown else {}


#: `drive`'s verify when no `expect` was given.
NO_EXPECT: dict[str, Any] = {
    "checked": False,
    "why": "no `expect` given; the act's own steps carried whatever verification they asked for"}


def act_told(ran: dict[str, Any]) -> dict[str, Any]:
    """`drive`'s `act`: what the list said, minus the envelope."""
    return {k: v for k, v in ran.items() if k not in ("status", "session")}


def act_stopped(ran: dict[str, Any]) -> tuple[contract.Code, str]:
    """The code and message of an act that did not end `ok`, and where it stopped."""
    code: contract.Code = ran.get("code", "step_failed")
    return code, f"the act stopped {where_stopped(ran.get('failed_at'))}: {ran.get('message')}"


def act_ran_out() -> dict[str, Any]:
    """`drive`'s verify when the act's own wait ran out."""
    return {"checked": False, **contract.unavailable(
        "the act ran out its wait before it ended (`act.verdict` TIMEOUT), so there is no "
        "effect of the whole act to verify")}


class SequenceMachine(ABC):
    """A server's half of a sequence, made for one list."""

    stoppers = "A breakpoint or a watch"
    undeclared = "no breakpoint, no change watch"

    @abstractmethod
    def answers_running(self, op: str, args: dict[str, Any]) -> bool:
        """Whether this step is sent without a stop."""

    @abstractmethod
    def running(self) -> bool:
        """Whether the machine runs now, as the session says."""

    def began_running(self) -> bool:
        """Whether the list begins on a running machine."""
        return self.running()

    @abstractmethod
    def leaves_running(self, op: str, reply: dict[str, Any]) -> bool:
        """Whether a step that needs a stop left the machine running."""

    @abstractmethod
    def wait_for_stop(self, seconds: float, progress: mprogress.Progress,
                      tail: bool = False) -> Waited:
        """The bounded wait for a stop; `tail` for the list's last."""

    @abstractmethod
    def can_be_stopped(self) -> bool:
        """Whether anything declared can stop the machine."""

    @abstractmethod
    def tail_stop(self) -> dict[str, Any]:
        """The surveyed stop the tail waited for."""

    @abstractmethod
    def account(self, ran: list[dict[str, Any]], keep_last: bool,
                also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """`ran` as the reply carries it (`scry_core.sequence_account.account`)."""

    def entry(self, op: str, reply: dict[str, Any]) -> dict[str, Any]:
        """One step in the account."""
        return {"op": op, "reply": reply}

    def missed(self, op: str, reply: dict[str, Any]) -> bool:
        """Whether the step's own wait ran out, which ends the list."""
        return False

    def rested(self, ran: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The stop reached during the last step, which answered on a running machine."""
        return None

    def noted(self, op: str, reply: dict[str, Any]) -> None:
        """A step answered `ok`: what the server keeps besides the account."""
        return None


@dataclass(frozen=True)
class Ended:
    """How a list ended: a refusal's `code` and `message` (None and "" for a list that ran to its
    end), the reply's `fields`, and how many steps `held` to their recorded answer."""
    code: contract.Code | None
    message: str
    fields: dict[str, Any]
    held: int = 0


@dataclass(frozen=True)
class Stop:
    """Why a cycle ends the list: `code` and `message` (None and "" for an answer) and its
    fields."""
    code: contract.Code | None
    message: str
    fields: dict[str, Any] = field(default_factory=dict)


class Cycle(ABC):
    """A list repeated until the machine says it is done (MAME's `until_frame`)."""

    limit = 0

    @abstractmethod
    def expired(self) -> bool:
        """Whether the clock ran out, checked before each step."""

    @abstractmethod
    def after(self, reply: dict[str, Any], steps_completed: int, step: str) -> Stop | bool:
        """After a step that answered: why the list ends, True when done, False to go on."""

    @abstractmethod
    def short(self, steps_completed: int) -> Stop | None:
        """After the loop: why the list ends if the cycle never got done, else None."""

    @abstractmethod
    def fields(self) -> dict[str, Any]:
        """What every ending of the cycle carries."""


@dataclass
class _Run:
    """One list's state as it runs."""
    machine: SequenceMachine
    cycle: Cycle | None
    ran: list[dict[str, Any]] = field(default_factory=list)
    held: int = 0
    running: bool = False
    released_last: bool = False   # the last step let the machine run
    released: bool = False        # some step let the machine run
    came_to_rest: bool = False    # the last step found the machine stopped
    waited: bool = False          # a wait was made: a verdict is earned

    def ended(self, code: contract.Code | None, message: str, *, keep_last: bool,
              also: list[dict[str, Any]] | None = None, **fields: Any) -> Ended:
        out = {**self.machine.account(self.ran, keep_last, also),
               "steps_completed": len(self.ran), **fields,
               **(self.cycle.fields() if self.cycle is not None else {})}
        return Ended(code, message, out, self.held)

    def stopped_by_cycle(self, why: Stop) -> Ended:
        return self.ended(why.code, why.message, keep_last=True, failed_at=none_failed(),
                          **why.fields)


def run(machine: SequenceMachine, steps: list[dict[str, Any]], ops: Ops, settle_seconds: float,
        progress: mprogress.Progress = mprogress.no_progress, name: str = "perform",
        tail_wait: bool = True, cycle: Cycle | None = None) -> Ended:
    """The list run, every step already judged. `settle_seconds` bounds each wait for a stop (0:
    none); `tail_wait` False when the caller waits for the list's effect its own way."""
    r = _Run(machine, cycle, running=machine.began_running(), waited=cycle is not None)
    began = time.monotonic()
    i = 0
    while i < (cycle.limit if cycle is not None else len(steps)):
        if cycle is not None and cycle.expired():
            break
        step = steps[i % len(steps)]
        op = str(step["op"])
        args = recording.step_arguments(step)
        if r.running and not machine.answers_running(op, args):
            try:
                state = machine.wait_for_stop(settle_seconds, progress)
            except contract.Invalid as e:
                # The channel failed mid-wait: the steps already sent are the caller's to know.
                return r.ended(e.code, f"while the list waited for a stop before "
                               f"{_named(i, op, len(steps), cycle)}: {e}", keep_last=True,
                               **{**_own(e), "failed_at": i})
            if state == "gone":
                return r.ended("session_broken", f"the emulator is GONE (its bound expired or it "
                               f"crashed) before {_named(i, op, len(steps), cycle)} could run",
                               keep_last=True, failed_at=i)
            if state == "running":
                why = (f"the machine was still running {settle_seconds:g}s after the previous "
                       f"step, so the console step {op!r} cannot be sent (it would be "
                       f"swallowed). {machine.stoppers} has to stop it first")
                if not settle_seconds:
                    # No wait was asked, so nothing ran out.
                    return r.ended("not_stopped", why, keep_last=True, failed_at=i)
                return r.ended(None, "", keep_last=True, failed_at=none_failed(),
                               verdict=contract.TIMEOUT,
                               note=f"{why}; it and the steps after it were not sent")
            # settle_seconds 0 asked for no wait, even if the stop had landed: no verdict.
            r.waited = r.waited or settle_seconds > 0
        if cycle is None:
            with mprogress.within(progress, f"{name} step {i + 1} of {len(steps)} ({op})",
                                  began):
                reply = ops[op](**args)
        else:
            reply = ops[op](**args)
        if reply.get("status") != "ok":
            return r.ended("step_failed",
                           f"{_named(i, op, len(steps), cycle)} failed: {reply.get('message')}",
                           keep_last=False, also=[reply], failed_at=i,
                           failed={"op": op, "reply": reply})
        if (apart := recording.diverged(step.get(recording.RECORDED) or {}, reply)) is not None:
            message, fields = recording.divergence(i, op, reply, apart)
            return r.ended("diverged", message, keep_last=False, also=[reply], **fields)
        r.held += bool(step.get(recording.RECORDED))
        r.ran.append(machine.entry(op, reply))
        machine.noted(op, reply)
        if machine.missed(op, reply):
            # What the rest of the list was built on did not happen.
            return r.ended(None, "", keep_last=True, failed_at=none_failed(),
                           verdict=contract.TIMEOUT,
                           note=f"{_named(i, op, len(steps), cycle)} waited for what it was to "
                                f"see and it did not come; the steps after it were not sent")
        if not machine.answers_running(op, args):
            r.came_to_rest = False
            r.running = r.released_last = machine.leaves_running(op, reply)
            r.released = r.released or r.released_last
        else:
            # Whether such a step stopped the machine is the session's to say, never the op's name.
            r.came_to_rest = r.running and not machine.running()
            r.running = r.running and not r.came_to_rest
            r.released_last = False
        if cycle is not None:
            done = cycle.after(reply, len(r.ran), _named(i, op, len(steps), cycle))
            if isinstance(done, Stop):
                return r.stopped_by_cycle(done)
            if done:
                i += 1
                break
        i += 1
    if cycle is not None and (short := cycle.short(len(r.ran))) is not None:
        return r.stopped_by_cycle(short)
    return _tail(r, settle_seconds, progress, tail_wait)


def _own(e: contract.Invalid) -> dict[str, Any]:
    """What a refusal carries beyond what the list's ending states itself."""
    return {k: v for k, v in e.fields.items() if k not in ("failed_at", "keep_last", "also")}


def _named(i: int, op: str, length: int, cycle: Cycle | None) -> str:
    """Step `i` counted from 1, inside its pass when a cycle repeats the list."""
    if cycle is None:
        return f"step {i + 1} ({op!r})"
    return f"step {i % length + 1} ({op!r}) of pass {i // length + 1}"


def _tail(r: _Run, settle_seconds: float, progress: mprogress.Progress,
          tail_wait: bool) -> Ended:
    """The list's ending once its steps are done."""
    m = r.machine
    final: dict[str, Any] = {}
    if r.running and not tail_wait:
        final = {"still_running": True,
                 "note": "the act ended with the machine running; `drive`'s wait for `expect` is "
                         "the wait"}
    elif r.running and not settle_seconds:
        final = {"still_running": True,
                 "note": "settle_seconds=0: the sequence ended with the machine running and no "
                         "stop was waited for"}
    elif r.running and not r.released_last and not m.can_be_stopped():
        # A key sent after a `resume` with nothing to stop it wants the machine left running; a
        # wait would sit out its whole bound.
        final = {"still_running": True,
                 "note": f"the sequence ended with the machine running after a step that "
                         f"answers on a running machine, and nothing declared can stop it "
                         f"({m.undeclared}), so no stop was waited for; declare one, or end the "
                         f"list with the step that releases the machine, to wait for its stop"}
    elif r.came_to_rest and (rested := m.rested(r.ran)) is not None:
        final = {"stopped": rested}
    elif r.running and not r.released:
        # Keys sent to a running program are not heading for a stop.
        final = {"still_running": True,
                 "note": "the list began with the machine running and no step of it released it, "
                         "so no stop was waited for"}
    elif r.running:
        try:
            state = m.wait_for_stop(settle_seconds, progress, tail=True)
        except contract.Invalid as e:
            return r.ended(e.code, f"while the list's tail waited for its stop: {e}",
                           keep_last=True, **{**_own(e), "failed_at": none_failed()})
        if state == "gone":
            return r.ended("session_broken", "the sequence ended with the machine running and "
                           "the emulator is now GONE (its bound expired or it crashed)",
                           keep_last=True, failed_at=none_failed())
        if state == "stopped":
            final = {"stopped": m.tail_stop()}
            r.waited = True
        else:
            final = {"verdict": contract.TIMEOUT,
                     "note": f"the sequence ended with the machine running and it did not stop "
                             f"within {settle_seconds:g}s"}
    if r.waited and "verdict" not in final and "still_running" not in final:
        final = {"verdict": contract.TARGET, **final}
    stopped = final.get("stopped")
    return r.ended(None, "", keep_last=True, also=[stopped] if isinstance(stopped, dict) else None,
                   failed_at=none_failed(), **final)
