"""The ladder both servers climb for their emulator, judged on a product of its own: who wins,
and who is answerable when nothing resolves."""

from __future__ import annotations

import os
import subprocess
import sys
import time
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
        tmp_path: Path, body: str, said: str) -> None:
    # The bound shortened only where it is the case: a busy host starts a program slowly.
    got = binaries.version(str(_build(tmp_path, body)),
                           seconds=0.2 if "sleep" in body else binaries.VERSION_TIMEOUT_S)
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


@pytest.mark.skipif(os.name == "nt", reason="a POSIX process group; Windows ends the tree")
def test_a_version_probe_that_runs_out_ends_what_its_build_started(tmp_path: Path) -> None:
    """A wrapper that does not `exec` leaves its emulator as a child: the bound ends the whole
    group, never the wrapper alone, so nothing the probe started outlives it."""
    pid_file = tmp_path / "child.pid"
    body = ("import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            f"open({str(pid_file)!r}, 'w').write(str(c.pid))\n"
            "time.sleep(30)")
    got = binaries.version(str(_build(tmp_path, body)), seconds=3.0)
    assert isinstance(got, dict) and "did not return in 3 s" in got["why"], got
    child = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"the build's child {child} outlived the probe")


def test_a_version_probe_reads_no_more_than_a_version_needs(tmp_path: Path) -> None:
    """A build that starts instead of answering can print without end: what is read is capped,
    and so is the line kept."""
    got = binaries.version(str(_build(tmp_path, "print('v' * 100000)")))
    assert isinstance(got, str) and 0 < len(got) <= binaries.VERSION_READ_MAX, len(got)


def test_a_version_probe_takes_the_launch_s_bound(tmp_path: Path) -> None:
    got = binaries.version(str(_build(tmp_path, "import time; time.sleep(5)")), seconds=0.3)
    assert isinstance(got, dict) and "did not return in 0.3 s" in got["why"], got


def test_a_relative_binary_is_refused_naming_the_rest_of_the_ladder() -> None:
    """A caller who typed a name rather than a path is told the other way to get a build."""
    with pytest.raises(Invalid, match="leave `binary` empty") as e:
        LADDER.resolve("emu")
    assert e.value.code == "bad_argument" and "EMU_BINARY" in str(e.value), str(e.value)


def test_on_windows_the_probe_is_its_own_group_and_the_tree_is_ended(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The Windows half, which this host cannot run for real: the probe is spawned in a new
    process group and, when its bound runs out, ended with `taskkill /T`, which takes the build's
    children with it; a probe that exited is left alone, since its pid may be another's now."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    spawned: list[dict[str, object]] = []
    ran: list[list[str]] = []

    hangs = [False]

    class Probe:
        pid = 4242
        returncode: int | None = None

        def wait(self, timeout: float | None = None) -> int:
            if hangs[0] and self.returncode is None:
                hangs[0] = False
                raise subprocess.TimeoutExpired("emu", timeout or 0)
            self.returncode = 0
            return 0

    def popen(argv: list[str], **kw: object) -> Probe:
        spawned.append(kw)
        return Probe()

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess, "run", lambda argv, **_k: ran.append(argv))
    assert binaries.version("C:/emu/emu.exe") == {
        "available": False, "why": "`C:/emu/emu.exe -version` printed nothing (rc=0)"}
    assert spawned[0]["creationflags"] == 0x200 and "start_new_session" not in spawned[0]
    assert ran == [], "a probe that exited is not looked for again"
    hangs[0] = True
    assert "did not return" in str(binaries.version("C:/emu/emu.exe", seconds=0.1))
    assert ran == [["taskkill", "/F", "/T", "/PID", "4242"]]
