"""`scry_core.recording.read_document`: the `perform` document a server replays from a path, and
every way a file is refused before a step runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scry_core import recording
from scry_core.reply_contract import Invalid


def _doc(tmp_path: Path, **fields: Any) -> Path:
    path = tmp_path / "session.json"
    body: dict[str, Any] = {
        "version": recording.DOCUMENT_VERSION, "server": "dosbox-x",
        "entry": "scry_dosbox_x.server", "start": {}, "steps": [{"op": "status"}],
        "needs": {"states": [], "declarations": {}}, **fields}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_document_read_from_a_path_gives_its_steps(tmp_path: Path) -> None:
    doc = recording.read_document(str(_doc(tmp_path)))
    assert doc["steps"] == [{"op": "status"}]


def test_a_version_this_reader_does_not_know_is_refused_by_name(tmp_path: Path) -> None:
    path = _doc(tmp_path, version=recording.DOCUMENT_VERSION + 1)
    with pytest.raises(Invalid, match=f"version {recording.DOCUMENT_VERSION + 1}"):
        recording.read_document(str(path))


def test_a_file_that_is_not_json_is_refused_naming_the_path(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    path.write_text("not a document\n", encoding="utf-8")
    with pytest.raises(Invalid, match="is not a JSON"):
        recording.read_document(str(path))


def test_a_document_that_is_a_json_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(Invalid, match="not a `perform` document"):
        recording.read_document(str(path))


@pytest.mark.parametrize("steps", [None, [], ["status"], {"op": "status"}])
def test_steps_that_are_not_a_list_of_objects_are_refused(tmp_path: Path, steps: object) -> None:
    path = _doc(tmp_path, steps=steps)
    with pytest.raises(Invalid, match="no steps"):
        recording.read_document(str(path))


def test_a_path_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="no `perform` document at"):
        recording.read_document(str(tmp_path / "gone.json"))


def test_a_relative_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="absolute path"):
        recording.read_document("session.json")


def test_the_steps_a_perform_replays_are_the_callers_or_the_documents() -> None:
    mine = [{"op": "status"}]
    assert recording.steps_to_replay(mine, "") is mine


def test_both_a_step_list_and_a_path_are_refused_naming_both() -> None:
    with pytest.raises(Invalid, match="steps and path name two lists of steps"):
        recording.steps_to_replay([{"op": "status"}], "~/.scry/perform/dos.json")


def test_neither_a_step_list_nor_a_path_is_refused() -> None:
    with pytest.raises(Invalid, match="give steps, or path to a `perform` document"):
        recording.steps_to_replay(None, "")


def test_a_path_gives_the_steps_of_the_document(tmp_path: Path) -> None:
    path = _doc(tmp_path)
    assert recording.steps_to_replay(None, str(path)) == [{"op": "status"}]
