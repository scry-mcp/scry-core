"""`scry_core.focus_watch`: the verdict over a sampler run captured on a real host (one DOSBox-X
start in front, then two behind while another application held the front), the TSV round trip,
the watch's thread against samplers of the test's own, and the host sampler itself."""

from __future__ import annotations

import ctypes.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scry_core import focus_watch as fw

CAPTURE = Path(__file__).parent / "fixtures" / "focus_watch" / "control.tsv"
# The three runs' windows as the capturing script printed them, epoch ms.
FRONT = (1792066911690, 1792066927110)
BEHIND = [(1792066929146, 1792066944534), (1792066946563, 1792066961878)]
WATCH_DEADLINE_S = 5.0


@pytest.fixture(scope="module")
def captured() -> list[fw.Sample]:
    return fw.load(CAPTURE)


def _finder(ms: int) -> fw.Sample:
    return fw.Sample(ms, "Finder", 9, (0, 0))


def test_the_front_start_is_seen_in_its_window(captured: list[fw.Sample]) -> None:
    v = fw.judge(captured, {"dosbox-x"}, start_ms=FRONT[0], end_ms=FRONT[1])
    assert v.status == "TOOK_FOCUS", v
    assert v.sample is not None and v.sample.app == "dosbox-x"
    assert "36 of 37" in v.reason


@pytest.mark.parametrize("window", BEHIND)
def test_a_start_behind_is_clean_though_another_app_held_the_front(
        captured: list[fw.Sample], window: tuple[int, int]) -> None:
    v = fw.judge(captured, {"dosbox-x"}, start_ms=window[0], end_ms=window[1])
    assert v.status == "CLEAN", v
    assert (v.examined, v.sample, v.distinct_pointers) == (37, None, 1)


def test_the_whole_capture_is_not_clean_and_excluding_the_front_window_is(
        captured: list[fw.Sample]) -> None:
    assert fw.judge(captured, {"dosbox-x"}).status == "TOOK_FOCUS"
    v = fw.judge(captured, {"dosbox-x"}, exclude=[FRONT])
    assert v.status == "CLEAN", v
    assert v.examined == len(captured) - 37


def test_names_decide_and_another_project_s_emulator_is_not_this_run_s(
        captured: list[fw.Sample]) -> None:
    a, b = BEHIND[1]
    clean = fw.judge(captured, {"mamed", "multicpu"}, start_ms=a, end_ms=b)
    assert (clean.status, clean.examined) == ("CLEAN", 37)
    assert fw.judge(captured, {"rltennis"}, start_ms=a, end_ms=b).status == "TOOK_FOCUS"


@pytest.mark.parametrize("names", ["dosbox-x", set(), []])
def test_one_string_or_no_name_is_refused_rather_than_clean(
        captured: list[fw.Sample], names: object) -> None:
    with pytest.raises(ValueError, match="non-empty collection"):
        fw.judge(captured, names, start_ms=FRONT[0], end_ms=FRONT[1])  # type: ignore[arg-type]


def test_the_window_edges_are_inclusive() -> None:
    samples = [fw.Sample(1000, "dosbox-x", 1, (0, 0)), _finder(2000),
               fw.Sample(3000, "dosbox-x", 1, (0, 0))]
    assert fw.judge(samples, {"dosbox-x"}, start_ms=1000, end_ms=1000).status == "TOOK_FOCUS"
    assert fw.judge(samples, {"dosbox-x"}, start_ms=3000, end_ms=3000).status == "TOOK_FOCUS"
    assert fw.judge(samples, {"dosbox-x"}, start_ms=1001, end_ms=2999).status == "CLEAN"
    edge = fw.judge(samples, {"dosbox-x"}, exclude=[(1000, 1000), (3000, 3000)])
    assert (edge.status, edge.examined) == ("CLEAN", 1)


