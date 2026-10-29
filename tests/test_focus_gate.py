"""`scry_core.focus_gate`: the control and the verdict a live section takes the watch through,
in `live_pool`'s words, and the actuator that moves the owner's Space for the control, against a
desk of the test's own."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from scry_core import focus_gate as fg
from scry_core import focus_watch as fw


@pytest.fixture(autouse=True)
def _opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control moves the owner's desk, so it runs only when asked: these tests ask."""
    monkeypatch.setenv(fg.OPT_IN_VAR, "1")


def _fake_run(stdout: str, rc: int = 0, stderr: str = "") -> object:
    def run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], rc, stdout, stderr)
    return run


class _Desk:
    """Spaces in a row and the owner on one of them; the shortcuts move along the row. `late`
    moves the owner and still reports the keystroke as unanswered, as an osascript that timed
    out after System Events had acted does."""

    def __init__(self, row: int, at: int, refuse: bool = False, lost: bool = False,
                 late: bool = False, off: bool = False) -> None:
        self.row, self.at, self.refuse, self.lost, self.late = row, at, refuse, lost, late
        self.off = off                  # the host's Mission Control shortcuts turned off
        self.pressed: list[int] = []
        self.events: list[str] = []

    def spaces(self) -> tuple[tuple[str, int], ...]:
        self.events.append("read")
        return (("A", self.at), ("B", 9))

    def clock(self) -> int:
        self.events.append("clock")
        return len(self.events)

    def press(self, key: int) -> str:
        self.pressed.append(key)
        self.events.append("press")
        if self.refuse:
            return "System Events refused the keystroke: not allowed"
        step = 1 if key == fg.KEY_RIGHT else -1
        if not self.off and 1 <= self.at + step <= self.row and not (self.lost and step < 0):
            self.at += step
        return "osascript did not answer: timed out" if self.late else ""


def _on(monkeypatch: pytest.MonkeyPatch, desk: _Desk) -> list[float]:
    """`move_space` pointed at `desk`: its Spaces, its keys, its count, and the settles taken."""
    monkeypatch.setattr(fw, "spaces", desk.spaces)
    monkeypatch.setattr(fw, "spaces_missing", lambda: "")
    monkeypatch.setattr(fw, "space_counts", lambda: (desk.row, 1))
    monkeypatch.setattr(fg, "_press", desk.press)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


@pytest.mark.parametrize(("desk", "keys", "why", "taken"), [
    (_Desk(3, 1), [124, 123], "", True),
    (_Desk(3, 3), [124, 123, 124], "", True),
    (_Desk(1, 1), [124, 123], fg.NO_OTHER_SPACE, False),
    (_Desk(3, 1, refuse=True), [124], "refused the keystroke", False),
    (_Desk(3, 1, lost=True), [124, 123], "left on", True),
    (_Desk(3, 1, late=True), [124, 123], "did not answer", True),
    (_Desk(3, 3, late=True), [124], "did not answer", False),
    (_Desk(3, 1, off=True), [124, 123], "may be off", False),
])
def test_move_space_moves_along_and_back_or_says_why_not(
        monkeypatch: pytest.MonkeyPatch, desk: _Desk, keys: list[int], why: str,
        taken: bool) -> None:
    at = desk.at
    slept = _on(monkeypatch, desk)
    monkeypatch.setattr(fw, "now_ms", desk.clock)
    m = fg.move_space(settle_s=0.5)
    began, ended, said = m.began, m.ended, m.why
    assert desk.pressed == keys
    assert (why in said) if why else said == ""
    assert m.taken == taken, m
    if not desk.lost:
        assert desk.at == at, "the owner is back where they started, whatever a key reported"
    assert desk.events[0] == "clock" and desk.events[-1] == "clock", \
        "the window opens before the first key and closes after the last reading"
    assert began < ended
    assert slept == [0.5] * len(keys), "each key pressed is given its settle, and only those"


