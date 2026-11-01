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
    assert w.request(None, None, shared=True, displays=TWO) == w.WindowRequest(0, False, (0, 0))


def test_a_watched_start_keeps_what_it_asked() -> None:
    assert w.request(1, True, shared=True, displays=TWO) == w.WindowRequest(1, True, (2048, 0))


def test_an_unwatched_start_has_no_window_to_ask_for() -> None:
    assert w.request(None, None, shared=False, displays=TWO) is None


@pytest.mark.parametrize(("display", "fullscreen", "named"),
                         [(0, None, "display"), (None, False, "fullscreen"), (1, True, "display")])
def test_an_unwatched_start_refuses_a_window_argument_rather_than_ignoring_it(
        display: int | None, fullscreen: bool | None, named: str) -> None:
    with pytest.raises(Invalid) as e:
        w.request(display, fullscreen, shared=False, displays=TWO)
    assert e.value.code == "bad_argument" and named in str(e.value) and "shared" in str(e.value)


@pytest.mark.parametrize("display", [2, 7, -1])
def test_a_display_the_host_lacks_is_refused_naming_how_many_it_has(display: int) -> None:
    with pytest.raises(Invalid) as e:
        w.request(display, None, shared=True, displays=TWO)
    assert e.value.code == "bad_argument"
    message = str(e.value)
    assert "2 displays" in message and "0 to 1" in message and str(display) in message


def test_a_single_display_host_says_so_in_the_singular() -> None:
    with pytest.raises(Invalid) as e:
        w.request(1, None, shared=True, displays=TWO[:1])
    assert "1 display (0)" in str(e.value)


def test_a_host_with_no_display_online_is_a_host_failure_not_a_bad_argument() -> None:
    with pytest.raises(Invalid) as e:
        w.request(None, None, shared=True, displays=[])
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


# ---- observing it ------------------------------------------------------------------------------

def test_observing_a_window_the_owner_dragged_to_another_display_answers_where_it_is() -> None:
    state = w.observe(PID, Host([seen(PID, (2300, 100, 400, 300))]))
    assert state.display == 1 and state.onscreen


def test_observing_names_no_display_so_asks_none_back() -> None:
    state = w.observe(PID, Host([seen(PID, (100, 100, 400, 300), onscreen=False)]))
    assert state.display == 0 and not state.onscreen


def test_observing_a_pid_with_no_window_is_a_refusal_that_sends_to_status() -> None:
    with pytest.raises(Invalid) as e:
        w.observe(PID, Host([]))
    assert e.value.code == "window_not_visible"
    assert "no window" in str(e.value) and str(PID) in str(e.value) and "status" in str(e.value)


# ---- bringing it forward -----------------------------------------------------------------------

def test_a_covered_window_is_brought_in_front_and_read_back() -> None:
    clock = Clock()
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (100, 100, 400, 300), onscreen=False)])
    state = w.bring_front(PID, host, 3.0, clock, clock.sleep, launched_behind=False)
    assert state.onscreen and state.front and host.activated == [1]


def test_the_window_activated_is_the_largest_of_the_pid_as_the_reading_picks_it() -> None:
    """MAME lists a small auxiliary window before its own; activating the first leaves the
    emulator's window where it was."""
    clock = Clock()
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (0, 652, 200, 200), number=7, onscreen=False),
                 seen(PID, (100, 100, 400, 300), number=1, onscreen=False)])
    state = w.bring_front(PID, host, 3.0, clock, clock.sleep, launched_behind=False)
    assert host.activated == [1], host.activated
    assert state.bounds == (100, 100, 400, 300)


def test_a_window_that_does_not_come_forward_is_a_refusal_with_what_was_read_back() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=False)
    assert e.value.code == "window_not_visible" and "not on screen" in str(e.value)
    assert e.value.fields["seen"]["onscreen"] is False and clock.now >= 1.0


def test_a_window_on_screen_but_covered_says_it_is_covered() -> None:
    clock = Clock()
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (100, 100, 400, 300))], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=False)
    assert "covered" in str(e.value)


def test_the_activation_the_host_refuses_is_said_with_its_reason() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False,
                refuses="the window server would not switch Spaces")
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=False)
    assert "would not switch Spaces" in str(e.value)


