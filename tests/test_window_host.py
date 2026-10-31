"""`scry_core.window_host`: what the macOS host lists, the choices around the two calls that move
the owner's desk, and (only with `SCRY_FOCUS_CONTROL=1`, which moves the desk) bringing a window
forward from behind a full-screen application, with the activation by pid alone as the control."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any

import pytest

from scry_core import focus_watch as fw
from scry_core import window as w
from scry_core import window_host as wh
from scry_core.reply_contract import Invalid
from scry_core.window_stand_ins import on_the_desk

DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="the host under test is macOS")


def _desktop() -> bool:
    return (sys.platform == "darwin" and bool(wh.MacHost().displays())
            and any(s.onscreen for s in wh.MacHost().windows()))


#: A logged-in desktop with a display awake; a host without one cannot list what is asked here.
DESKTOP = pytest.mark.skipif(not _desktop(), reason="no desktop session: no display or no window")
SPACES = pytest.mark.skipif(sys.platform == "darwin" and fw._managed() is None,
                            reason="the window server's Space listing is unavailable")


def managed(current: int, held: list[int], ident: str = "D1") -> dict[str, Any]:
    return {"Display Identifier": ident, "Current Space": {"ManagedSpaceID": current},
            "Spaces": [{"ManagedSpaceID": s} for s in held]}


# ---- the choices around the shims --------------------------------------------------------------

def test_a_space_not_shown_is_switched_to_on_the_display_that_holds_it() -> None:
    desk = [managed(1, [1, 5], "MAIN"), managed(9, [9, 12], "SIDE")]
    assert wh.plan_switch([12], desk) == ("SIDE", 12)
    assert wh.plan_switch([5], desk) == ("MAIN", 5)


def test_a_space_already_shown_needs_no_switch() -> None:
    assert wh.plan_switch([1], [managed(1, [1, 5])]) is None


def test_a_window_on_several_spaces_needs_no_switch_when_one_of_them_is_shown() -> None:
    assert wh.plan_switch([5, 1], [managed(1, [1, 5])]) is None


def test_a_window_on_several_spaces_none_shown_is_switched_to_the_first_a_display_holds() -> None:
    desk = [managed(1, [1, 5, 6], "MAIN")]
    assert wh.plan_switch([77, 6, 5], desk) == ("MAIN", 6)


def test_a_space_no_display_holds_has_no_switch() -> None:
    assert wh.plan_switch([77], [managed(1, [1, 5])]) is None
    assert wh.plan_switch([], [managed(1, [1, 5])]) is None


def test_a_display_the_listing_wrote_oddly_is_passed_over_not_trusted() -> None:
    odd: dict[str, Any] = {"Display Identifier": "X", "Spaces": [{"ManagedSpaceID": 3}]}
    assert wh.plan_switch([3], [odd, managed(1, [1, 3], "OK")]) == ("OK", 3)


LISTING: list[dict[str, Any]] = [
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 10, "kCGWindowNumber": 1,
     "kCGWindowBounds": {"X": 10.4, "Y": 20.6, "Width": 640.0, "Height": 400.0},
     "kCGWindowIsOnscreen": True},
    {"kCGWindowLayer": 25, "kCGWindowOwnerPID": 11, "kCGWindowNumber": 2,
     "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 2048, "Height": 30}},
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 12, "kCGWindowNumber": 3,
     "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 2048, "Height": 30}},
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 13, "kCGWindowNumber": 4, "kCGWindowAlpha": 0,
     "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 2048, "Height": 1152}},
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 14, "kCGWindowNumber": 5,
     "kCGWindowBounds": {"X": 5, "Y": 5, "Width": 300, "Height": 200}},
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": "x", "kCGWindowNumber": 6,
     "kCGWindowBounds": {"X": 5, "Y": 5, "Width": 300, "Height": 200}},
    {"kCGWindowLayer": 0, "kCGWindowOwnerPID": 15, "kCGWindowNumber": 7},
]


def test_the_listing_keeps_ordinary_windows_in_the_servers_order() -> None:
    assert wh.seen_from(LISTING) == [
        w.Seen(pid=10, number=1, bounds=(10, 21, 640, 400), onscreen=True),
        w.Seen(pid=14, number=5, bounds=(5, 5, 300, 200), onscreen=False)]


def test_an_activation_reports_why_it_failed_and_nothing_when_it_did_not() -> None:
    ok = subprocess.CompletedProcess([], 0, "true", "")
    bad = subprocess.CompletedProcess([], 1, "", "no such process\n")
    assert wh.activation_error(ok) == ""
    assert wh.activation_error(bad) == "activation refused: no such process"
    assert wh.activation_error("osascript did not answer") == "osascript did not answer"


def _host(monkeypatch: pytest.MonkeyPatch, spaces: list[int], desk: list[Any] | None
          ) -> tuple[wh.MacHost, list[Any]]:
    calls: list[Any] = []
    host = wh.MacHost()
    monkeypatch.setattr(host, "spaces_of", lambda _w: spaces)
    monkeypatch.setattr(fw, "_managed", lambda: desk)
    def switch(ident: str, space: int) -> None:
        calls.append(("switch", ident, space))

    def app(pid: int) -> str:
        calls.append(("app", pid))
        return ""
    monkeypatch.setattr(wh, "switch_space", switch)
    monkeypatch.setattr(wh, "activate_app", app)
    return host, calls


WINDOW = w.Seen(pid=42, number=9, bounds=(0, 0, 400, 300), onscreen=False)


def test_a_window_on_a_hidden_space_gets_its_space_then_its_application(
        monkeypatch: pytest.MonkeyPatch) -> None:
    host, calls = _host(monkeypatch, [5], [managed(1, [1, 5], "MAIN")])
    assert host.activate(WINDOW) == ""
    assert calls == [("switch", "MAIN", 5), ("app", 42)]


def test_a_window_on_the_shown_space_only_gets_its_application(
        monkeypatch: pytest.MonkeyPatch) -> None:
    host, calls = _host(monkeypatch, [1], [managed(1, [1, 5])])
    assert host.activate(WINDOW) == "" and calls == [("app", 42)]


@pytest.mark.parametrize(("spaces", "desk"), [([], [managed(1, [1])]), ([5], None)])
def test_a_host_that_cannot_say_where_the_window_is_says_so_and_does_nothing(
        monkeypatch: pytest.MonkeyPatch, spaces: list[int], desk: list[Any] | None) -> None:
    host, calls = _host(monkeypatch, spaces, desk)
    assert "would not say which Space" in host.activate(WINDOW) and calls == []


def test_the_platforms_have_their_hosts_and_any_other_is_refused_by_name() -> None:
    assert isinstance(wh.for_platform("darwin"), wh.MacHost)
    assert isinstance(wh.for_platform("win32"), wh.WindowsHost)
    with pytest.raises(Invalid) as e:
        wh.for_platform("linux")
    assert e.value.code == "host_failed" and "linux" in str(e.value)
    with pytest.raises(Invalid):
        w.host("linux")


@pytest.mark.skipif(sys.platform == "win32", reason="the Windows host exists there")
def test_the_windows_host_is_built_on_windows_only() -> None:
    host = wh.WindowsHost()
    for ask in (host.displays, host.windows):
        with pytest.raises(AssertionError, match="Windows only"):
            ask()
    with pytest.raises(AssertionError, match="Windows only"):
        host.above(WINDOW)
    with pytest.raises(AssertionError, match="Windows only"):
        host.activate(WINDOW)


# ---- what the real macOS host lists ------------------------------------------------------------

@DESKTOP
def test_the_main_display_is_index_0_at_the_origin() -> None:
    displays = wh.MacHost().displays()
    assert [d.index for d in displays] == list(range(len(displays)))
    assert displays[0].bounds[:2] == (0, 0) and min(displays[0].bounds[2:]) > 0
    assert len({d.bounds for d in displays}) == len(displays)


@DESKTOP
@SPACES
def test_a_window_the_server_lists_is_listed_here_with_the_space_that_holds_it() -> None:
    host = wh.MacHost()
    shown = [s for s in host.windows() if s.onscreen]
    mine = fw.windows()
    assert {s.number for s in shown} <= {x["kCGWindowNumber"] for x in mine}
    desk = fw._managed() or []
    held = {int(s["ManagedSpaceID"]) for d in desk for s in d["Spaces"]}
    assert set(host.spaces_of(shown[0])) <= held


@DESKTOP
def test_the_windows_above_one_are_on_screen_and_never_itself() -> None:
    host = wh.MacHost()
    shown = [s for s in host.windows() if s.onscreen]
    over = host.above(shown[-1])
    assert all(isinstance(s, w.Seen) and s.onscreen and s.number != shown[-1].number
               for s in over)


def _above_host(monkeypatch: pytest.MonkeyPatch, over: list[w.Seen],
                spaces: dict[int, list[int]]) -> wh.MacHost:
    """A host whose window server answers `over` for any window and puts windows on `spaces`."""
    host = wh.MacHost()
    monkeypatch.setattr(host, "_over", lambda _w: over)
    monkeypatch.setattr(host, "spaces_of", lambda s: spaces[s.number])
    monkeypatch.setattr(fw, "_managed", lambda: [managed(1, [1, 4891, 3938])])
    return host


COVER = w.Seen(pid=200, number=2, bounds=(0, 0, 2048, 1152), onscreen=True)
BESIDE = w.Seen(pid=300, number=3, bounds=(0, 0, 500, 500), onscreen=True)


def test_a_cover_on_a_space_the_display_is_not_showing_does_not_cover(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """MAME's window, with a full-screen application on another Space: the window server still
    lists that application's window on screen and above, though the display shows the other."""
    host = _above_host(monkeypatch, [COVER, BESIDE], {9: [1], 2: [4891], 3: [1]})
    assert host.above(WINDOW) == [BESIDE]