def test_move_space_presses_nothing_when_the_spaces_cannot_be_read(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Desk(3, 1)
    monkeypatch.setattr(fw, "spaces", lambda: None)
    monkeypatch.setattr(fw, "spaces_missing", lambda: "")
    monkeypatch.setattr(fg, "_press", desk.press)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    m = fg.move_space(settle_s=0.5)
    assert desk.pressed == [] and "could not be read" in m.why and not m.taken


def test_move_space_on_a_host_without_the_space_symbols_presses_nothing_and_says_which(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Desk(3, 1)
    monkeypatch.setattr(fw, "spaces_missing", lambda: "CGSCopyManagedDisplaySpaces")
    monkeypatch.setattr(fg, "_press", desk.press)
    m = fg.move_space(settle_s=0.5)
    assert desk.pressed == [] and not m.taken and "no CGSCopyManagedDisplaySpaces" in m.why


def test_move_space_presses_no_way_back_when_a_reading_fails_after_a_key(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Desk(3, 1)
    monkeypatch.setattr(fw, "spaces", lambda: None if desk.pressed else desk.spaces())
    monkeypatch.setattr(fw, "spaces_missing", lambda: "")
    monkeypatch.setattr(fg, "_press", desk.press)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    m = fg.move_space(settle_s=0.5)
    assert desk.pressed == [fg.KEY_RIGHT], "a key back on a blind reading may move the owner"
    assert "could not be read after a key" in m.why and "left on None" in m.why
    assert m.taken


def test_press_sends_mission_control_s_shortcut_and_survives_any_bytes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        seen.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    assert fg._press(fg.KEY_RIGHT) == ""
    argv, kw = seen[0]
    assert argv[0] == "osascript" and argv[-1].endswith("key code 124 using control down")
    assert kw["errors"] == "replace" and kw["timeout"] == fw.OSASCRIPT_TIMEOUT_S


def test_press_says_why_a_keystroke_did_not_go(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("", 1, "not allowed to send keystrokes"))
    assert "not allowed" in fg._press(124)

    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("osascript", 5)
    monkeypatch.setattr(subprocess, "run", hang)
    assert "did not answer" in fg._press(124)
    monkeypatch.setattr(subprocess, "run", _fake_run(""))
    assert fg._press(123) == ""


class _Watched:
    def __init__(self, samples: list[fw.Sample]) -> None:
        self.samples, self.path, self.exited = samples, Path("w.tsv"), False

    def __exit__(self, *exc: object) -> None:
        self.exited = True


def _app(ms: int, app: str = "Finder", spaces: tuple[int, ...] = (1,)) -> fw.Sample:
    return fw.Sample(ms, app, 9, (0, 0), spaces=tuple((f"D{i}", n) for i, n in enumerate(spaces)))


def _control_case(monkeypatch: pytest.MonkeyPatch, front_app: str, behind_app: str,
                  moved: bool, why: str = "", blind: tuple[int, int] | None = None,
                  taken: bool = True) -> fg.Control:
    """`blind` is a stretch whose samples are errors: the instrument could not read the host."""
    samples = [fw.Sample(ms, error="osascript did not answer")
               if blind is not None and blind[0] <= ms <= blind[1] else
               _app(ms, front_app if 1000 <= ms <= 2000 else
                    behind_app if 3000 <= ms <= 4000 else "Finder",
                    (2,) if moved and 5500 <= ms <= 5600 else (1,))
               for ms in range(1000, 6001, 100)]
    # Each start's window is the one ITS mode was given, so a control that held them the other
    # way round would judge the front start over the behind window.
    asked: list[bool] = []

    def hold(background: bool) -> tuple[int, int]:
        asked.append(background)
        return (3000, 4000) if background else (1000, 2000)
    monkeypatch.setattr(fg, "move_space", lambda: fg.Moved(5000, 6000, why, taken))
    c = fg.control(_Watched(samples), {"mame"}, hold)
    assert asked == [False, True], asked
    return c


def test_a_control_window_the_instrument_could_not_read_is_blocked_not_failed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    c = _control_case(monkeypatch, "mame", "Finder", moved=True, blind=(1000, 2000))
    assert c.front.status == "BLOCKED" and c.since is None, c
    c = _control_case(monkeypatch, "mame", "Finder", moved=True, blind=(3000, 4000))
    assert c.behind.status == "BLOCKED" and c.since is None, c


def test_a_control_that_holds_passes_its_three_cells_and_opens_the_judged_window(
        monkeypatch: pytest.MonkeyPatch) -> None:
    c = _control_case(monkeypatch, "mame", "Finder", moved=True)
    assert [o.status for o in (c.front, c.behind, c.space)] == ["OK", "OK", "OK"]
    assert c.since == 6000


@pytest.mark.parametrize("front, behind, moved, why, want", [
    ("Finder", "Finder", True, "", ("FAIL", "OK", "OK")),
    ("mame", "mame", True, "", ("OK", "FAIL", "OK")),
    ("mame", "Finder", False, "", ("OK", "OK", "FAIL")),
    ("mame", "Finder", True, "a keystroke was refused", ("OK", "OK", "FAIL")),
])
def test_a_control_that_does_not_hold_clears_nothing(
        monkeypatch: pytest.MonkeyPatch, front: str, behind: str, moved: bool, why: str,
        want: tuple[str, str, str]) -> None:
    c = _control_case(monkeypatch, front, behind, moved, why)
    assert (c.front.status, c.behind.status, c.space.status) == want
    assert c.since is None
    if why:
        assert c.space.reason.startswith(why)


def test_without_the_opt_in_the_control_takes_nothing_from_the_desk_and_says_so(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fg.OPT_IN_VAR)
    asked: list[bool] = []

    def hold(background: bool) -> tuple[int, int]:
        asked.append(background)
        return 3000, 4000

    def never() -> fg.Moved:
        raise AssertionError("the owner's Space was moved without being asked")
    monkeypatch.setattr(fg, "move_space", never)
    samples = [_app(ms) for ms in range(1000, 6001, 100)]
    c = fg.control(_Watched(samples), {"mame"}, hold)
    assert asked == [True], "a start was put in front without being asked"
    assert (c.front.status, c.behind.status, c.space.status) == ("BLOCKED", "OK", "BLOCKED")
    for cell in (c.front, c.space):
        assert fg.OPT_IN_VAR in cell.reason and "desk" in cell.reason
    assert c.since is None


def test_a_space_move_inside_the_behind_window_blocks_that_cell_and_names_nobody(
        monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [_app(ms, "mame" if 1000 <= ms <= 2000 else "Finder",
                    (2,) if ms == 3500 or 5500 <= ms <= 5600 else (1,))
               for ms in range(1000, 6001, 100)]
    windows = iter([(1000, 2000), (3000, 4000)])
    monkeypatch.setattr(fg, "move_space", lambda: fg.Moved(5000, 6000))
    c = fg.control(_Watched(samples), {"mame"}, lambda background: next(windows))
    assert c.behind.status == "BLOCKED" and "Spaces" in c.behind.reason
    assert c.front.status == c.space.status == "OK" and c.since is None


def test_a_space_control_that_could_not_be_taken_is_blocked_not_failed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    c = _control_case(monkeypatch, "mame", "Finder", moved=False, why=fg.NO_OTHER_SPACE,
                      taken=False)
    assert (c.front.status, c.behind.status, c.space.status) == ("OK", "OK", "BLOCKED")
    assert c.space.reason == fg.NO_OTHER_SPACE and c.since is None


def test_a_space_control_the_watch_was_blind_through_is_blocked_not_failed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    c = _control_case(monkeypatch, "mame", "Finder", moved=True, blind=(5000, 6000))
    assert c.space.status == "BLOCKED" and c.since is None, c


@pytest.mark.parametrize("samples, since, end, status, says", [
    ([_app(ms) for ms in range(0, 70_001, 500)], 0, 70_000, "OK", "none of"),
    ([_app(ms, "mame" if ms == 30_000 else "Finder") for ms in range(0, 70_001, 500)],
     0, 70_000, "FAIL", "TOOK_FOCUS"),
    ([_app(ms) for ms in range(0, 70_001, 500)], None, 70_000, "BLOCKED", "did not hold"),
    ([_app(ms) for ms in range(0, 30_001, 500)], 0, 30_000, "BLOCKED", "too little to judge"),
    ([_app(ms, spaces=(2,) if ms > 40_000 else (1,)) for ms in range(0, 70_001, 500)],
     0, 70_000, "BLOCKED", "nothing names who moved it"),
    ([_app(ms) for ms in range(0, 70_001, 5000)], 0, 70_000, "BLOCKED", "cannot judge the run"),
])
def test_the_verdict_is_judged_only_after_a_control_and_a_window_long_enough(
        samples: list[fw.Sample], since: int | None, end: int, status: str, says: str) -> None:
    watch = _Watched(samples)
    v = fg.verdict(watch, {"mame"}, since, end)
    assert (v.status, watch.exited) == (status, True)
    assert says in v.reason and "w.tsv" in v.reason


def test_without_the_opt_in_a_clean_run_is_unproven_and_a_stolen_focus_still_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(fg.OPT_IN_VAR)
    clean = _Watched([_app(ms) for ms in range(0, 70_001, 500)])
    v = fg.verdict(clean, {"mame"}, None, 70_000)
    assert v.status == "BLOCKED" and "unproven" in v.reason and fg.OPT_IN_VAR in v.reason
    assert clean.exited
    stolen = _Watched([_app(ms, "mame" if ms == 30_000 else "Finder")
                       for ms in range(0, 70_001, 500)])
    v = fg.verdict(stolen, {"mame"}, None, 70_000)
    assert v.status == "FAIL" and "TOOK_FOCUS" in v.reason and "w.tsv" in v.reason
    v = fg.verdict(_Watched([]), {"mame"}, None, 70_000)
    assert v.status == "BLOCKED" and "no sample" in v.reason


@pytest.mark.parametrize("window_ms, status", [(fg.MIN_WINDOW_MS - 1, "BLOCKED"),
                                               (fg.MIN_WINDOW_MS, "OK")])
def test_a_window_is_long_enough_from_its_minimum_on(window_ms: int, status: str) -> None:
    samples = [_app(ms) for ms in range(0, window_ms + 1, 500)] + [_app(window_ms)]
    assert fg.verdict(_Watched(samples), {"mame"}, 0, window_ms).status == status



class _Shuffled(_Desk):
    """A desk whose system lists the same displays in the other order after any key."""

    def spaces(self) -> tuple[tuple[str, int], ...]:
        a, b = super().spaces()
        return (b, a) if self.pressed else (a, b)


def test_the_same_displays_listed_in_another_order_are_no_move_and_press_no_way_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Shuffled(1, 1)                  # one Space: no key moves the owner
    _on(monkeypatch, desk)
    m = fg.move_space(settle_s=0.5)
    assert desk.pressed == [fg.KEY_RIGHT, fg.KEY_LEFT], "a key back was pressed on a reorder"
    assert m.why == fg.NO_OTHER_SPACE and not m.taken


class _Drifting(_Desk):
    """A desk with one Space whose last reading finds the owner elsewhere: no key moved them."""

    def spaces(self) -> tuple[tuple[str, int], ...]:
        reads = self.events.count("read")
        got = super().spaces()
        return (("A", 7), got[1]) if reads >= 3 else got


def test_an_owner_found_elsewhere_with_no_key_having_moved_them_fails_the_control(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Drifting(1, 1)
    _on(monkeypatch, desk)
    m = fg.move_space(settle_s=0.5)
    assert "left on" in m.why and m.taken, m


def test_a_watch_that_failed_at_its_end_is_a_blocked_verdict_not_an_exception() -> None:
    class Failed(_Watched):
        def __exit__(self, *_a: object) -> None:
            raise OSError(28, "No space left on device")
    v = fg.verdict(Failed([_app(ms) for ms in range(0, 70_001, 500)]), {"mame"}, 0, 70_000)
    assert v.status == "BLOCKED" and "No space left" in v.reason
