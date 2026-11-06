"""The store a repository declares for its own program (`.scry/`): the root found by walking up,
a `start` profile read against it, and the caller's argument winning."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from scry_core import project_store as ps
from scry_core.reply_contract import Invalid

#: What a reading server hands in: `start`'s keys, and which of them hold paths.
KEYS = {"conf", "cwd", "files", "program", "shared", "symbols"}
PATH_KEYS = {"conf", "cwd", "files", "symbols"}


def stored(root: Path, values: dict[str, Any] | None = None, name: str = "dos") -> Path:
    """A profile in `root`'s own store, and its path."""
    path = root / ps.STORE / "start" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": ps.FORMAT, **(values or {})}), encoding="utf-8")
    return path


def test_the_root_is_a_directory_holding_a_store(tmp_path: Path) -> None:
    (tmp_path / ps.STORE).mkdir()
    assert ps.root([tmp_path]) == tmp_path


def test_the_root_is_found_above_the_start(tmp_path: Path) -> None:
    (tmp_path / ps.STORE).mkdir()
    below = tmp_path / "a" / "b"
    below.mkdir(parents=True)
    assert ps.root([below]) == tmp_path


def test_the_first_start_holding_a_store_wins(tmp_path: Path) -> None:
    (tmp_path / "one" / ps.STORE).mkdir(parents=True)
    (tmp_path / "two" / ps.STORE).mkdir(parents=True)
    assert ps.root([tmp_path / "one" / "x", tmp_path / "two"]) == tmp_path / "one"


def test_no_store_at_or_above_is_none(tmp_path: Path) -> None:
    assert ps.root([tmp_path]) is None


def test_a_name_is_found_in_its_kinds_directory(tmp_path: Path) -> None:
    path = stored(tmp_path)
    assert ps.locate([tmp_path], "dos") == path


def test_a_name_is_found_walking_up(tmp_path: Path) -> None:
    path = stored(tmp_path)
    below = tmp_path / "a" / "b"
    below.mkdir(parents=True)
    assert ps.locate([below], "dos") == path


def test_the_nearest_store_holding_the_name_wins(tmp_path: Path) -> None:
    near = stored(tmp_path / "repo")
    stored(tmp_path)
    assert ps.locate([tmp_path / "repo" / "sub"], "dos") == near


def test_a_store_without_the_name_does_not_stop_the_walk(tmp_path: Path) -> None:
    (tmp_path / "repo" / ps.STORE / "maps").mkdir(parents=True)
    outer = stored(tmp_path)
    assert ps.locate([tmp_path / "repo"], "dos") == outer


def test_a_name_found_nowhere_is_refused_naming_the_directories(tmp_path: Path) -> None:
    below = tmp_path / "repo"
    below.mkdir()
    with pytest.raises(Invalid, match=r"no \.scry/start/dos\.json") as refused:
        ps.locate([below], "dos")
    said = str(refused.value)
    assert str(below) in said and str(tmp_path) in said


def test_a_search_with_no_starting_directory_is_refused() -> None:
    with pytest.raises(Invalid, match="no directory to search"):
        ps.locate([], "dos")


def test_a_directory_two_starts_share_is_searched_once(tmp_path: Path) -> None:
    stored(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(Invalid) as refused:
        ps.locate([repo, repo / "sub"], "nope")
    searched = str(refused.value).split("searched ", 1)[1]
    assert searched.split(", ").count(str(tmp_path)) == 1


@pytest.mark.parametrize("name", ["", "a/b", "a\\b", ".", "..", "dos.json", "a\x00b"])
def test_a_name_that_is_not_one_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(Invalid, match="is not an entry name"):
        ps.locate([tmp_path], name)


def test_a_kind_the_store_does_not_hold_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="'recipes' is not one"):
        ps.locate([tmp_path], "dos", kind="recipes")


def test_another_kind_is_found_in_its_own_directory(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "maps" / "lineup.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert ps.locate([tmp_path], "lineup", kind="maps") == path


def test_a_profile_is_read_without_its_format(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "LINEUP.EXE", "shared": True})
    assert ps.read(path, KEYS) == {"program": "LINEUP.EXE", "shared": True}


def test_root_resolves_to_the_directory_holding_the_store(tmp_path: Path) -> None:
    path = stored(tmp_path, {"conf": "${root}/confs/dos.conf"})
    assert ps.read(path, KEYS, PATH_KEYS)["conf"] == f"{tmp_path}/confs/dos.conf"


def test_a_relative_path_resolves_against_the_root(tmp_path: Path) -> None:
    path = stored(tmp_path, {"cwd": "games/lineup"})
    resolved = ps.read(path, KEYS, PATH_KEYS)["cwd"]
    assert resolved == os.path.join(str(tmp_path), "games/lineup")


