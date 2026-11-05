"""An emulator launched as an app bundle: what the bundle resolves to, what `open` is handed, the
handle to a process this server did not spawn, and what its exit status can honestly be."""

from __future__ import annotations

import os
import plistlib
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from scry_core import app_launch
from scry_core.reply_contract import Invalid


def _bundle(where: Path, executable: str = "emu", info: dict[str, Any] | None = None) -> Path:
    """A minimal `.app` whose `Contents/MacOS/<executable>` exists."""
    bundle = where / "Probe.app"
    macos = bundle / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    plist = {"CFBundleExecutable": executable, "CFBundleIdentifier": "local.scry.test",
             "CFBundlePackageType": "APPL", "NSPrincipalClass": "NSApplication"}
    told = plist if info is None else info
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(told))
    (macos / executable).write_text("#!/bin/sh\n")
    return bundle


def _ok(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, 0, "", "")


def test_a_bundle_resolves_to_the_executable_its_plist_names(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    assert app_launch.is_bundle(bundle)
    assert app_launch.executable_of(bundle) == str(bundle / "Contents" / "MacOS" / "emu")


@pytest.mark.parametrize("damage", ["no-plist", "bad-plist", "no-key", "empty-name"])
def test_what_is_not_a_bundle_names_none(tmp_path: Path, damage: str) -> None:
    bundle = _bundle(tmp_path)
    plist = bundle / "Contents" / "Info.plist"
    if damage == "no-plist":
        plist.unlink()
    elif damage == "bad-plist":
        plist.write_text("not a plist")
    elif damage == "no-key":
        plist.write_bytes(plistlib.dumps({"CFBundlePackageType": "APPL"}))
    else:
        plist.write_bytes(plistlib.dumps({"CFBundleExecutable": ""}))
    assert app_launch.executable_of(bundle) is None
    assert not app_launch.is_bundle(bundle)


def test_a_directory_that_is_no_bundle_is_not_one(tmp_path: Path) -> None:
    plain = tmp_path / "plain.app"
    plain.mkdir()
    assert not app_launch.is_bundle(plain)
    assert not app_launch.is_bundle(tmp_path / "missing.app")
    assert not app_launch.is_bundle(tmp_path / "emu")


def test_the_open_command_connects_the_channels_and_hands_over_the_emulator_argv(
        tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    argv = app_launch.open_argv(
        bundle, ["/bundle/emu", "circus", "-debug"], stdout="/s/out.log",
        stdin_fifo="/s/console.fifo", env={"A": "1", "B": "two words"})
    assert argv[:6] == ["/usr/bin/open", "-n", "-a", str(bundle), "-i", "/s/console.fifo"]
    assert argv[6:10] == ["-o", "/s/out.log", "--stderr", "/s/out.log"]
    assert argv[10:] == ["--env", "A=1", "--env", "B=two words", "--args", "circus", "-debug"]


def test_without_a_fifo_or_env_the_route_passes_neither(tmp_path: Path) -> None:
    argv = app_launch.open_argv(_bundle(tmp_path), ["emu", "circus"], stdout="/s/out.log")
    assert "-i" not in argv
    assert "--env" not in argv
    assert argv[-2:] == ["--args", "circus"]


def test_launch_hands_back_the_pid_it_found_and_a_console_that_writes_into_the_fifo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _bundle(tmp_path)
    fifo = tmp_path / "console.fifo"
    seen: dict[str, Any] = {}

    def run_open(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        return _ok(cmd)

    monkeypatch.setattr(app_launch, "run_open", run_open)
    monkeypatch.setattr(app_launch, "find_pid", lambda token, timeout: 4242)
    proc = app_launch.launch(bundle, ["/bundle/emu", "circus", "-debugger_port", "5000"],
                             stdout=str(tmp_path / "out.log"), stdin_fifo=str(fifo),
                             token="-debugger_port 5000")
    assert proc.pid == 4242
    assert fifo.is_fifo()
    assert seen["cmd"] == app_launch.open_argv(
        bundle, ["/bundle/emu", "circus", "-debugger_port", "5000"],
        stdout=str(tmp_path / "out.log"), stdin_fifo=str(fifo))
    assert proc.stdin is not None
    proc.stdin.write(b"print(1)\n")
    proc.stdin.flush()
    with open(fifo, "rb") as reader:
        assert reader.read(9) == b"print(1)\n"


def test_a_refused_open_is_a_host_failure_carrying_its_words(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_launch, "run_open",
                        lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "Launch failed."))
    with pytest.raises(Invalid, match="Launch failed") as e:
        app_launch.launch(_bundle(tmp_path), ["emu", "circus"], stdout=str(tmp_path / "o.log"),
                          token="tok")
    assert e.value.code == "host_failed"


def test_a_pid_that_never_appears_is_refused_naming_the_token(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_launch, "run_open", _ok)
    monkeypatch.setattr(app_launch, "find_pid", lambda token, timeout: None)
    with pytest.raises(Invalid, match="tok") as e:
        app_launch.launch(_bundle(tmp_path), ["emu", "circus"], stdout=str(tmp_path / "o.log"),
                          token="tok")
    assert e.value.code == "host_failed"


def test_find_pid_polls_the_session_itself_until_pgrep_names_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[list[str]] = []

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        runs.append(argv)
        out = "" if len(runs) < 3 else "4321\n"
        return subprocess.CompletedProcess(argv, 0 if out else 1, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert app_launch.find_pid("-debugger_port 5000", 1.0) == 4321
    assert runs[0] == ["/usr/bin/pgrep", "-f", "-u", str(os.getuid()), "--",
                       "-debugger_port 5000"]


def test_find_pid_gives_up_at_its_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", ""))
    assert app_launch.find_pid("tok", 0.0) is None


def test_a_process_is_alive_until_the_kernel_says_there_is_none(
        monkeypatch: pytest.MonkeyPatch) -> None:
    proc = app_launch.AppProcess(50)
    calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))
        if len(calls) > 1:
            raise ProcessLookupError

    monkeypatch.setattr(os, "kill", fake_kill)
    assert proc.poll() is None
    assert proc.poll() == 0
    assert proc.poll() == 0          # remembered: one look at the kernel is enough


def test_wait_raises_at_its_bound_while_the_process_lives(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = app_launch.AppProcess(50)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)
    with pytest.raises(subprocess.TimeoutExpired):
        proc.wait(0.0)
    monkeypatch.setattr(os, "kill",
                        lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError))
    assert app_launch.AppProcess(51).wait(1.0) == 0


