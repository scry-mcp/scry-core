"""`scry_core.window_host`: what the macOS host lists, the choices around the two calls that move
the owner's desk, and (only with `SCRY_FOCUS_CONTROL=1`, which moves the desk) bringing a window
forward from behind a full-screen application, with the activation by pid alone as the control."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from scry_core import focus_watch as fw
from scry_core import window as w
from scry_core import window_host as wh
from scry_core.reply_contract import Invalid
from scry_core.window_stand_ins import (
    built,
    comes_forward,
    on_the_desk,
    shown,
    under_a_cover,
    until,
)

DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="the host under test is macOS")


def _desktop() -> bool:
    return (sys.platform == "darwin" and bool(wh.MacHost().displays())
            and any(s.onscreen for s in wh.MacHost().windows()))


#: A logged-in desktop with a display awake; a host without one cannot list what is asked here.
DESKTOP = pytest.mark.skipif(not _desktop(), reason="no desktop session: no display or no window")
SPACES = pytest.mark.skipif(sys.platform == "darwin" and fw.managed() is None,
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
    monkeypatch.setattr(fw, "managed", lambda: desk)
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


#: A process that asks for the displays, then says whether LaunchServices holds it as an
#: application, and whether every display came back with its usable area.
ASKS_DISPLAYS = """
import json, os, subprocess
from scry_core import window_host as wh
displays = wh.MacHost().displays()
asn = subprocess.run(["lsappinfo", "find", f"pid={os.getpid()}"], capture_output=True,
                     text=True).stdout.strip()
print(json.dumps({"registered": bool(asn), "usable": all(d.usable for d in displays),
                  "displays": len(displays)}))
"""


@DESKTOP
def test_asking_for_the_displays_does_not_make_the_server_an_application() -> None:
    """A process macOS holds as an application is pinged by the window server, and one with no
    event loop then shows as not responding; the server asks for the displays from a child."""
    out = subprocess.run([sys.executable, "-c", ASKS_DISPLAYS], capture_output=True, text=True,
                         check=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    got = json.loads(out.stdout)
    assert got["displays"] > 0 and got["usable"] is True, got
    assert got["registered"] is False, got
    control = ASKS_DISPLAYS.replace("wh.MacHost().displays()", "wh.screens_here() or [1]")
    control = control.replace("all(d.usable for d in displays)", "True")
    out = subprocess.run([sys.executable, "-c", control], capture_output=True, text=True,
                         check=True, env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert json.loads(out.stdout)["registered"] is True, "lsappinfo saw no registration at all"


@DESKTOP
def test_the_child_reads_the_screens_this_process_would_read() -> None:
    assert wh.screens() == wh.screens_here() != []


@DESKTOP
@SPACES
def test_a_window_the_server_lists_is_listed_here_with_the_space_that_holds_it() -> None:
    host = wh.MacHost()
    shown = [s for s in host.windows() if s.onscreen]
    mine = fw.windows()
    assert {s.number for s in shown} <= {x["kCGWindowNumber"] for x in mine}
    desk = fw.managed() or []
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
    monkeypatch.setattr(fw, "managed", lambda: [managed(1, [1, 4891, 3938])])
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
    monkeypatch.setattr(fw, "graphics", lambda: None)
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
    brought = w.bring_front(pid, host, 8.0, launched_behind=False)
    assert brought.onscreen and brought.front


def _window_tool(pid: int) -> Any:  # needs the desk
    """A `window` tool of the shape a server's replies have, over the real host."""
    def tool(front: bool = False) -> dict[str, Any]:  # needs the desk
        try:
            return {"status": "ok",
                    **w.answer(pid, w.WindowRequest(0, False, (0, 0)), front=front,
                               launched_behind=False)}
        except Invalid as refused:
            return {"status": "INVALID", "code": refused.code, "message": str(refused)}
    return tool


@on_the_desk
def test_the_shared_tier_helpers_bring_a_covered_window_forward(  # needs the desk
        tmp_path: Path) -> None:
    target = subprocess.Popen([str(built(tmp_path, "target"))])
    try:
        until("the target window listed on screen",
              lambda: shown(target.pid, wh.MacHost()) is True)
        with under_a_cover(target.pid, tmp_path):
            comes_forward(_window_tool(target.pid))
    finally:
        target.terminate()
        target.wait(timeout=10)


