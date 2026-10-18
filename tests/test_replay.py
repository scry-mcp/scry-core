"""`scry_core.replay`: the runner of a replay document over a double server on stdio, its exit
codes and its lines."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scry_core import replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_server.py"




def _repo(tmp_path: Path, steps: list[dict[str, Any]], states: list[str] | None = None,
          server: str = "mame") -> Path:
    shutil.copyfile(FIXTURE, tmp_path / replay.SERVERS[server])
    doc = tmp_path / "session.json"
    doc.write_text(json.dumps({"version": 1, "server": server, "start": {"system": "board"},
                               "steps": steps, "needs": {"states": states or []}}))
    return doc


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, doc: Path, *argv: str) -> int:
    monkeypatch.chdir(tmp_path)
    return replay.main([str(doc), *argv])


def test_a_document_whose_steps_hold_replays_with_exit_0(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 4,
                            "recorded": {"pc": "0x10", "frame": 4}}], states=["boot"])
    assert _run(monkeypatch, tmp_path, doc, "--binary", "/opt/mame") == 0
    out = capsys.readouterr().out
    assert "OK start: started board on /opt/mame" in out
    assert "OK perform: 1 steps, 1 holding to a recorded answer" in out
    assert "REPLAY session: every step held" in out
    assert (tmp_path / "tmp" / "replays" / "session" / "transcript.md").is_file()


def test_a_step_that_diverges_is_exit_1_naming_the_step_and_the_field(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 4}, {"op": "run_for", "frames": 5,
                            "recorded": {"frame": 6}}], server="dosbox-x")
    assert _run(monkeypatch, tmp_path, doc) == 1
    out = capsys.readouterr().out
    assert "FAIL perform: diverged at step 2 of 2 (run_for): frame recorded 6, got 5" in out
    assert "REPLAY session: it did not hold" in out


def test_a_step_that_fails_is_exit_1_in_the_servers_own_words(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}, {"op": "fails"}])
    assert _run(monkeypatch, tmp_path, doc) == 1
    assert "FAIL perform: step 2 of 2 (fails) failed: no such op" in capsys.readouterr().out


def test_the_runner_runs_as_a_module() -> None:
    ran = subprocess.run([sys.executable, "-m", "scry_core.replay", "--help"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert ran.returncode == 0 and "Exit codes: 0 every step held" in ran.stdout


def test_a_state_the_document_needs_and_the_server_lacks_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}], states=["boot", "missing"])
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert "the server does not have: ['missing']" in out
    assert "REPLAY" not in out, "an INVALID run carries no verdict about the server"


def test_a_start_the_server_refuses_is_exit_3_with_no_verdict(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}])
    monkeypatch.setenv("REPLAY_DOUBLE_REFUSES_START", "1")
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert "INVALID start: the server refused the start" in out and "REPLAY" not in out


def test_a_server_that_does_not_start_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}])
    (tmp_path / "server.py").write_text("raise SystemExit(5)\n")
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert "INVALID: the server did not start" in capsys.readouterr().out


@pytest.mark.parametrize("text, says", [
    ("not json", "not a readable document"),
    ('{"version": 2}', "not a version 1 replay document"),
    ('{"version": 1, "server": "other", "steps": [{}]}', "names server 'other'"),
    ('{"version": 1, "server": "mame", "steps": []}', "holds no steps"),
    ('{"version": 1, "server": "mame", "steps": [1]}', "one that is not an object"),
    ('{"version": 1, "server": "mame", "steps": [{}], "start": []}', "`start` is an object"),
    ('{"version": 1, "server": "mame", "steps": [{}], "needs": {"states": "boot"}}',
     "a list of state names"),
])
def test_a_document_that_is_not_one_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        text: str, says: str) -> None:
    doc = tmp_path / "bad.json"
    doc.write_text(text)
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert says in capsys.readouterr().out


def test_a_document_that_is_not_text_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = tmp_path / "bin.json"
    doc.write_bytes(b"\xff\xfe\x00")
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert "not a readable document" in capsys.readouterr().out


def test_anything_else_that_stops_the_run_before_a_verdict_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}])
    (tmp_path / "a-file").write_text("")
    assert _run(monkeypatch, tmp_path, doc, "--transcript",
                str(tmp_path / "a-file" / "t.md")) == 3
    assert capsys.readouterr().out.startswith("INVALID: ")


def test_an_unknown_option_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as e:
        replay.main(["x.json", "--speed", "2"])
    assert e.value.code == 2


def test_the_perform_line_counts_the_steps_in_either_servers_word(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}, {"op": "run_for", "frames": 2}],
                server="dosbox-x")
    monkeypatch.setenv("REPLAY_DOUBLE_SAYS_COMPLETED", "1")
    assert _run(monkeypatch, tmp_path, doc) == 0
    assert "OK perform: 2 steps, 0 holding to a recorded answer" in capsys.readouterr().out


def test_a_list_that_ended_before_its_last_step_is_exit_1_naming_what_ran(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 1}, {"op": "run_for", "frames": 2}])
    monkeypatch.setenv("REPLAY_DOUBLE_ENDS_EARLY", "1")
    assert _run(monkeypatch, tmp_path, doc) == 1
    out = capsys.readouterr().out
    assert "FAIL perform: 1 of 2 steps ran: the last step was not sent" in out
    assert "every step held" not in out
