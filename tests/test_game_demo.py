"""A game's script against a platform's binding: what the binding may say, and what the shared
steps check."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from scry_core.demo import Reply, Run, Step, StepFailed
from scry_core.game_demo import (
    Binding,
    Press,
    arrived,
    exact,
    found,
    heard,
    map_load,
    sound,
    word_is,
    words,
)

COIN = Press("input", {"port": ":P1", "field": "Coin 1"})


def _binding(rate_hz: float = 50.0, **over: object) -> Binding:
    return Binding(platform="board", boot=[], inputs={"COIN": COIN}, rate_hz=rate_hz,
                   sound=Path("/ref.wav"), map=lambda run: Path("/game.screen-map.json"),
                   **over)  # type: ignore[arg-type]


@pytest.mark.parametrize(("rate_hz", "ms", "frames"), [
    (50.0, 2000, 100), (50.0, 1, 1), (70.086, 2000, 141), (50.0801, 2000, 101), (70.0, 0, 0)])
def test_milliseconds_are_whole_frames_of_the_platforms_screen_rounded_up(
        rate_hz: float, ms: int, frames: int) -> None:
    assert _binding(rate_hz).frames(ms) == frames


def test_a_press_is_the_bound_call_and_an_unbound_action_is_refused_when_built() -> None:
    step = _binding(volatile={"since_mark": "timing"}).press("press coin", "COIN",
                                                             lambda r, run: "in")
    assert (step.name, step.tool, step.args, step.volatile) == (
        "press coin", "input", {"port": ":P1", "field": "Coin 1"}, {"since_mark": "timing"})
    assert step.args is not COIN.args, "a step holds its own arguments"
    with pytest.raises(KeyError, match="board binds no 'START'; it binds \\['COIN'\\]"):
        _binding().press("press start", "START", lambda r, run: "")


def _run(tmp_path: Path) -> Run:
    return Run(dir=tmp_path)


def test_words_are_little_endian_sixteen_bit_and_word_is_checks_the_first(
        tmp_path: Path) -> None:
    reply = Reply({"hex": "0300ff01"})
    assert words(reply) == [3, 0x1FF]
    assert word_is("Credits", 3)(reply, _run(tmp_path)) == "Credits holds 3"
    with pytest.raises(StepFailed, match="Credits holds 3, not 2"):
        word_is("Credits", 2)(reply, _run(tmp_path))


def test_found_names_the_screen_and_its_controls_or_says_what_it_saw(tmp_path: Path) -> None:
    hit = Reply({"matched": True, "screen": "play", "controls": [{"name": "well"}]})
    assert found("play")(hit, _run(tmp_path)) == "the play screen, its controls well"
    bare = Reply({"matched": True, "screen": "play", "controls": []})
    assert found("play")(bare, _run(tmp_path)) == "the play screen"
    with pytest.raises(StepFailed, match="answered no screen, not play"):
        found("play")(Reply({"matched": False, "controls": []}), _run(tmp_path))


def test_arrived_needs_the_target_and_a_control_that_counted(tmp_path: Path) -> None:
    check = arrived("Level_Write")
    assert check(Reply({"verdict": "TARGET", "control_hits": 3}), _run(tmp_path)) == (
        "stopped at Level_Write")
    with pytest.raises(StepFailed, match="verdict TIMEOUT"):
        check(Reply({"verdict": "TIMEOUT", "control_hits": 3}), _run(tmp_path))
    with pytest.raises(StepFailed, match="the control never fired"):
        check(Reply({"verdict": "TARGET", "control_hits": 0}), _run(tmp_path))


def test_the_map_is_loaded_from_a_copy_in_the_run(tmp_path: Path) -> None:
    shared = tmp_path / "pkg" / "game.screen-map.json"
    shared.parent.mkdir()
    shared.write_text("{}", encoding="utf-8")
    run = Run(dir=tmp_path / "run")
    run.dir.mkdir()
    step = map_load("map", lambda run: shared)
    assert callable(step.args)
    args = step.args(run)
    assert args == {"method": "load", "path": run.dir / "game.screen-map.json"}
    assert (run.dir / "game.screen-map.json").read_text() == "{}"
    assert step.check(Reply({"screens": 4, "controls": 10}), run) == (
        "4 screens and 10 controls loaded")


def _wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x01\x00" * 8)
    return path


def test_the_sound_records_into_the_run_then_holds_it_to_the_reference(tmp_path: Path) -> None:
    reference = _wav(tmp_path / "ref.wav")
    binding = Binding("board", [], {}, 50.0, reference,
                      lambda run: Path("/game.screen-map.json"))
    steps: list[Step] = sound(binding, 2000, "music.wav")
    assert [(s.name, s.tool) for s in steps] == [
        ("record", "audio_record"), ("heard", "audio_compare"), ("exact", "audio_compare")]
    run = Run(dir=tmp_path)
    stale = _wav(tmp_path / "music.wav")
    record, measure, diff = (s.args(run) for s in steps if callable(s.args))
    assert not stale.exists(), "the server writes no file over an existing one"
    assert record == {"frames": 100, "dest": tmp_path / "music.wav"}
    assert measure == {"method": "measure", "path": tmp_path / "music.wav"}
    assert diff == {"method": "diff", "a": tmp_path / "music.wav", "b": reference,
                    "align": False}
    assert steps[0].check(Reply({"verdict": "ELAPSED"}), run) == (
        "100 frames recorded, the first whole frames past 2000 ms")
    with pytest.raises(StepFailed, match="verdict TIMEOUT"):
        steps[0].check(Reply({"verdict": "TIMEOUT"}), run)


def test_heard_and_exact_fail_on_silence_and_on_a_difference(tmp_path: Path) -> None:
    run = _run(tmp_path)
    loud = Reply({"measures": [{"silent": False, "peak_dbfs": -8.27}]})
    assert heard(loud, run) == "a sound, peaking at -8.27 dBFS"
    with pytest.raises(StepFailed, match="silent"):
        heard(Reply({"measures": [{"silent": True, "peak_dbfs": -90}]}), run)
    ref = Path("/x/music.wav")
    assert exact(ref)(Reply({"exact": True}), run) == (
        "the recording is music.wav, sample for sample")
    with pytest.raises(StepFailed, match="differs from music.wav: audible, 41 dB"):
        exact(ref)(Reply({"exact": False, "class": "audible", "snr_db": 41}), run)
