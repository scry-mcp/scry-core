"""The window doubles servers run their `start` and `window` against: an emulator that opens its
window where it was asked, and four ways the desk can differ."""

from __future__ import annotations

from scry_core import window as w
from scry_core.window_stand_ins import hosts

PID = 7


def _asked(request: w.WindowRequest | None) -> hosts.Obeying:
    return hosts.Obeying(lambda: None if request is None else (PID, request))


def test_an_emulator_that_was_asked_for_no_window_lists_none() -> None:
    assert _asked(None).windows() == []


def test_the_window_opens_on_the_asked_display_and_fills_it_when_asked_to() -> None:
    windowed = _asked(w.WindowRequest(1, False))
    state = w.state_of(PID, windowed.windows(), windowed.displays(), windowed.above)
    assert state is not None and state.display == 1 and not state.fullscreen and state.front
    filled = _asked(w.WindowRequest(1, True))
    state = w.state_of(PID, filled.windows(), filled.displays(), filled.above)
    assert state is not None and state.display == 1 and state.fullscreen


def test_absent_lists_no_window_even_when_one_was_asked() -> None:
    assert hosts.Absent(lambda: (PID, w.WindowRequest(0, False))).windows() == []


def test_covered_is_off_screen_until_activated() -> None:
    covered = hosts.Covered(lambda: (PID, w.WindowRequest(0, False)))
    assert [s.onscreen for s in covered.windows()] == [False]
    covered.activate(covered.windows()[0])
    assert [s.onscreen for s in covered.windows()] == [True]


def test_dragged_lists_the_window_on_the_other_display() -> None:
    dragged = hosts.Dragged(lambda: (PID, w.WindowRequest(0, False)))
    state = w.state_of(PID, dragged.windows(), dragged.displays(), dragged.above)
    assert state is not None and state.display == 1


def test_stuck_is_listed_but_never_shown_whatever_is_done() -> None:
    stuck = hosts.Stuck(lambda: (PID, w.WindowRequest(0, False)))
    stuck.activate(stuck.windows()[0])
    assert [s.onscreen for s in stuck.windows()] == [False]


def test_bordered_never_fills_the_display_it_was_asked_to() -> None:
    bordered = hosts.Bordered(lambda: (PID, w.WindowRequest(0, True)))
    state = w.state_of(PID, bordered.windows(), bordered.displays(), bordered.above)
    assert state is not None and state.display == 0 and not state.fullscreen


def test_late_lists_the_window_only_after_a_number_of_readings() -> None:
    late = hosts.Late(lambda: (PID, w.WindowRequest(0, False)), after=2)
    assert [len(late.windows()) for _ in range(4)] == [0, 0, 1, 1]


def test_with_auxiliary_lists_a_small_window_of_the_pid_before_its_main_one() -> None:
    aux = hosts.WithAuxiliary(lambda: (PID, w.WindowRequest(1, False)))
    listed = aux.windows()
    assert [s.pid for s in listed] == [PID, PID]
    first, main = (s.bounds[2] * s.bounds[3] for s in listed)
    assert first < main
