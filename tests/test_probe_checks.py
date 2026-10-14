"""`scry_core.probe_checks` on the probe's frozen fixture: each helper names what it finds, and
names nothing on a surface that has nothing wrong, so a repository's one assertion means what it
says."""

from __future__ import annotations

import dataclasses
import json
import shutil
import types
from pathlib import Path
from typing import Any

import pytest

from scry_core import probe, probe_checks
from scry_core.client_cap import CLIENT_TEXT_CAP

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "probe"


def _tasks() -> list[dict[str, Any]]:
    text = (FIXTURES / "tasks" / "mame.json").read_text()
    doc: dict[str, list[dict[str, Any]]] = json.loads(text)
    return doc["tasks"]


@pytest.fixture
def repo(tmp_path: Path) -> probe.ProbeRepo:
    """A repository laid out as `repository` reads it, its servers the frozen fixture's."""
    (tmp_path / "mcp_probe").mkdir()
    shutil.copytree(FIXTURES / "tasks", tmp_path / "mcp_probe" / "tasks")
    frozen = str(FIXTURES / "servers.py")
    (tmp_path / "mcp_probe" / "servers.py").write_text(
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('frozen', {frozen!r})\n"
        "frozen = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(frozen)\n"
        "ROOT = frozen.ROOT\nload = frozen.load\nCAPTURED = ('mame',)\n")
    at = probe_checks.repository(tmp_path)
    assert at.tasks_dir == tmp_path / "mcp_probe" / "tasks"
    return dataclasses.replace(at, captured_dir=tmp_path / "captured")


@pytest.fixture
def narrowed_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    """The surface narrowed to the fixture's tasks, which on the whole roster are holes."""
    real = probe.load_surface
    monkeypatch.setattr(probe, "load_surface", lambda repo, server: probe_checks.narrowed(
        real(repo, server), _tasks()))


def test_refused_names_the_holes_of_a_task_set(repo: probe.ProbeRepo) -> None:
    holes = probe_checks.refused(repo, "mame")
    assert holes and all(h.startswith(("no task on mame ", "no task names mame ")) for h in holes)


def test_refused_names_nothing_once_the_tasks_cover(
        repo: probe.ProbeRepo, narrowed_surface: None) -> None:
    assert probe_checks.refused(repo, "mame") == []


def test_captures_misjudged_names_a_task_with_no_capture_and_nothing_when_each_has_one(
        repo: probe.ProbeRepo, narrowed_surface: None) -> None:
    dest = repo.captured_dir / "mame"
    dest.mkdir(parents=True)
    texts = [(FIXTURES / "answers" / f"mame-run{k}.txt").read_text() for k in (1, 2, 3)]
    for task in _tasks():
        runs = [{"lines": [ln for ln in t.splitlines() if ln.startswith(f"{task['id']}:")],
                 "right": True} for t in texts]
        (dest / f"{task['id']}.json").write_text(json.dumps({"task": task, "runs": runs}))
    assert probe_checks.captures_misjudged(repo, "mame") == []
    (dest / "M3.json").unlink()
    assert probe_checks.captures_misjudged(repo, "mame") == ["mame: no capture of task M3"]


def test_over_cap_measures_the_objects_the_probe_reads(repo: probe.ProbeRepo) -> None:
    assert probe_checks.over_cap(repo) == []

    async def list_tools() -> list[Any]:
        return [types.SimpleNamespace(name="t", description="x" * CLIENT_TEXT_CAP + "cut")]

    module = types.ModuleType("long")
    module.mcp = types.SimpleNamespace(instructions="i",  # type: ignore[attr-defined]
                                       list_tools=list_tools)
    over = probe_checks.over_cap(dataclasses.replace(repo, modules={"long": module}))
    assert over == [f'long t {CLIENT_TEXT_CAP + 3} > {CLIENT_TEXT_CAP}: "cut"']


def test_judge_line_judges_one_answer_on_the_narrowed_surface(repo: probe.ProbeRepo) -> None:
    surface = probe.load_surface(repo, "mame")
    right = 'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 6}}'
    wrong = 'M1: {"tool": "read_memory", "args": {"ref": "PlayerX", "length": 7}}'
    assert probe_checks.judge_line(surface, _tasks(), "M1", right).right
    assert probe_checks.judge_line(surface, _tasks(), "M1", wrong).why == "length=7, expected 6"
    assert set(probe_checks.narrowed(surface, _tasks()).tools) == {"read_memory"}
