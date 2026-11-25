"""`scry_core.committed_run`: a committed run read back as the steps it made, and the timeline
its steps' own `events` name for it, in the order and with the arguments the run wrote."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_demo import _demo, _pointed, _run, _said

from scry_core import committed_run, timeline
from scry_core import demo as d
from scry_core.verdict import EXIT_PASS, Invalid


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calls.log"
    monkeypatch.setenv("DEMO_LOG", str(path))
    return path


def _steps() -> list[d.Step]:
    return [
        d.Step("boot", "start", {"value": 7}, _said("value")),
        d.Step("fire", "press", {"key": "Fire 1", "frames": 4}, _said("summary")),
        d.Step("aim", "point", {"x": 12, "y": 34}, _said("summary"), events=_pointed),
        d.Step("end", "close", {}, lambda reply, run: "closed"),
    ]


def test_the_steps_of_a_committed_run_come_back_in_order_with_their_calls_and_replies(
        tmp_path: Path, log: Path) -> None:
    assert _run(_demo(tmp_path, _steps()), tmp_path) == EXIT_PASS
    entries = committed_run.read(tmp_path / "out" / "transcript-normalised.md")
    assert [(e.step, e.tool) for e in entries] == [
        ("boot", "start"), ("fire", "press"), ("aim", "point"), ("end", "close")]
    assert entries[1].args == {"key": "Fire 1", "frames": 4}
    assert entries[1].reply["status"] == "ok"


def test_the_timeline_of_a_committed_run_names_what_its_steps_fired_and_is_the_one_the_run_wrote(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, _steps())
    assert _run(demo, tmp_path) == EXIT_PASS
    written = timeline.loads((tmp_path / "out" / "transcript-timeline.json").read_text())
    read_back = committed_run.timeline_of(demo, tmp_path / "out" / "transcript.md")
    assert read_back["calls"] == written["calls"]
    assert read_back["calls"][2]["events"], "the point named no events"


def test_a_file_that_is_no_transcript_is_invalid_and_not_an_empty_run(tmp_path: Path) -> None:
    other = tmp_path / "README.md"
    other.write_text("# Not a run\n", encoding="utf-8")
    with pytest.raises(Invalid, match="not a transcript"):
        committed_run.read(other)


def test_a_run_that_ended_without_close_still_reads_its_last_step_whole(
        tmp_path: Path, log: Path) -> None:
    """The runner appends its own `close` call to the whole transcript, after the last step."""
    assert _run(_demo(tmp_path, _steps()[:-1]), tmp_path) == EXIT_PASS
    entries = committed_run.read(tmp_path / "out" / "transcript.md")
    assert [e.step for e in entries] == ["boot", "fire", "aim"]
    assert all(e.reply["status"] == "ok" for e in entries)
