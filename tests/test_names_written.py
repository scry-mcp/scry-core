"""`scry_core.names_written`: the new files of each case judged by their names, the names
another program fixes left out, and a whole run that judged none told apart from a narrowed one."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scry_core.names_written import Names


def _config(keyword: str = "", args: tuple[str, ...] = ("tests",)) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(keyword=keyword), args=list(args),
                           getini=lambda _name: ["tests"])


def test_each_case_is_judged_for_the_files_new_since_the_last(tmp_path: Path) -> None:
    names = Names(fixed={"MCPDUMP.BIN"})
    scratch, state = tmp_path / "scratch", tmp_path / "state"
    (scratch / "gfx").mkdir(parents=True)
    (scratch / "gfx" / "snapshot-1.png").write_bytes(b"")
    (scratch / "MCPDUMP.BIN").write_bytes(b"")
    assert names.outside([scratch, state, None]) == [] and names.judged == 1
    (scratch / "gfx" / "Screen_View-2.png").write_bytes(b"")
    (scratch / "tally-1.txt.tmp").write_bytes(b"")
    state.mkdir()
    (state / "Boss_1.sav").write_bytes(b"")
    assert names.outside([str(scratch), state]) == [
        scratch / "gfx" / "Screen_View-2.png", scratch / "tally-1.txt.tmp", state / "Boss_1.sav"]
    assert names.outside([scratch, state]) == [], "a file is judged once, by the case that left it"
    assert names.cases == 3 and names.judged == 4


@pytest.mark.parametrize(("left", "config", "invalid"), [
    ([], _config(), True),
    (["snapshot-1.png"], _config(), False),
    (["MCPDUMP.BIN"], _config(), True),
    ([], _config(keyword="dash"), False),
    ([], _config(args=("tests/test_x.py",)), False),
])
def test_a_whole_run_that_judged_no_file_is_invalid_and_a_narrowed_one_is_not(
        tmp_path: Path, left: list[str], config: SimpleNamespace, invalid: bool) -> None:
    names = Names(fixed={"MCPDUMP.BIN"})
    for name in left:
        (tmp_path / name).write_bytes(b"")
    assert names.outside([tmp_path]) == []
    assert names.judged_nothing(config) is invalid


def test_a_run_whose_cases_never_asked_is_not_judged() -> None:
    assert Names().judged_nothing(_config()) is False
