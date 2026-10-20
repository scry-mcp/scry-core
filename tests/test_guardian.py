"""`scry_core.guardian` against REAL processes: whether a child outlives its parent, or its
deadline, is a property of processes. Its "emulator" is `sleep`, and its "server" an interpreter
these cases SIGKILL, the ending that runs no `finally`."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scry_core import guardian

POSIX = pytest.mark.skipif(not guardian.SUPPORTED, reason="the guardian is POSIX only")

# The server stand-in: spawns the "emulator" and its guardian as a server does (unless told not
# to, for the control), prints both pids, and waits to be killed.
SERVER = """
import subprocess, sys, time
from scry_core import guardian
child = subprocess.Popen(["sleep", "60"])
guard = (guardian.spawn(child, "scry-test", float(sys.argv[2]))
         if sys.argv[1] == "guarded" else None)
print(child.pid, guard.pid if guard else 0, flush=True)
time.sleep(60)
"""

WITHIN_S = 5 * guardian.POLL_S


def _alive(pid: int) -> bool:
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                          text=True, check=False).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _server(mode: str = "guarded", deadline: float = 0.0
            ) -> tuple[subprocess.Popen[str], int, int]:
    proc = subprocess.Popen([sys.executable, "-c", SERVER, mode, repr(deadline)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    child, guard = (int(n) for n in proc.stdout.readline().split())
    return proc, child, guard


def _reap(*pids: int) -> None:
    for pid in pids:
        if pid and _alive(pid):
            os.kill(pid, signal.SIGKILL)


@POSIX
def test_a_sigkilled_server_takes_its_emulator_with_it() -> None:
    proc, child, guard = _server()
    try:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        assert _gone_within(child, WITHIN_S), "the emulator outlived its server"
        assert _gone_within(guard, WITHIN_S), "the guardian lingered"
    finally:
        _reap(child, guard)


@POSIX
def test_without_a_guardian_the_emulator_outlives_its_server() -> None:
    """THE CONTROL: the same ending with no guardian leaves the child running under init, so
    the case above is the guardian's doing and not the child dying with its parent."""
    proc, child, _ = _server("bare")
    try:
        proc.send_signal(signal.SIGKILL)
        proc.wait()
        assert not _gone_within(child, WITHIN_S), "the child died on its own"
    finally:
        _reap(child)


@POSIX
def test_a_live_server_keeps_its_emulator_while_no_deadline_is_set() -> None:
    proc, child, guard = _server()
    try:
        assert not _gone_within(child, 3 * guardian.POLL_S)
        assert _alive(guard)
    finally:
        proc.kill()
        proc.wait()
        _gone_within(child, WITHIN_S)
        _reap(child, guard)


@POSIX
def test_a_deadline_ends_the_emulator_of_a_live_server() -> None:
    proc, child, guard = _server(deadline=time.time() + 1.5)
    try:
        assert _alive(child)
        assert _gone_within(child, 1.5 + WITHIN_S), "the emulator outlived its deadline"
        assert _gone_within(guard, WITHIN_S), "the guardian lingered"
        assert proc.poll() is None, "the deadline took the server too"
    finally:
        proc.kill()
        proc.wait()
        _reap(child, guard)


@POSIX
def test_the_guardian_leaves_when_its_emulator_does_and_goes_by_its_name() -> None:
    child = subprocess.Popen(["sleep", "60"])
    guard = guardian.spawn(child, "scry-test")
    try:
        assert guard is not None
        deadline = time.monotonic() + 5
        shown = ""
        while time.monotonic() < deadline and shown.strip() != "scry-test-guardian":
            shown = subprocess.run(["ps", "-o", "command=", "-p", str(guard.pid)],
                                   capture_output=True, text=True, check=False).stdout
            time.sleep(0.05)
        assert shown.strip() == "scry-test-guardian", shown
        child.kill()
        child.wait()
        assert guard.wait(timeout=WITHIN_S) == 0
    finally:
        child.kill()
        guardian.stop(guard)