@pytest.mark.parametrize(("mine", "theirs"), [([1], [1, 4891]), ([1], []), ([], [4891]),
                                              ([1], [0]), ([1], [0, 99])])
def test_a_window_on_every_space_or_of_an_unknown_one_still_covers(
        monkeypatch: pytest.MonkeyPatch, mine: list[int], theirs: list[int]) -> None:
    """THE CONTROL: only a Space known to differ clears a window; a doubt keeps it covering."""
    host = _above_host(monkeypatch, [COVER], {9: mine, 2: theirs})
    assert host.above(WINDOW) == [COVER]


@DARWIN
def test_a_host_without_coregraphics_lists_nothing_and_knows_no_space(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fw, "_graphics", lambda: None)
    host = wh.MacHost()
    assert host.displays() == [] and host.above(WINDOW) == [] and host.spaces_of(WINDOW) == []


def test_the_switch_waits_for_the_window_to_be_shown_then_lets_the_transition_settle(
        monkeypatch: pytest.MonkeyPatch) -> None:
    host = wh.MacHost()
    polls = iter([[], [w.Seen(42, 9, (0, 0, 400, 300), False)],
                  [w.Seen(42, 9, (0, 0, 400, 300), True)]])
    napped: list[float] = []
    monkeypatch.setattr(host, "windows", lambda: next(polls))
    monkeypatch.setattr("scry_core.window_host.time.sleep", napped.append)
    host._until_shown(WINDOW)
    assert napped == [wh.SWITCH_POLL_S, wh.SWITCH_POLL_S, wh.SWITCH_SETTLE_S]


