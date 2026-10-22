"""The sequence executor's rules, each on a double of a machine: the one place they are held for
both servers (`scry_core.sequence`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from scry_core import progress as mprogress
from scry_core import recording, sequence
from scry_core import reply_contract as contract


class Double(sequence.SequenceMachine):
    """A machine whose stops are scripted: `waits` is what each wait for a stop finds, in order;
    `releases` the ops that let it run; `stopping` the ops that answer on a running machine and
    stop it (a `stop`)."""

    stoppers = "A breakpoint or a watch"
    undeclared = "no breakpoint"

    def __init__(self, waits: list[sequence.Waited | Exception] | None = None,
                 running: bool = False,
                 can_stop: bool = True, missed_ops: frozenset[str] = frozenset(),
                 rests: bool = False, began: bool | None = None) -> None:
        self.waits = list(waits or [])
        self.is_running = running
        self.can_stop = can_stop
        self.missed_ops = missed_ops
        self.rests = rests
        self.began = began
        self.asked_waits: list[tuple[float, bool]] = []
        self.noted_ops: list[str] = []

    def answers_running(self, op: str, args: dict[str, Any]) -> bool:
        return op in ("send_keys", "stop", "status")

    def running(self) -> bool:
        return self.is_running

    def began_running(self) -> bool:
        return self.is_running if self.began is None else self.began

    def leaves_running(self, op: str, reply: dict[str, Any]) -> bool:
        return op == "resume"

    def wait_for_stop(self, seconds: float, progress: Any, tail: bool = False) -> sequence.Waited:
        self.asked_waits.append((seconds, tail))
        state = self.waits.pop(0) if self.waits else "stopped"
        if isinstance(state, Exception):
            raise state
        if state == "stopped":
            self.is_running = False
        return state

    def can_be_stopped(self) -> bool:
        return self.can_stop

    def tail_stop(self) -> dict[str, Any]:
        return {"stop_seq": 9, "pc": "0x10"}

    def account(self, ran: list[dict[str, Any]], keep_last: bool,
                also: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"ran": list(ran), "keep_last": keep_last, "also": also}

    def missed(self, op: str, reply: dict[str, Any]) -> bool:
        return op in self.missed_ops

    def rested(self, ran: list[dict[str, Any]]) -> dict[str, Any] | None:
        return {"stop_seq": 4} if self.rests else None

    def noted(self, op: str, reply: dict[str, Any]) -> None:
        self.noted_ops.append(op)


def _ops(m: Double, calls: list[str], fail: str = "") -> sequence.Ops:
    """Tools that record their calls; `resume` lets the machine run, `stop` stops it, `fail`
    answers INVALID."""
    def tool(name: str) -> Callable[..., dict[str, Any]]:
        def call(**kw: Any) -> dict[str, Any]:
            calls.append(name)
            mprogress.bridge(None)(0.0, None, "working")    # a step's own line, as a tool's
            if name == fail:
                return {"status": "INVALID", "code": "bad_argument", "message": "no"}
            if name == "resume":
                m.is_running = True
            if name == "stop":
                m.is_running = False
            return {"status": "ok", "value": kw.get("value", 1)}
        return call
    return {n: tool(n) for n in ("resume", "read_memory", "send_keys", "stop", "status",
                                 "log_wait")}


def _run(m: Double, steps: list[dict[str, Any]], settle: float = 5.0, fail: str = "",
         **kw: Any) -> tuple[sequence.Ended, list[str]]:
    calls: list[str] = []
    return sequence.run(m, steps, _ops(m, calls, fail), settle, **kw), calls


def test_a_step_that_needs_a_stop_waits_for_it_and_the_list_earns_target() -> None:
    m = Double(waits=["stopped"])
    ended, calls = _run(m, [{"op": "resume"}, {"op": "read_memory"}])
    assert calls == ["resume", "read_memory"]
    assert m.asked_waits == [(5.0, False)]
    assert ended.code is None
    assert ended.fields["verdict"] == contract.TARGET
    assert ended.fields["steps_completed"] == 2
    assert ended.fields["failed_at"] == sequence.none_failed()


def test_a_wait_that_runs_out_ends_the_list_with_timeout_and_sends_nothing_after() -> None:
    m = Double(waits=["running"])
    ended, calls = _run(m, [{"op": "resume"}, {"op": "read_memory"}, {"op": "status"}])
    assert calls == ["resume"]
    assert ended.code is None
    assert ended.fields["verdict"] == contract.TIMEOUT
    assert "'read_memory' cannot be sent" in ended.fields["note"]
    assert "A breakpoint or a watch has to stop it first" in ended.fields["note"]
    assert ended.fields["note"].endswith("it and the steps after it were not sent")


def test_with_no_wait_asked_a_step_that_cannot_be_sent_is_not_stopped() -> None:
    m = Double(waits=["running"])
    ended, calls = _run(m, [{"op": "resume"}, {"op": "read_memory"}], settle=0.0)
    assert calls == ["resume"]
    assert ended.code == "not_stopped"
    assert ended.fields["failed_at"] == 1
    assert "verdict" not in ended.fields


def test_an_emulator_gone_before_a_step_is_session_broken() -> None:
    m = Double(waits=["gone"])
    ended, _ = _run(m, [{"op": "resume"}, {"op": "read_memory"}])
    assert ended.code == "session_broken"
    assert ended.fields["failed_at"] == 1


def test_a_step_that_fails_ends_the_list_beside_the_steps_before_it() -> None:
    m = Double()
    ended, calls = _run(m, [{"op": "status"}, {"op": "read_memory"}, {"op": "status"}],
                        fail="read_memory")
    assert calls == ["status", "read_memory"]
    assert ended.code == "step_failed"
    assert ended.message.startswith("step 2 ('read_memory') failed: no")
    assert [e["op"] for e in ended.fields["ran"]] == ["status"]
    assert ended.fields["failed"]["op"] == "read_memory"
    assert ended.fields["failed_at"] == 1


def test_a_replay_that_leaves_its_recording_is_diverged_and_held_counts_the_rest() -> None:
    m = Double()
    steps: list[dict[str, Any]] = [
             {"op": "read_memory", "value": 1, recording.RECORDED: {"value": 1}},
             {"op": "read_memory", "value": 2, recording.RECORDED: {"value": 3}},
             {"op": "status"}]
    ended, calls = _run(m, steps)
    assert calls == ["read_memory", "read_memory"]
    assert ended.code == "diverged"
    assert ended.held == 1


def test_a_list_that_waited_for_nothing_carries_no_verdict() -> None:
    m = Double()
    ended, _ = _run(m, [{"op": "status"}, {"op": "read_memory"}])
    assert ended.code is None
    assert "verdict" not in ended.fields
    assert m.noted_ops == ["status", "read_memory"]


def test_a_list_begun_on_a_running_machine_waits_before_its_first_console_step() -> None:
    m = Double(waits=["stopped"], running=True)
    ended, _ = _run(m, [{"op": "read_memory"}])
    assert m.asked_waits == [(5.0, False)]
    assert ended.fields["verdict"] == contract.TARGET


def test_a_steps_own_missed_wait_ends_the_list_where_the_machine_says_so() -> None:
    m = Double(missed_ops=frozenset({"log_wait"}))
    ended, calls = _run(m, [{"op": "log_wait"}, {"op": "status"}])
    assert calls == ["log_wait"]
    assert ended.fields["verdict"] == contract.TIMEOUT
    assert "step 1 ('log_wait') waited for what it was to see" in ended.fields["note"]
    # A machine that says nothing of a step's own wait goes on.
    plain = Double()
    _, calls = _run(plain, [{"op": "log_wait"}, {"op": "status"}])
    assert calls == ["log_wait", "status"]


def test_the_tail_waits_for_the_stop_and_hands_it_back_surveyed() -> None:
    m = Double(waits=["stopped"])
    ended, _ = _run(m, [{"op": "resume"}])
    assert m.asked_waits == [(5.0, True)]
    assert ended.fields["stopped"] == {"stop_seq": 9, "pc": "0x10"}
    assert ended.fields["verdict"] == contract.TARGET


@pytest.mark.parametrize("state, code, verdict", [("running", None, contract.TIMEOUT),
                                                  ("gone", "session_broken", None)])
def test_the_tails_wait_ends_in_timeout_or_finds_the_emulator_gone(
        state: sequence.Waited, code: str | None, verdict: str | None) -> None:
    m = Double(waits=[state])
    ended, _ = _run(m, [{"op": "resume"}])
    assert ended.code == code
    assert ended.fields.get("verdict") == verdict
    assert "stopped" not in ended.fields


def test_the_tail_does_not_wait_when_the_caller_waits_or_no_wait_was_asked() -> None:
    for kw, said in (({"tail_wait": False}, "`drive`'s wait for `expect` is the wait"),
                     ({"settle": 0.0}, "settle_seconds=0")):
        m = Double()
        settle = kw.pop("settle", 5.0)
        ended, _ = _run(m, [{"op": "resume"}], settle=settle, **kw)
        assert m.asked_waits == []
        assert ended.fields["still_running"] is True
        assert said in ended.fields["note"]
        assert "verdict" not in ended.fields


def test_the_tail_does_not_wait_for_a_stop_nothing_declared_can_produce() -> None:
    m = Double(waits=["stopped"], can_stop=False)
    ended, _ = _run(m, [{"op": "resume"}, {"op": "send_keys"}], settle=0.0)
    assert ended.fields["note"] == "settle_seconds=0: the sequence ended with the machine " \
                                   "running and no stop was waited for"
    m = Double(waits=["stopped"], can_stop=False)
    ended, _ = _run(m, [{"op": "resume"}, {"op": "send_keys"}])
    assert m.asked_waits == []
    assert ended.fields["still_running"] is True
    assert "(no breakpoint)" in ended.fields["note"]
    # ...but a list whose LAST step released the machine waits all the same.
    m = Double(waits=["stopped"], can_stop=False)
    ended, _ = _run(m, [{"op": "resume"}])
    assert "stopped" in ended.fields


def test_a_stop_met_during_the_last_step_is_the_tails_where_the_machine_names_it() -> None:
    m = Double(rests=True)
    ended, _ = _run(m, [{"op": "resume"}, {"op": "stop"}])
    assert ended.fields["stopped"] == {"stop_seq": 4}
    assert m.asked_waits == []
    quiet = Double()
    ended, _ = _run(quiet, [{"op": "resume"}, {"op": "stop"}])
    assert "stopped" not in ended.fields and "verdict" not in ended.fields


class Window(sequence.Cycle):
    """A cycle done after `done_after` steps, or ending with a refusal at `refuse_at`."""

    limit = 7

    def __init__(self, done_after: int = 0, refuse_at: int = 0, expire_at: int = 0) -> None:
        self.done_after, self.refuse_at, self.expire_at = done_after, refuse_at, expire_at
        self.seen = 0
        self.named: list[str] = []

    def expired(self) -> bool:
        return bool(self.expire_at) and self.seen >= self.expire_at

    def after(self, reply: dict[str, Any], steps_completed: int,
              step: str) -> sequence.Stop | bool:
        self.seen += 1
        assert steps_completed == self.seen
        self.named.append(step)
        if self.refuse_at and self.seen == self.refuse_at:
            return sequence.Stop("unexpected_answer", "no frame", {"frame_reached": 3})
        return bool(self.done_after) and self.seen >= self.done_after

    def short(self, steps_completed: int) -> sequence.Stop | None:
        if self.done_after and self.seen >= self.done_after:
            return None
        return sequence.Stop(None, "", {"verdict": contract.TIMEOUT})

    def fields(self) -> dict[str, Any]:
        return {"until_frame": 99}


def test_a_cycle_repeats_the_list_until_it_is_done_and_every_ending_carries_its_fields() -> None:
    held = {"op": "status", recording.RECORDED: {"value": 1}}
    window = Window(done_after=5)
    ended, calls = _run(Double(), [held, {"op": "read_memory"}], cycle=window)
    assert calls == ["status", "read_memory", "status", "read_memory", "status"]
    # THE CYCLE NAMES A STEP AS EVERY MESSAGE DOES: inside its pass, from 1.
    assert window.named[2:4] == ["step 1 ('status') of pass 2", "step 2 ('read_memory') of pass 2"]
    assert ended.fields["until_frame"] == 99
    assert ended.fields["verdict"] == contract.TARGET      # a cycle waited for its window
    assert ended.held == 3


def test_a_cycle_ends_on_its_own_refusal_its_bound_or_its_clock() -> None:
    held = {"op": "status", recording.RECORDED: {"value": 1}}
    ended, _ = _run(Double(), [held], cycle=Window(refuse_at=3))
    assert ended.code == "unexpected_answer" and ended.message == "no frame"
    assert ended.fields["frame_reached"] == 3 and ended.fields["until_frame"] == 99
    assert ended.fields["steps_completed"] == 3 and ended.held == 3
    assert ended.fields["keep_last"] is True
    ended, calls = _run(Double(), [held], cycle=Window())
    assert len(calls) == Window.limit and ended.fields["verdict"] == contract.TIMEOUT
    assert ended.held == Window.limit and ended.fields["failed_at"] == sequence.none_failed()
    ended, calls = _run(Double(), [{"op": "status"}], cycle=Window(expire_at=2))
    assert len(calls) == 2 and ended.fields["verdict"] == contract.TIMEOUT
    ended, _ = _run(Double(), [{"op": "read_memory"}], cycle=Window(), fail="read_memory")
    assert ended.code == "step_failed" and ended.fields["until_frame"] == 99


def test_a_cycle_reports_no_line_per_step_and_a_list_reports_one_per_step() -> None:
    lines: list[str] = []
    def heard(progress: float, total: float | None, message: str) -> None:
        lines.append(message)
    _run(Double(), [{"op": "status"}, {"op": "read_memory"}], progress=heard, name="drive")
    assert lines == ["drive step 1 of 2 (status): working",
                     "drive step 2 of 2 (read_memory): working"]
    lines.clear()
    _run(Double(), [{"op": "status"}], cycle=Window(done_after=2), progress=heard)
    assert lines == []


def test_the_account_keeps_the_last_step_unless_a_step_failed_and_hands_on_what_ended_it() -> None:
    ended, _ = _run(Double(), [{"op": "status"}, {"op": "read_memory"}], fail="read_memory")
    assert ended.fields["keep_last"] is False
    assert ended.fields["also"] == [{"status": "INVALID", "code": "bad_argument",
                                     "message": "no"}]
    ended, _ = _run(Double(), [{"op": "read_memory", "value": 2,
                                recording.RECORDED: {"value": 3}}])
    assert ended.fields["keep_last"] is False and ended.fields["also"] == [
        {"status": "ok", "value": 2}]
    ended, _ = _run(Double(waits=["stopped"]), [{"op": "resume"}])
    assert ended.fields["keep_last"] is True
    assert ended.fields["also"] == [{"stop_seq": 9, "pc": "0x10"}]
    for m, steps, settle in ((Double(waits=["running"]), [{"op": "resume"},
                                                          {"op": "read_memory"}], 5.0),
                             (Double(waits=["running"]), [{"op": "resume"},
                                                          {"op": "read_memory"}], 0.0),
                             (Double(missed_ops=frozenset({"log_wait"})), [{"op": "log_wait"}],
                              5.0)):
        ended, _ = _run(m, steps, settle=settle)
        assert ended.fields["keep_last"] is True and ended.fields["also"] is None


def test_held_counts_only_the_steps_that_carried_a_recorded_answer_on_every_ending() -> None:
    held: dict[str, Any] = {"op": "status", recording.RECORDED: {"value": 1}}
    cases: list[tuple[Double, list[dict[str, Any]], float]] = [
            (Double(), [held, {"op": "status"}, held], 5.0),
            (Double(waits=["running"]), [held, {"op": "resume"}, {"op": "read_memory"}], 0.0),
            (Double(waits=["gone"]), [held, {"op": "resume"}, {"op": "read_memory"}], 5.0),
            (Double(waits=["stopped"]), [held, {"op": "resume"}], 5.0)]
    for m, steps, settle in cases:
        ended, _ = _run(m, steps, settle=settle)
        assert ended.held == len([s for s in steps if s is held]), ended


def test_a_machine_may_begin_a_list_as_stopped_whatever_its_flag_says() -> None:
    m = Double(running=True, began=False, waits=["stopped"])
    ended, calls = _run(m, [{"op": "send_keys"}])
    assert calls == ["send_keys"] and m.asked_waits == []
    assert "verdict" not in ended.fields and "still_running" not in ended.fields


def test_a_list_begun_running_that_released_nothing_waits_for_no_stop_at_its_tail() -> None:
    """Keys sent to a running program, a breakpoint declared: the list was not heading for a
    stop, so it hands the machine back running instead of sitting out its bound; one that
    released the machine itself still waits for the stop it was heading for."""
    m = Double(running=True, can_stop=True, waits=["stopped"])
    ended, calls = _run(m, [{"op": "send_keys"}, {"op": "send_keys"}])
    assert calls == ["send_keys", "send_keys"] and m.asked_waits == [], m.asked_waits
    assert ended.fields["still_running"] is True and "verdict" not in ended.fields, ended.fields
    released = Double(running=True, can_stop=True, waits=["stopped", "stopped"])
    ended, _ = _run(released, [{"op": "send_keys"}, {"op": "resume"}])
    assert released.asked_waits[-1] == (5.0, True), released.asked_waits   # the tail's


def test_a_stop_is_only_met_by_a_step_after_the_machine_ran_and_a_later_release_forgets_it(
        ) -> None:
    # A list that never ran the machine meets no stop, whatever `running()` says after a step.
    m = Double(rests=True)
    ended, _ = _run(m, [{"op": "status"}])
    assert "stopped" not in ended.fields
    # A stop met, then a release: the tail waits for the new stop, not the old one.
    m = Double(rests=True, waits=["stopped"])
    ended, _ = _run(m, [{"op": "resume"}, {"op": "stop"}, {"op": "resume"}])
    assert ended.fields["stopped"] == {"stop_seq": 9, "pc": "0x10"}


def test_the_base_machine_and_cycle_cannot_stand_in_for_a_server() -> None:
    with pytest.raises(TypeError):
        sequence.SequenceMachine()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        sequence.Cycle()  # type: ignore[abstract]
    m = Double()
    assert m.entry("op", {"a": 1}) == {"op": "op", "reply": {"a": 1}}
    assert sequence.SequenceMachine.missed(m, "op", {}) is False
    assert sequence.SequenceMachine.rested(m, []) is None
    assert sequence.SequenceMachine.began_running(Double(running=True)) is True
    sequence.SequenceMachine.noted(m, "op", {})


def test_a_channel_that_fails_during_a_mid_list_wait_ends_the_list_with_what_ran() -> None:
    """A terminal that overflows, or a machine that dies, while the list waits for a stop: the
    caller gets the account of what ran, the failure as its end, never a bare refusal that hides
    the steps already sent."""
    m = Double(waits=[contract.Invalid("unexpected_answer", "the terminal buffer overflowed")])
    ended, calls = _run(m, [{"op": "send_keys"}, {"op": "resume"}, {"op": "read_memory"}])
    assert calls == ["send_keys", "resume"], calls
    assert ended.code == "unexpected_answer" and ended.fields["failed_at"] == 2, ended
    assert "overflowed" in ended.message and "step 3 ('read_memory')" in ended.message, ended
    assert [e["op"] for e in ended.fields["ran"]] == ["send_keys", "resume"]


def test_a_channel_that_fails_during_the_tail_s_wait_ends_with_what_ran() -> None:
    m = Double(waits=[contract.Invalid("session_broken", "the stub hung up")])
    ended, _ = _run(m, [{"op": "status"}, {"op": "resume"}])
    assert ended.code == "session_broken" and "stub hung up" in ended.message, ended
    assert [e["op"] for e in ended.fields["ran"]] == ["status", "resume"]


def test_where_an_act_stopped_counts_from_one() -> None:
    assert sequence.where_stopped(0) == "at step 1"
    assert sequence.where_stopped(sequence.none_failed()) == "after its last step"


def test_a_refusal_carrying_the_list_s_own_fields_ends_it_all_the_same() -> None:
    """A wait's refusal that names a `failed_at` of its own is the list's to place: the list's
    ending states where it failed, and the refusal's other fields ride beside it."""
    e = contract.Invalid("unexpected_answer", "cut", failed_at=7, keep_last=False, extra=1)
    assert sequence._own(e) == {"extra": 1}
