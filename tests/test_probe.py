"""`scry_core.probe`, judged offline through its seam.

The probe is pointed at `fixtures/probe/servers.py`: real tools of the two emulator servers,
frozen as the client delivered them. The answers under `fixtures/probe/answers/` were RECORDED
from real haiku runs of the fixture tasks beside them, on a surface narrowed to the tools those
tasks name (one task file with a single task is a coverage hole on the full surface, by design).
The two `claude-*.json` documents are what a real `claude --print --output-format json` printed:
one answer, and one run refused for its budget. What judges a server's own tasks, captures and
pre-gate check lives in that server's suite.
"""

import dataclasses
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from scry_core import probe, probe_captures, probe_checks
from scry_core import probe_any_of as any_of

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "probe"
SERVERS_FILE = FIXTURES / "servers.py"

REPO = probe.configure(SERVERS_FILE, FIXTURES / "tasks")
SURFACES = {s: probe.load_surface(REPO, s) for s in ("mame", "dosbox-x")}
#: The tasks directory a run names, which `probe_env` points at a copy a test may edit.
TASKS = {"dir": FIXTURES / "tasks"}


def _pointed() -> list[str]:
    """The two options every run names: the fixture servers and the tasks the probe reads now."""
    return ["--servers", str(SERVERS_FILE), "--tasks", str(TASKS["dir"])]


def _tasks(server: str) -> list[dict[str, Any]]:
    doc: dict[str, list[dict[str, Any]]] = json.loads(
        (FIXTURES / "tasks" / f"{server}.json").read_text())
    return doc["tasks"]


def _narrowed(server: str) -> probe.Surface:
    """The real surface, narrowed to the tools the fixture tasks name."""
    return probe_checks.narrowed(SURFACES[server], _tasks(server))


@pytest.fixture
def probe_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The probe pointed at the fixtures: tasks and answers copied where a test may edit them,
    and its output kept under `tmp_path`."""
    tasks, answers = tmp_path / "tasks", tmp_path / "answers"
    shutil.copytree(FIXTURES / "tasks", tasks)
    shutil.copytree(FIXTURES / "answers", answers)
    real = probe.configure

    def pointed_here(servers: Path, tasks_dir: Path) -> probe.ProbeRepo:
        return dataclasses.replace(real(servers, tasks_dir), out_dir=tmp_path / "out",
                                   captured_dir=tmp_path / "captured")

    monkeypatch.setattr(probe, "configure", pointed_here)
    monkeypatch.setitem(TASKS, "dir", tasks)
    monkeypatch.setattr(probe, "load_surface", lambda _repo, server: _narrowed(server))
    monkeypatch.setenv(probe.ANSWERS_ENV, str(answers))
    return tmp_path


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    rc = probe.main([*argv, *_pointed()])
    return rc, capsys.readouterr().out.splitlines()


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert text.count(old) == 1, f"{old!r} is not in {path} exactly once"
    path.write_text(text.replace(old, new))


def _judge(server: str, task_id: str, line: str) -> probe.Verdict:
    return probe_checks.judge_line(SURFACES[server], _tasks(server), task_id, line)


# ---- a whole run, through the seam ------------------------------------------------------------


@pytest.mark.parametrize(("server", "tool"), [("mame", "read_memory"), ("dosbox-x", "step")])
def test_captured_answers_pass_and_the_path_is_last(
        probe_env: Path, capsys: pytest.CaptureFixture[str], server: str, tool: str) -> None:
    rc, lines = _run([server], capsys)
    assert rc == probe.EXIT_PASS, lines
    assert lines[:2] == [f"PASS {server} {tool} 3/3",
                         "SUMMARY 1 tools over 3 run(s): 1 PASS, 0 FAIL"]
    out = Path(lines[-1])
    assert len(lines) == 3 and out.parent == probe_env / "out" and out.is_dir()
    assert (out / "report.txt").read_text().splitlines() == lines
    assert (out / f"{server}-run3.txt").read_text() == (probe_env / "answers" /
                                                         f"{server}-run3.txt").read_text()
    verdicts = json.loads((out / f"{server}-verdicts.json").read_text())
    assert len(verdicts) == 3 and all(v["right"] for run in verdicts for v in run.values())


def test_one_wrong_run_fails_the_tool_and_names_the_task(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _edit(probe_env / "answers" / "mame-run2.txt", ', "length": 6', "")
    rc, lines = _run(["mame"], capsys)
    assert rc == probe.EXIT_FAIL
    assert lines[:2] == ["FAIL mame read_memory 2/3 (M1)",
                         "SUMMARY 1 tools over 3 run(s): 0 PASS, 1 FAIL"]
    verdict = json.loads((Path(lines[-1]) / "mame-verdicts.json").read_text())[1]["M1"]
    assert verdict["right"] is False and verdict["why"] == "length=16, expected 6"


def test_two_runs_in_one_second_keep_two_directories(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A run's directory is named by the second it started in, which two runs can share; each
    still gets its own. The two runs answer differently, so an overwrite would show in what
    the first one left."""
    real = probe.new_run_dir
    monkeypatch.setattr(probe, "new_run_dir", lambda repo, _now: real(repo, SAME_SECOND))
    _edit(probe_env / "answers" / "mame-run2.txt", ', "length": 6', "")
    first = _run(["mame"], capsys)[1]
    _edit(probe_env / "answers" / "mame-run2.txt", '"ref": "PlayerX"',
          '"ref": "PlayerX", "length": 6')
    second = _run(["mame"], capsys)[1]
    assert (first[0], second[0]) == ("FAIL mame read_memory 2/3 (M1)",
                                     "PASS mame read_memory 3/3"), (first, second)
    assert first[-1] != second[-1], "both runs wrote into one directory"
    for lines, right in ((first, False), (second, True)):
        out = Path(lines[-1])
        assert out.parent == probe_env / "out" and out.name.startswith("20000102T030405Z-")
        assert (out / "report.txt").read_text().splitlines() == lines
        verdicts = json.loads((out / "mame-verdicts.json").read_text())
        assert verdicts[1]["M1"]["right"] is right, verdicts


#: Any one second, given in a zone other than UTC so the name shows which zone it is spelled in.
SAME_SECOND = dt.datetime(2000, 1, 2, 4, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=1)))