def _pseudo(handle: int) -> int | None:
    """What `ctypes.c_void_p(handle).value` reads back: the unsigned form of a pseudo-handle."""
    return ctypes.c_void_p(handle).value


class _User32:
    """A user32 whose DPI calls answer what the test says; a missing one is simply absent."""

    def __init__(self, sets: int, held: int | None, *, same_as: tuple[int, ...] = (),
                 absent: str = "") -> None:
        self.calls: list[str] = []
        if absent != "set":
            self.SetProcessDpiAwarenessContext = self._set(sets)
        if absent != "get":
            self.GetThreadDpiAwarenessContext = self._get(held)
        if absent != "equal":
            self.AreDpiAwarenessContextsEqual = lambda a, b: int(
                a == held and b.value in [_pseudo(c) for c in same_as])

    def _set(self, answer: int) -> Any:
        def set_context(context: Any) -> int:
            self.calls.append(f"set {context.value}")
            return answer
        return set_context

    def _get(self, held: int | None) -> Any:
        def get_context() -> int | None:
            self.calls.append("get")
            return held
        return get_context


def test_a_process_that_becomes_per_monitor_aware_asks_nothing_more() -> None:
    user32 = _User32(sets=1, held=None)
    wh.require_per_monitor_aware(user32)
    assert user32.calls == [f"set {_pseudo(-4)}"]


def test_a_process_that_already_chose_per_monitor_awareness_is_accepted() -> None:
    wh.require_per_monitor_aware(_User32(sets=0, held=7, same_as=(-3,)))


def test_a_process_that_already_chose_to_be_unaware_is_refused_aloud() -> None:
    with pytest.raises(Invalid, match="scaled") as e:
        wh.require_per_monitor_aware(_User32(sets=0, held=7))
    assert e.value.code == "host_failed"


@pytest.mark.parametrize("absent", ["set", "get", "equal"])
def test_a_windows_without_the_dpi_calls_is_refused_by_name(absent: str) -> None:
    with pytest.raises(Invalid, match="1703") as e:
        wh.require_per_monitor_aware(_User32(sets=0, held=7, absent=absent))
    assert e.value.code == "host_failed"


# ---- the usable area and the scale -------------------------------------------------------------

def test_a_screens_rectangle_is_flipped_from_the_bottom_left_origin_to_the_top_left_one() -> None:
    # The main screen is 1152 high; its visible frame starts 0 above the bottom and is 30 short
    # of the top (the menu bar): in the window list's coordinates it starts 30 down.
    assert wh.cg_rect((0.0, 0.0, 2048.0, 1122.0), 1152.0) == (0, 30, 2048, 1122)
    # A screen to the right and above the main one has a negative top.
    assert wh.cg_rect((2048.0, 500.0, 1920.0, 1080.0), 1152.0) == (2048, -428, 1920, 1080)


def test_each_display_takes_the_visible_frame_and_scale_of_the_screen_with_its_bounds() -> None:
    plain = [w.Display(0, (0, 0, 2048, 1152)), w.Display(1, (2048, 0, 2048, 1152))]
    screens = [((2048, 0, 2048, 1152), (2048, 0, 2048, 1152), 2.0),
               ((0, 0, 2048, 1152), (0, 30, 2048, 1122), 1.0)]
    got = wh.with_usable(plain, screens)
    assert [(d.usable, d.scale) for d in got] == [((0, 30, 2048, 1122), 1.0),
                                                  ((2048, 0, 2048, 1152), 2.0)]


def test_a_display_no_screen_matches_keeps_no_usable_area_rather_than_a_guess() -> None:
    lone = [w.Display(0, (0, 0, 2048, 1152))]
    assert wh.with_usable(lone, [((5, 5, 10, 10), (5, 5, 10, 10), 1.0)]) == lone


@DARWIN
@DESKTOP
def test_the_real_main_display_loses_at_most_its_menu_bar_and_dock_and_never_gains() -> None:
    main = wh.MacHost().displays()[0]
    assert main.usable is not None and main.scale >= 1.0
    bx, by, bw, bh = main.bounds
    ux, uy, uw, uh = main.usable
    assert bx <= ux and by <= uy and uw <= bw and uh <= bh and uh < bh + 1