def test_a_window_with_no_sample_is_invalid_never_clean(captured: list[fw.Sample]) -> None:
    v = fw.judge(captured, {"dosbox-x"}, start_ms=1, end_ms=2)
    assert (v.status, v.examined) == ("INVALID", 0)
    assert fw.judge([], {"dosbox-x"}).status == "INVALID"


def test_a_stretch_nobody_sampled_makes_the_window_invalid() -> None:
    two = [_finder(0), _finder(1000)]
    v = fw.judge(two, {"dosbox-x"}, start_ms=0, end_ms=900_000)
    assert v.status == "INVALID" and "1000 and 900000" in v.reason
    late = fw.judge(two, {"dosbox-x"}, start_ms=-fw.MAX_GAP_MS - 1, end_ms=1000)
    assert late.status == "INVALID", late
    inner = [_finder(0), _finder(fw.MAX_GAP_MS + 1), _finder(fw.MAX_GAP_MS + 2)]
    assert fw.judge(inner, {"dosbox-x"}).status == "INVALID"
    at_bound = [_finder(0), _finder(fw.MAX_GAP_MS)]
    assert fw.judge(at_bound, {"dosbox-x"}, start_ms=0, end_ms=fw.MAX_GAP_MS).status == "CLEAN"


def test_an_excluded_stretch_is_not_a_gap_but_the_judged_rest_still_is() -> None:
    around = [_finder(0), _finder(1000), _finder(60_000), _finder(61_000)]
    assert fw.judge(around, {"dosbox-x"}, exclude=[(1000, 60_000)]).status == "CLEAN"
    assert fw.judge(around, {"dosbox-x"}, exclude=[(5000, 60_000)]).status == "INVALID"
    outside = fw.judge(around, {"dosbox-x"}, start_ms=0, end_ms=1000,
                       exclude=[(50_000, 70_000)])
    assert outside.status == "CLEAN", outside


def test_one_sample_the_instrument_could_not_take_makes_the_window_invalid(
        captured: list[fw.Sample]) -> None:
    broken = fw.Sample(BEHIND[0][0] + 5, error="System Events did not answer")
    v = fw.judge([*captured, broken], {"dosbox-x"}, start_ms=BEHIND[0][0],
                 end_ms=BEHIND[0][1])
    assert v.status == "INVALID" and v.sample == broken
    assert "did not answer" in v.reason
    outside = fw.judge([*captured, broken], {"dosbox-x"}, start_ms=BEHIND[1][0],
                       end_ms=BEHIND[1][1])
    assert outside.status == "CLEAN"


def test_a_theft_seen_is_reported_over_a_sample_that_failed(captured: list[fw.Sample]) -> None:
    broken = fw.Sample(FRONT[0] + 5, error="System Events did not answer")
    v = fw.judge([broken, *captured], {"dosbox-x"}, start_ms=FRONT[0], end_ms=FRONT[1])
    assert v.status == "TOOK_FOCUS" and v.sample is not None and v.sample.app == "dosbox-x"


def test_a_moved_pointer_is_recorded_and_not_judged() -> None:
    samples = [fw.Sample(1, "Finder", 9, (0, 0)), fw.Sample(2, "Finder", 9, (5, 7))]
    v = fw.judge(samples, {"dosbox-x"})
    assert (v.status, v.distinct_pointers) == ("CLEAN", 2)


@pytest.mark.parametrize("sample", [
    fw.Sample(10, "dosbox-x", 42, (3, 4)),
    fw.Sample(11, "Code Helper", 7, None),
    fw.Sample(12, error="osascript did not answer: boom"),
    fw.Sample(13),
    fw.Sample(14, "Finder", 9, (0, 0), spaces=(1, 4)),
])
def test_a_sample_survives_its_line(sample: fw.Sample) -> None:
    assert fw.parse(sample.line()) == sample


@pytest.mark.parametrize("app", ["a\tb", "a\nb", "a\rb", "a\x0bb", "a b"])
def test_a_name_that_would_break_the_record_is_written_as_one_field(
        tmp_path: Path, app: str) -> None:
    path = tmp_path / "w.tsv"
    path.write_text(fw.Sample(5, app, 1, None).line() + "\n" +
                    fw.Sample(6, error=f"why {app}").line() + "\n", encoding="utf-8")
    back = fw.load(path)
    assert [s.epoch_ms for s in back] == [5, 6]
    assert back[0].app == "a b" and back[1].error == "why a b"


