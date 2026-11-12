"""The `.scry/README.md` a repository's folder renders to, and the command that writes it."""
from __future__ import annotations

import json
import runpy
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from scry_core import project_store, scry_readme

ABOUT = {
    "format": "scry-about/1",
    "purpose": "How Demo starts under SCRY.",
    "server": "dosbox-x",
    "build": {"command": "make conf", "note": "Needs DOSBox-X."},
    "files": {
        "start/dos.json": "boots the game.",
        "maps/demo-screen-map.json": "the game's screens.",
        "perform/tour.json": "drives the attract and a coin.",
    },
}


def _store(base: Path, about: Mapping[str, object] | None = None,
           names: tuple[str, ...] = ("start/dos.json", "maps/demo-screen-map.json",
                                     "perform/tour.json")) -> Path:
    for name in names:
        path = base / ".scry" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
    if about is not None:
        (base / ".scry" / "about.json").write_text(json.dumps(about))
    return base


def _about(**changes: object) -> dict[str, object]:
    return {**ABOUT, **changes}


def test_the_sections_come_in_the_order_a_cold_reader_needs(tmp_path: Path) -> None:
    text = scry_readme.render(_store(tmp_path, ABOUT))
    marks = ["How Demo starts under SCRY.", "MCP servers", "Build first", "make conf",
             "How to start", 'start(profile="<name>")', "`dos` (`start/dos.json`): boots the game.",
             "`maps/demo-screen-map.json`: the game's screens.",
             "`perform/tour.json`: drives the attract and a coin."]
    at = [text.index(mark) for mark in marks]
    assert at == sorted(at), "a section is out of order"
    assert text.endswith("\n") and "\n\n\n" not in text


def test_the_render_names_the_server_the_manifest_declares(tmp_path: Path) -> None:
    text = scry_readme.render(_store(tmp_path, _about(server="mame")))
    assert "`mame` server's `start` tool" in text and "dosbox-x` server's" not in text


def test_a_folder_with_no_start_recipe_has_no_how_to_start(tmp_path: Path) -> None:
    only_maps = ("maps/demo-screen-map.json",)
    about = _about(files={"maps/demo-screen-map.json": "the game's screens."}, build=None)
    text = scry_readme.render(_store(tmp_path, about, only_maps))
    assert "How to start" not in text and "Build first" not in text
    assert "the game's screens." in text


def test_the_build_step_is_left_out_when_the_manifest_has_none(tmp_path: Path) -> None:
    about = _about()
    del about["build"]
    assert "Build first" not in scry_readme.render(_store(tmp_path, about))


def test_a_note_comes_after_the_files(tmp_path: Path) -> None:
    text = scry_readme.render(_store(tmp_path, _about(notes=["A paragraph for this repo."])))
    assert text.index("perform/tour.json") < text.index("A paragraph for this repo.")


def test_a_file_with_no_line_is_refused_by_name(tmp_path: Path) -> None:
    about = _about(files={"start/dos.json": "boots the game."})
    with pytest.raises(scry_readme.Refused,
                       match=r"maps/demo-screen-map\.json.*perform/tour\.json"):
        scry_readme.render(_store(tmp_path, about))


def test_a_line_for_a_file_that_is_not_there_is_refused_by_name(tmp_path: Path) -> None:
    files = {**ABOUT["files"], "start/ghost.json": "a recipe that was deleted."}  # type: ignore[dict-item]
    with pytest.raises(scry_readme.Refused, match=r"start/ghost\.json"):
        scry_readme.render(_store(tmp_path, _about(files=files)))


@pytest.mark.parametrize("about, message", [
    (_about(format="scry-about/2"), "format"),
    (_about(server="bochs"), "server"),
    (_about(purpose=""), "purpose"),
    (_about(purpose="two\nlines"), "purpose"),
    (_about(extra=1), "extra"),
    (_about(build={"command": "make"} | {"flag": 1}), "flag"),
    (_about(notes="not a list"), "notes"),
    (_about(build="make"), "build"),
    (_about(files=["start/dos.json"]), "files"),
    (_about(files={"start/dos.json": "", "maps/demo-screen-map.json": "x",
                   "perform/tour.json": "x"}), "start/dos.json"),
])
def test_a_manifest_that_breaks_the_format_is_refused_naming_the_key(
        tmp_path: Path, about: dict[str, object], message: str) -> None:
    with pytest.raises(scry_readme.Refused, match=message):
        scry_readme.render(_store(tmp_path, about))


