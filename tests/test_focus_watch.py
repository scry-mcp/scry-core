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


def test_the_whole_capture_is_not_clean(captured: list[fw.Sample]) -> None:
    assert fw.judge(captured, {"dosbox-x"}).status == "TOOK_FOCUS"


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


def test_one_sample_the_instrument_could_not_take_is_a_short_gap_not_a_verdict(
        captured: list[fw.Sample]) -> None:
    """A process that exits under the sampler fails one sample: a blink of blindness, judged as
    the gap it is, so the window around it still clears."""
    broken = fw.Sample(BEHIND[0][0] + 5, error="Can't get application process 1234")
    v = fw.judge(sorted([*captured, broken], key=lambda s: s.epoch_ms), {"dosbox-x"},
                 start_ms=BEHIND[0][0], end_ms=BEHIND[0][1])
    assert (v.status, v.examined) == ("CLEAN", 37), v


def test_samples_that_failed_for_longer_than_the_gap_bound_make_the_window_invalid() -> None:
    blind = [_finder(0), *(fw.Sample(ms, error="System Events did not answer")
                           for ms in range(500, fw.MAX_GAP_MS + 1000, 500)),
             _finder(fw.MAX_GAP_MS + 1000)]
    v = fw.judge(blind, {"dosbox-x"})
    assert v.status == "INVALID" and "not watched throughout" in v.reason, v


def test_a_window_whose_every_sample_failed_is_invalid_and_says_why() -> None:
    v = fw.judge([fw.Sample(1, error="osascript did not answer: boom")], {"dosbox-x"})
    assert (v.status, v.examined) == ("INVALID", 0) and "boom" in v.reason


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
    fw.Sample(14, "Finder", 9, (0, 0), spaces=(("00000000-0000-0000-0000-000000000004", 1),
                                              ("Main", 4))),
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