def test_a_line_in_neither_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="not a focus_watch sample"):
        fw.parse("12\tdosbox-x\n")


def _wait_for(watch: fw.FocusWatch, count: int) -> None:
    deadline = time.monotonic() + WATCH_DEADLINE_S
    while len(watch.samples) < count:
        assert time.monotonic() < deadline, f"the watch took {len(watch.samples)} samples"
        time.sleep(0.001)


def test_the_watch_samples_until_it_exits_and_writes_each_sample(tmp_path: Path) -> None:
    ticks = iter(range(1000))
    path = tmp_path / "w.tsv"
    with fw.FocusWatch(path, interval_s=0.001, sample=lambda: _finder(next(ticks))) as watch:
        _wait_for(watch, 5)
    assert not watch._thread.is_alive()
    taken = len(watch.samples)
    time.sleep(0.05)
    assert len(watch.samples) == taken >= 5
    assert fw.load(path) == watch.samples


def test_a_sampler_that_raises_leaves_an_error_sample_and_the_window_invalid(
        tmp_path: Path) -> None:
    calls = iter(range(1000))

    def sampler() -> fw.Sample:
        i = next(calls)
        if i == 3:
            raise RuntimeError("boom")
        return _finder(i)
    with fw.FocusWatch(tmp_path / "w.tsv", interval_s=0.001, sample=sampler) as watch:
        _wait_for(watch, 6)
    errors = [s for s in watch.samples if s.error]
    assert len(errors) == 1 and "RuntimeError: boom" in errors[0].error
    assert fw.judge(watch.samples, {"dosbox-x"}).status == "INVALID"


def test_a_record_that_cannot_be_written_stops_the_watch_and_says_so(
        tmp_path: Path) -> None:
    watch = fw.FocusWatch(tmp_path / "w.tsv", interval_s=0.001, sample=lambda: _finder(1))
    with pytest.raises(OSError, match="disk full"), watch:
        def full(_text: str) -> int:
            raise OSError("disk full")
        watch._out.write = full  # type: ignore[method-assign]
        deadline = time.monotonic() + WATCH_DEADLINE_S
        while watch._thread.is_alive():
            assert time.monotonic() < deadline
            time.sleep(0.001)


def test_a_watch_whose_record_cannot_be_opened_refuses_before_sampling(
        tmp_path: Path) -> None:
    watch = fw.FocusWatch(tmp_path / "missing" / "w.tsv", sample=lambda: fw.Sample(1))
    with pytest.raises(FileNotFoundError), watch:
        pass
    assert watch.samples == []


@pytest.mark.skipif(sys.platform != "darwin", reason="the window server is macOS's")
def test_the_host_sampler_names_a_frontmost_process_and_the_pointer() -> None:
    s = fw.sample_host()
    assert not s.error, s
    assert s.app and s.pid and s.pointer is not None and s.spaces


def test_off_macos_every_sample_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(fw, "_MACOS", False)
    s = fw.sample_host()
    assert "macOS only" in s.error
    assert fw.judge([s], {"dosbox-x"}).status == "INVALID"


def _fake_run(stdout: str, rc: int = 0, stderr: str = "") -> object:
    def run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        time.sleep(0.02)
        return subprocess.CompletedProcess([], rc, stdout, stderr)
    return run