def test_no_guardian_for_a_process_this_server_did_not_spawn() -> None:
    """The guardian kills BY PID, and a stand-in's pid may be anybody's (init's, in doubles)."""

    class Double:
        pid = 1

    assert guardian.spawn(Double(), "x") is None


def test_no_guardian_where_the_host_has_none(monkeypatch: pytest.MonkeyPatch) -> None:
    child = subprocess.Popen(["sleep", "60"])
    try:
        monkeypatch.setattr(guardian, "SUPPORTED", False)
        assert guardian.spawn(child, "x") is None
    finally:
        child.kill()
        child.wait()


@POSIX
def test_stop_ends_a_guardian_and_takes_none() -> None:
    child = subprocess.Popen(["sleep", "60"])
    guard = guardian.spawn(child, "scry-test")
    try:
        guardian.stop(guard)
        assert guard is not None and guard.poll() is not None
        assert _alive(child.pid), "stopping the guardian took its emulator"
        guardian.stop(None)
    finally:
        child.kill()
        child.wait()


@POSIX
def test_watch_leaves_quietly_when_the_child_dies_between_its_poll_and_its_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int]] = []

    def kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))
        if sig == signal.SIGKILL:
            raise ProcessLookupError

    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(guardian, "started", lambda pid: "the same start")
    guardian.watch(os.getppid() + 1, 12345, 0.01, 0.0)   # "reparented" at the first look
    assert calls == [(12345, 0), (12345, signal.SIGKILL)]


