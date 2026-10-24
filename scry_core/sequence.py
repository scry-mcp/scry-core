"""THE SEQUENCE EXECUTOR: a list of a server's own operations run in order in one call, the rules
`perform`, `drive`'s act and `start`'s plan hold on both servers, written once.

The list was judged whole before this runs (`scry_core.steps` and each server's value checks), so
a list with one bad step never released the machine at its first. A step that needs a stopped
machine, after one that let it run, waits for the stop, since a console command sent to a running
machine is swallowed; a step that answers INVALID, or a replayed one whose answer left its
recording, ends the list where it is cheapest to read. THE TAIL: a list that ends with the machine
running hands back the stop it was heading for, surveyed, and a list that waited for a stop earns
a verdict, `TARGET` when every wait it made ended at one.

WHAT DIFFERS IS THE MACHINE'S, handed in as a `SequenceMachine`: how a stop is waited for and
proved, which steps answer on a running machine, what can stop one, how a step is kept in the
account, and the survey at the stop. MAME's window of frames (`until_frame`) is a `Cycle` of its
own, and a step whose own wait for what it was to see ran out (`SequenceMachine.missed`) ends the
list as a run's wait does.
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
    """Where a `drive` act stopped, counted from 1 as every message counts steps: at a step, or
    after its last one when the tail's wait ended it (`failed_at` unavailable)."""
    return f"at step {failed_at + 1}" if isinstance(failed_at, int) else "after its last step"


def refused_text(refused: list[dict[str, Any]]) -> str:
    """The message of a list refused before anything ran: every refusal, each by its step
    (counted from 1, as every message counts steps) and its op (a step that is no mapping has
    none to name, and its own message quotes it)."""
    def one(e: dict[str, Any]) -> str:
        op = f" ({e['op']!r})" if isinstance(e.get("op"), str) else ""
        return f"step {e['step'] + 1}{op} {e['message']}"
    return (f"{prose.counted(len(refused), 'step')} refused before anything ran: "
            + "; ".join(one(e) for e in refused) + ". Nothing was run")


def step_op(step: object) -> str | None:
    """The operation a list's step names: its `op` as text, or None for a step that is no mapping
    or names none."""
    return str(step.get("op")) if isinstance(step, dict) and "op" in step else None


def not_a_step(index: int, step: object, no_op: str) -> dict[str, Any]:
    """The refusal of a step naming no operation of the server, `no_op` saying why there is none
    to name when the step names none at all. THE VOCABULARY IS NAMED ONCE, in the refusal's own
    `operations` (`vocabulary_named`), never inside this message: a message is repeated in
    `errors` and in the joined refusal, and a list of every operation in each copy buries the one
    step that failed."""
    return {"step": index, "op": contract.or_unavailable(step_op(step), no_op),
            "code": "bad_argument",
            "message": f"is not a step ({step!r}): see `operations` for the server's own "
                       "operation names"}


def vocabulary_named(refused: list[dict[str, Any]], ops: Ops) -> dict[str, Any]:
    """What a list's refusal names beside its errors: the vocabulary, `operations`, when a step
    named no operation of it, and nothing otherwise."""
    unknown = any(not isinstance(e["op"], str) or e["op"] not in ops for e in refused)
    return {"operations": sorted(ops)} if unknown else {}


#: `drive`'s verify when no `expect` was given.
NO_EXPECT: dict[str, Any] = {
    "checked": False,
    "why": "no `expect` given; the act's own steps carried whatever verification they asked for"}


def act_told(ran: dict[str, Any]) -> dict[str, Any]:
    """`drive`'s `act`: what the list said, minus the envelope's own fields, so an act reads as
    `perform` does (`failed` only when a step failed; `failed_at` says so either way)."""
    return {k: v for k, v in ran.items() if k not in ("status", "session")}


def act_stopped(ran: dict[str, Any]) -> tuple[contract.Code, str]:
    """The code and the message of an act that did not end `ok`: the list's own code (a step
    that failed is `step_failed`; a list the executor ended says why), and where it stopped."""
    code: contract.Code = ran.get("code", "step_failed")
    return code, f"the act stopped {where_stopped(ran.get('failed_at'))}: {ran.get('message')}"


