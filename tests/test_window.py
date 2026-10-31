"""`scry_core.window`: the window a server was asked for, judged from what the host lists. The
host is a double that lists windows front to back and answers what is above one; the macOS host
has its own tests in `test_window_host.py`."""

from __future__ import annotations

import pytest

from scry_core import window as w
from scry_core.reply_contract import Invalid

TWO = [w.Display(0, (0, 0, 2048, 1152)), w.Display(1, (2048, 0, 2048, 1152))]
PID, OTHER = 100, 200


def state_of(pid: int, listed: list[w.Seen], displays: list[w.Display] = TWO
             ) -> w.WindowState | None:
    return w.state_of(pid, listed, displays, w.above_in_order(listed))


def seen(pid: int, bounds: w.Rect, onscreen: bool = True, number: int = 1) -> w.Seen:
    return w.Seen(pid=pid, number=number, bounds=bounds, onscreen=onscreen)


class Host:
    """A desk that is told what it lists; `after` polls make a window appear, and `activate`
    records its calls and, when `brings`, puts the window in front."""

    def __init__(self, listed: list[w.Seen], displays: list[w.Display] = TWO,
                 appears_after: int = 0, brings: bool = True, refuses: str = "") -> None:
        self.listed, self._displays, self.polls = listed, displays, 0
        self.appears_after, self.brings, self.refuses = appears_after, brings, refuses
        self.activated: list[int] = []

    def displays(self) -> list[w.Display]:
        return self._displays

    def windows(self) -> list[w.Seen]:
        self.polls += 1
        return self.listed if self.polls > self.appears_after else []

    def above(self, window: w.Seen) -> list[w.Seen]:
        return w.above_in_order(self.listed)(window)

    def activate(self, window: w.Seen) -> str:
        self.activated.append(window.number)
        if self.brings:
            self.listed = [seen(window.pid, window.bounds, True, window.number),
                           *(x for x in self.listed if x.number != window.number)]
        return self.refuses


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# ---- the request -------------------------------------------------------------------------------

def test_a_watched_start_asking_nothing_opens_on_the_main_display_windowed() -> None:
    assert w.request(None, None, shared=True, display_count=2) == w.WindowRequest(0, False)


def test_a_watched_start_keeps_what_it_asked() -> None:
    assert w.request(1, True, shared=True, display_count=2) == w.WindowRequest(1, True)


def test_an_unwatched_start_has_no_window_to_ask_for() -> None:
    assert w.request(None, None, shared=False, display_count=2) is None


@pytest.mark.parametrize(("display", "fullscreen", "named"),
                         [(0, None, "display"), (None, False, "fullscreen"), (1, True, "display")])
def test_an_unwatched_start_refuses_a_window_argument_rather_than_ignoring_it(
        display: int | None, fullscreen: bool | None, named: str) -> None:
    with pytest.raises(Invalid) as e:
        w.request(display, fullscreen, shared=False, display_count=2)
    assert e.value.code == "bad_argument" and named in str(e.value) and "shared" in str(e.value)


@pytest.mark.parametrize("display", [2, 7, -1])
def test_a_display_the_host_lacks_is_refused_naming_how_many_it_has(display: int) -> None:
    with pytest.raises(Invalid) as e:
        w.request(display, None, shared=True, display_count=2)
    assert e.value.code == "bad_argument"
    message = str(e.value)
    assert "2 displays" in message and "0 to 1" in message and str(display) in message


def test_a_single_display_host_says_so_in_the_singular() -> None:
    with pytest.raises(Invalid) as e:
        w.request(1, None, shared=True, display_count=1)
    assert "1 display (0)" in str(e.value)


def test_a_host_with_no_display_online_is_a_host_failure_not_a_bad_argument() -> None:
    with pytest.raises(Invalid) as e:
        w.request(None, None, shared=True, display_count=0)
    assert e.value.code == "host_failed" and "display" in str(e.value)


# ---- what the host shows -----------------------------------------------------------------------

def test_a_window_is_read_as_the_display_holding_its_centre() -> None:
    state = state_of(PID, [seen(PID, (2300, 100, 400, 300))], TWO)
    assert state is not None and state.display == 1 and state.onscreen