def test_a_run_directory_is_made_with_its_missing_parents(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real root sits under a `tmp/` a fresh clone does not have."""
    repo = dataclasses.replace(REPO, out_dir=tmp_path / "tmp" / "mcp_probe")
    out = probe.new_run_dir(repo, SAME_SECOND)
    assert out.is_dir() and out.parent == tmp_path / "tmp" / "mcp_probe"
    assert out.name.startswith("20000102T030405Z-"), out.name


def test_runs_counts_only_the_runs_asked_for(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (probe_env / "answers" / "dosbox-x-run2.txt").unlink()
    rc, lines = _run(["dosbox-x", "--runs", "1"], capsys)
    assert rc == probe.EXIT_PASS and lines[0] == "PASS dosbox-x step 1/1"


# ---- the per-task capture: what the check refuses --------------------------------------------


def _captured_by_hand(tmp_path: Path) -> tuple[Path, Path]:
    """The narrowed mame fixture, one capture per task, written from the real answers beside
    it (all three runs right), and a copy of its task file a test may edit."""
    tasks_file = tmp_path / "mame.json"
    shutil.copy(FIXTURES / "tasks" / "mame.json", tasks_file)
    captured = tmp_path / "captured"
    captured.mkdir()
    texts = [(FIXTURES / "answers" / f"mame-run{k}.txt").read_text() for k in (1, 2, 3)]
    for task in _tasks("mame"):
        runs = [{"lines": [ln for ln in t.splitlines() if ln.startswith(f"{task['id']}:")],
                 "right": True} for t in texts]
        (captured / f"{task['id']}.json").write_text(json.dumps({"task": task, "runs": runs}))
    return captured, tasks_file


def _problems(captured: Path, tasks_file: Path) -> list[str]:
    return probe_captures.capture_problems(REPO, "mame", captured, tasks_file)


def test_a_capture_of_every_task_judged_as_it_was_has_no_problem(tmp_path: Path) -> None:
    assert _problems(*_captured_by_hand(tmp_path)) == []


def test_a_directory_with_no_capture_examined_nothing(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    for f in captured.iterdir():
        f.unlink()
    for where in (captured, tmp_path / "absent"):
        problems = _problems(where, tasks_file)
        assert len(problems) == 1 and problems[0].startswith("INVALID: no capture examined")


def test_a_task_with_no_capture_is_named(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    (captured / "M3.json").unlink()
    (captured / "M1.json").unlink()
    assert _problems(captured, tasks_file) == ["mame: no capture of task M1, M3"]


def test_a_capture_of_no_task_is_an_orphan(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    doc = json.loads((captured / "M1.json").read_text())
    doc["task"]["id"] = "M9"
    (captured / "M9.json").write_text(json.dumps(doc))
    assert _problems(captured, tasks_file) == [
        "mame M9: captured, but the task file holds no task M9"]


def test_a_capture_answered_to_another_question_is_stale(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    _edit(tasks_file, "Read 6 bytes of memory at the symbol PlayerX.",
          "Read 7 bytes of memory at the symbol PlayerX.")
    assert _problems(captured, tasks_file) == [
        "mame M1: captured for another question than the task file asks now"]


def test_a_stored_verdict_the_surface_no_longer_gives_is_named(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    m1 = json.loads((captured / "M1.json").read_text())
    m1["runs"][1]["right"] = False
    (captured / "M1.json").write_text(json.dumps(m1))
    m3 = json.loads((captured / "M3.json").read_text())
    m3["runs"][2]["lines"] = [m3["runs"][2]["lines"][0].replace('"length": 12', '"length": 13')]
    (captured / "M3.json").write_text(json.dumps(m3))
    assert _problems(captured, tasks_file) == [
        "mame M1 run 2: judged right now, captured as wrong",
        "mame M3 run 3: judged wrong now (length=13, expected 12), captured as right"]


def test_a_task_edited_from_one_to_true_is_stale(tmp_path: Path) -> None:
    """`True` is not `1` to the judge, so it is not the same question either."""
    captured, tasks_file = _captured_by_hand(tmp_path)
    _edit(tasks_file, '"length": 6}', '"length": 1}')
    m1 = json.loads((captured / "M1.json").read_text())
    m1["task"]["args"]["length"] = True
    (captured / "M1.json").write_text(json.dumps(m1))
    assert _problems(captured, tasks_file) == [
        "mame M1: captured for another question than the task file asks now"]


def test_a_capture_whose_tool_left_the_surface_is_named(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whole = SURFACES["mame"]
    monkeypatch.setattr(probe, "load_surface", lambda _repo, _server: dataclasses.replace(
        whole, tools={n: t for n, t in whole.tools.items() if n != "read_memory"}))
    problems = _problems(*_captured_by_hand(tmp_path))
    assert [p.split(":")[0] for p in problems] == ["mame M1", "mame M3"], problems
    assert all("cannot be judged now" in p for p in problems), problems


@pytest.mark.parametrize(("content", "problem"), [
    ("{", "M1.json is not a capture"),
    ('{"task": {"id": "M1"}}', "M1.json is not a capture"),
    ('{"task": {"id": "M1"}, "runs": []}', "M1.json is not a capture"),
    ('{"task": {"id": "M1"}, "runs": [{"lines": "M1: x", "right": true}]}',
     "M1.json is not a capture"),
    ('{"task": {"id": "M2"}, "runs": [{"lines": [], "right": true}]}', "M1.json holds task M2"),
])
def test_a_file_that_is_not_a_capture_of_its_name_is_named(
        tmp_path: Path, content: str, problem: str) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    (captured / "M1.json").write_text(content)
    problems = _problems(captured, tasks_file)
    assert len(problems) == 1 and problems[0].startswith(f"mame M1: {problem}"), problems


# ---- the per-task capture: what the writer takes from a real run ----------------------------


def _a_run(capsys: pytest.CaptureFixture[str]) -> Path:
    """A run directory exactly as a real run leaves it, made through the seam."""
    _, lines = _run(["mame"], capsys)
    return Path(lines[-1])


def _capture(run_dir: Path, ids: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, list[str]]:
    return _run(["mame", "--capture", str(run_dir), "--ids", ids], capsys)


def _written(probe_env: Path, tid: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((probe_env / "captured" / "mame" / f"{tid}.json").read_text())
    return doc


def test_the_writer_captures_only_the_ids_named_and_makes_no_run_directory(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    runs_before = sorted((probe_env / "out").iterdir())
    rc, lines = _capture(run_dir, "M1,M3", capsys)
    assert rc == probe.EXIT_PASS, lines
    assert sorted(p.name for p in (probe_env / "captured" / "mame").iterdir()) == [
        "M1.json", "M3.json"]
    assert len(lines) == 3 and lines[0].endswith("M1.json") and lines[2].startswith("SUMMARY 2")
    m1 = _written(probe_env, "M1")
    assert m1["task"] == next(t for t in _tasks("mame") if t["id"] == "M1")
    assert m1["runs"] == [{"lines": ['M1: {"tool": "read_memory", "args": {"ref": "PlayerX", '
                                     '"length": 6}}'], "right": True}] * 3
    assert sorted((probe_env / "out").iterdir()) == runs_before


def test_the_writer_keeps_every_line_and_the_root_mark(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    answers = probe_env / "answers" / "mame-run2.txt"
    answers.write_text(answers.read_text() + '\nM1: {"tool": "status", "args": {}}\n')
    _edit(probe_env / "answers" / "mame-run3.txt", '"ref": "PlayerX"',
          f'"ref": "{REPO.root}/PlayerX"')
    run_dir = _a_run(capsys)
    assert _capture(run_dir, "M1", capsys)[0] == probe.EXIT_PASS
    runs = _written(probe_env, "M1")["runs"]
    assert [len(r["lines"]) for r in runs] == [1, 2, 1]
    assert [r["right"] for r in runs] == [True, False, False]
    assert runs[2]["lines"][0].startswith('M1: {"tool": "read_memory", "args": {"ref": '
                                          f'"{probe.ROOT_MARK}/PlayerX"')
    assert str(REPO.root) not in json.dumps(runs)


def test_what_the_writer_captures_is_judged_as_it_was(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _edit(probe_env / "answers" / "mame-run2.txt", ', "length": 6', "")
    run_dir = _a_run(capsys)
    assert _capture(run_dir, "M1,M2,M3", capsys)[0] == probe.EXIT_PASS
    assert _written(probe_env, "M1")["runs"][1]["right"] is False
    assert probe_captures.capture_problems(REPO, "mame", probe_env / "captured" / "mame",
                                  probe_env / "tasks" / "mame.json") == []


@pytest.mark.parametrize(("argv", "said"), [
    (["mame", "--capture", "x"], "go together"), (["mame", "--ids", "M1"], "go together"),
    (["mame", "--capture", "x", "--ids", "M1", "--runs", "1"], "without --runs"),
    (["mame", "--capture", "x", "--ids", "M1", "--check"], "without --runs"),
    (["dosbox-x", "--capture", "x", "--ids", "D1"], "dosbox-x has no capture"),
    (["all", "--capture", "x", "--ids", "M1"], "all has no capture"),
    (["mame", "--capture", "x", "--ids", ""], "empty id"),
    (["mame", "--capture", "x", "--ids", "M1,,M3"], "empty id"),
    (["mame", "--capture", "x", "--ids", "M1,M1"], "an id twice"),
])
def test_a_capture_asked_wrongly_is_usage(
        argv: list[str], said: str, probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        probe.main([*argv, *_pointed()])
    assert exc.value.code == 2 and said in capsys.readouterr().err
    assert not (probe_env / "captured").exists() and not (probe_env / "out").exists()


def _invalid(probe_env: Path, run_dir: Path, ids: str, said: str,
             capsys: pytest.CaptureFixture[str]) -> None:
    rc, lines = _capture(run_dir, ids, capsys)
    assert rc == probe.EXIT_INVALID and lines[0].startswith("INVALID ") and said in lines[0], lines
    assert not (probe_env / "captured").exists()


def test_a_directory_holding_no_run_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = probe_env / "empty"
    empty.mkdir()
    _invalid(probe_env, empty, "M1", "holds no run", capsys)


def test_an_id_the_task_file_does_not_hold_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _invalid(probe_env, _a_run(capsys), "M1,M9", "task file holds no task M9", capsys)


def test_an_id_the_run_did_not_judge_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    verdicts = run_dir / "mame-verdicts.json"
    doc = json.loads(verdicts.read_text())
    del doc[1]["M3"]
    verdicts.write_text(json.dumps(doc))
    _invalid(probe_env, run_dir, "M3", "judged no task M3", capsys)


def test_a_run_missing_one_of_its_answers_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    (run_dir / "mame-run3.txt").unlink()
    _invalid(probe_env, run_dir, "M1", "mame-run3.txt", capsys)


@pytest.mark.parametrize("verdicts", ["[]", "{", '[{"M1": {}}]', '[{"M1": true}]',
                                      '[{"M1": {"right": 1}}]'])
def test_verdicts_that_cannot_be_read_are_invalid_not_a_fail(
        probe_env: Path, capsys: pytest.CaptureFixture[str], verdicts: str) -> None:
    run_dir = _a_run(capsys)
    (run_dir / "mame-verdicts.json").write_text(verdicts)
    (run_dir / "mame-run2.txt").unlink()
    (run_dir / "mame-run3.txt").unlink()
    _invalid(probe_env, run_dir, "M1", "mame-verdicts.json", capsys)


def test_a_capture_that_breaks_is_invalid_not_a_fail(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    (run_dir / "mame-run1.txt").write_bytes(b"M1: \xff\xfe\n")
    _invalid(probe_env, run_dir, "M1", "the capture broke", capsys)


def test_a_run_made_on_another_surface_is_not_captured(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A description edited since the run means the model read another text than the one the
    capture would be filed under."""
    run_dir = _a_run(capsys)
    narrowed = _narrowed("mame")
    edited = dataclasses.replace(narrowed.tools["read_memory"],
                                 description=narrowed.tools["read_memory"].description + " More.")
    monkeypatch.setattr(probe, "load_surface", lambda _repo, _server: dataclasses.replace(
        narrowed, tools={"read_memory": edited}))
    _invalid(probe_env, run_dir, "M1", "another surface", capsys)


def test_a_capture_whose_check_no_longer_knows_its_tool_is_named(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "load_surface", lambda _repo, _server: dataclasses.replace(
        _narrowed("mame"), check=_unknown_tool_check))
    problems = _problems(*_captured_by_hand(tmp_path))
    assert [p.split(":")[0] for p in problems] == ["mame M1", "mame M3"], problems
    assert all("does not know read_memory" in p for p in problems), problems


def test_a_task_judged_otherwise_now_than_in_its_run_is_not_captured(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    _edit(probe_env / "tasks" / "mame.json", '"length": 6}', '"length": 7}')
    _invalid(probe_env, run_dir, "M1", "M1 run 1 is judged wrong now", capsys)


def test_a_prompt_cut_short_since_the_run_is_asked_otherwise(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    _edit(probe_env / "tasks" / "mame.json", "at the symbol PlayerX.", "at the symbol PlayerX")
    _invalid(probe_env, run_dir, "M1", "M1 was asked otherwise", capsys)


def test_a_task_naming_the_tree_round_trips_through_the_mark(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A task file and an answer that name this tree are stored with `{root}`, and the capture
    is still judged right wherever the tree sits."""
    task = {"id": "M4", "prompt": f"Read 6 bytes at the symbol named {probe.ROOT_MARK}/x.",
            "tool": "read_memory", "args": {"ref": f"{probe.ROOT_MARK}/x", "length": 6}}
    _edit(probe_env / "tasks" / "mame.json", "\n]}", ",\n  " + json.dumps(task) + "\n]}")
    for k in (1, 2, 3):
        answers = probe_env / "answers" / f"mame-run{k}.txt"
        answers.write_text(answers.read_text() + '\nM4: {"tool": "read_memory", "args": '
                           f'{{"ref": "{REPO.root}/x", "length": 6}}}}\n')
    run_dir = _a_run(capsys)
    assert _capture(run_dir, "M1,M2,M3,M4", capsys)[0] == probe.EXIT_PASS
    m4 = _written(probe_env, "M4")
    assert m4["task"] == task and str(REPO.root) not in json.dumps(m4)
    assert [r["right"] for r in m4["runs"]] == [True] * 3
    assert probe_captures.capture_problems(REPO, "mame", probe_env / "captured" / "mame",
                                  probe_env / "tasks" / "mame.json") == []


def test_a_capture_taken_again_replaces_only_its_own_file(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _capture(_a_run(capsys), "M1,M3", capsys)[0] == probe.EXIT_PASS
    m3 = (probe_env / "captured" / "mame" / "M3.json").read_text()
    _edit(probe_env / "answers" / "mame-run2.txt", ', "length": 6', "")
    assert _capture(_a_run(capsys), "M1", capsys)[0] == probe.EXIT_PASS
    assert [r["right"] for r in _written(probe_env, "M1")["runs"]] == [True, False, True]
    assert (probe_env / "captured" / "mame" / "M3.json").read_text() == m3


def test_a_task_asked_otherwise_since_the_run_is_not_captured(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = _a_run(capsys)
    _edit(probe_env / "tasks" / "mame.json", "Read 12 bytes of memory", "Read 14 bytes of memory")
    rc, lines = _capture(run_dir, "M1,M3", capsys)
    assert rc == probe.EXIT_INVALID and "M3" in lines[0] and "asked" in lines[0], lines
    assert not (probe_env / "captured").exists()


# ---- the judge ------------------------------------------------------------------------------


@pytest.mark.parametrize(("line", "why"), [
    # An argument left out that the task needs: its default is not the expected value.
    ('M1: {"tool": "read_memory", "args": {"ref": "PlayerX"}}', "length=16, expected 6"),
    ('M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6, "size": 6}}',
     "it does not bind to the signature: got an unexpected keyword argument 'size'"),
    ('M1: {"tool": "memdump", "args": {"ref": "PlayerX", "length": 6}}',
     "called 'memdump', expected 'read_memory'"),
    ('M1: {"tool": "read_memory", "args": {"ref": "playerx", "length": 6}}',
     'ref="playerx", expected "PlayerX"'),
    ('M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": "6"}}',
     'length="6", expected 6'),
    ("M1: CANNOT there is no such symbol", "answered CANNOT"),
    ("M1: read_memory(ref='PlayerX', length=6)", "the line does not parse"),
    ('M1: {"name": "read_memory"}', 'not {"tool": <name>, "args": {...}}'),
    ('M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}\n'
     'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}', "answered 2 times"),
    ("M2: CANNOT one machine per server", "no answer line"),
])
def test_a_call_that_is_not_the_expected_one_is_wrong(line: str, why: str) -> None:
    verdict = _judge("mame", "M1", line)
    assert (verdict.right, verdict.why) == (False, why)


def test_the_right_call_is_right_however_it_is_dressed() -> None:
    for line in ['M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}',
                 '- **M1**: `{"tool": "read_memory", "args": {"length": 6.0, "ref": "PlayerX"}}`']:
        assert _judge("mame", "M1", line).right, line


def test_an_argument_passed_at_its_default_counts_as_absent() -> None:
    line = ('D1: {"tool": "step", "args": {"mode": "into", "count": 3, "e9": "none", '
            '"e9_filter": "."}}')
    assert _judge("dosbox-x", "D1", line).right


def test_allowed_arguments_take_any_value_and_any_of_takes_either() -> None:
    surface = _narrowed("dosbox-x")
    task = {"id": "D1", "prompt": "p", "tool": "step",
            "args": {"mode": {"any_of": ["into", "over"]}, "count": 3}, "allow": ["e9_filter"]}
    for mode, right in [("into", True), ("over", True), ("out", False)]:
        line = (f'D1: {{"tool": "step", "args": {{"mode": "{mode}", "count": 3, '
                f'"e9_filter": "PlayerX"}}}}')
        assert probe.judge(surface, task, probe.parse(line, ["D1"])["D1"]).right is right


def test_equivalent_whole_calls_are_each_right() -> None:
    whole = SURFACES["mame"]
    surface = dataclasses.replace(whole, tools={"watch_add": whole.tools["watch_add"]})
    shown = {"ref": "SpriteBuf", "mode": "show"}
    task: dict[str, Any] = {"id": "W1", "prompt": "p", "tool": "watch_add", "args": {"any_of": [
        dict(shown, fmt="u8[12]"), dict(shown, length=12, fmt="u8"),
        dict(shown, length=12, fmt="u8[12]")]}}
    assert probe.task_problems(surface, [task]) == []
    assert probe.coverage_holes(surface, [task]) == ["no task names mame watch_add.by",
                                                     "no task names mame watch_add.cpu",
                                                     "no task names mame watch_add.condition",
                                                     "no task names mame watch_add.trigger",
                                                     "no task names mame watch_add.space",
                                                     "no task names mame watch_add.trigger_type",
                                                     "mame has no CANNOT task"]
    for args, why in [('"length": 12, "fmt": "u8"', "right"), ('"fmt": "u8[12]"', "right"),
                      ('"fmt": "u8[12]", "length": 12', "right"),
                      ('"fmt": "u8"', 'fmt="u8", expected "u8[12]"')]:
        line = ('W1: {"tool": "watch_add", "args": {"ref": "SpriteBuf", "mode": "show", '
                f'{args}}}}}')
        assert probe.judge(surface, task, probe.parse(line, ["W1"])["W1"]).why == why, args
    task["args"]["any_of"].append(dict(shown, size=12))
    assert probe.task_problems(surface, [task]) == ["mame task W1: watch_add has no argument size"]


def test_true_is_not_one() -> None:
    assert any_of.same(1, 1.0) and not any_of.same(True, 1) and not any_of.same(1, True)
    assert any_of.same({"a": [1, "x"]}, {"a": [1.0, "x"]}) and not any_of.same([1], [1, 2])
    assert not any_of.same({"a": 1}, {"b": 1}) and not any_of.same("1", 1)


def test_a_cannot_task_is_right_only_as_a_refusal() -> None:
    assert _judge("mame", "M2", "M2: CANNOT one machine per server").right
    call = 'M2: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}'
    assert _judge("mame", "M2", call).why == "expected CANNOT"
    assert _judge("mame", "M2", "M1: CANNOT elsewhere").why == "no answer line"


def test_a_check_that_does_not_know_the_tool_is_invalid() -> None:
    surface = dataclasses.replace(_narrowed("mame"), check=_unknown_tool_check)
    line = 'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}'
    with pytest.raises(probe.Invalid, match="does not know read_memory"):
        probe.judge(surface, _tasks("mame")[0], probe.parse(line, ["M1"])["M1"])


def _unknown_tool_check(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
    raise AssertionError(f"no such tool for a pre-gate check: {tool!r}")


# ---- what is refused before a model is asked ------------------------------------------------


def _refused(probe_env: Path, capsys: pytest.CaptureFixture[str], server: str) -> list[str]:
    rc, lines = _run([server], capsys)
    assert rc == probe.EXIT_INVALID, lines
    assert Path(lines[-1]).is_dir() and not list(Path(lines[-1]).glob("*-run*.txt"))
    return lines[:-1]


def test_a_property_no_task_names_is_a_coverage_hole(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _edit(probe_env / "tasks" / "dosbox-x.json", ', "e9_stamp"]', "]")
    assert _refused(probe_env, capsys, "dosbox-x") == [
        "INVALID no task names dosbox-x step.e9_stamp"]


def test_a_tool_with_no_task_and_a_server_with_no_refusal_are_holes() -> None:
    surface = SURFACES["mame"]
    holes = probe.coverage_holes(surface, _tasks("mame")[:1])
    assert "no task on mame watch_add" in holes and "mame has no CANNOT task" in holes
    # every tool but the one M1 covers, the missing refusal, and the `cpu` M1 does not name
    assert "no task names mame read_memory.cpu" in holes
    assert len(holes) == len(surface.tools) - 1 + 1 + 1


def test_a_value_the_description_holds_is_contamination(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tasks = probe_env / "tasks" / "mame.json"
    _edit(tasks, '"length": 6}', '"length": 1024}')
    assert _refused(probe_env, capsys, "mame") == [
        "INVALID mame task M1: '1024' is in read_memory's own description"]
    _edit(tasks, '"length": 1024}', '"length": 1024}, "grammar": [1024]')
    rc, _ = _run(["mame"], capsys)
    assert rc == probe.EXIT_FAIL  # the captured answers say 6: judged, no longer refused


def test_the_model_is_shown_only_what_the_client_delivers() -> None:
    """A text past the client's cap is cut where the client cuts it, once, in the surface the
    probe loads, and the prompt carries that surface, so no task can PASS on words the client
    never delivers; the server's own cap test still refuses the text in its battery."""
    from scry_core.client_cap import CLIENT_TEXT_CAP

    long = "x" * CLIENT_TEXT_CAP + " PASTTHECUT"
    whole = SURFACES["mame"]
    module = types.ModuleType("long_server")
    module.read_memory = lambda ref, length=16, cpu="": None  # type: ignore[attr-defined]
    listed = [types.SimpleNamespace(name="read_memory", description=long,
                                    input_schema=whole.tools["read_memory"].schema)]

    async def list_tools() -> list[Any]:
        return listed

    module.mcp = types.SimpleNamespace(instructions=long,  # type: ignore[attr-defined]
                                       list_tools=list_tools)
    surface = probe.load_surface(dataclasses.replace(REPO, modules={"long": module}), "long")
    assert "PASTTHECUT" not in surface.instructions + surface.tools["read_memory"].description
    assert "PASTTHECUT" not in probe.prompt_for(surface, [])


def test_a_hex_literal_in_the_prompt_is_checked_too() -> None:
    surface = _narrowed("mame")
    task = {"id": "M3", "prompt": "Read at 0x400.", "tool": "read_memory", "args": {"ref": "x"}}
    assert probe.contamination(surface, [task]) == []
    task["prompt"] = "Read at 0x1234 and nothing else."
    assert probe.contamination(surface, [task]) == []
    described = dataclasses.replace(surface.tools["read_memory"],
                                    description="e.g. `ref=0x1234`")
    narrowed = dataclasses.replace(surface, tools={"read_memory": described})
    assert probe.contamination(narrowed, [task]) == [
        "mame task M3: '0x1234' is in read_memory's own description"]


def test_values_are_read_at_every_depth() -> None:
    assert list(any_of.leaves({"a": [1, {"any_of": [2, "x"]}], "b": {"c": 3}})) == [1, 2, "x", 3]
    assert any_of.concrete({"a": [{"any_of": [1, 2]}], "b": {"any_of": ["x", "y"]}}) == {
        "a": [1], "b": "x"}


def test_contamination_passes_over_a_task_that_names_no_tool() -> None:
    task = {"id": "M9", "prompt": "Read at 0x2A40.", "tool": "nope", "args": {"ref": "x"}}
    assert probe.contamination(_narrowed("mame"), [task]) == []


def test_small_numbers_and_booleans_are_not_contamination() -> None:
    assert probe._spellings(15) == [] and probe._spellings(True) == []
    assert probe._spellings(None) == [] and probe._spellings(" ") == []
    assert probe._spellings(16) == ["16", "0x10"] and probe._spellings(2.5) == []
    assert probe._spellings(20.5) == ["20.5"] and probe._spellings([1]) == []


@pytest.mark.parametrize(("task", "problem"), [
    ({"prompt": "p", "tool": "step"}, "task #0: needs an `id` of letters, digits, `_` or `-`"),
    ({"id": "D1", "prompt": "", "tool": "step", "args": {"count": 3}}, "task D1: needs a `prompt`"),
    ({"id": "D1", "prompt": "p", "tool": "stepp"}, "task D1: `tool` names no tool of this server"),
    ({"id": "D1", "prompt": "p", "tool": "step", "args": {"steps": 3}},
     "task D1: step has no argument steps"),
    ({"id": "D1", "prompt": "p", "tool": "step", "args": {"count": 3}, "allow": ["count"]},
     "task D1: count both expected and allowed"),
    ({"id": "D1", "prompt": "p", "tool": "step", "args": []},
     "task D1: `args` must be an object, or an `any_of` list of objects"),
    ({"id": "D1", "prompt": "p", "tool": "step", "expect": "RIGHT"},
     "task D1: `expect` can only be 'CANNOT'"),
    ({"id": "D1", "prompt": "p", "expect": "CANNOT", "about": "nope"},
     "task D1: `about` names no tool of this server"),
    ({"id": "D1", "prompt": "p", "expect": "CANNOT", "about": "step", "tool": "step"},
     "task D1: a CANNOT task carries no `tool` or `args`"),
    ({"id": "D1", "prompt": "p", "tool": "step", "note": "x"}, "task D1: unknown key(s) note"),
])
def test_a_task_the_server_cannot_hold_is_refused(task: dict[str, Any], problem: str) -> None:
    assert probe.task_problems(_narrowed("dosbox-x"), [task]) == [f"dosbox-x {problem}"]


def test_a_required_argument_must_be_expected_or_allowed_and_ids_are_unique() -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory", "args": {"length": 6}}
    problems = probe.task_problems(_narrowed("mame"), [task, dict(task, args={"ref": "x"})])
    assert problems == ["mame task M1: required ref neither expected nor allowed",
                        "mame task M1: the id is used twice"]


def test_a_task_file_with_nothing_to_examine_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (probe_env / "tasks" / "mame.json").write_text('{"tasks": []}')
    assert _refused(probe_env, capsys, "mame")[0].startswith("INVALID ")
    assert "holds no tasks" in _refused(probe_env, capsys, "mame")[0]
    (probe_env / "tasks" / "mame.json").write_text("{")
    assert "mame.json" in _refused(probe_env, capsys, "mame")[0]


def _toy(**tools: Any) -> types.ModuleType:
    """A server module with `tools` as its attributes, listed by name with a one-word
    description and a schema offering only `ref`."""
    async def list_tools() -> list[Any]:
        return [types.SimpleNamespace(name=n, description="d",
                                      input_schema={"properties": {"ref": {}}}) for n in tools]

    module = types.ModuleType("toy")
    for name, fn in tools.items():
        setattr(module, name, fn)
    module.mcp = types.SimpleNamespace(instructions="i",  # type: ignore[attr-defined]
                                       list_tools=list_tools)
    return module


def test_a_server_that_lists_no_tool_is_invalid() -> None:
    with pytest.raises(probe.Invalid, match="lists no tools"):
        probe.load_surface(dataclasses.replace(REPO, modules={"mame": _toy()}), "mame")


@pytest.mark.parametrize("args", [{"any_of": []}, {"ref": {"any_of": []}, "length": 6}])
def test_an_any_of_with_no_alternative_is_refused(
        args: dict[str, Any], probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    task = {"id": "M1", "prompt": "p", "tool": "read_memory", "args": args}
    assert probe.task_problems(_narrowed("mame"), [task]) == [
        "mame task M1: an `any_of` with no alternative accepts nothing"]
    (probe_env / "tasks" / "mame.json").write_text(json.dumps({"tasks": [task]}))
    assert _run(["mame"], capsys)[0] == probe.EXIT_INVALID


def test_a_grammar_entry_exempts_its_value_whatever_the_case() -> None:
    whole = SURFACES["mame"]
    described = dataclasses.replace(whole.tools["read_memory"], description="`Bug` is a word")
    surface = dataclasses.replace(whole, tools={"read_memory": described})
    task: dict[str, Any] = {"id": "M1", "prompt": "p", "tool": "read_memory",
                            "args": {"ref": "bug"}}
    assert probe.contamination(surface, [task]) == [
        "mame task M1: 'bug' is in read_memory's own description"]
    task["grammar"] = ["BUG"]
    assert probe.contamination(surface, [task]) == []


def _with_default(xs: tuple[int, ...] = (1, 2)) -> None:
    """A tool whose default is not JSON: a tuple, which a model can only write as a list."""


def test_a_default_left_in_place_is_compared_as_json() -> None:
    import inspect

    tool = probe.Tool("t", "d", {"properties": {"xs": {}}}, inspect.signature(_with_default))
    surface = probe.Surface("s", "i", {"t": tool}, None)
    task = {"id": "T1", "prompt": "p", "tool": "t"}
    for line in ['T1: {"tool": "t", "args": {}}', 'T1: {"tool": "t", "args": {"xs": [1, 2]}}']:
        assert probe.judge(surface, task, probe.parse(line, ["T1"])["T1"]).right, line


def test_the_tally_is_per_tool_across_runs() -> None:
    whole = SURFACES["mame"]
    surface = dataclasses.replace(whole, tools={n: whole.tools[n] for n in (
        "read_memory", "memdump", "status")})
    tasks = [{"id": "A", "tool": "read_memory"}, {"id": "B", "tool": "read_memory"},
             {"id": "C", "tool": "memdump"}, {"id": "D", "expect": "CANNOT", "about": "status"}]
    right, wrong = probe.Verdict(True, "", ""), probe.Verdict(False, "", "")
    runs = [{"A": wrong, "B": right, "C": wrong, "D": right},
            {"A": right, "B": wrong, "C": wrong, "D": right},
            {"A": right, "B": right, "C": wrong, "D": right}]
    outcome = probe.tally(surface, tasks, runs)
    assert outcome.lines == ["FAIL mame read_memory 1/3 (A, B)", "FAIL mame memdump 0/3 (C)",
                             "PASS mame status 3/3"]
    assert (outcome.passed, outcome.failed) == (1, 2)


def test_all_runs_every_server_and_sums_them(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    _edit(probe_env / "answers" / "dosbox-x-run1.txt", '"count": 3', '"count": 4')
    rc, lines = _run(["all"], capsys)
    assert (rc, lines[:-1]) == (probe.EXIT_FAIL, [
        "PASS mame read_memory 3/3", "FAIL dosbox-x step 2/3 (D1)",
        "SUMMARY 2 tools over 3 run(s): 1 PASS, 1 FAIL"])


def test_a_probe_that_breaks_is_invalid_not_a_fail(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any) -> None:
        raise KeyError("verdicts")

    monkeypatch.setattr(probe, "run_model", broken)
    rc, lines = _run(["mame"], capsys)
    assert (rc, lines[0]) == (probe.EXIT_INVALID, "INVALID the probe broke, so nothing here is "
                                                  "a verdict: KeyError: 'verdicts'")


# ---- --check: the refusals alone, for the commit path ---------------------------------------


def test_check_covered_is_0_and_writes_nothing(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(probe.ANSWERS_ENV)  # a model call here would fail: none is made
    monkeypatch.setenv("PATH", str(probe_env))
    assert _run(["all", "--check"], capsys) == (probe.EXIT_PASS, [
        "OK mame: 3 tasks cover 1 tools", "OK dosbox-x: 2 tasks cover 1 tools"])
    assert not (probe_env / "out").exists()


def test_check_names_every_refusal_and_is_1(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    _edit(probe_env / "tasks" / "dosbox-x.json", ', "e9_stamp"]', "]")
    assert _run(["all", "--check"], capsys) == (probe.EXIT_FAIL, [
        "OK mame: 3 tasks cover 1 tools", "REFUSED no task names dosbox-x step.e9_stamp"])


def test_check_that_cannot_examine_is_3(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    (probe_env / "tasks" / "mame.json").write_text("{")
    rc, lines = _run(["mame", "--check"], capsys)
    assert rc == probe.EXIT_INVALID and lines[0].startswith("INVALID ") and "mame.json" in lines[0]

    def broken(_repo: probe.ProbeRepo, _server: str) -> None:
        raise KeyError("tools")

    monkeypatch.setattr(probe, "load_surface", broken)
    assert _run(["mame", "--check"], capsys) == (probe.EXIT_INVALID, [
        "INVALID the check broke, so nothing here is a verdict: KeyError: 'tools'"])


def test_check_names_an_entry_that_is_not_a_task(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _edit(probe_env / "tasks" / "mame.json", "\n]}", ',\n  "oops"\n]}')
    assert _run(["mame", "--check"], capsys) == (probe.EXIT_FAIL, [
        "REFUSED mame task #3: needs an `id` of letters, digits, `_` or `-`"])


@pytest.mark.parametrize(("task", "refused"), [
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": 5}',
     "mame task M4: `args` must be an object, or an `any_of` list of objects"),
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX"}, "allow": 3}',
     "mame task M4: `allow` must be a list of argument names"),
    ('{"prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX", "length": 1024}}',
     "mame task #3: needs an `id` of letters, digits, `_` or `-`"),
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX"}, '
     '"allow": ["length", "cpu"], "grammar": 7}',
     "mame task M4: `grammar` must be a list of strings or numbers"),
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"ref": "PlayerX"}, '
     '"allow": ["length", "cpu"], "grammar": [[1]]}',
     "mame task M4: `grammar` must be a list of strings or numbers"),
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"any_of": 5}}',
     "mame task M4: an `any_of` with no alternative accepts nothing"),
    ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"ref": "x"}, "allow": [3]}',
     "mame task M4: `allow` must be a list of argument names"),
    ('{"id": "M4", "prompt": "p", "expect": "CANNOT", "about": "read_memory", "allow": 3}',
     "mame task M4: `allow` must be a list of argument names"),
    ('{"id": "M4", "prompt": "p", "about": "read_memory", "args": {"ref": "x"}}',
     "mame task M4: `about` belongs to a CANNOT task; a call names its `tool`\n"
     "mame task M4: `tool` names no tool of this server"),
])
def test_a_malformed_task_is_refused_and_never_breaks_the_later_passes(
        probe_env: Path, capsys: pytest.CaptureFixture[str], task: str, refused: str) -> None:
    """A task `task_problems` names is not handed to the coverage and contamination passes,
    which read its `args`, `allow`, `grammar` and `id` as the shapes those must have: the check
    answers REFUSED, never a traceback (the no-id case carries a value its tool's description
    holds, so contamination would have reached it)."""
    _edit(probe_env / "tasks" / "mame.json", "\n]}", f",\n  {task}\n]}}")
    assert _run(["mame", "--check"], capsys) == (
        probe.EXIT_FAIL, [f"REFUSED {line}" for line in refused.split("\n")])