def test_a_store_with_no_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(scry_readme.Refused, match="about.json"):
        scry_readme.render(_store(tmp_path, None))


def test_the_readme_and_the_manifest_are_not_entries(tmp_path: Path) -> None:
    base = _store(tmp_path, ABOUT)
    (base / ".scry" / "README.md").write_text("old")
    assert "about.json" not in scry_readme.render(base).replace("`about.json`", "")


def test_the_template_names_only_what_the_render_fills() -> None:
    template = scry_readme.TEMPLATE.read_text(encoding="utf-8")
    assert scry_readme.fields(template) == set(scry_readme.FIELDS)


def test_the_command_writes_then_finds_it_unchanged(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _store(tmp_path, ABOUT)
    assert scry_readme.main([str(base)]) == 0
    first = (base / ".scry" / "README.md").read_text()
    assert first == scry_readme.render(base)
    assert scry_readme.main([str(base)]) == 0
    assert (base / ".scry" / "README.md").read_text() == first
    assert "unchanged" in capsys.readouterr().out


def test_check_passes_on_a_current_readme_and_writes_nothing(tmp_path: Path) -> None:
    base = _store(tmp_path, ABOUT)
    scry_readme.main([str(base)])
    assert scry_readme.main(["--check", str(base)]) == 0


def test_check_refuses_a_drifted_or_missing_readme_and_leaves_it_alone(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _store(tmp_path, ABOUT)
    assert scry_readme.main(["--check", str(base)]) == 1
    assert not (base / ".scry" / "README.md").exists()
    (base / ".scry" / "README.md").write_text("edited by hand\n")
    assert scry_readme.main(["--check", str(base)]) == 1
    assert (base / ".scry" / "README.md").read_text() == "edited by hand\n"
    assert "DRIFT" in capsys.readouterr().err


def test_a_manifest_refusal_is_a_usage_exit_and_writes_nothing(tmp_path: Path) -> None:
    base = _store(tmp_path, _about(server="bochs"))
    assert scry_readme.main([str(base)]) == 2
    assert not (base / ".scry" / "README.md").exists()


def test_no_store_above_the_directory_is_invalid_not_clean(tmp_path: Path) -> None:
    assert scry_readme.main([str(tmp_path)]) == 3


def test_a_store_with_no_entry_is_invalid_not_clean(tmp_path: Path) -> None:
    (tmp_path / ".scry").mkdir()
    (tmp_path / ".scry" / "about.json").write_text(json.dumps(_about(files={})))
    assert scry_readme.main([str(tmp_path)]) == 3


@pytest.mark.parametrize("text, message", [("{not json", "not JSON"), ("[]", "JSON object")])
def test_a_manifest_that_is_not_a_json_object_is_refused(
        tmp_path: Path, text: str, message: str) -> None:
    base = _store(tmp_path, ABOUT)
    (base / ".scry" / "about.json").write_text(text)
    with pytest.raises(scry_readme.Refused, match=message):
        scry_readme.render(base)


def test_run_as_a_module_it_exits_with_the_main_s_code(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["scry_readme", "--check", str(_store(tmp_path, ABOUT))])
    sys.modules.pop("scry_core.scry_readme", None)
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("scry_core.scry_readme", run_name="__main__")
    assert stop.value.code == 1


def test_the_default_directory_finds_the_store_from_a_subdirectory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _store(tmp_path, ABOUT)
    (base / "sub").mkdir()
    monkeypatch.chdir(base / "sub")
    assert scry_readme.main(["--check"]) == 1
    assert scry_readme.main([]) == 0
    assert scry_readme.main(["--check"]) == 0


def test_a_carriage_return_is_not_one_line(tmp_path: Path) -> None:
    with pytest.raises(scry_readme.Refused, match="purpose"):
        scry_readme.render(_store(tmp_path, _about(purpose="a\rb")))


@pytest.mark.parametrize("make, flags", [
    (lambda page: page.write_bytes(b"\xff"), ["--check"]),
    (lambda page: page.mkdir(), []),
])
def test_a_page_that_cannot_be_read_or_written_is_invalid_not_drift(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], make: object,
        flags: list[str]) -> None:
    base = _store(tmp_path, ABOUT)
    make(base / ".scry" / "README.md")  # type: ignore[operator]
    assert scry_readme.main([*flags, str(base)]) == 3
    assert "INVALID" in capsys.readouterr().err


def test_the_page_lists_exactly_the_kinds_the_store_holds() -> None:
    assert tuple(kind for kind, _, _ in scry_readme._KINDS) == project_store.KINDS