def act_ran_out() -> dict[str, Any]:
    """`drive`'s verify when the act's own wait ran out: nothing of the whole act to verify."""
    return {"checked": False, **contract.unavailable(
        "the act ran out its wait before it ended (`act.verdict` TIMEOUT), so there is no "
        "effect of the whole act to verify")}


class SequenceMachine(ABC):
    """A server's half of a sequence, made for one list: what its machine decides. The abstract
    methods are the ones every server answers; the rest default to the plain answer."""

    #: What can stop a running machine, as a sentence names it first.
    stoppers = "A breakpoint or a watch"
    #: What a session with nothing declared to stop it lacks, in the tail's note.
    undeclared = "no breakpoint, no change watch"

    @abstractmethod
    def answers_running(self, op: str, args: dict[str, Any]) -> bool:
        """Whether this step answers on a running machine, so it is sent without a stop."""

    @abstractmethod
    def running(self) -> bool:
        """Whether the machine runs now, as the session says, with nothing typed to learn it."""

    def began_running(self) -> bool:
        """Whether the list begins on a running machine, so its first step that needs a stop
        waits for one."""
        return self.running()

    @abstractmethod
    def leaves_running(self, op: str, reply: dict[str, Any]) -> bool:
        """Whether a step that needs a stopped machine left it running, read from its reply."""

    @abstractmethod
    def wait_for_stop(self, seconds: float, progress: mprogress.Progress,
                      tail: bool = False) -> Waited:
        """The bounded wait for a stop; `tail` for the list's last, whose survey follows."""

    @abstractmethod
    def can_be_stopped(self) -> bool:
        """Whether anything declared can stop the machine, so a wait for a stop can end."""

    @abstractmethod
    def tail_stop(self) -> dict[str, Any]:
        """The surveyed stop a list's tail waited for."""

    @abstractmethod
    def account(self, ran: list[dict[str, Any]], keep_last: bool,
                also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """`ran` as the reply carries it (`scry_core.sequence_account.account`)."""

    def entry(self, op: str, reply: dict[str, Any]) -> dict[str, Any]:
        """One step in the account."""
        return {"op": op, "reply": reply}

    def missed(self, op: str, reply: dict[str, Any]) -> bool:
        """Whether the step's own wait for what it was to see ran out, which ends the list."""
        return False

    def rested(self, ran: list[dict[str, Any]]) -> dict[str, Any] | None:
        """The stop the machine came to during the list's last step, which answered on a running
        machine (a `stop`, a breakpoint met while a key went in), as the tail names it; None to
        name none."""
        return None

    def noted(self, op: str, reply: dict[str, Any]) -> None:
        """A step answered `ok`: what the server keeps of it besides the account."""
        return None


@dataclass(frozen=True)
class Ended:
    """How a list ended: a refusal's `code` and `message` (None and "" for a list that ran to its
    end, a verdict included), the reply's `fields`, and how many steps `held` to the answer a
    recording kept for them."""
    code: contract.Code | None
    message: str
    fields: dict[str, Any]
    held: int = 0


@dataclass(frozen=True)
class Stop:
    """Why a cycle ends the list: a refusal's `code` and `message` (None and "" for an answer)
    and the fields it adds; `run` puts the account and the count around them."""
    code: contract.Code | None
    message: str
    fields: dict[str, Any] = field(default_factory=dict)


class Cycle(ABC):
    """A list repeated until the machine says it is done (MAME's `until_frame`): its bound in
    steps, its clock, its judgement after each step, and the fields every ending carries. Its
    steps report no progress line of their own: the cycle reports its own."""

    #: The most steps the cycle runs.
    limit = 0

    @abstractmethod
    def expired(self) -> bool:
        """Whether the cycle's clock ran out, checked before each step."""

    @abstractmethod
    def after(self, reply: dict[str, Any], steps_completed: int, step: str) -> Stop | bool:
        """After a step that answered, `step` named as every message names it: why the list
        ends, True when the cycle is done, False to go on."""

    @abstractmethod
    def short(self, steps_completed: int) -> Stop | None:
        """After the loop: why the list ends when the cycle never got done, else None."""

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
    released_last: bool = False   # the LAST step is the one that let the machine run
    released: bool = False        # SOME step let the machine run: the list is heading for a stop
    came_to_rest: bool = False    # the LAST step answered on a running machine and found it stopped
    waited: bool = False          # a wait for a stop was asked for and made: a verdict is earned

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
    """The list run, every step already judged: how it ended (`Ended`). `settle_seconds` bounds
    each wait for a stop (0: none); `tail_wait` False when the caller waits for the list's effect
    its own way; `cycle` repeats the list (`Cycle`)."""
    # A LIST BEGUN ON A RUNNING MACHINE (after a `resume`) waits for its stop before its first
    # step that needs one, as one that released the machine itself does.
    r = _Run(machine, cycle, running=machine.began_running(), waited=cycle is not None)
    began = time.monotonic()            # the list's line rises from here
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
                # THE CHANNEL FAILED WHILE THE LIST WAITED (a terminal that overflowed, a stub
                # that hung up): the steps already sent are the caller's to know, so the list
                # ends with them, the failure as its end.
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
                    # NO WAIT WAS ASKED, so nothing ran out: the step could not be sent at all.
                    return r.ended("not_stopped", why, keep_last=True, failed_at=i)
                # THE WAIT RAN OUT: a verdict, and the list ends here with what it completed.
                return r.ended(None, "", keep_last=True, failed_at=none_failed(),
                               verdict=contract.TIMEOUT,
                               note=f"{why}; it and the steps after it were not sent")
            # A wait with `settle_seconds` 0 was not asked for, even when the stop had already
            # landed: it earns no verdict.
            r.waited = r.waited or settle_seconds > 0
        if cycle is None:
            with mprogress.within(progress, f"{name} step {i + 1} of {len(steps)} ({op})",
                                  began):
                reply = ops[op](**args)  # the list was judged whole: every op is the server's
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
            # A STEP'S OWN WAIT FOR WHAT IT WAS TO SEE RAN OUT: what the rest of the list was
            # built on did not happen, so it ends here with the verdict, as a wait of the list's
            # own does.
            return r.ended(None, "", keep_last=True, failed_at=none_failed(),
                           verdict=contract.TIMEOUT,
                           note=f"{_named(i, op, len(steps), cycle)} waited for what it was to "
                                f"see and it did not come; the steps after it were not sent")
        if not machine.answers_running(op, args):
            r.came_to_rest = False
            r.running = r.released_last = machine.leaves_running(op, reply)
            r.released = r.released or r.released_last
        else:
            # A STEP THAT ANSWERS ON A RUNNING MACHINE DOES NOT RELEASE IT, and whether it
            # stopped it is the session's to say, never the op's name: a `stop`, or a breakpoint
            # met while a key went in, did.
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
    """What a refusal that ended the list carries of its own, past what the list's ending
    states itself (where it failed, what it keeps)."""
    return {k: v for k, v in e.fields.items() if k not in ("failed_at", "keep_last", "also")}


def _named(i: int, op: str, length: int, cycle: Cycle | None) -> str:
    """Step `i` as the caller counts it, from 1 as the progress line does, and inside its pass
    when a cycle repeats the list."""
    if cycle is None:
        return f"step {i + 1} ({op!r})"
    return f"step {i % length + 1} ({op!r}) of pass {i // length + 1}"


def _tail(r: _Run, settle_seconds: float, progress: mprogress.Progress,
          tail_wait: bool) -> Ended:
    """The list's ending once its steps are done (THE TAIL, in the module docstring)."""
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
        # THE LAST STEP ANSWERED ON A RUNNING MACHINE AND NOTHING DECLARED CAN STOP IT: a list
        # ending in a key sent after a `resume`, with no breakpoint, wants the machine left
        # running, where a wait would sit out its whole bound for a stop nothing can produce.
        final = {"still_running": True,
                 "note": f"the sequence ended with the machine running after a step that "
                         f"answers on a running machine, and nothing declared can stop it "
                         f"({m.undeclared}), so no stop was waited for; declare one, or end the "
                         f"list with the step that releases the machine, to wait for its stop"}
    elif r.came_to_rest and (rested := m.rested(r.ran)) is not None:
        final = {"stopped": rested}
    elif r.running and not r.released:
        # A LIST BEGUN ON A RUNNING MACHINE THAT RELEASED NOTHING is not heading for a stop (keys
        # sent to a running program): it hands the machine back running, where a wait would sit
        # out its bound for a stop the list never asked for.
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