def test_a_value_that_is_not_a_path_is_not_resolved_against_the_root(tmp_path: Path) -> None:
    path = stored(tmp_path, {"cwd": "games/lineup"})
    assert ps.read(path, KEYS)["cwd"] == "games/lineup"


def test_an_absolute_path_is_taken_as_given(tmp_path: Path) -> None:
    path = stored(tmp_path, {"cwd": "/opt/guest"})
    assert ps.read(path, KEYS, PATH_KEYS)["cwd"] == "/opt/guest"


@pytest.mark.parametrize("value", ["C:\\GAMES\\LINEUP", "C:/GAMES/LINEUP",
                                   "\\\\server\\share\\lineup", "\\guest", "~\\guest"])
def test_a_windows_shaped_path_is_absolute_on_any_host(tmp_path: Path, value: str) -> None:
    path = stored(tmp_path, {"cwd": value})
    assert ps.read(path, KEYS, PATH_KEYS)["cwd"] == value


def test_each_path_of_a_list_resolves(tmp_path: Path) -> None:
    path = stored(tmp_path, {"files": ["one.bin", "C:\\two.bin"]})
    assert ps.read(path, KEYS, PATH_KEYS)["files"] == [os.path.join(str(tmp_path), "one.bin"),
                                                       "C:\\two.bin"]


def test_a_path_key_holding_a_table_resolves_every_entry(tmp_path: Path) -> None:
    path = stored(tmp_path, {"symbols": {"0x100": "maps/main.map"}})
    assert ps.read(path, KEYS, PATH_KEYS)["symbols"] == {
        "0x100": str(tmp_path / "maps" / "main.map")}


def test_home_resolves_to_the_users_home(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(tmp_path / "home"))
    path = stored(tmp_path, {"program": "${home}/games/lineup"})
    assert ps.read(path, KEYS)["program"] == f"{tmp_path / 'home'}/games/lineup"


