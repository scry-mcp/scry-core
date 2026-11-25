"""`scry_core.presence`: the states a session's calls set, the one writer that delivers only the
latest (a quick call still shown, a failed delivery sent again), a delivery that fails said in
`reply` and never in a call's own reply, the pointer a session moves, and the declaration of
which tools drive held against a registry."""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from scry_core import boundary, overlay, presence
from scry_core.envelope import Envelope

#: Long enough for an idle writer to have sent anything it was going to.
QUIET_S = 0.2


class _Adapter:
    """Records every state shown; `gate` holds a delivery until it is set, `fail` raises."""

    def __init__(self) -> None:
        self.shown: list[presence.State] = []
        self.payloads: list[presence.Payload] = []
        self.gate = threading.Event()
        self.gate.set()
        self.fail: BaseException | None = None
        self.entered = threading.Event()
        #: Whether `still()` held at each repaint asked for.
        self.repaints: list[bool] = []
        self.repaint_fails = False
        self.wakes = 0

    def show(self, state: presence.State, payload: presence.Payload) -> None:
        self.entered.set()
        self.gate.wait(5)
        if self.fail is not None:
            raise self.fail
        self.shown.append(state)
        self.payloads.append(payload)

    def wake(self) -> None:
        self.wakes += 1

    def repaint(self, still: Callable[[], bool]) -> None:
        self.repaints.append(still())
        if self.repaint_fails:
            raise RuntimeError("the console is gone")


def _call(tool: str, nested: bool = False, read_only: bool = False,
          **given: Any) -> boundary.Call:
    return boundary.Call(tool, given, nested, read_only)


def _settle(adapter: _Adapter, n: int) -> None:
    """Until `n` states were shown, then quiet: the assertion after it sees the whole run."""
    deadline = time.monotonic() + 5
    while len(adapter.shown) < n and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(QUIET_S)


def _open(adapter: _Adapter, driving: tuple[str, ...] = ("run_for",),
          asked: overlay.Overlay = overlay.OVERLAY,
          look: presence.Look = presence.LOOK) -> presence.Presence:
    shown = presence.Presence.open(adapter, driving, asked, look)
    assert shown.held is not None and shown.reply() is True and shown.adapter is adapter
    return shown.held


def test_open_shows_held_before_it_answers_and_starts_a_daemon_writer() -> None:
    a = _Adapter()
    p = _open(a)
    assert a.shown == ["held"] and p.reply() is True
    assert p._thread.is_alive() and p._thread.daemon, "a server that exits must not wait on it"
    p.close()


def test_close_wakes_a_repaint_that_waits_for_the_lock() -> None:
    """The close happens under the lock, so no release would wake a repaint waiting for it."""
    a = _Adapter()
    p = _open(a)
    p.close()
    assert a.wakes == 1


@pytest.mark.parametrize(("raised", "why"), [
    (presence.Unavailable("no window to draw on"), "no window to draw on"),
    (OSError("refused"), "the first delivery failed: OSError: refused"),
])
def test_open_that_cannot_draw_says_why_in_place_of_true(raised: BaseException, why: str) -> None:
    a = _Adapter()
    a.fail = raised
    shown = presence.Presence.open(a, ("run_for",))
    assert shown.held is None and shown.reply() == {"available": False, "why": why}
    shown.close()                                   # nothing to stop: a no-op


def test_a_driving_call_turns_it_acting_and_its_end_back_to_held() -> None:
    a = _Adapter()
    p = _open(a)
    p.began(_call("run_for"))
    _settle(a, 2)
    p.ended(_call("run_for"), "ok")
    _settle(a, 3)
    assert a.shown == ["held", "acting", "held"]
    p.close()


def test_a_still_call_leaves_the_state_held() -> None:
    a = _Adapter()
    p = _open(a)
    p.began(_call("registers", read_only=True))
    with p._cv:
        assert (p._want, p._pulse) == ("held", False), "a still call set no state"
    p.ended(_call("registers", read_only=True), "ok")
    time.sleep(QUIET_S)
    assert a.shown == ["held"]
    p.close()


