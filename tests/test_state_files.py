"""What holds no state under a state's name is named, never opened: a dangling link, a directory,
a link to one, a FIFO; a regular file and nothing at all are not refused here. And the name
itself: the alphabet and the bound both servers take."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scry_core import host_program, state_files
from scry_core.reply_contract import Invalid
from scry_core.state_files import not_a_state, refused_load


def test_a_regular_file_and_an_absent_one_are_not_judged(tmp_path: Path) -> None:
    (tmp_path / "a.sav").write_bytes(b"x")
    assert not_a_state(tmp_path / "a.sav") is None
    assert not_a_state(tmp_path / "absent.sav") is None


def test_a_dangling_link_says_where_it_points(tmp_path: Path) -> None:
    (tmp_path / "x.sav").symlink_to("/nowhere.zip")
    assert not_a_state(tmp_path / "x.sav") == (
        "the file is a link to /nowhere.zip, and no file is reached through it")


def test_a_directory_and_a_link_to_one_are_named(tmp_path: Path) -> None:
    (tmp_path / "d.sav").mkdir()
    (tmp_path / "l.sav").symlink_to(tmp_path / "d.sav")
    assert not_a_state(tmp_path / "d.sav") == "the file is a directory, not a state"
    assert not_a_state(tmp_path / "l.sav") == (
        f"the file is a link to {tmp_path / 'd.sav'}, which is a directory, not a state")


def test_a_fifo_is_named_and_never_opened(tmp_path: Path) -> None:
    host_program.fifo(tmp_path / "f.sav")
    assert not_a_state(tmp_path / "f.sav") == "the file is a FIFO, not a state"


def test_a_load_of_a_name_that_holds_no_state_is_refused_naming_what_is_there(
        tmp_path: Path) -> None:
    (tmp_path / "d.sav").mkdir()
    why = not_a_state(tmp_path / "d.sav")
    assert why is not None
    e = refused_load("d", tmp_path / "d.sav", why)
    assert e.code == "unknown_ref" and why in str(e) and "'d'" in str(e), str(e)


def test_a_link_to_a_fifo_is_named_with_its_target(tmp_path: Path) -> None:
    host_program.fifo(tmp_path / "f")
    (tmp_path / "l.sav").symlink_to(tmp_path / "f")
    assert not_a_state(tmp_path / "l.sav") == (
        f"the file is a link to {tmp_path / 'f'}, which is a FIFO, not a state")


def test_a_link_target_is_named_without_the_windows_long_path_prefix(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows' `readlink` answers an absolute target as `\\\\?\\C:\\...`, a form for its own API
    that no reader types back: the target is named as a path."""
    (tmp_path / "d.sav").mkdir()
    (tmp_path / "l.sav").symlink_to(tmp_path / "d.sav")
    monkeypatch.setattr(os, "readlink", lambda _p: "\\\\?\\C:\\states\\d.sav")
    said = not_a_state(tmp_path / "l.sav")
    assert said == ("the file is a link to C:\\states\\d.sav, which is a directory, "
                    "not a state"), said


@pytest.mark.parametrize("name", ["a", "Level_2-b", "9lives", "x" * state_files.STATE_NAME_MAX])
def test_a_state_name_of_the_alphabet_within_the_bound_is_taken(name: str) -> None:
    assert state_files.check_state_name(name, "a file") == name


@pytest.mark.parametrize("name", ["", "-x", "_x", "a b", "a/b", "a.sta", "x\n",
                                  "x" * (state_files.STATE_NAME_MAX + 1), 7],
                         ids=["empty", "a leading dash", "a leading underscore", "a space",
                              "a slash", "a dot", "a newline", "one past the bound", "no string"])
def test_any_other_state_name_is_refused_saying_what_it_becomes(name: object) -> None:
    with pytest.raises(Invalid, match="It becomes a file name") as e:
        state_files.check_state_name(name, "a file name")
    assert e.value.code == "bad_argument"