def test_kill_signals_the_pid_and_a_process_already_gone_is_no_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: seen.append((pid, sig)))
    app_launch.AppProcess(77).kill()
    assert seen == [(77, signal.SIGKILL)]
    monkeypatch.setattr(os, "kill",
                        lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError))
    app_launch.AppProcess(78).kill()


def test_the_exit_status_of_an_app_is_unavailable_and_a_childs_is_its_code() -> None:
    class Child:
        exit_code_known = True

    assert app_launch.exit_status(Child(), 3) == 3
    said = app_launch.exit_status(app_launch.AppProcess(9), 0)
    assert isinstance(said, dict)
    assert said["available"] is False
    assert "not known" in said["why"]


def test_run_open_hands_back_the_programmes_own_answer() -> None:
    assert app_launch.run_open(["/usr/bin/true"]).returncode == 0


def test_find_pid_ignores_a_line_that_is_no_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    said = [("warning\n", 0), ("77\n", 0)]

    def fake_run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        out, rc = said.pop(0)
        return subprocess.CompletedProcess(argv, rc, out, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert app_launch.find_pid("tok", 5.0) == 77


def test_a_process_of_another_user_is_alive_and_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "kill",
                        lambda pid, sig: (_ for _ in ()).throw(PermissionError))
    assert app_launch.AppProcess(5).poll() is None


def test_wait_without_a_bound_ends_when_the_process_does(
        monkeypatch: pytest.MonkeyPatch) -> None:
    proc = app_launch.AppProcess(5)
    answers = iter([None, 0])
    monkeypatch.setattr(proc, "poll", lambda: next(answers))
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert proc.wait() == 0


def test_a_refused_open_does_not_leave_the_console_held(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fifo = tmp_path / "console.fifo"
    monkeypatch.setattr(app_launch, "run_open",
                        lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "no"))
    with pytest.raises(Invalid):
        app_launch.launch(_bundle(tmp_path), ["emu", "x"], stdout=str(tmp_path / "o.log"),
                          stdin_fifo=str(fifo), token="tok")
    with pytest.raises(OSError):
        os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)


def test_the_working_directory_rides_as_its_own_variable(tmp_path: Path) -> None:
    """A bundle's launcher cannot learn `cwd` any other way: `open` sets `/`."""
    argv = app_launch.open_argv(_bundle(tmp_path), ["emu", "circus"], stdout="/s/o.log",
                                cwd="/scratch")
    assert f"{app_launch.CWD_VAR}=/scratch" in argv
    assert argv[argv.index("--env") - 0] == "--env"