def test_state_resolves_to_the_session_scratch(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${state}/lineup.exe"})
    assert ps.read(path, KEYS, state="/run/scratch")["program"] == "/run/scratch/lineup.exe"


def test_state_with_no_scratch_is_refused_naming_it(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${state}/lineup.exe"})
    with pytest.raises(Invalid, match=r"\$\{state\}"):
        ps.read(path, KEYS)


def test_a_variable_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUEST", "LINEUP")
    path = stored(tmp_path, {"program": "${env:GUEST}.EXE"})
    assert ps.read(path, KEYS)["program"] == "LINEUP.EXE"


def test_an_unset_variable_is_refused_naming_it(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${env:SCRY_GUEST_NOPE}.EXE"})
    with pytest.raises(Invalid, match="SCRY_GUEST_NOPE"):
        ps.read(path, KEYS)


def test_env_with_no_variable_name_is_refused(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${env:}"})
    with pytest.raises(Invalid, match="names no variable"):
        ps.read(path, KEYS)


def test_a_placeholder_that_is_not_one_is_refused_naming_it(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${nope}/x"})
    with pytest.raises(Invalid, match=r"\$\{nope\}"):
        ps.read(path, KEYS)


def test_an_unclosed_placeholder_is_refused(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "${nope/x"})
    with pytest.raises(Invalid, match="no closing brace"):
        ps.read(path, KEYS)


def test_a_key_start_does_not_take_is_refused_naming_it(tmp_path: Path) -> None:
    path = stored(tmp_path, {"logfile": "guest.log"})
    with pytest.raises(Invalid, match="logfile"):
        ps.read(path, KEYS)


def test_a_version_the_reader_does_not_know_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "start" / "dos.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"format": "scry-start/2"}', encoding="utf-8")
    with pytest.raises(Invalid, match="scry-start/2"):
        ps.read(path, KEYS)


def test_a_profile_with_no_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "start" / "dos.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"program": "X"}', encoding="utf-8")
    with pytest.raises(Invalid, match="declares no `format`"):
        ps.read(path, KEYS)


def test_a_profile_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "start" / "dos.json"
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(Invalid, match="is a list"):
        ps.read(path, KEYS)


def test_a_profile_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "start" / "dos.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(Invalid, match="could not be read as JSON"):
        ps.read(path, KEYS)


def test_a_profile_past_the_cap_is_refused_naming_it(tmp_path: Path) -> None:
    path = stored(tmp_path, {"program": "x" * ps.PROFILE_BYTES_MAX})
    with pytest.raises(Invalid, match=str(ps.PROFILE_BYTES_MAX)):
        ps.read(path, KEYS)


def test_a_profile_in_no_store_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "dos.json"
    path.write_text('{"format": "scry-start/1"}', encoding="utf-8")
    with pytest.raises(Invalid, match=r"in no \.scry/"):
        ps.read(path, KEYS)


def test_a_profile_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    path = tmp_path / ps.STORE / "start" / "dos.json"
    with pytest.raises(Invalid, match="could not be read"):
        ps.read(path, KEYS)


def test_the_callers_value_wins_and_the_profile_supplies_the_rest() -> None:
    values, from_profile = ps.precedence({"cwd": "a", "program": "p"}, {"cwd": "b"})
    assert values == {"cwd": "b", "program": "p"}
    assert from_profile == ["program"]


def test_nothing_given_leaves_the_profile_whole() -> None:
    values, from_profile = ps.precedence({"program": "p"}, {})
    assert values == {"program": "p"} and from_profile == ["program"]


def test_a_key_only_the_caller_gives_is_not_the_profiles() -> None:
    values, from_profile = ps.precedence({"program": "p"}, {"shared": True})
    assert values == {"program": "p", "shared": True} and from_profile == ["program"]


def test_a_profile_fills_only_the_names_the_caller_did_not_give(tmp_path: Path) -> None:
    stored(tmp_path, {"conf": "boot.conf", "program": "GAME.EXE", "shared": True})
    found = ps.applied("dos", starting=[tmp_path], keys=KEYS, path_keys=PATH_KEYS,
                       given={"conf"}, arguments={"conf": "/given/boot.conf", "program": "",
                                                  "shared": False})
    assert found.arguments == {"conf": "/given/boot.conf", "program": "GAME.EXE",
                               "shared": True}
    assert found.supplied == ["program", "shared"]
    assert found.file == tmp_path / ps.STORE / "start" / "dos.json"
    assert found.name == "dos"


def test_the_profiles_paths_resolve_against_the_base_of_its_store(tmp_path: Path) -> None:
    stored(tmp_path, {"conf": "cfg/boot.conf", "cwd": "guest"})
    below = tmp_path / "a"
    below.mkdir()
    found = ps.applied("dos", starting=[below], keys=KEYS, path_keys=PATH_KEYS, given=set(),
                       arguments={"conf": "", "cwd": ""})
    assert found.arguments == {"conf": str(tmp_path / "cfg" / "boot.conf"),
                               "cwd": str(tmp_path / "guest")}


def test_a_profile_named_by_its_path_is_read_there(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"program": "GAME.EXE"})
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    found = ps.applied(str(entry), starting=[elsewhere], keys=KEYS, path_keys=PATH_KEYS,
                       given=set(), arguments={"program": ""})
    assert found.arguments["program"] == "GAME.EXE"
    assert found.file == entry


def test_the_names_the_profile_did_not_fill_are_none_supplied(tmp_path: Path) -> None:
    stored(tmp_path, {"shared": True})
    found = ps.applied("dos", starting=[tmp_path], keys=KEYS, path_keys=PATH_KEYS,
                       given={"shared"}, arguments={"shared": False})
    assert found.supplied == []
    assert found.arguments == {"shared": False}


def test_the_reply_block_names_the_profile_its_file_and_what_it_supplied(tmp_path: Path) -> None:
    entry = stored(tmp_path, {"program": "GAME.EXE"})
    found = ps.applied("dos", starting=[tmp_path], keys=KEYS, path_keys=PATH_KEYS, given=set(),
                       arguments={"program": ""})
    assert found.shown() == {"name": "dos", "file": str(entry), "supplied": ["program"]}


def test_a_profile_found_nowhere_is_refused_naming_the_directories_searched(
        tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="searched"):
        ps.applied("nowhere", starting=[tmp_path], keys=KEYS, path_keys=PATH_KEYS, given=set(),
                   arguments={})


def test_a_key_no_server_takes_is_refused_by_name(tmp_path: Path) -> None:
    stored(tmp_path, {"steps": []})
    with pytest.raises(Invalid, match="steps"):
        ps.applied("dos", starting=[tmp_path], keys=KEYS, path_keys=PATH_KEYS, given=set(),
                   arguments={})


def test_a_required_argument_the_call_and_the_profile_both_lack_is_refused_by_name() -> None:
    with pytest.raises(Invalid, match="conf"):
        ps.demanded({"conf": "", "cwd": "/guest", "session_seconds": None},
                    ("conf", "cwd", "session_seconds"), tool="start")


def test_a_required_argument_the_call_gives_is_taken() -> None:
    ps.demanded({"conf": "/boot.conf", "cwd": "/guest", "session_seconds": 30},
                ("conf", "cwd", "session_seconds"), tool="start")
