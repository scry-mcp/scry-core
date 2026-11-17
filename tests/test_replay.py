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

from scry_core import recording, replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay_server.py"


#: A step that holds to what the double answers, so a document carries something to hold to.
HELD1 = {"op": "run_for", "frames": 1, "recorded": {"pc": "0x10", "frame": 1}}
HELD2 = {"op": "run_for", "frames": 2, "recorded": {"pc": "0x10", "frame": 2}}


def _lists(refs: list[str]) -> dict[str, Any]:
    """The double's two lists, as a server declares them (`Recorder.lists`)."""
    return {"breakpoints": {"tool": "declaration_list",
                            "refs": [r for r in refs if not r.startswith("w:")]},
            "watches": {"tool": "declaration_list",
                        "refs": [r for r in refs if r.startswith("w:")]}}


def _repo(tmp_path: Path, steps: list[dict[str, Any]], states: list[str] | None = None,
          server: str = "mame", declarations: list[str] | None = None,
          entry: str = "server.py") -> Path:
    shutil.copyfile(FIXTURE, tmp_path / "server.py")
    doc = tmp_path / "session.json"
    doc.write_text(json.dumps({"version": 3, "server": server, "entry": entry,
                               "start": {"system": "board"}, "steps": steps,
                               "needs": {"states": states or [],
                                         "declarations": _lists(declarations or [])}}))
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
    assert "OK perform: 1 step, 1 holding to a recorded answer" in out
    assert "REPLAY session: every step held" in out
    assert (tmp_path / "tmp" / "replays" / "session" / "transcript.md").is_file()


def test_an_entry_that_is_a_module_name_is_started_with_dash_m(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    """A packaged server has no entry file at the repository root, and running its file as a
    script would put the package directory first on the path."""
    package = tmp_path / "packaged"
    package.mkdir()
    (package / "__init__.py").write_text("")
    shutil.copyfile(FIXTURE, package / "server.py")
    doc = _repo(tmp_path, [{"op": "run_for", "frames": 4, "recorded": {"frame": 4}}],
                entry="packaged.server")
    assert _run(monkeypatch, tmp_path, doc, "--binary", "/opt/mame") == 0
    assert "REPLAY session: every step held" in capsys.readouterr().out


@pytest.mark.parametrize("entry", ["server.py", "dosbox_x_server.py"])
def test_an_entry_file_that_is_gone_is_refused_naming_it_before_any_server_starts(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        entry: str) -> None:
    doc = _repo(tmp_path, [HELD1], entry=entry)
    (tmp_path / "server.py").unlink()
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert out.startswith(f"INVALID: the document's entry `{entry}` is not a file in "), out
    assert "importable module name" in out and "did not start" not in out


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
    doc = _repo(tmp_path, [HELD1, {"op": "fails"}])
    assert _run(monkeypatch, tmp_path, doc) == 1
    assert "FAIL perform: step 2 of 2 (fails) failed: no such op" in capsys.readouterr().out


def test_the_runner_runs_as_a_module() -> None:
    ran = subprocess.run([sys.executable, "-m", "scry_core.replay", "--help"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert ran.returncode == 0 and "Exit codes: 0 every step held" in ran.stdout


def test_a_state_the_document_needs_and_the_server_lacks_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1], states=["boot", "missing"])
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert "the server does not have: ['missing']" in out
    assert "REPLAY" not in out, "an INVALID run carries no verdict about the server"


def test_a_start_the_server_refuses_is_exit_3_with_no_verdict(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1])
    monkeypatch.setenv("REPLAY_DOUBLE_REFUSES_START", "1")
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert "INVALID start: the server refused the start" in out and "REPLAY" not in out


def test_a_server_that_does_not_start_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1])
    (tmp_path / "server.py").write_text("raise SystemExit(5)\n")
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert "INVALID: the server did not start" in capsys.readouterr().out


@pytest.mark.parametrize("text, says", [
    ("not json", "not a readable document"),
    ('{"version": 2}', "not a version 3 replay document"),
    ('{"version": 3, "steps": [{}]}', "names no server entry"),
    ('{"version": 3, "entry": "../x.py", "steps": [{}]}', "names no server entry"),
    ('{"version": 3, "entry": "pkg/x", "steps": [{}]}', "names no server entry"),
    ('{"version": 3, "entry": "x.py", "steps": []}', "holds no steps"),
    ('{"version": 3, "entry": "x.py", "steps": [1]}', "one that is not an object"),
    ('{"version": 3, "entry": "x.py", "steps": [{}], "start": []}', "`start` is an object"),
    ('{"version": 3, "entry": "x.py", "steps": [{}], "needs": {"states": "boot"}}',
     "a list of names"),
    ('{"version": 3, "entry": "x.py", "steps": [{}], '
     '"needs": {"declarations": {"breakpoints": {"tool": "b", "refs": "0x10"}}}}',
     "each list key's `tool` and `refs`"),
    ('{"version": 3, "entry": "x.py", "steps": [{"op": "run_for"}]}', "nothing held to"),
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
    doc = _repo(tmp_path, [HELD1])
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
    doc = _repo(tmp_path, [HELD1, HELD2],
                server="dosbox-x")
    monkeypatch.setenv("REPLAY_DOUBLE_SAYS_COMPLETED", "1")
    assert _run(monkeypatch, tmp_path, doc) == 0
    assert "OK perform: 2 steps, 2 holding to a recorded answer" in capsys.readouterr().out


def test_a_list_that_ended_before_its_last_step_is_exit_1_naming_what_ran(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1, HELD2])
    monkeypatch.setenv("REPLAY_DOUBLE_ENDS_EARLY", "1")
    assert _run(monkeypatch, tmp_path, doc) == 1
    out = capsys.readouterr().out
    assert "FAIL perform: 1 of 2 steps ran: the last step was not sent" in out
    assert "every step held" not in out


def test_a_server_that_says_another_count_of_held_steps_is_exit_1(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1, {"op": "run_for", "frames": 3}])
    monkeypatch.setenv("REPLAY_DOUBLE_LIES", "1")
    assert _run(monkeypatch, tmp_path, doc) == 1
    assert "the server says 2 steps held to their recorded answer and the document records 1" \
        in capsys.readouterr().out