def test_the_writer_sends_only_the_latest_state_once_a_slow_delivery_returns() -> None:
    a = _Adapter()
    p = _open(a)
    a.gate.clear()
    a.entered.clear()
    p.began(_call("run_for"))                      # in flight, held at the gate
    assert a.entered.wait(5)
    p.ended(_call("run_for"), "ok")
    p.began(_call("run_for"))
    p.ended(_call("run_for"), "ok")         # three changes while the first is in flight
    a.gate.set()
    _settle(a, 3)
    # the one in flight lands, then the latest; the two between are skipped, never reordered
    assert a.shown == ["held", "acting", "held"]
    p.close()


def test_a_call_never_waits_on_a_delivery_in_flight() -> None:
    a = _Adapter()
    p = _open(a)
    a.gate.clear()
    a.entered.clear()
    p.began(_call("run_for"))
    assert a.entered.wait(5)                # the writer is stuck in the adapter
    t = time.monotonic()
    p.ended(_call("run_for"), "ok")
    p.began(_call("run_for"))
    assert time.monotonic() - t < 0.1
    a.gate.set()
    p.close()


def test_a_driving_call_over_before_the_writer_woke_is_still_shown_acting() -> None:
    a = _Adapter()
    p = _open(a)
    with p._cv:                             # the writer cannot wake between the two
        p.began(_call("run_for"))
        p.ended(_call("run_for"), "ok")
    _settle(a, 3)
    assert a.shown == ["held", "acting", "held"]
    p.close()


def test_a_delivery_that_fails_is_said_by_reply_and_sent_again_until_it_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(presence, "RETRY_S", 0.05)
    a = _Adapter()
    p = _open(a)
    a.fail = ConnectionError("the channel dropped")
    p.began(_call("run_for"))
    p.ended(_call("run_for"), "ok")
    deadline = time.monotonic() + 5
    while p.reply() is True and time.monotonic() < deadline:
        time.sleep(0.01)
    assert p.reply() == {"available": False,
                         "why": "a delivery failed: ConnectionError: the channel dropped"}
    a.fail = None                           # the emulator answers again, nothing else changes
    _settle(a, 3)
    assert a.shown == ["held", "acting", "held"] and p.reply() is True
    p.close()


def test_redeliver_sends_the_same_state_again() -> None:
    a = _Adapter()
    p = _open(a)
    p.redeliver()
    _settle(a, 2)
    assert a.shown == ["held", "held"]
    p.close()


def test_close_lets_a_stuck_delivery_land_and_sends_nothing_after_it() -> None:
    a = _Adapter()
    p = _open(a)
    a.gate.clear()
    a.entered.clear()
    p.began(_call("run_for"))
    assert a.entered.wait(5)                # the writer is inside `acting`
    p.ended(_call("run_for"), "ok")                      # a change that must never be sent
    t = time.monotonic()
    p.close()
    assert time.monotonic() - t < presence.CLOSE_WAIT_S + 0.5
    a.gate.set()
    time.sleep(QUIET_S)
    assert a.shown == ["held", "acting"] and not p._thread.is_alive()


def test_close_wakes_an_idle_writer() -> None:
    a = _Adapter()
    p = _open(a)
    assert p._thread.is_alive()
    p.close()
    assert not p._thread.is_alive()


def test_one_string_for_the_driving_tools_is_refused() -> None:
    with pytest.raises(TypeError, match="never one string"):
        presence.Presence(_Adapter(), "run_for")
    with pytest.raises(TypeError, match="never one string"):
        presence.check_classified(["run_for"], "run_for", [])


def test_a_slot_routes_to_the_session_s_presence_and_to_nothing_without_one() -> None:
    a = _Adapter()
    current: list[presence.Presence | None] = [None]
    slot = presence.Slot(lambda: current[0])
    slot.began(_call("run_for"))                   # no session: nothing happens
    held = _open(a)
    current[0] = held
    slot.began(_call("run_for"))
    _settle(a, 2)
    slot.ended(_call("run_for"), "ok")
    _settle(a, 3)
    current[0] = None
    slot.ended(_call("run_for"), "ok")
    assert a.shown == ["held", "acting", "held"]
    held.close()