def test_main_names_the_process_before_it_watches(monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_core import process_name
    seen: list[object] = []
    monkeypatch.setattr(process_name, "set_title", seen.append)
    monkeypatch.setattr(guardian, "watch", lambda *a: seen.append(a))
    guardian.main(["10", "20", "0.5", "7.0", "scry-x-guardian"])
    assert seen == ["scry-x-guardian", (10, 20, 0.5, 7.0)]


def test_a_name_the_host_refuses_costs_the_name_never_the_watch(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from scry_core import process_name

    def refuse(_title: str) -> None:
        raise OSError("no titles here")
    watched: list[object] = []
    monkeypatch.setattr(process_name, "set_title", refuse)
    monkeypatch.setattr(guardian, "watch", lambda *a: watched.append(a))
    guardian.main(["10", "20", "0.5", "0.0", "x"])
    assert watched == [(10, 20, 0.5, 0.0)]


def test_set_title_hands_the_title_to_setproctitle(monkeypatch: pytest.MonkeyPatch) -> None:
    import setproctitle

    from scry_core import process_name
    seen: list[str] = []
    monkeypatch.setattr(setproctitle, "setproctitle", seen.append)
    process_name.set_title("scry-x")
    assert seen == ["scry-x"]


def test_only_windows_has_no_guardian() -> None:
    posix = sys.platform != "win32"
    assert posix == guardian.SUPPORTED


@POSIX
def test_a_reused_pid_is_left_alone_and_one_it_may_not_signal_too(
        monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []
    born = iter(["Mon Oct 20 03:00:00 2026", "Mon Oct 20 03:05:00 2026"])
    monkeypatch.setattr(guardian, "started", lambda pid: next(born))

    def kill(pid: int, sig: int) -> None:
        if sig == signal.SIGKILL:
            killed.append(pid)
    monkeypatch.setattr(os, "kill", kill)
    guardian.watch(os.getppid() + 1, 4242, 0.01, 0.0)       # parent gone, but not our child
    assert killed == []

    def foreign(pid: int, sig: int) -> None:
        raise PermissionError
    monkeypatch.setattr(os, "kill", foreign)
    monkeypatch.setattr(guardian, "started", lambda pid: "same")
    guardian.watch(os.getppid() + 1, 4242, 0.01, 0.0)       # returns, rather than dying


@POSIX
def test_started_reads_a_live_pid_and_nothing_for_a_gone_one() -> None:
    gone = subprocess.Popen(["true"])
    gone.wait()
    assert guardian.started(os.getpid()) and guardian.started(gone.pid) == ""


@POSIX
def test_watch_leaves_when_the_child_is_already_gone_and_sleeps_while_all_is_well(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = subprocess.Popen(["true"])
    gone.wait()
    guardian.watch(os.getppid(), gone.pid, 0.01, 0.0)      # returns: nothing to watch
    slept: list[float] = []
    killed: list[int] = []
    monkeypatch.setattr(time, "sleep", slept.append)

    def kill(pid: int, sig: int) -> None:
        if sig == signal.SIGKILL:
            killed.append(pid)
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(guardian, "started", lambda pid: "the same start")
    clock = iter([0.0, 5.0, 10.0])
    monkeypatch.setattr(time, "time", lambda: next(clock))
    guardian.watch(os.getppid(), 4242, 0.25, 7.0)          # well at 0 and 5, past it at 10
    assert (slept, killed) == ([0.25, 0.25], [4242])


@POSIX
def test_a_host_where_ps_cannot_be_asked_still_kills_by_the_pid(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def no_ps(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("ps")
    monkeypatch.setattr(subprocess, "run", no_ps)
    assert guardian.started(1) is None
    killed: list[int] = []

    def kill(pid: int, sig: int) -> None:
        if sig == signal.SIGKILL:
            killed.append(pid)
    monkeypatch.setattr(os, "kill", kill)
    guardian.watch(os.getppid() + 1, 4242, 0.01, 0.0)
    assert killed == [4242]


@POSIX
def test_a_ps_that_says_nothing_for_a_live_pid_cannot_say_rather_than_gone(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, str]] = []

    def silent(*_a: object, **k: object) -> subprocess.CompletedProcess[str]:
        seen.append(k["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess([], 1, "", "ps: lstart: keyword not found")
    monkeypatch.setattr(subprocess, "run", silent)
    assert guardian.started(os.getpid(), proc="/nonexistent") is None
    assert seen and seen[0]["TZ"] == "UTC" and seen[0]["LC_ALL"] == "C"


@POSIX
def test_proc_gives_the_kernels_start_time_past_a_name_with_spaces(tmp_path: Path) -> None:
    (tmp_path / "77").mkdir()
    fields = " ".join(str(n) for n in range(3, 30))           # field 3 on: the state, ...
    (tmp_path / "77" / "stat").write_text(f"77 (a) b) {fields}\n")
    assert guardian.started(77, proc=str(tmp_path)) == "22"
    assert guardian.started(78, proc=str(tmp_path)) == ""


@POSIX
def test_the_guardian_imports_from_the_servers_own_path(tmp_path: Path) -> None:
    """`-I` drops PYTHONPATH and the user's site: the path the program carries is what reaches
    a `scry_core` found there."""
    package = tmp_path / "scry_core"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "guardian.py").write_text(
        "def main(argv):\n    open(argv[0], 'w').write('found')\n")
    marker = tmp_path / "marker"
    subprocess.run([sys.executable, "-I", "-c", guardian.program([str(tmp_path), ""]),
                    str(marker)], check=False, capture_output=True, timeout=30)
    assert marker.read_text() == "found"
    assert "''" not in guardian.program([""]) and guardian.name_of("scry-x") == "scry-x-guardian"


@POSIX
def test_a_proc_that_cannot_be_read_falls_back_to_ps(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "proc"
    not_a_dir.write_text("")
    assert guardian.started(os.getpid(), proc=str(not_a_dir))


@POSIX
def test_a_pid_ps_says_nothing_of_and_we_may_not_signal_cannot_be_told(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run",
                        lambda *_a, **_k: subprocess.CompletedProcess([], 1, "", ""))

    def denied(_pid: int, _sig: int) -> None:
        raise PermissionError("not ours")
    monkeypatch.setattr(os, "kill", denied)
    assert guardian.started(1, proc="/nonexistent") is None