@pytest.mark.parametrize("env, says", [
    ("REPLAY_DOUBLE_REFUSES_LIST", "the server did not play the list: step 1 names no op"),
    ("REPLAY_DOUBLE_RAISES", "INVALID perform"),
    ("REPLAY_DOUBLE_DIES", "INVALID"),
])
def test_a_server_that_breaks_instead_of_answering_is_exit_3_not_a_failure(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        env: str, says: str) -> None:
    doc = _repo(tmp_path, [HELD1])
    monkeypatch.setenv(env, "1")
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert says in out and "REPLAY board" not in out and "REPLAY session" not in out, out


def test_a_store_that_declares_otherwise_than_the_recorded_start_found_is_exit_3(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _repo(tmp_path, [HELD1], declarations=["0x10", "w:0x20"])
    monkeypatch.setenv("REPLAY_DOUBLE_DECLARED", "0x10")
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert "`declaration_list` lists [] where the recorded session's start found ['w:0x20']" \
        in capsys.readouterr().out
    monkeypatch.setenv("REPLAY_DOUBLE_DECLARED", "0x10,w:0x20")
    assert _run(monkeypatch, tmp_path, doc) == 0


@pytest.mark.parametrize("env, says", [
    ("REPLAY_DOUBLE_LISTS_FAIL", "INVALID breakpoints: the server did not answer"),
    ("REPLAY_DOUBLE_START_DIES", "INVALID start"),
    ("REPLAY_DOUBLE_STATES_NOT_A_LIST", "answered no list"),
])
def test_a_server_that_breaks_around_the_steps_is_exit_3_too(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
        env: str, says: str) -> None:
    doc = _repo(tmp_path, [HELD1], states=["boot"])
    monkeypatch.setenv(env, "1")
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert says in capsys.readouterr().out


def _stored(tmp_path: Path, start: dict[str, Any], step: dict[str, Any]) -> Path:
    """A replay document a `.scry/` store holds, with the double server beside it."""
    shutil.copyfile(FIXTURE, tmp_path / "server.py")
    doc = tmp_path / ".scry" / "perform" / "session.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(json.dumps({"version": 3, "server": "mame", "entry": "server.py",
                               "start": start, "steps": [{**HELD1, **step}],
                               "needs": {"states": [], "declarations": _lists([])}}))
    return doc


def test_a_stored_document_replays_with_its_placeholders_resolved(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    monkeypatch.setenv("REPLAY_BOARD", "board")
    doc = _stored(tmp_path, {"system": "${env:REPLAY_BOARD}", "binary": "${root}/mame"},
                  {"path": "${root}/states/boot.sta"})
    assert recording.read_document(str(doc))["steps"][0]["path"] == f"{tmp_path}/states/boot.sta"
    assert _run(monkeypatch, tmp_path, doc) == 0
    out = capsys.readouterr().out
    assert "OK start: started board on ./mame" in out, out            # the root spelled .
    assert "REPLAY session: every step held" in out, out


def test_a_stored_document_that_needs_a_sessions_scratch_is_exit_3_naming_it(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    doc = _stored(tmp_path, {"system": "board"}, {"path": "${state}/boot.sta"})
    assert _run(monkeypatch, tmp_path, doc) == 3
    out = capsys.readouterr().out
    assert "`${state}`" in out and "perform(path=)" in out and "REPLAY" not in out, out


def test_the_lists_a_replay_reads_are_the_ones_the_document_names(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
        ) -> None:
    """Which tools list a server's declarations is the server's word, carried by the document:
    a third list the recorded server had is read too, and one the server lacks is no verdict."""
    doc = _repo(tmp_path, [HELD1])
    data = json.loads(doc.read_text())
    data["needs"]["declarations"]["regpoints"] = {"tool": "declaration_list", "refs": []}
    doc.write_text(json.dumps(data))
    assert _run(monkeypatch, tmp_path, doc) == 3
    assert "answered no `regpoints` list" in capsys.readouterr().out