def test_a_pid_with_no_window_cannot_be_brought_forward() -> None:
    clock = Clock()
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, Host([]), 1.0, clock, clock.sleep, launched_behind=False)
    assert e.value.code == "window_not_visible" and "no window" in str(e.value)
    assert clock.now >= 1.0

def test_a_background_session_that_does_not_come_forward_says_a_background_app_cannot() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=True)
    message = str(e.value)
    assert "background=true" in message and "may be what keeps it behind" in message
    assert "background=false" in message


def test_a_session_not_launched_behind_never_blames_the_background() -> None:
    """THE CONTROL: the same failure without the hint carries no word about it."""
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False)
    with pytest.raises(Invalid) as e:
        w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=False)
    assert "background" not in str(e.value)


def test_a_background_session_that_does_come_forward_is_returned_not_refused() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300), onscreen=False)])
    state = w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=True)
    assert state.front


def test_a_window_already_in_front_is_not_activated() -> None:
    clock = Clock()
    host = Host([seen(PID, (100, 100, 400, 300))])
    state = w.bring_front(PID, host, 1.0, clock, clock.sleep, launched_behind=False)
    assert state.front and host.activated == []


def test_a_window_gone_from_the_list_has_nothing_known_above_it() -> None:
    gone = seen(PID, (0, 0, 400, 300))
    assert w.above_in_order([seen(OTHER, (0, 0, 2048, 1152), number=2)])(gone) == []


def test_a_window_that_moved_between_two_readings_is_still_found_by_its_handle() -> None:
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    before = seen(PID, (100, 100, 400, 300), number=1)
    after = seen(PID, (900, 500, 400, 300), number=1)
    assert w.above_in_order([cover, after])(before) == [cover]


def test_launched_behind_has_no_default_so_a_server_that_forgets_it_fails_aloud() -> None:
    clock = Clock()
    with pytest.raises(TypeError, match="launched_behind"):
        w.bring_front(PID, Host([seen(PID, (0, 0, 400, 300))]), 1.0, clock,  # type: ignore[call-arg]
                      clock.sleep)


# ---- what a server's start and window tool call --------------------------------------------------

def _desk(monkeypatch: pytest.MonkeyPatch, host: Host) -> None:
    monkeypatch.setattr(w, "host", lambda _platform="": host)
    monkeypatch.setattr(w, "WAIT_S", 0.0)


def test_requested_reads_the_displays_only_for_a_watched_start(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Counting(Host):
        asked = 0

        def displays(self) -> list[w.Display]:
            self.asked += 1
            return super().displays()

    counting = Counting([])
    _desk(monkeypatch, counting)
    assert w.requested(False, None, None) is None and counting.asked == 0
    w.requested(True, None, None)
    assert counting.asked == 1
    _desk(monkeypatch, Host([]))
    assert w.requested(True, 1, True) == w.WindowRequest(1, True, (2048, 0))
    with pytest.raises(Invalid) as e:
        w.requested(True, 2, None)
    assert e.value.code == "bad_argument" and "2 displays" in str(e.value)


def test_prove_returns_the_window_on_the_asked_display(monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([seen(PID, (2148, 100, 400, 300))]))
    assert w.prove(PID, w.WindowRequest(1, False, (2048, 0))).display == 1


def test_prove_refuses_a_fullscreen_that_does_not_fill_the_display(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([seen(PID, (100, 100, 400, 300))]))
    with pytest.raises(Invalid) as e:
        w.prove(PID, w.WindowRequest(0, True, (0, 0)))
    assert e.value.code == "window_not_visible" and "does not fill" in str(e.value)
    assert e.value.fields["asked_display"] == 0 and e.value.fields["seen"]["fullscreen"] is False


def test_prove_accepts_a_fullscreen_that_fills_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([seen(PID, (0, 0, 2048, 1152))]))
    assert w.prove(PID, w.WindowRequest(0, True, (0, 0))).fullscreen is True


def test_prove_waits_for_a_fullscreen_window_to_fill_the_display_it_first_appeared_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """An emulator placed by position shows its window first and goes full screen after."""
    class Growing(Host):
        def windows(self) -> list[w.Seen]:
            self.polls += 1
            bounds = (2048, 0, 2048, 1152) if self.polls > 3 else (2088, 40, 640, 400)
            return [seen(PID, bounds)]

    _desk(monkeypatch, Growing([]))
    monkeypatch.setattr(w, "WAIT_S", 5.0)
    monkeypatch.setattr(w, "POLL_S", 0.0)
    got = w.prove(PID, w.WindowRequest(1, True, (2048, 0)))
    assert got.fullscreen is True and got.display == 1