def test_a_window_that_is_never_shown_ends_the_wait_at_its_bound(
        monkeypatch: pytest.MonkeyPatch) -> None:
    host = wh.MacHost()
    now = [0.0]
    monkeypatch.setattr(host, "windows", list)
    monkeypatch.setattr("scry_core.window_host.time.monotonic", lambda: now[0])
    monkeypatch.setattr("scry_core.window_host.time.sleep",
                        lambda s: now.__setitem__(0, now[0] + s))
    host._until_shown(WINDOW)
    assert now[0] >= wh.SWITCH_BOUND_S


# ---- bringing a window forward from behind a full-screen application ---------------------------

@on_the_desk
def test_the_control_activating_by_pid_alone_leaves_the_window_behind(  # needs the desk
        behind_a_fullscreen_app: tuple[int, wh.MacHost]) -> None:
    """The way that failed in the field: rc 0, and the window stays where it was."""
    pid, host = behind_a_fullscreen_app
    lone = w.state_of(pid, host.windows(), host.displays(), host.above)
    assert lone is not None and not lone.onscreen        # the setup holds: it is behind
    assert wh.activate_app(pid) == ""
    time.sleep(2.5)
    still = w.state_of(pid, host.windows(), host.displays(), host.above)
    assert still is not None and not still.onscreen, "the control no longer fails: re-measure"


@on_the_desk
def test_a_window_behind_a_fullscreen_application_comes_forward_by_its_space_and_its_app(
        # needs the desk
        behind_a_fullscreen_app: tuple[int, wh.MacHost]) -> None:
    pid, host = behind_a_fullscreen_app
    brought = w.bring_front(pid, host, 8.0)
    assert brought.onscreen and brought.front