def test_a_named_frontmost_process_is_stamped_inside_the_call(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", _fake_run("dosbox-x\t68339\n"))
    monkeypatch.setattr(fw, "_spaces", lambda: (1, 4))
    before = int(time.time() * 1000)
    s = fw.sample_host()
    after = int(time.time() * 1000)
    assert (s.app, s.pid, s.error, s.spaces) == ("dosbox-x", 68339, "", (1, 4))
    assert before + 5 <= s.epoch_ms <= after - 5


@pytest.mark.parametrize(("stdout", "rc", "stderr", "why"), [
    ("", 1, "execution error: not allowed\n", "not allowed"),
    ("Finder\t\n", 0, "", "Finder"),
])
def test_a_system_events_answer_without_a_pid_is_an_error(
        monkeypatch: pytest.MonkeyPatch, stdout: str, rc: int, stderr: str, why: str) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout, rc, stderr))
    s = fw.sample_host()
    assert why in s.error
    assert fw.parse(s.line()) == fw.Sample(s.epoch_ms, error=s.error.replace("\n", " "))


def test_an_osascript_that_never_answers_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("osascript", fw.OSASCRIPT_TIMEOUT_S)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", hang)
    assert "did not answer" in fw.sample_host().error


def test_no_coregraphics_means_no_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    fw._graphics.cache_clear()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    try:
        assert fw._pointer() is None
    finally:
        fw._graphics.cache_clear()


def _on(ms: int, *spaces: int) -> fw.Sample:
    return fw.Sample(ms, "Finder", 9, (0, 0), spaces=spaces)


def test_a_space_that_moved_inside_the_window_is_its_own_verdict() -> None:
    v = fw.judge([_on(1, 1, 4), _on(2, 1, 4), _on(3, 2, 4)], {"dosbox-x"})
    assert v.status == "SPACE_CHANGED" and v.sample is not None and v.sample.epoch_ms == 3
    assert "[1, 4]" in v.reason and "[2, 4]" in v.reason
    assert fw.judge([_on(1, 1, 4), _on(2, 1, 4)], {"dosbox-x"}).status == "CLEAN"


def test_a_space_moved_and_put_back_is_seen_at_its_first_move() -> None:
    """The control's own shape: along, then back to where the window began."""
    v = fw.judge([_on(1, 1, 4), _on(2, 2, 4), _on(3, 1, 4)], {"dosbox-x"})
    assert v.status == "SPACE_CHANGED" and v.sample is not None and v.sample.epoch_ms == 2


def test_any_display_s_space_counts_not_only_the_first() -> None:
    v = fw.judge([_on(1, 1, 4), _on(2, 1, 5)], {"dosbox-x"})
    assert v.status == "SPACE_CHANGED" and v.sample is not None and v.sample.epoch_ms == 2


def test_a_moved_space_is_reported_over_a_later_change_of_displays() -> None:
    v = fw.judge([_on(1, 1, 4), _on(2, 2, 4), _on(3, 2)], {"dosbox-x"})
    assert v.status == "SPACE_CHANGED" and v.sample is not None and v.sample.epoch_ms == 2


def test_a_moved_space_is_reported_over_a_stretch_unwatched() -> None:
    far = 1 + fw.MAX_GAP_MS * 4
    v = fw.judge([_on(1, 1, 4), _on(far, 2, 4)], {"dosbox-x"})
    assert v.status == "SPACE_CHANGED"


def test_the_window_s_own_first_sample_is_the_baseline() -> None:
    """A Space that moved BEFORE the window opened is not this window's doing."""
    v = fw.judge([_on(1, 2, 4), _on(5, 1, 4), _on(6, 1, 4)], {"dosbox-x"}, start_ms=5)
    assert v.status == "CLEAN"


def test_a_theft_of_the_focus_is_reported_over_a_moved_space() -> None:
    front = fw.Sample(3, "dosbox-x", 42, (0, 0), spaces=(2, 4))
    assert fw.judge([_on(1, 1, 4), front], {"dosbox-x"}).status == "TOOK_FOCUS"


def test_a_moved_space_is_reported_over_a_sample_that_failed() -> None:
    broken = fw.Sample(2, error="System Events did not answer")
    assert fw.judge([_on(1, 1, 4), broken, _on(3, 2, 4)], {"dosbox-x"}).status == "SPACE_CHANGED"