def test_a_sampler_that_raises_leaves_an_error_sample_and_a_short_gap(
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
    # a failed sample is no verdict of its own: the window is judged on the samples taken
    assert fw.judge(watch.samples, {"dosbox-x"}).status == "CLEAN"


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
    if s.error or s.pointer is None:
        pytest.skip("the window server did not answer (displays asleep?): "
                    f"{s.error or 'no pointer'}")
    assert s.app and s.pid and s.spaces


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
    monkeypatch.setattr(fw, "spaces", lambda: (("A", 1), ("B", 4)))
    monkeypatch.setattr(fw, "spaces_missing", lambda: "")
    monkeypatch.setattr(fw, "_pointer", lambda: (10, 20))
    before = int(time.time() * 1000)
    s = fw.sample_host()
    after = int(time.time() * 1000)
    assert (s.app, s.pid, s.error, s.spaces) == ("dosbox-x", 68339, "", (("A", 1), ("B", 4)))
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
    return fw.Sample(ms, "Finder", 9, (0, 0),
                     spaces=tuple((f"D{i}", n) for i, n in enumerate(spaces)))


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
    front = fw.Sample(3, "dosbox-x", 42, (0, 0), spaces=(("D0", 2), ("D1", 4)))
    assert fw.judge([_on(1, 1, 4), front], {"dosbox-x"}).status == "TOOK_FOCUS"


def test_a_moved_space_is_reported_over_a_sample_that_failed() -> None:
    broken = fw.Sample(2, error="System Events did not answer")
    assert fw.judge([_on(1, 1, 4), broken, _on(3, 2, 4)], {"dosbox-x"}).status == "SPACE_CHANGED"


def test_a_record_with_no_spaces_field_loads() -> None:
    assert fw.parse("12\tFinder\t9\t0,0") == fw.Sample(12, "Finder", 9, (0, 0))


def test_a_bare_number_space_is_keyed_by_position() -> None:
    assert fw.parse("12\tFinder\t9\t0,0\t1,4").spaces == (("#0", 1), ("#1", 4))


def test_the_same_displays_listed_in_another_order_are_the_same_spaces() -> None:
    a = fw.Sample(1, "Finder", 9, (0, 0), spaces=(("A", 1), ("B", 4)))
    b = fw.Sample(2, "Finder", 9, (0, 0), spaces=(("B", 4), ("A", 1)))
    assert fw.judge([a, b], {"dosbox-x"}).status == "CLEAN"
    moved = fw.Sample(3, "Finder", 9, (0, 0), spaces=(("B", 5), ("A", 1)))
    assert fw.judge([a, b, moved], {"dosbox-x"}).status == "SPACE_CHANGED"


def test_a_display_swapped_for_another_is_a_change_of_displays_not_a_move() -> None:
    a = fw.Sample(1, "Finder", 9, (0, 0), spaces=(("A", 1), ("B", 4)))
    b = fw.Sample(2, "Finder", 9, (0, 0), spaces=(("A", 1), ("C", 4)))
    v = fw.judge([a, b], {"dosbox-x"})
    assert v.status == "INVALID" and "displays changed" in v.reason


def test_spaces_that_cannot_be_read_make_the_sample_an_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", _fake_run("Finder\t9\n"))
    monkeypatch.setattr(fw, "spaces_missing", lambda: "")
    for unread in (None, ()):
        monkeypatch.setattr(fw, "spaces", lambda unread=unread: unread)
        s = fw.sample_host()
        assert "Spaces could not be read" in s.error
        assert fw.judge([s], {"dosbox-x"}).status == "INVALID"


def test_no_coregraphics_means_no_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    fw._graphics.cache_clear()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    try:
        assert fw.spaces() is None and fw.spaces_missing() == ""
    finally:
        fw._graphics.cache_clear()


def test_a_host_without_the_space_symbols_samples_without_spaces_and_says_which(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Bare:
        CGSMainConnectionID = object()
    assert fw.spaces_missing(Bare()) == "CGSCopyManagedDisplaySpaces"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(fw, "_MACOS", True)
    monkeypatch.setattr(subprocess, "run", _fake_run("Finder\t9\n"))
    monkeypatch.setattr(fw, "_graphics", lambda: (Bare(), Bare()))
    monkeypatch.setattr(fw, "_pointer", lambda: (1, 2))
    s = fw.sample_host()
    assert (s.error, s.spaces, s.app) == ("", (), "Finder")
    assert fw.spaces() is None
    v = fw.judge([s], {"dosbox-x"}, start_ms=s.epoch_ms, end_ms=s.epoch_ms)
    assert v.status == "CLEAN" and "no Space was recorded" in v.reason


class _Graphics:
    """CoreGraphics and CoreFoundation as `spaces` calls them: the managed list, its data,
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
    return plistlib.dumps([{"Display Identifier": f"D{i}", "Current Space": {"ManagedSpaceID": n}}
                           for i, n in enumerate(current)], fmt=plistlib.FMT_BINARY)


@pytest.mark.parametrize(("managed", "data", "raw", "want", "released"), [
    (7, 8, _plist(1, 4), (("D0", 1), ("D1", 4)), [8, 7]),
    (0, 8, _plist(1), None, []),
    (7, 0, _plist(1), None, [7]),
    (7, 8, b"not a plist", None, [8, 7]),
    (7, 8, _plist(), (), [8, 7]),
])
def test_spaces_reads_the_window_server_s_list_and_releases_what_it_was_handed(
        monkeypatch: pytest.MonkeyPatch, managed: int, data: int, raw: bytes,
        want: tuple[tuple[str, int], ...] | None, released: list[int]) -> None:
    g = _Graphics(managed, data, raw)
    monkeypatch.setattr(fw, "_graphics", lambda: (g, g))
    assert fw.spaces() == want
    assert g.released == released, "every reference handed over is released, once"


def test_spaces_reads_a_capture_of_the_window_server_s_own_list(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The list as the window server hands it over (two displays, one holding a full-screen app
    on a Space of its own), anonymised: the shape the double above stands in for."""
    raw = (CAPTURE.parent / "managed-display-spaces.plist").read_bytes()
    g = _Graphics(7, 8, raw)
    monkeypatch.setattr(fw, "_graphics", lambda: (g, g))
    assert fw.spaces() == (("00000000-0000-0000-0000-000000000004", 1),
                           ("00000000-0000-0000-0000-000000000007", 4))


def test_a_change_in_the_number_of_displays_is_invalid_not_a_move() -> None:
    v = fw.judge([_on(1, 1, 4), _on(2, 1)], {"dosbox-x"})
    assert v.status == "INVALID" and "displays changed" in v.reason


def test_samples_with_and_without_a_space_reading_cannot_be_judged() -> None:
    v = fw.judge([_on(1, 1, 4), fw.Sample(2, "Finder", 9, (0, 0))], {"dosbox-x"})
    assert v.status == "INVALID" and "no Space reading" in v.reason
    old = fw.judge([fw.Sample(1, "Finder", 9, (0, 0))], {"dosbox-x"})
    assert old.status == "CLEAN" and "no Space was recorded" in old.reason


def test_now_ms_is_the_epoch_in_milliseconds() -> None:
    before = int(time.time() * 1000)
    assert before <= fw.now_ms() <= int(time.time() * 1000)


def test_binding_a_coregraphics_without_the_space_symbols_binds_the_rest_and_raises_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    class Function:
        restype: object = None
        argtypes: object = None

    class Library:
        def __init__(self, names: tuple[str, ...]) -> None:
            for name in names:
                setattr(self, name, Function())

    cg_names = ("CGEventCreate", "CGEventGetLocation", "CGWindowListCopyWindowInfo")
    cf_names = ("CFPropertyListCreateData", "CFDataGetLength", "CFDataGetBytePtr", "CFRelease")
    made = iter([Library(cg_names), Library(cf_names)])
    fw._graphics.cache_clear()
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: name)
    monkeypatch.setattr(ctypes, "CDLL", lambda _path: next(made))
    try:
        libs = fw._graphics()
        assert libs is not None
        cg = libs[0]
        assert cg.CGEventCreate.restype is ctypes.c_void_p
        assert fw.spaces_missing(cg) == "CGSMainConnectionID" and fw.spaces() is None
    finally:
        fw._graphics.cache_clear()


def test_a_property_list_that_will_not_serialise_is_none_and_still_released() -> None:
    released: list[int] = []

    class Refusing:
        def CFPropertyListCreateData(self, *_a: object) -> int:  # noqa: N802
            return 0

        def CFRelease(self, ref: int) -> None:  # noqa: N802
            released.append(ref)
    assert fw.plist_of(Refusing(), 77) is None  # type: ignore[arg-type]
    assert released == [77]


def test_space_counts_reads_each_displays_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fw, "_managed", lambda: [{"Spaces": [1, 2, 3]}, {"Spaces": [4]}])
    assert fw.space_counts() == (3, 1)
    monkeypatch.setattr(fw, "_managed", lambda: [{"no": 1}])
    assert fw.space_counts() is None
    monkeypatch.setattr(fw, "_managed", lambda: None)
    assert fw.space_counts() is None


def test_no_windows_and_no_spaces_where_the_host_cannot_be_asked(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fw, "_graphics", lambda: None)
    assert fw.windows() == []
    monkeypatch.setattr(fw, "_managed", lambda: [{"Display Identifier": "A"}])
    assert fw.spaces() is None