def test_prove_refuses_a_window_that_fills_a_different_display_than_the_one_asked(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Wanders(Host):
        def windows(self) -> list[w.Seen]:
            self.polls += 1
            bounds = (0, 0, 2048, 1152) if self.polls > 2 else (2088, 40, 640, 400)
            return [seen(PID, bounds)]

    _desk(monkeypatch, Wanders([]))
    monkeypatch.setattr(w, "WAIT_S", 0.01)
    monkeypatch.setattr(w, "POLL_S", 0.0)
    with pytest.raises(Invalid) as e:
        w.prove(PID, w.WindowRequest(1, True, (2048, 0)))
    assert e.value.code == "window_not_visible" and e.value.fields["asked_display"] == 1


def test_prove_spends_one_bound_even_when_the_window_never_fills(
        monkeypatch: pytest.MonkeyPatch) -> None:
    host = Host([seen(PID, (2088, 40, 640, 400))], appears_after=12)
    _desk(monkeypatch, host)
    monkeypatch.setattr(w, "WAIT_S", 0.3)
    monkeypatch.setattr(w, "POLL_S", 0.01)
    with pytest.raises(Invalid):
        w.prove(PID, w.WindowRequest(1, True, (2048, 0)))
    assert host.polls <= 0.3 / 0.01 + 5


def test_prove_and_answer_wait_for_the_one_bound_core_holds(
        monkeypatch: pytest.MonkeyPatch) -> None:
    bounds: list[float] = []
    _desk(monkeypatch, Host([]))
    monkeypatch.setattr(w, "WAIT_S", 7.5)

    def waited(pid: int, display: int, bound_s: float, *_a: object) -> w.WindowState:
        bounds.append(bound_s)
        return w.WindowState(display, (0, 0, 1, 1), True, True, False)

    def brought(pid: int, host: object, bound_s: float, *_a: object, **_k: object
                ) -> w.WindowState:
        bounds.append(bound_s)
        return w.WindowState(0, (0, 0, 1, 1), True, True, False)

    monkeypatch.setattr(w, "wait_visible", waited)
    monkeypatch.setattr(w, "bring_front", brought)
    w.prove(PID, w.WindowRequest(0, False, (0, 0)))
    w.answer(PID, w.WindowRequest(0, False, (0, 0)), front=True, launched_behind=False)
    assert bounds == [7.5, 7.5]


def test_prove_refuses_a_window_that_never_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([]))
    with pytest.raises(Invalid) as e:
        w.prove(PID, w.WindowRequest(0, False, (0, 0)))
    assert e.value.code == "window_not_visible"


def test_answer_without_a_window_request_is_no_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([seen(PID, (0, 0, 400, 300))]))
    with pytest.raises(Invalid) as e:
        w.answer(PID, None, front=False, launched_behind=False)
    assert e.value.code == "no_channel" and "shared=true" in str(e.value)


def test_answer_reports_the_window_and_front_brings_it_forward(
        monkeypatch: pytest.MonkeyPatch) -> None:
    cover = seen(OTHER, (0, 0, 2048, 1152), number=2)
    host = Host([cover, seen(PID, (100, 100, 400, 300))])
    _desk(monkeypatch, host)
    asked = w.WindowRequest(0, False, (0, 0))
    assert w.answer(PID, asked, front=False, launched_behind=False)["window"]["front"] is False
    assert host.activated == []
    assert w.answer(PID, asked, front=True, launched_behind=False)["window"]["front"] is True
    assert host.activated == [1]


def test_answer_passes_the_background_launch_to_the_refusal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _desk(monkeypatch, Host([seen(PID, (100, 100, 400, 300), onscreen=False)], brings=False))
    with pytest.raises(Invalid) as e:
        w.answer(PID, w.WindowRequest(0, False, (0, 0)), front=True, launched_behind=True)
    assert "background=true" in str(e.value)


def test_the_window_summary_names_display_screen_and_front() -> None:
    reply = {"window": {"display": 1, "onscreen": True, "front": False}}
    assert w.summary({}, reply) == "window: display 1, on screen, covered"
    assert w.summary({}, {"window": {"display": 0, "onscreen": False, "front": True}}) == (
        "window: display 0, off screen, in front")


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
