"""`scry_core.guardian` against REAL processes: whether a child outlives its parent, or its
deadline, is a property of processes. Its "emulator" is an interpreter asleep, and its "server" one
these cases kill outright (SIGKILL, or `TerminateProcess`), the ending that runs no `finally`."""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scry_core import guardian, process_tree

POSIX = pytest.mark.skipif(not guardian.WATCHER, reason="the watcher process is POSIX's")
#: The job's own cases; coverage, judged on macOS, leaves them out by this name.
WINDOWS_ONLY = pytest.mark.skipif(guardian.WATCHER, reason="the job is Windows'")

# The server stand-in: spawns the "emulator" and its guardian as a server does (unless told not
# to, for the control), prints both pids, and waits to be killed.
SERVER = """
import subprocess, sys, time
from scry_core import guardian, process_tree
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
guard = (guardian.spawn(child, "scry-test", float(sys.argv[2]))
         if sys.argv[1] == "guarded" else None)
print(child.pid, getattr(guard, "pid", 0), flush=True)
time.sleep(60)
"""

WITHIN_S = 5 * guardian.POLL_S
#: Any host has one: an MSYS `sleep` is no Windows host's own.
EMULATOR = [sys.executable, "-c", "import time; time.sleep(60)"]


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not process_tree.pid_alive(pid):
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
        if pid and process_tree.pid_alive(pid):
            os.kill(pid, guardian.KILL)


def test_a_sigkilled_server_takes_its_emulator_with_it() -> None:
    proc, child, guard = _server()
    try:
        proc.kill()
        proc.wait()
        assert _gone_within(child, WITHIN_S), "the emulator outlived its server"
        assert not guard or _gone_within(guard, WITHIN_S), "the guardian lingered"  # 0: a job
    finally:
        _reap(child, guard)


def test_without_a_guardian_the_emulator_outlives_its_server() -> None:
    """THE CONTROL: the same ending with no guardian leaves the child running under init, so
    the case above is the guardian's doing and not the child dying with its parent."""
    proc, child, _ = _server("bare")
    try:
        proc.kill()
        proc.wait()
        assert not _gone_within(child, WITHIN_S), "the child died on its own"
    finally:
        _reap(child)


@POSIX
def test_a_live_server_keeps_its_emulator_while_no_deadline_is_set() -> None:
    proc, child, guard = _server()
    try:
        assert not _gone_within(child, 3 * guardian.POLL_S)
        assert process_tree.pid_alive(guard)
    finally:
        proc.kill()
        proc.wait()
        _gone_within(child, WITHIN_S)
        _reap(child, guard)


@POSIX
def test_a_deadline_ends_the_emulator_of_a_live_server() -> None:
    proc, child, guard = _server(deadline=time.time() + 1.5)
    try:
        assert process_tree.pid_alive(child)
        assert _gone_within(child, 1.5 + WITHIN_S), "the emulator outlived its deadline"
        assert _gone_within(guard, WITHIN_S), "the guardian lingered"
        assert proc.poll() is None, "the deadline took the server too"
    finally:
        proc.kill()
        proc.wait()
        _reap(child, guard)


@POSIX
def test_the_guardian_leaves_when_its_emulator_does_and_goes_by_its_name() -> None:
    child = subprocess.Popen(EMULATOR)
    guard = guardian.spawn(child, "scry-test")
    try:
        assert isinstance(guard, subprocess.Popen)
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


@WINDOWS_ONLY
def test_on_windows_the_job_ends_what_it_still_holds_when_it_closes() -> None:
    """`stop` comes once the emulator is reaped, so closing the job ends nothing then."""
    child = subprocess.Popen(EMULATOR)
    guard = guardian.spawn(child, "scry-test")
    try:
        assert isinstance(guard, guardian.Job) and guard.poll() is None
        assert process_tree.pid_alive(child.pid), "the control: the job left it running"
        guardian.stop(guard)
        assert guard.poll() == 0 and _gone_within(child.pid, WITHIN_S)
        guardian.stop(guard)
    finally:
        _reap(child.pid)


@POSIX
def test_stop_ends_a_guardian_and_takes_none() -> None:
    child = subprocess.Popen(EMULATOR)
    guard = guardian.spawn(child, "scry-test")
    try:
        guardian.stop(guard)
        assert guard is not None and guard.poll() is not None
        assert process_tree.pid_alive(child.pid), "stopping the guardian took its emulator"
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
        if sig == guardian.KILL:
            raise ProcessLookupError

    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(guardian, "started", lambda pid: "the same start")
    guardian.watch(os.getppid() + 1, 12345, 0.01, 0.0)   # "reparented" at the first look
    assert calls == [(12345, 0), (12345, guardian.KILL)]


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


def test_a_job_is_ended_once_and_answers_as_a_stopped_guard_after(
        monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    # never a real CloseHandle: 7 is some live handle of this very process on Windows
    monkeypatch.setattr(guardian, "_close_handle", closed.append)
    job = guardian.Job(7)
    assert job.poll() is None
    job.kill()
    job.kill()
    assert (job.poll(), job.wait(1.0), job.handle, closed) == (0, 0, None, [7])


def test_a_child_gone_before_its_job_holds_it_has_no_guard_and_a_live_one_is_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows refuses to place a process that already ended: there is nothing left to end."""
    def refused(pid: int) -> guardian.Job:
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(guardian, "_job", refused)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    assert guardian.spawn(gone, "scry-x") is None
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(PermissionError):
            guardian.spawn(live, "scry-x")
    finally:
        live.kill()
        live.wait()

@pytest.mark.skipif(sys.platform == "win32", reason="this host makes them")
def test_a_job_is_asked_of_windows_alone() -> None:
    with pytest.raises(OSError, match="Windows'"):
        guardian._job(1)


@POSIX
def test_a_reused_pid_is_left_alone_and_one_it_may_not_signal_too(
        monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []
    born = iter(["Mon Oct 20 03:00:00 2026", "Mon Oct 20 03:05:00 2026"])
    monkeypatch.setattr(guardian, "started", lambda pid: next(born))

    def kill(pid: int, sig: int) -> None:
        if sig == guardian.KILL:
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
        if sig == guardian.KILL:
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
    # A host with no /proc (macOS), where `ps` is the only way to a start time.
    no_proc = functools.partial(guardian.started, proc="/nonexistent")
    monkeypatch.setattr(guardian, "started", no_proc)
    assert guardian.started(1) is None
    killed: list[int] = []

    def kill(pid: int, sig: int) -> None:
        if sig == guardian.KILL:
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