def test_a_window_straddling_two_displays_belongs_to_the_one_with_its_centre() -> None:
    left = state_of(PID, [seen(PID, (1800, 100, 400, 300))], TWO)      # centre at 2000
    right = state_of(PID, [seen(PID, (1900, 100, 400, 300))], TWO)     # centre at 2100
    assert (left.display, right.display) == (0, 1)      # type: ignore[union-attr]


def test_a_window_on_no_display_is_said_to_be_on_none() -> None:
    state = state_of(PID, [seen(PID, (9000, 9000, 400, 300))], TWO)
    assert state is not None and state.display == w.NO_DISPLAY


def test_a_pid_owning_no_window_has_no_state() -> None:
    assert state_of(PID, [seen(OTHER, (0, 0, 400, 300))], TWO) is None


def test_the_largest_window_of_the_pid_is_the_emulators() -> None:
    small, big = seen(PID, (0, 0, 100, 30), number=1), seen(PID, (50, 50, 640, 400), number=2)
    state = state_of(PID, [small, big], TWO)
    assert state is not None and state.bounds == (50, 50, 640, 400)


def test_a_window_the_size_of_its_display_is_fullscreen() -> None:
    full = state_of(PID, [seen(PID, (2048, 0, 2048, 1152))], TWO)
    inset = state_of(PID, [seen(PID, (2048, 0, 2048, 1100))], TWO)
    assert (full.fullscreen, inset.fullscreen) == (True, False)     # type: ignore[union-attr]


def test_a_window_nothing_covers_is_in_front() -> None:
    state = state_of(PID, [seen(PID, (100, 100, 400, 300))], TWO)
    assert state is not None and state.front


def test_a_window_with_another_applications_window_over_its_centre_is_not_in_front() -> None:
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    state = state_of(PID, [cover, seen(PID, (100, 100, 400, 300))], TWO)
    assert state is not None and state.onscreen and not state.front


def test_the_emulators_own_smaller_window_over_it_does_not_cover_it() -> None:
    """A debugger window opened by the same process is not another application in the way."""
    own = seen(PID, (250, 200, 100, 100), number=2)
    state = state_of(PID, [own, seen(PID, (100, 100, 400, 300))])
    assert state is not None and state.front


def test_a_window_only_partly_covered_away_from_its_centre_is_still_in_front() -> None:
    corner = seen(OTHER, (0, 0, 120, 120), number=2)
    state = state_of(PID, [corner, seen(PID, (100, 100, 400, 300))], TWO)
    assert state is not None and state.front


def test_a_window_behind_a_cover_that_is_not_on_screen_is_in_front_of_nothing_either() -> None:
    """A window on another Space is not on screen, and is not in front of anything shown."""
    state = state_of(PID, [seen(PID, (100, 100, 400, 300), onscreen=False)], TWO)
    assert state is not None and not state.onscreen and not state.front


def test_a_cover_on_another_space_does_not_cover() -> None:
    away = seen(OTHER, (0, 0, 2048, 1152), onscreen=False, number=2)
    state = state_of(PID, [away, seen(PID, (100, 100, 400, 300))], TWO)
    assert state is not None and state.front


def test_the_state_is_the_reply_block() -> None:
    state = state_of(PID, [seen(PID, (2048, 0, 2048, 1152))], TWO)
    assert state is not None and state.block() == {
        "display": 1, "bounds": {"x": 2048, "y": 0, "width": 2048, "height": 1152},
        "onscreen": True, "front": True, "fullscreen": True}


# ---- waiting for the window --------------------------------------------------------------------

def test_a_window_already_there_is_returned_without_waiting() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300))])
    state = w.wait_visible(PID, 0, 5.0, host, clock, clock.sleep)
    assert state.display == 0 and clock.slept == []


def test_a_window_that_appears_late_is_waited_for() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300))], appears_after=3)
    state = w.wait_visible(PID, 0, 5.0, host, clock, clock.sleep)
    assert state.onscreen and host.polls == 4 and len(clock.slept) == 3


def test_a_window_that_never_appears_is_a_refusal_after_the_bound_not_before() -> None:
    clock = Clock()
    host = Host([], appears_after=0)
    with pytest.raises(Invalid) as e:
        w.wait_visible(PID, 0, 2.0, host, clock, clock.sleep)
    assert e.value.code == "window_not_visible"
    assert clock.now >= 2.0 and "no window" in str(e.value) and str(PID) in str(e.value)
    assert "seen" not in e.value.fields and e.value.fields["asked_display"] == 0