def test_the_screens_are_read_through_the_runtime_in_the_right_order(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def send(obj: int, selector: str, restype: Any, *args: Any) -> Any:
        calls.append(selector)
        return {"screens": 7, "count": 2, "objectAtIndex:": 100 + args[0] if args else 0,
                "frame": wh._NSRect(0, 0, 10, 10), "visibleFrame": wh._NSRect(0, 1, 10, 8),
                "backingScaleFactor": 2.0}.get(selector, 0)

    monkeypatch.setattr(wh, "_send", send)
    monkeypatch.setattr(wh, "_class", lambda name: 1)
    monkeypatch.setattr(ctypes, "CDLL", lambda name: None)
    got = wh.screens_here()
    assert got == [((0, 0, 10, 10), (0, 1, 10, 8), 2.0)] * 2
    assert calls[:2] == ["screens", "count"]


def test_the_screens_come_back_from_the_child_and_a_child_that_fails_gives_none(
        monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: list[str], **k: Any) -> subprocess.CompletedProcess[str]:
        asked.append((argv, k["env"]))
        return subprocess.CompletedProcess(argv, 0, answers[0], "")
    monkeypatch.setattr(subprocess, "run", run)
    answers = ['[[[0, 0, 10, 10], [0, 1, 10, 8], 2.0]]']
    assert wh.screens() == [((0, 0, 10, 10), (0, 1, 10, 8), 2.0)]
    argv, env = asked[0]
    assert argv == [sys.executable, "-c", wh.SCREENS_CHILD], argv
    assert env["PYTHONPATH"].split(os.pathsep) == sys.path
    for odd in ("", "Traceback", "[[1]]"):
        answers[0] = odd
        assert wh.screens() == [], odd
    monkeypatch.setattr(sys, "executable", "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        FileNotFoundError("no such file")))
    assert wh.screens() == []


def test_the_screens_are_asked_again_only_when_the_displays_move(
        monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    def screens() -> list[Any]:
        calls.append(1)
        return [((0, 0, 10, 10), (0, 1, 10, 8), 2.0)]
    monkeypatch.setattr(wh, "screens", screens)
    monkeypatch.setattr(wh, "_SCREENS_READ", {})
    one = [w.Display(0, (0, 0, 10, 10))]
    wh.screens_for(one), wh.screens_for(one)
    assert len(calls) == 1
    wh.screens_for([w.Display(0, (0, 0, 20, 10))])
    assert len(calls) == 2


def test_a_child_that_answered_no_screen_is_asked_again(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A child that failed once (a slow import, a load spike) must not stand for the displays."""
    answers: list[list[Any]] = [[], [((0, 0, 10, 10), (0, 1, 10, 8), 2.0)]]
    monkeypatch.setattr(wh, "screens", lambda: answers.pop(0))
    monkeypatch.setattr(wh, "_SCREENS_READ", {})
    one = [w.Display(0, (0, 0, 10, 10))]
    assert wh.screens_for(one) == []
    assert wh.screens_for(one) == [((0, 0, 10, 10), (0, 1, 10, 8), 2.0)]


def test_a_child_that_hangs_gives_no_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(argv: list[str], **k: Any) -> subprocess.CompletedProcess[str]:
        assert k.get("timeout") == wh.SCREENS_TIMEOUT_S, k
        raise subprocess.TimeoutExpired(argv, k["timeout"])
    monkeypatch.setattr(subprocess, "run", run)
    assert wh.screens() == []


def test_a_desk_that_lists_no_screen_gives_no_usable_area(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wh, "_class", lambda name: 1)
    monkeypatch.setattr(wh, "_send", lambda obj, selector, restype, *a: 0)
    monkeypatch.setattr(ctypes, "CDLL", lambda name: None)
    assert wh.screens_here() == []


@pytest.mark.parametrize(("hresult", "dpi", "scale"), [(0, 96, 1.0), (0, 288, 3.0), (0, 144, 1.5)])
def test_a_monitors_scale_is_its_dpi_over_96(hresult: int, dpi: int, scale: float) -> None:
    assert wh.scale_from(hresult, dpi) == scale


@pytest.mark.parametrize(("hresult", "dpi"), [(-2147024809, 96), (1, 96), (0, 0)])
def test_a_failed_dpi_reading_is_refused_never_taken_for_a_scale_of_one(
        hresult: int, dpi: int) -> None:
    with pytest.raises(Invalid) as e:
        wh.scale_from(hresult, dpi)
    assert e.value.code == "host_failed" and "DPI" in str(e.value)
