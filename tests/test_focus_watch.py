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
    assert s.app and s.pid and s.pointer is not None


def test_off_macos_every_sample_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
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
    monkeypatch.setattr(subprocess, "run", _fake_run("dosbox-x\t68339\n"))
    before = int(time.time() * 1000)
    s = fw.sample_host()
    after = int(time.time() * 1000)
    assert (s.app, s.pid, s.error) == ("dosbox-x", 68339, "")
    assert before + 5 <= s.epoch_ms <= after - 5


@pytest.mark.parametrize(("stdout", "rc", "stderr", "why"), [
    ("", 1, "execution error: not allowed\n", "not allowed"),
    ("Finder\t\n", 0, "", "Finder"),
])
def test_a_system_events_answer_without_a_pid_is_an_error(
        monkeypatch: pytest.MonkeyPatch, stdout: str, rc: int, stderr: str, why: str) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout, rc, stderr))
    s = fw.sample_host()
    assert why in s.error
    assert fw.parse(s.line()) == fw.Sample(s.epoch_ms, error=s.error.replace("\n", " "))


def test_an_osascript_that_never_answers_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired("osascript", fw.OSASCRIPT_TIMEOUT_S)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", hang)
    assert "did not answer" in fw.sample_host().error


def test_no_coregraphics_means_no_pointer(monkeypatch: pytest.MonkeyPatch) -> None:
    fw._graphics.cache_clear()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    try:
        assert fw._pointer() is None
    finally:
        fw._graphics.cache_clear()