def test_a_failing_delivery_never_reaches_the_reply_of_the_call_it_marks() -> None:
    a = _Adapter()
    p = _open(a)
    a.fail = RuntimeError("the emulator is gone")
    lock = boundary.ServerLock()

    def invoke(fn: Callable[..., Any], bound: inspect.BoundArguments) -> dict[str, Any]:
        return dict(fn(*bound.args, **bound.kwargs))

    b = boundary.Boundary(Envelope("t", instructions="i", refusal=lambda *a: {}), lock,
                          invoke=invoke, end=lambda n, o: ("stopped", None),
                          refusal_line=lambda n, r: n, session_block=lambda whole: {},
                          take_cancelled=lambda: None, keep_cancelled=lambda r: None,
                          doc=lambda n, t: t, listener=presence.Slot(lambda: p))

    @b.tool("Run", summary=lambda args, reply: "ran")
    def run_for() -> dict[str, Any]:
        return {"status": "ok", "ran": True}

    assert run_for() == {"summary": "ran", "status": "ok", "ran": True, "session": {}}
    deadline = time.monotonic() + 5
    while p.reply() is True and time.monotonic() < deadline:
        time.sleep(0.01)
    assert p.reply() == {"available": False,
                         "why": "a delivery failed: RuntimeError: the emulator is gone"}
    p.close()


def test_check_classified_names_every_tool_off_its_one_side() -> None:
    assert presence.check_classified(["a", "b"], {"a"}, {"b"}) == []
    assert presence.check_classified(["a", "b", "c"], {"a", "x"}, {"a", "b"}) == [
        "c: registered but declared neither driving nor still",
        "x: declared but not registered",
        "a: declared both driving and still"]


def test_held_is_a_share_of_acting_whatever_acting_is() -> None:
    assert presence.Look(acting_alpha=0.6).held_alpha == pytest.approx(0.2)
    assert presence.LOOK.held_alpha == pytest.approx(presence.LOOK.acting_alpha / 3)


def test_driving_lights_a_block_as_a_driving_call_would() -> None:
    a = _Adapter()
    shown = presence.Presence.open(a, ())
    with shown.driving():
        _settle(a, 2)
    _settle(a, 3)
    assert a.shown == ["held", "acting", "held"]
    shown.close()
    with presence.Shown().driving():                 # not drawn: the block still runs
        pass
    assert presence.Shown().reply() is False


def test_the_held_after_a_driving_call_is_repainted_once_and_never_at_open() -> None:
    a = _Adapter()
    p = _open(a)
    time.sleep(QUIET_S)
    assert a.repaints == []                  # `open` shows held itself, before any call
    p.began(_call("run_for"))
    _settle(a, 2)
    p.ended(_call("run_for"), "ok")
    _settle(a, 3)
    assert a.shown == ["held", "acting", "held"] and a.repaints == [True]
    p.close()


def test_a_call_that_begins_before_the_repaint_makes_it_moot() -> None:
    a = _Adapter()
    p = _open(a)
    p.began(_call("run_for"))
    _settle(a, 2)
    a.gate.clear()                           # the held after the call is held in delivery...
    a.entered.clear()
    p.ended(_call("run_for"), "ok")
    assert a.entered.wait(5)
    p.began(_call("run_for"))                       # ...while the next call begins
    a.gate.set()
    _settle(a, 4)
    assert a.shown == ["held", "acting", "held", "acting"] and a.repaints == []
    p.close()


def test_a_repaint_that_fails_is_said_by_reply_until_a_delivery_lands() -> None:
    a = _Adapter()
    a.repaint_fails = True
    p = _open(a)
    p.began(_call("run_for"))
    p.ended(_call("run_for"), "ok")
    _settle(a, 2)
    deadline = time.monotonic() + 5
    while p.reply() is True and time.monotonic() < deadline:
        time.sleep(0.01)
    assert p.reply() == {"available": False,
                         "why": "a repaint failed: RuntimeError: the console is gone"}
    p.began(_call("run_for"))
    _settle(a, 4)
    assert a.shown[-1] == "acting" and p.reply() is True
    p.close()