def test_a_window_on_the_wrong_display_is_a_refusal_naming_both_displays() -> None:
    clock = Clock()
    host = Host([seen(PID, (2300, 100, 400, 300))])
    with pytest.raises(Invalid) as e:
        w.wait_visible(PID, 0, 1.0, host, clock, clock.sleep)
    assert e.value.code == "window_not_visible"
    assert "display 1" in str(e.value) and "display 0" in str(e.value)
    assert e.value.fields["seen"]["display"] == 1


def test_a_window_that_moves_onto_the_asked_display_in_time_is_accepted() -> None:
    clock = Clock()
    away, there = seen(PID, (2300, 100, 400, 300)), seen(PID, (100, 100, 400, 300))
    host = Host([away])
    real_windows = host.windows

    def moving() -> list[w.Seen]:
        listed = real_windows()
        if host.polls >= 3:
            host.listed = [there]
        return listed
    host.windows = moving       # type: ignore[method-assign]
    assert w.wait_visible(PID, 0, 5.0, host, clock, clock.sleep).display == 0


def test_a_window_on_the_right_display_but_off_screen_is_returned_and_says_so() -> None:
    """The protocol reads `onscreen` in the reply: not being shown is the caller's to judge."""
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)])
    state = w.wait_visible(PID, 0, 1.0, host, clock, clock.sleep)
    assert state.display == 0 and not state.onscreen


# ---- bringing it forward -----------------------------------------------------------------------

def test_a_covered_window_is_brought_in_front_and_read_back() -> None:
    clock = Clock()
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (100, 100, 400, 300), onscreen=False)])
    state = w.bring_front(PID, host, 3.0, clock, clock.sleep)
    assert state.onscreen and state.front and host.activated == [1]


def test_a_window_that_does_not_come_forward_is_a_refusal_with_what_was_read_back() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep)
    assert e.value.code == "window_not_visible" and "not on screen" in str(e.value)
    assert e.value.fields["seen"]["onscreen"] is False and clock.now >= 1.0


def test_a_window_on_screen_but_covered_says_it_is_covered() -> None:
    clock = Clock()
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (100, 100, 400, 300))], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep)
    assert "covered" in str(e.value)


def test_the_activation_the_host_refuses_is_said_with_its_reason() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False,
                refuses="the window server would not switch Spaces")
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep)
    assert "would not switch Spaces" in str(e.value)


def test_a_pid_with_no_window_cannot_be_brought_forward() -> None:
    clock = Clock()
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, Host([]), 1.0, clock, clock.sleep)
    assert e.value.code == "window_not_visible" and "no window" in str(e.value)
    assert clock.now >= 1.0


def test_a_window_already_in_front_is_not_activated() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300))])
    state = w.bring_front(PID, host, 1.0, clock, clock.sleep)
    assert state.front and host.activated == []


def test_a_window_gone_from_the_list_has_nothing_known_above_it() -> None:
    gone = seen(PID, (0, 0, 400, 300))
    assert w.above_in_order([seen(OTHER, (0, 0, 2048, 1152), number=2)])(gone) == []


# ---- launching behind -------------------------------------------------------------------------

@pytest.mark.parametrize(("background", "watched", "behind"), [
    (None, True, False), (None, False, True), (True, True, True), (False, False, False)])
def test_a_launch_goes_behind_unless_watched_and_the_caller_may_say_otherwise(
        background: bool | None, watched: bool, behind: bool) -> None:
    assert w.judge_background(background, watched) is behind


def test_the_background_hint_is_set_or_removed_never_inherited() -> None:
    base = {"PATH": "/bin", w.BACKGROUND_VAR: "1"}
    assert w.launch_environment(base, background=True) == {"PATH": "/bin", w.BACKGROUND_VAR: "1"}
    assert w.launch_environment(base, background=False) == {"PATH": "/bin"}
    assert w.launch_environment({"PATH": "/bin"}, background=True)[w.BACKGROUND_VAR] == "1"
    assert base[w.BACKGROUND_VAR] == "1"            # the caller's mapping is left as it was
