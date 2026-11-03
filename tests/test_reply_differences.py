"""`scry_core.reply_differences`: the page of the advance tools' reply differences is read off the
servers' generated pages and never typed, and the committed page is the run's."""

from __future__ import annotations

from pathlib import Path

import pytest

from scry_core import reply_differences as rd

PAGE = """<!-- scry-reference:begin run_to -->
| argument | type | default |
|---|---|---|
| `ref` | string | |

| reply field | type |
|---|---|
| `pc` | string |
| `{extra}` | string |

text after the table
<!-- scry-reference:begin stop -->
| reply field | type |
|---|---|
| `pc` | string |
"""
ONLY_ONE = ("<!-- scry-reference:begin screen_wait -->\n| reply field | type |\n|---|---|\n"
            "| `pc` | s |\n")


def _servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    mame, dosbox = tmp_path / "mame", tmp_path / "dosbox"
    for directory, extra in ((mame, "cpu"), (dosbox, "cause")):
        (directory / "docs/reference").mkdir(parents=True)
        (directory / rd.SERVER_PAGE).write_text(PAGE.format(extra=extra) + (
            ONLY_ONE if directory == dosbox else ""), encoding="utf-8")
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)
    return mame, dosbox


def test_reply_fields_reads_only_the_reply_table_of_each_tool() -> None:
    assert rd.reply_fields(PAGE.format(extra="cpu")) == {"run_to": ["pc", "cpu"], "stop": ["pc"]}


def test_the_page_splits_each_tool_into_shared_and_one_sided_fields() -> None:
    page = rd.render({"run_to": ["pc", "cpu"], "stop": ["pc"]},
                     {"run_to": ["pc", "cause"], "stop": ["pc"], "screen_wait": ["pc"]})
    assert "| `run_to` | `pc` | `cpu` | `cause` |" in page
    assert "| `stop` | `pc` | - | - |" in page
    assert "Tools only DOSBox-X has: `screen_wait`." in page and "Tools only MAME has: -." in page


def test_write_then_check_agree_and_a_changed_page_is_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    mame, dosbox = _servers(tmp_path, monkeypatch)
    args = ["--mame", str(mame), "--dosbox-x", str(dosbox)]
    assert rd.main(args) == 1 and "differs" in capsys.readouterr().err
    assert rd.main([*args, "--write"]) == 0
    assert rd.main(args) == 0
    rd.OUT_PAGE.write_text("edited by hand", encoding="utf-8")
    assert rd.main(args) == 1


@pytest.mark.parametrize("damage", ["missing", "no tool"])
def test_a_page_that_cannot_be_compared_is_invalid_not_agreement(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        damage: str) -> None:
    mame, dosbox = _servers(tmp_path, monkeypatch)
    if damage == "missing":
        (mame / rd.SERVER_PAGE).unlink()
    else:
        (mame / rd.SERVER_PAGE).write_text("no blocks here", encoding="utf-8")
    assert rd.main(["--mame", str(mame), "--dosbox-x", str(dosbox)]) == 3
    assert "INVALID" in capsys.readouterr().err


def test_the_clones_default_to_the_environment_then_to_code(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCRY_MAME_DIR", str(tmp_path))
    monkeypatch.delenv("SCRY_DOSBOX_X_DIR", raising=False)
    assert rd._clone("SCRY_MAME_DIR", "scry-mame") == tmp_path
    assert rd._clone("SCRY_DOSBOX_X_DIR", "scry-dosbox-x") == Path.home() / "Code/scry-dosbox-x"


def test_the_committed_page_is_the_servers_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipped where the two servers' clones are not beside this one."""
    if not all((rd._clone(env, name) / rd.SERVER_PAGE).is_file()
               for env, name in (("SCRY_MAME_DIR", "scry-mame"),
                                 ("SCRY_DOSBOX_X_DIR", "scry-dosbox-x"))):
        pytest.skip("the servers' clones are not here: set SCRY_MAME_DIR and SCRY_DOSBOX_X_DIR")
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert rd.main([]) == 0, "docs/advance-differences.md differs: rerun reply_differences --write"