def test_a_repaint_reads_still_false_once_a_call_began_while_it_ran() -> None:
    seen: list[bool] = []

    class Slow(_Adapter):
        def repaint(self, still: Callable[[], bool]) -> None:
            seen.append(still())
            p.began(_call("run_for"))              # a call begins while the repaint runs
            seen.append(still())

    a = Slow()
    p = _open(a)
    p.began(_call("run_for"))
    p.ended(_call("run_for"), "ok")
    _settle(a, 3)
    assert seen[:2] == [True, False]
    p.close()


def _until(a: _Adapter, ok: Callable[[presence.Payload], bool], after: int = 0
           ) -> presence.Payload:
    """The first payload delivered past the first `after` for which `ok` holds, waiting."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        for payload in list(a.payloads)[after:]:
            if ok(payload):
                return payload
        time.sleep(0.01)
    raise AssertionError(f"never delivered; delivered {a.payloads}")


def test_the_pointer_and_its_buttons_reported_reach_the_payload() -> None:
    a = _Adapter()
    p = _open(a)
    p.button("left", True)                       # no pointer yet: nothing to report
    p.moved(10, 20)
    p.button("left", True)
    p.button("right", True)
    p.button("left", False)
    p.moved(11, 21)
    _until(a, lambda pl: pl.pointer == presence.Pointer(11, 21, ("right",)))
    p.close()


def test_the_recording_reported_reaches_the_payload_and_two_kinds_make_both() -> None:
    a = _Adapter()
    p = _open(a)
    assert a.payloads[0].recording == "none"
    p.recording("video", True)
    _until(a, lambda pl: pl.recording == "video")
    p.recording("audio", True)
    _until(a, lambda pl: pl.recording == "both")
    p.recording("video", False)
    _until(a, lambda pl: pl.recording == "audio")
    p.recording("audio", False)
    _until(a, lambda pl: pl.recording == "none", after=3)
    p.close()


def test_a_shown_session_forwards_the_recording_to_its_presence() -> None:
    a = _Adapter()
    p = _open(a)
    shown = presence.Shown(held=p, adapter=a)
    shown.recording("audio", True)
    _until(a, lambda pl: pl.recording == "audio")
    shown.recording("audio", False)
    _until(a, lambda pl: pl.recording == "none", after=1)
    shown.close()


def test_a_kind_started_twice_ends_with_one_end() -> None:
    a = _Adapter()
    p = _open(a)
    p.recording("audio", True)
    p.recording("audio", True)
    _until(a, lambda pl: pl.recording == "audio")
    p.recording("audio", False)
    _until(a, lambda pl: pl.recording == "none", after=1)
    p.close()


def test_a_recording_is_not_delivered_with_the_record_layer_off() -> None:
    a = _Adapter()
    p = _open(a, asked=overlay.Overlay(record=False))
    p.recording("video", True)
    p.began(_call("run_for"))
    _settle(a, 2)
    assert {pl.recording for pl in a.payloads} == {"none"}
    p.close()


def test_the_record_mark_is_red_and_blinks_once_a_second() -> None:
    assert (presence.LOOK.record_rgb, presence.LOOK.record_blink_s) == (0xFF3B30, 1.0)


def test_a_layer_not_asked_is_never_delivered() -> None:
    a = _Adapter()
    p = _open(a, asked=overlay.Overlay(pointer=False, record=False))
    p.moved(1, 2)
    p.recording("video", True)
    p.began(_call("run_for"))
    p.ended(_call("run_for"), "ok")
    _settle(a, 3)
    assert all(pl == presence.Payload(layers=("edge",)) for pl in a.payloads)
    p.close()


def test_a_session_without_presence_takes_input_reports_and_does_nothing() -> None:
    shown = presence.Shown()
    shown.moved(1, 1)
    shown.button("left", True)
    shown.recording("video", True)
    a = _Adapter()
    held = presence.Presence.open(a, ())
    held.moved(1, 2)
    _until(a, lambda pl: pl.pointer == presence.Pointer(1, 2))
    held.close()
