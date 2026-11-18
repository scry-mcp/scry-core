"""`scry_core.reply_differences`: the page of the reply differences of every tool both servers
register is read off the servers' generated pages and never typed, and the committed page is the
run's."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scry_core import reply_differences as rd

PAGE = """<!-- scry-reference:begin run_to -->
### Arguments

- `ref` (string, required): Where to stop.

### What comes back

- `pc`: Where it stopped.

<details><summary>All 2 reply fields</summary>

- `pc` (string)
- `{extra}` (string)

</details>

- `later` (a list after the fold is no field)
<!-- scry-reference:begin stop -->
<details><summary>All 1 reply fields</summary>

- `pc` (string)

</details>
"""
ONLY_ONE = ("<!-- scry-reference:begin wait -->\n<details><summary>All 1 reply fields</summary>"
            "\n\n- `pc` (s)\n\n</details>\n")
SCREEN_WAIT = ("<!-- scry-reference:begin screen_wait -->\n<details><summary>All 1 reply fields"
               "</summary>\n\n- `verdict` (s)\n\n</details>\n")


def _servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Two servers whose shared `screen_wait` sits on another family page in each."""
    mame, dosbox = tmp_path / "mame", tmp_path / "dosbox"
    for directory, extra in ((mame, "cpu"), (dosbox, "cause")):
        (directory / rd.SERVER_PAGES).mkdir(parents=True)
        (directory / rd.SERVER_PAGES / "advance.md").write_text(PAGE.format(extra=extra) + (
            ONLY_ONE + SCREEN_WAIT if directory == dosbox else ""), encoding="utf-8")
    (mame / rd.SERVER_PAGES / "screen.md").write_text(SCREEN_WAIT, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)
    return mame, dosbox


def test_reply_fields_reads_only_the_folded_list_of_each_tool() -> None:
    assert rd.reply_fields(PAGE.format(extra="cpu")) == {"run_to": ["pc", "cpu"], "stop": ["pc"]}


def test_the_page_splits_each_tool_into_shared_and_one_sided_fields() -> None:
    page = rd.render({"run_to": ["pc", "cpu"], "stop": ["pc"]},
                     {"run_to": ["pc", "cause"], "stop": ["pc"], "screen_wait": ["pc"]})
    assert "| `run_to` | `pc` | `cpu` | `cause` |" in page
    assert "| `stop` | `pc` | - | - |" in page
    assert "Only DOSBox-X has: `screen_wait`." in page
    assert "Only MAME has: -." in page


def test_write_then_check_agree_and_a_changed_page_is_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    mame, dosbox = _servers(tmp_path, monkeypatch)
    args = ["--mame", str(mame), "--dosbox-x", str(dosbox)]
    assert rd.main(args) == 1 and "differs" in capsys.readouterr().err
    assert rd.main([*args, "--write"]) == 0
    assert rd.main(args) == 0
    written = rd.OUT_PAGE.read_text(encoding="utf-8")
    assert "| `screen_wait` | `verdict` | - | - |" in written
    assert "Only DOSBox-X has: `wait`." in written
    rd.OUT_PAGE.write_text("edited by hand", encoding="utf-8")
    assert rd.main(args) == 1


@pytest.mark.parametrize("damage", ["missing", "no tool", "fields without a block"])
def test_a_page_that_cannot_be_compared_is_invalid_not_agreement(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
        damage: str) -> None:
    mame, dosbox = _servers(tmp_path, monkeypatch)
    pages = sorted((mame / rd.SERVER_PAGES).glob("*.md"))
    if damage == "missing":
        for page in pages:
            page.unlink()
    elif damage == "no tool":
        for page in pages:
            page.write_text("no blocks here", encoding="utf-8")
    else:
        for page in pages:
            page.write_text(ONLY_ONE.split("\n", 1)[1], encoding="utf-8")
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
    beside = Path(__file__).resolve().parents[2]
    for env, name in (("SCRY_MAME_DIR", "scry-mame"), ("SCRY_DOSBOX_X_DIR", "scry-dosbox-x")):
        if not os.environ.get(env):        # the run's home is its own, and holds no clone
            monkeypatch.setenv(env, str(beside / name))
    if not all(any((rd._clone(env, name) / rd.SERVER_PAGES).glob("*.md"))
               for env, name in (("SCRY_MAME_DIR", "scry-mame"),
                                 ("SCRY_DOSBOX_X_DIR", "scry-dosbox-x"))):
        pytest.skip("the servers' clones are not here: set SCRY_MAME_DIR and SCRY_DOSBOX_X_DIR")
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert rd.main([]) == 0, "docs/reply-differences.md differs: rerun reply_differences --write"