def test_a_record_written_before_spaces_were_read_still_loads() -> None:
    assert fw.parse("12\tFinder\t9\t0,0") == fw.Sample(12, "Finder", 9, (0, 0))


def test_spaces_that_cannot_be_read_make_the_sample_an_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", _fake_run("Finder\t9\n"))
    for unread in (None, ()):
        monkeypatch.setattr(fw, "_spaces", lambda unread=unread: unread)
        s = fw.sample_host()
        assert "Spaces could not be read" in s.error
        assert fw.judge([s], {"dosbox-x"}).status == "INVALID"


def test_no_coregraphics_means_no_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    fw._graphics.cache_clear()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    try:
        assert fw._spaces() is None
    finally:
        fw._graphics.cache_clear()


class _Graphics:
    """CoreGraphics and CoreFoundation as `_spaces` calls them: the managed list, its data,
    and the bytes, each of which the window server may fail to hand over."""

    def __init__(self, managed: int, data: int, raw: bytes) -> None:
        self.managed, self.data, self.raw = managed, data, raw
        self.released: list[int] = []
        self._buf = ctypes.create_string_buffer(raw, len(raw))

    def CGSMainConnectionID(self) -> int:  # noqa: N802 -- the C name
        return 1

    def CGSCopyManagedDisplaySpaces(self, _cid: int) -> int:  # noqa: N802
        return self.managed

    def CFPropertyListCreateData(self, *_a: object) -> int:  # noqa: N802
        return self.data

    def CFDataGetBytePtr(self, _d: int) -> int:  # noqa: N802
        return ctypes.addressof(self._buf)

    def CFDataGetLength(self, _d: int) -> int:  # noqa: N802
        return len(self.raw)

    def CFRelease(self, ref: int) -> None:  # noqa: N802
        self.released.append(ref)


def _plist(*current: int) -> bytes:
    import plistlib
    return plistlib.dumps([{"Current Space": {"ManagedSpaceID": n}} for n in current],
                          fmt=plistlib.FMT_BINARY)


@pytest.mark.parametrize(("managed", "data", "raw", "want", "released"), [
    (7, 8, _plist(1, 4), (1, 4), [8, 7]),
    (0, 8, _plist(1), None, []),
    (7, 0, _plist(1), None, [7]),
    (7, 8, b"not a plist", None, [8, 7]),
    (7, 8, _plist(), (), [8, 7]),
])
def test_spaces_reads_the_window_server_s_list_and_releases_what_it_was_handed(
        monkeypatch: pytest.MonkeyPatch, managed: int, data: int, raw: bytes,
        want: tuple[int, ...] | None, released: list[int]) -> None:
    g = _Graphics(managed, data, raw)
    monkeypatch.setattr(fw, "_graphics", lambda: (g, g))
    assert fw._spaces() == want
    assert g.released == released, "every reference handed over is released, once"


