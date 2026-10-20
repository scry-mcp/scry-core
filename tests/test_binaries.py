"""The ladder both servers climb for their emulator, judged on a product of its own: who wins,
and who is answerable when nothing resolves."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scry_core import binaries
from scry_core.reply_contract import Invalid

LADDER = binaries.Ladder(product="Emu", executable="emu", variable="EMU_BINARY")


def _build(where: Path, body: str = "print('Emu 1.0')") -> Path:
    """An executable named `emu` that runs `body` as Python, on this host's terms: a `#!/bin/sh`
    script with its exec bit on POSIX, an `emu.cmd` on Windows, which runs no shebang. Both are
    written on every host, and the one this host runs is answered."""
    where.mkdir(parents=True, exist_ok=True)
    (where / "emu.py").write_text(body + "\n")
    (where / "emu.cmd").write_text(f'@"{sys.executable}" "{where / "emu.py"}" %*\r\n')
    exe = where / "emu"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{where / "emu.py"}" "$@"\n')
    exe.chmod(0o755)
    return where / "emu.cmd" if os.name == "nt" else exe


@pytest.mark.parametrize(("rung", "code"), [
    ("argument", "bad_argument"), ("EMU_BINARY", "host_failed"), ("PATH", "host_failed")])
def test_a_rung_that_names_no_executable_is_answered_by_whoever_set_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rung: str, code: str) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv("EMU_BINARY", raising=False)
    gone = str(tmp_path / "gone")
    if rung == "EMU_BINARY":
        monkeypatch.setenv("EMU_BINARY", gone)
    with pytest.raises(Invalid, match=f"no Emu binary resolves from the {rung} rung") as e:
        LADDER.resolve(gone if rung == "argument" else "")
    assert e.value.code == code


def test_the_first_rung_holding_a_value_is_taken_and_named(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(_build(tmp_path / "path").parent))
    monkeypatch.setenv("EMU_BINARY", str(_build(tmp_path / "var")))
    given = _build(tmp_path / "arg")
    assert LADDER.resolve(str(given)) == binaries.Resolved(str(given), "argument")
    assert LADDER.resolve("").origin == "EMU_BINARY"
    monkeypatch.delenv("EMU_BINARY")
    assert LADDER.resolve("").origin == "PATH"
    assert Path(LADDER.resolve("").path).parent == tmp_path / "path"
    assert binaries.facts(LADDER.resolve(""))["version"] == "Emu 1.0"


def test_why_a_path_is_no_executable_is_said_in_its_owners_words(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.write_text("")
    (tmp_path / "dangling").symlink_to(tmp_path / "nowhere")
    assert [binaries.why_not(str(p)) for p in (tmp_path / "gone", tmp_path / "dangling",
                                                 tmp_path, plain)] == [
        "no such file", "no such file", "a directory", "not executable"]


@pytest.mark.parametrize(("body", "said"), [
    ("import sys; sys.stderr.write('banner\\n'); sys.exit(1)", "banner"),
    ("pass", "printed nothing (rc=0)"),
    ("import time; time.sleep(5)", "did not return in 0.2 s"),
], ids=["a banner on stderr with rc 1", "nothing printed", "a build that hangs"])
def test_a_version_is_the_first_line_printed_or_why_there_is_none(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, said: str) -> None:
    if "sleep" in body:      # the bound shortened only where it is the case: a busy host
        monkeypatch.setattr(binaries, "VERSION_TIMEOUT_S", 0.2)   # starts a program slowly
    got = binaries.version(str(_build(tmp_path, body)))
    assert got == said if isinstance(got, str) else said in got["why"], got


def test_a_version_that_cannot_run_is_unavailable(tmp_path: Path) -> None:
    got = binaries.version(str(tmp_path / "gone"))
    assert isinstance(got, dict) and "could not run" in got["why"]


def test_the_version_probe_is_spawned_with_the_environment_it_is_handed(
        tmp_path: Path) -> None:
    build = str(_build(tmp_path, "import os; print(os.environ.get('SCRY_HINT', 'none'))"))
    bare = {k: v for k, v in os.environ.items() if k != "SCRY_HINT"}
    assert binaries.version(build, bare) == "none"
    assert binaries.version(build, {**bare, "SCRY_HINT": "behind"}) == "behind"
    resolved = binaries.Resolved(build, "binary")
    assert binaries.facts(resolved, {**os.environ, "SCRY_HINT": "behind"})["version"] == "behind"