def test_a_required_argument_left_to_allow_is_not_put_to_the_servers_judge(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A call the task does not fix whole has no value to judge: the task is taken as it is,
    never a traceback from binding a call that lacks the argument."""
    task = ('{"id": "M4", "prompt": "p", "tool": "read_memory", "args": {"length": 6}, '
            '"allow": ["ref", "cpu"]}')
    _edit(probe_env / "tasks" / "mame.json", "\n]}", f",\n  {task}\n]}}")
    assert _run(["mame", "--check"], capsys) == (probe.EXIT_PASS, [
        "OK mame: 4 tasks cover 1 tools"])


def test_a_check_that_cannot_be_imported_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def unimportable(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
        raise ModuleNotFoundError("No module named 'mame_args'")

    surface = dataclasses.replace(_narrowed("mame"), check=unimportable)
    with pytest.raises(probe.Invalid, match="mame's check cannot be imported"):
        probe.task_problems(surface, _tasks("mame"))


def test_check_refuses_runs_beside_it(probe_env: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        probe.main(["mame", "--check", "--runs", "2", *_pointed()])
    assert exc.value.code == 2


# ---- exit codes ----------------------------------------------------------------------------


def test_a_missing_capture_or_an_empty_answer_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (probe_env / "answers" / "mame-run3.txt").unlink()
    assert _run(["mame"], capsys) == (probe.EXIT_INVALID, [
        f"INVALID {probe.ANSWERS_ENV} holds no mame-run3.txt",
        _only_out(probe_env)])
    (probe_env / "answers" / "mame-run3.txt").write_text("I would read the memory.\n")
    rc, lines = _run(["mame"], capsys)
    assert (rc, lines[0]) == (probe.EXIT_INVALID,
                              "INVALID mame run 3 answered no line for any task")


def _only_out(probe_env: Path) -> str:
    """The one run directory: a name orders nothing once two runs can share a second."""
    (out,) = (probe_env / "out").iterdir()
    return str(out)


@pytest.mark.parametrize("argv", [[], ["mamé"], ["mame", "--runs", "0"], ["mame", "--runs", "x"],
                                  ["mame", "--seconds", "3"]])
def test_usage_is_exit_2(argv: list[str], probe_env: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        probe.main([*argv, *_pointed()])
    assert exc.value.code == 2


# ---- the model call itself ----------------------------------------------------------------


def _fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: str | Path,
                 rc: int = 0) -> Path:
    """A `claude` on PATH that prints a document a real run printed and records its argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv = tmp_path / "argv"
    fake = bin_dir / "claude"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{argv}"\ncat > "{argv}.stdin"\n'
                    f'cat "{FIXTURES / document}"\nexit {rc}\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(probe.ANSWERS_ENV, raising=False)
    return argv


def test_the_model_is_asked_with_nothing_but_the_prompt(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    argv = _fake_claude(probe_env, monkeypatch, "claude-ok.json")
    rc, lines = _run(["mame", "--runs", "1"], capsys)
    assert rc == probe.EXIT_PASS, lines
    # WRITTEN OUT, not read back from `MODEL_COMMAND`: what keeps settings, MCP servers and tools
    # away from the model is these exact words, so a change to any of them is a change to see here.
    assert argv.read_text().splitlines() == [
        "--print", "--model", "haiku", "--effort", "low", "--max-budget-usd", "1",
        "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config", "--tools", "",
        "--output-format", "json"]
    out = Path(lines[-1])
    assert json.loads((out / "mame-run1.json").read_text())["result"] == (
        out / "mame-run1.txt").read_text()
    prompt = (out / "mame-prompt.txt").read_text()
    assert Path(f"{argv}.stdin").read_text() == prompt, "the model was not sent the prompt"
    assert "--- tool: read_memory" in prompt and "M2: Read 6 bytes at PlayerX" in prompt
    assert SURFACES["mame"].instructions in prompt


@pytest.mark.parametrize(("document", "rc", "message"), [
    ("claude-budget-exhausted.json", 1, "`claude` exited 1"),
    ("claude-budget-exhausted.json", 0, "`claude` reported an error"),
    ("tasks/mame.json", 0, "`claude` reported an error"),
    ("answers/mame-run1.txt", 0, "`claude` printed no JSON document"),
])
def test_a_model_call_that_failed_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
        document: str, rc: int, message: str) -> None:
    _fake_claude(probe_env, monkeypatch, document, rc)
    code, lines = _run(["mame", "--runs", "1"], capsys)
    assert code == probe.EXIT_INVALID and lines[0].startswith(f"INVALID {message}"), lines


def test_a_document_that_is_not_an_object_or_not_text_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    printed = probe_env / "printed"
    printed.write_text("null\n")
    _fake_claude(probe_env, monkeypatch, printed)
    assert _run(["mame", "--runs", "1"], capsys)[1][0].startswith(
        "INVALID `claude` reported an error")
    printed.write_bytes(b"\xff\xfe\n")
    assert _run(["mame", "--runs", "1"], capsys)[1][0].startswith(
        "INVALID `claude` printed no JSON document")


def test_a_claude_that_cannot_be_run_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    (probe_env / "bin" / "claude").mkdir(parents=True)
    monkeypatch.setenv("PATH", str(probe_env / "bin"))
    monkeypatch.delenv(probe.ANSWERS_ENV)
    assert _run(["mame", "--runs", "1"], capsys)[1][0].startswith(
        "INVALID `claude` could not be run:")


def test_no_claude_or_one_that_hangs_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(probe.ANSWERS_ENV)
    monkeypatch.setenv("PATH", str(probe_env))
    assert _run(["mame", "--runs", "1"], capsys)[1][0] == "INVALID `claude` is not on PATH"
    _fake_claude(probe_env, monkeypatch, "claude-ok.json")
    (probe_env / "bin" / "claude").write_text("#!/bin/sh\nexec /bin/sleep 5\n")
    monkeypatch.setattr(probe, "CLAUDE_TIMEOUT_S", 0.2)
    assert _run(["mame", "--runs", "1"], capsys)[1][0] == (
        "INVALID `claude` did not answer within 0.2 s")


# ---- pointing the probe at a repository ----------------------------------------------------


@pytest.mark.parametrize("missing", ["--servers", "--tasks"])
def test_the_servers_file_and_the_tasks_are_required(
        missing: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Neither has a default: this module belongs to no repository, and a default would read
    another one's."""
    argv = ["all", "--check", *_pointed()]
    i = argv.index(missing)
    del argv[i:i + 2]
    with pytest.raises(SystemExit) as exc:
        probe.main(argv)
    assert exc.value.code == 2 and missing in capsys.readouterr().err


def test_run_as_a_module_with_no_servers_file_it_exits_2() -> None:
    done = subprocess.run([sys.executable, "-m", "scry_core.probe", "all", "--check"],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 2 and "--servers" in done.stderr, done


def test_run_as_a_module_on_the_fixture_it_checks_every_server() -> None:
    """The control for the case above: the same command, pointed, examines both servers (the
    fixture tasks cover one mame tool of the four frozen, so mame is refused by design)."""
    done = subprocess.run([sys.executable, "-m", "scry_core.probe", "all", "--check",
                           *_pointed_at(FIXTURES / "tasks")],
                          capture_output=True, text=True, check=False)
    assert done.returncode == probe.EXIT_FAIL, done
    assert done.stdout.splitlines() == [
        "REFUSED no task on mame watch_add", "REFUSED no task on mame memdump",
        "REFUSED no task on mame status", "OK dosbox-x: 2 tasks cover 1 tools"], done


def _pointed_at(tasks: Path) -> list[str]:
    return ["--servers", str(SERVERS_FILE), "--tasks", str(tasks)]


def test_a_server_the_file_does_not_load_is_usage(
        capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        probe.main(["nes", "--check", *_pointed()])
    assert exc.value.code == 2
    assert "'nes' (choose from mame, dosbox-x, all)" in capsys.readouterr().err


@pytest.mark.parametrize(("text", "said"), [
    ("ROOT = 1\n", "defines no `load()` and `ROOT`"),
    ("from pathlib import Path\nROOT = Path('.')\ndef load():\n    return {}\n",
     "loads no server"),
])
def test_a_servers_file_the_probe_cannot_use_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, said: str) -> None:
    servers = tmp_path / "servers.py"
    servers.write_text(text)
    rc = probe.main(["all", "--check", "--servers", str(servers), "--tasks", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == probe.EXIT_INVALID and out.startswith("INVALID ") and said in out, out


def test_a_servers_file_that_is_not_there_or_breaks_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("raise KeyError('nope')\n")
    for path, said in [(tmp_path / "absent.py", "absent.py"),
                       (broken, "the servers file broke")]:
        rc = probe.main(["all", "--check", "--servers", str(path), "--tasks", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == probe.EXIT_INVALID and said in out, out
    assert probe.main(["all", "--check", "--servers", str(tmp_path / "x.txt"),
                       "--tasks", str(tmp_path)]) == probe.EXIT_INVALID


def _servers_file(tmp_path: Path, extra: str) -> Path:
    """A servers file loading the frozen fixture, with `extra` appended."""
    servers = tmp_path / "servers.py"
    servers.write_text(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('frozen', {str(SERVERS_FILE)!r})\n"
        "frozen = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(frozen)\n"
        "ROOT = frozen.ROOT\nload = frozen.load\n" + extra)
    return servers


@pytest.mark.parametrize(("extra", "said"), [
    ("CHECKS = {'dosbox_x': print}\n", "names dosbox_x in `CHECKS` or `CAPTURED`"),
    ("CAPTURED = ('mame', 'nes')\n", "names nes in `CHECKS` or `CAPTURED`"),
    ("CAPTURED = 'mame'\n", "`CHECKS` is a dict and `CAPTURED` a tuple"),
    ("CHECKS = [print]\n", "`CHECKS` is a dict and `CAPTURED` a tuple"),
    ("def load():\n    return [1]\n", "loads no server"),
])
def test_a_servers_file_naming_what_it_does_not_load_is_refused_and_changes_nothing(
        tmp_path: Path, extra: str, said: str) -> None:
    """A judge filed under a misspelt name would leave its server judged by signature alone,
    in silence."""
    with pytest.raises(probe.Invalid, match=said):
        probe.configure(_servers_file(tmp_path, extra), tmp_path)


@pytest.mark.parametrize("argv", [["mame", "--check", "--runs", "2"],
                                  ["mame", "--capture", "x"],
                                  ["mame", "--capture", "x", "--ids", "M1", "--check"]])
def test_a_wrong_call_is_usage_before_the_servers_file_runs(
        tmp_path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        probe.main([*argv, "--servers", str(tmp_path / "absent.py"), "--tasks", str(tmp_path)])
    assert exc.value.code == 2


def test_a_run_directory_that_cannot_be_made_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(_repo: probe.ProbeRepo, _now: dt.datetime) -> Path:
        raise PermissionError("read-only")

    monkeypatch.setattr(probe, "new_run_dir", refused)
    rc, lines = _run(["mame"], capsys)
    assert rc == probe.EXIT_INVALID and lines[0].startswith("INVALID no run directory"), lines


def test_a_judge_the_servers_file_gives_judges_the_call(tmp_path: Path) -> None:
    """`CHECKS` is how a repository hands the probe its server's own pre-gate judge."""
    servers = tmp_path / "servers.py"
    servers.write_text(
        f"from pathlib import Path\nimport importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('frozen', {str(SERVERS_FILE)!r})\n"
        f"frozen = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(frozen)\n"
        f"ROOT = frozen.ROOT\nload = frozen.load\n"
        f"def _step(tool, given, effective):\n"
        f"    if effective['e9'] not in ('none', 'log'):\n"
        f"        raise ValueError(f\"e9={{effective['e9']!r}} is not a route\")\n"
        f"CHECKS = {{'dosbox-x': _step}}\n")
    surface = probe.load_surface(probe.configure(servers, FIXTURES / "tasks"), "dosbox-x")
    task = next(t for t in _tasks("dosbox-x") if t["id"] == "D1")
    good = 'D1: {"tool": "step", "args": {"mode": "into", "count": 3}}'
    bad = 'D1: {"tool": "step", "args": {"mode": "into", "count": 3, "e9": "sideways"}}'
    assert probe.judge(surface, task, probe.parse(good, ["D1"])["D1"]).right
    verdict = probe.judge(surface, task, probe.parse(bad, ["D1"])["D1"])
    assert (verdict.right, verdict.why) == (
        False, "the server's check refuses it: e9='sideways' is not a route")


# ---- what the engine hands a server's own judge ---------------------------------------------


def _recording(calls: list[tuple[str, dict[str, Any], dict[str, Any]]],
               refuse: str = "") -> probe.Check:
    def judge(tool: str, given: dict[str, Any], effective: dict[str, Any]) -> None:
        calls.append((tool, dict(given), dict(effective)))
        if refuse and effective.get("count") == 0:
            raise ValueError(refuse)
    return judge


def test_a_judge_gets_the_arguments_given_and_those_with_defaults_apart() -> None:
    """One server's judge rules on what the caller passed, another's on what the tool runs
    with: the engine hands both, and keeps them apart."""
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    surface = dataclasses.replace(SURFACES["dosbox-x"], check=_recording(calls))
    task = next(t for t in _tasks("dosbox-x") if t["id"] == "D1")
    line = 'D1: {"tool": "step", "args": {"mode": "into", "count": 3}}'
    assert probe.judge(surface, task, probe.parse(line, ["D1"])["D1"]).right
    assert calls == [("step", {"mode": "into", "count": 3},
                      {"count": 3, "mode": "into", "e9": "none", "e9_filter": ".",
                       "e9_stamp": None})]


def test_an_expected_call_the_servers_judge_refuses_is_a_task_problem() -> None:
    """The task's own expected call, its first alternative at every `any_of`, is put to the
    server's judge: a task that expects what the server refuses judges nothing it claims to."""
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    surface = dataclasses.replace(SURFACES["dosbox-x"],
                                  check=_recording(calls, refuse="count=0 is no step"))
    args: dict[str, Any] = {"mode": "into", "count": {"any_of": [0, 3]}}
    task = {"id": "D1", "prompt": "p", "tool": "step", "args": args,
            "allow": ["e9", "e9_filter", "e9_stamp"]}
    assert probe.task_problems(surface, [task]) == [
        "dosbox-x task D1: its own expected call is refused: the server's check refuses it: "
        "count=0 is no step"]
    assert calls[0][1] == {"mode": "into", "count": 0}
    args["count"] = {"any_of": [3, 0]}
    assert probe.task_problems(surface, [task]) == []


def test_a_call_with_no_args_is_a_call_with_none() -> None:
    """A tool that takes nothing is written without `args`, which is how a model writes it."""
    task = {"id": "S1", "prompt": "p", "tool": "status"}
    surface = dataclasses.replace(SURFACES["mame"], tools={"status": SURFACES["mame"].tools[
        "status"]})
    for line in ['S1: {"tool": "status"}', 'S1: {"tool": "status", "args": {}}']:
        assert probe.judge(surface, task, probe.parse(line, ["S1"])["S1"]).right, line


def test_a_parameter_the_schema_does_not_offer_is_not_the_models_to_pass() -> None:
    """`ctx` is injected by the SDK and absent from the schema: the signature the probe binds
    a model's call to is narrowed to what the client was shown."""
    def read(ref: str, ctx: object = None) -> None:
        """unused"""

    surface = probe.load_surface(dataclasses.replace(REPO, modules={"toy": _toy(read=read)}),
                                 "toy")
    assert list(surface.tools["read"].signature.parameters) == ["ref"]
    task = {"id": "T1", "prompt": "p", "tool": "read", "args": {"ref": "x"}}
    line = 'T1: {"tool": "read", "args": {"ref": "x", "ctx": 1}}'
    assert not probe.judge(surface, task, probe.parse(line, ["T1"])["T1"]).right


def test_the_repository_is_one_object_and_its_directories_hang_from_its_root() -> None:
    """Everything the engine reads comes from the object `configure` returns, its two directories
    derived from the root as `--help` states; frozen, so no call can re-point it."""
    assert REPO.root == SERVERS_FILE.parent.resolve() and REPO.tasks_dir == FIXTURES / "tasks"
    assert REPO.out_dir == REPO.root / "tmp" / "mcp_probe"
    assert REPO.captured_dir == REPO.root / "tests" / "fixtures" / "mcp_probe" / "captured"
    assert REPO.captured_servers == ("mame",) and REPO.servers == ("mame", "dosbox-x")
    assert REPO.checks == {}
    with pytest.raises(dataclasses.FrozenInstanceError):
        REPO.root = Path()  # type: ignore[misc]
    with pytest.raises(TypeError):
        REPO.modules["other"] = types.ModuleType("other")  # type: ignore[index]
    assert "`ROOT/tmp/mcp_probe/`" in probe.__doc__ and (
        "`ROOT/tests/fixtures/mcp_probe/captured/<server>/`" in probe.__doc__)


def test_two_repositories_are_probed_side_by_side_without_either_moving(
        tmp_path: Path) -> None:
    """A second `configure` returns its own object and leaves the first as it was."""
    servers = _servers_file(tmp_path, "CHECKS = {'dosbox-x': print}\n")
    other = probe.configure(servers, tmp_path)
    assert other.root == REPO.root and other.tasks_dir == tmp_path and other.checks
    assert REPO.tasks_dir == FIXTURES / "tasks" and REPO.checks == {}


def test_a_report_that_cannot_be_written_is_invalid(
        probe_env: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """1 is a verdict, so a run whose report could not be kept answers INVALID, not a FAIL."""
    real = probe.new_run_dir

    def unwritable(repo: probe.ProbeRepo, now: dt.datetime) -> Path:
        out = real(repo, now)
        (out / "report.txt").mkdir()
        return out

    monkeypatch.setattr(probe, "new_run_dir", unwritable)
    rc, lines = _run(["mame"], capsys)
    assert rc == probe.EXIT_INVALID and lines[0].startswith("INVALID the report could not be")


def test_a_capture_check_on_a_task_file_with_no_id_is_invalid(tmp_path: Path) -> None:
    captured, tasks_file = _captured_by_hand(tmp_path)
    _edit(tasks_file, "\n]}", ',\n  "oops"\n]}')
    with pytest.raises(probe.Invalid, match="not a task with an `id`"):
        probe_captures.capture_problems(REPO, "mame", captured, tasks_file)



def test_an_expected_object_matches_key_by_key_with_alternatives_inside() -> None:
    expected = {"a": {"any_of": [1, 2]}, "b": [3]}
    assert any_of.matches(expected, {"a": 2, "b": [3]})
    assert not any_of.matches(expected, {"a": 2, "b": [3], "c": 0})