def test_spaces_reads_a_capture_of_the_window_server_s_own_list(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The list as the window server hands it over (two displays, one holding a full-screen app
    on a Space of its own), anonymised: the shape the double above stands in for."""
    raw = (CAPTURE.parent / "managed-display-spaces.plist").read_bytes()
    g = _Graphics(7, 8, raw)
    monkeypatch.setattr(fw, "_graphics", lambda: (g, g))
    assert fw._spaces() == (1, 4)


class _Desk:
    """Spaces in a row and the owner on one of them; the shortcuts move along the row. `late`
    moves the owner and still reports the keystroke as unanswered, as an osascript that timed
    out after System Events had acted does."""

    def __init__(self, row: int, at: int, refuse: bool = False, lost: bool = False,
                 late: bool = False) -> None:
        self.row, self.at, self.refuse, self.lost, self.late = row, at, refuse, lost, late
        self.pressed: list[int] = []
        self.events: list[str] = []

    def spaces(self) -> tuple[int, ...]:
        self.events.append("read")
        return (self.at, 9)

    def clock(self) -> int:
        self.events.append("clock")
        return len(self.events)

    def press(self, key: int) -> str:
        self.pressed.append(key)
        self.events.append("press")
        if self.refuse:
            return "System Events refused the keystroke: not allowed"
        step = 1 if key == fw.KEY_RIGHT else -1
        if 1 <= self.at + step <= self.row and not (self.lost and step < 0):
            self.at += step
        return "osascript did not answer: timed out" if self.late else ""


@pytest.mark.parametrize(("desk", "keys", "why"), [
    (_Desk(3, 1), [124, 123], ""),
    (_Desk(3, 3), [124, 123, 124], ""),
    (_Desk(1, 1), [124, 123], "no other Space"),
    (_Desk(3, 1, refuse=True), [124], "refused the keystroke"),
    (_Desk(3, 1, lost=True), [124, 123], "left on"),
    (_Desk(3, 1, late=True), [124, 123], "did not answer"),
    (_Desk(3, 3, late=True), [124], "did not answer"),
])
def test_move_space_moves_along_and_back_or_says_why_not(
        monkeypatch: pytest.MonkeyPatch, desk: _Desk, keys: list[int], why: str) -> None:
    at = desk.at
    monkeypatch.setattr(fw, "_spaces", desk.spaces)
    monkeypatch.setattr(fw, "_press", desk.press)
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    monkeypatch.setattr(fw, "now_ms", desk.clock)
    began, ended, said = fw.move_space(settle_s=0.5)
    assert desk.pressed == keys
    assert (why in said) if why else said == ""
    if not desk.lost:
        assert desk.at == at, "the owner is back where they started, whatever a key reported"
    assert desk.events[0] == "clock" and desk.events[-1] == "clock", \
        "the window opens before the first key and closes after the last reading"
    assert began < ended
    assert slept == [0.5] * len(keys), "each key pressed is given its settle, and only those"


def test_move_space_presses_nothing_when_the_spaces_cannot_be_read(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Desk(3, 1)
    monkeypatch.setattr(fw, "_spaces", lambda: None)
    monkeypatch.setattr(fw, "_press", desk.press)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    _began, _ended, said = fw.move_space(settle_s=0.5)
    assert desk.pressed == [] and "could not be read" in said


def test_move_space_presses_no_way_back_when_a_reading_fails_after_a_key(
        monkeypatch: pytest.MonkeyPatch) -> None:
    desk = _Desk(3, 1)
    monkeypatch.setattr(fw, "_spaces", lambda: None if desk.pressed else desk.spaces())
    monkeypatch.setattr(fw, "_press", desk.press)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    _began, _ended, said = fw.move_space(settle_s=0.5)
    assert desk.pressed == [fw.KEY_RIGHT], "a key back on a blind reading may move the owner"
    assert "could not be read after a key" in said and "left on None" in said


def test_press_sends_mission_control_s_shortcut_and_survives_any_bytes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        seen.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    assert fw._press(fw.KEY_RIGHT) == ""
    argv, kw = seen[0]
    assert argv[0] == "osascript" and argv[-1].endswith("key code 124 using control down")
    assert kw["errors"] == "replace" and kw["timeout"] == fw.OSASCRIPT_TIMEOUT_S


def test_press_says_why_a_keystroke_did_not_go(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run("", 1, "not allowed to send keystrokes"))
    assert "not allowed" in fw._press(124)

    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("osascript", 5)
    monkeypatch.setattr(subprocess, "run", hang)
    assert "did not answer" in fw._press(124)
    monkeypatch.setattr(subprocess, "run", _fake_run(""))
    assert fw._press(123) == ""


def test_a_change_in_the_number_of_displays_is_invalid_not_a_move() -> None:
    v = fw.judge([_on(1, 1, 4), _on(2, 1)], {"dosbox-x"})
    assert v.status == "INVALID" and "displays changed" in v.reason


def test_samples_with_and_without_a_space_reading_cannot_be_judged() -> None:
    v = fw.judge([_on(1, 1, 4), fw.Sample(2, "Finder", 9, (0, 0))], {"dosbox-x"})
    assert v.status == "INVALID" and "no Space reading" in v.reason
    old = fw.judge([fw.Sample(1, "Finder", 9, (0, 0))], {"dosbox-x"})
    assert old.status == "CLEAN" and "no Space was recorded" in old.reason


# THE CONTROL AND THE VERDICT: what each window judged is decided here, and each server maps the
# outcome onto its own cell call.
class _Watched:
    def __init__(self, samples: list[fw.Sample]) -> None:
        self.samples, self.path, self.exited = samples, Path("w.tsv"), False

    def __exit__(self, *exc: object) -> None:
        self.exited = True


def _app(ms: int, app: str = "Finder", spaces: tuple[int, ...] = (1,)) -> fw.Sample:
    return fw.Sample(ms, app, 9, (0, 0), spaces=spaces)


def _control_case(monkeypatch: pytest.MonkeyPatch, front_app: str, behind_app: str,
                  moved: bool, why: str = "", blind: tuple[int, int] | None = None) -> fw.Control:
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
    monkeypatch.setattr(fw, "move_space", lambda: (5000, 6000, why))
    c = fw.control(_Watched(samples), {"mame"}, hold)
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
    assert [o.status for o in (c.front, c.behind, c.space)] == ["PASS", "PASS", "PASS"]
    assert c.since == 6000


@pytest.mark.parametrize("front, behind, moved, why, want", [
    ("Finder", "Finder", True, "", ("FAIL", "PASS", "PASS")),
    ("mame", "mame", True, "", ("PASS", "FAIL", "PASS")),
    ("mame", "Finder", False, "", ("PASS", "PASS", "FAIL")),
    ("mame", "Finder", True, "a keystroke was refused", ("PASS", "PASS", "FAIL")),
])
def test_a_control_that_does_not_hold_clears_nothing(
        monkeypatch: pytest.MonkeyPatch, front: str, behind: str, moved: bool, why: str,
        want: tuple[str, str, str]) -> None:
    c = _control_case(monkeypatch, front, behind, moved, why)
    assert (c.front.status, c.behind.status, c.space.status) == want
    assert c.since is None
    if why:
        assert c.space.reason.startswith(why)


def test_a_space_move_inside_the_behind_window_blocks_that_cell_and_names_nobody(
        monkeypatch: pytest.MonkeyPatch) -> None:
    samples = [_app(ms, "mame" if 1000 <= ms <= 2000 else "Finder",
                    (2,) if ms == 3500 or 5500 <= ms <= 5600 else (1,))
               for ms in range(1000, 6001, 100)]
    windows = iter([(1000, 2000), (3000, 4000)])
    monkeypatch.setattr(fw, "move_space", lambda: (5000, 6000, ""))
    c = fw.control(_Watched(samples), {"mame"}, lambda background: next(windows))
    assert c.behind.status == "BLOCKED" and "Spaces" in c.behind.reason
    assert c.front.status == c.space.status == "PASS" and c.since is None


@pytest.mark.parametrize("samples, since, end, status, says", [
    ([_app(ms) for ms in range(0, 70_001, 500)], 0, 70_000, "PASS", "none of"),
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
    v = fw.verdict(watch, {"mame"}, since, end)
    assert (v.status, watch.exited) == (status, True)
    assert says in v.reason and "w.tsv" in v.reason


@pytest.mark.parametrize("window_ms, status", [(fw.MIN_WINDOW_MS - 1, "BLOCKED"),
                                               (fw.MIN_WINDOW_MS, "PASS")])
def test_a_window_is_long_enough_from_its_minimum_on(window_ms: int, status: str) -> None:
    samples = [_app(ms) for ms in range(0, window_ms + 1, 500)] + [_app(window_ms)]
    assert fw.verdict(_Watched(samples), {"mame"}, 0, window_ms).status == status


def test_now_ms_is_the_epoch_in_milliseconds() -> None:
    before = int(time.time() * 1000)
    assert before <= fw.now_ms() <= int(time.time() * 1000)
