"""Ending a launched process with its tree, and asking whether a pid lives."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from scry_core import process_tree


def _sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            start_new_session=sys.platform != "win32")


def test_a_pid_that_runs_is_alive_and_one_that_ended_is_not() -> None:
    proc = _sleeper()
    try:
        assert process_tree.pid_alive(proc.pid)
    finally:
        proc.kill()
        proc.wait()
    assert not process_tree.pid_alive(proc.pid)


@pytest.mark.skipif(sys.platform == "win32", reason="a zombie is a POSIX state")
def test_a_zombie_awaiting_its_parent_is_not_alive() -> None:
    proc = _sleeper()
    proc.kill()
    deadline = time.monotonic() + 5
    while process_tree.pid_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert not process_tree.pid_alive(proc.pid)
    finally:
        proc.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="ps")
def test_a_ps_that_fails_is_an_error_and_not_a_process_that_is_gone(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **_k: subprocess.CompletedProcess(
        argv, 2, "", "ps: broken"))
    with pytest.raises(OSError, match="rc=2"):
        process_tree.pid_alive(1)


@pytest.mark.skipif(sys.platform == "win32", reason="process groups")
def test_ending_a_tree_ends_the_grandchild_and_reaps_the_leader() -> None:
    leader = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys; c = subprocess.Popen([sys.executable, '-c', "
         "'import time; time.sleep(60)']); print(c.pid, flush=True); c.wait()"],
        stdout=subprocess.PIPE, start_new_session=True, text=True)
    assert leader.stdout is not None
    grandchild = int(leader.stdout.readline())
    assert process_tree.pid_alive(grandchild)
    process_tree.end_tree(leader, wait_s=5.0)
    deadline = time.monotonic() + 5
    while process_tree.pid_alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert leader.returncode is not None and not process_tree.pid_alive(grandchild)


def test_on_windows_the_tree_is_taskkilled_while_the_process_still_runs(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    ran: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **_k: ran.append(argv))

    class Proc:
        pid = 4242

        def wait(self, timeout: float) -> int:
            return 0
    process_tree.end_tree(Proc(), still_running=True, wait_s=0.1)  # type: ignore[arg-type]
    process_tree.end_tree(Proc(), still_running=False, wait_s=0.1)  # type: ignore[arg-type]
    assert ran == [["taskkill", "/F", "/T", "/PID", "4242"]], "a reaped pid may be another's now"


@pytest.mark.skipif(sys.platform == "win32", reason="the probe is the Windows half")
def test_the_windows_probe_is_refused_anywhere_else() -> None:
    with pytest.raises(OSError, match="Windows"):
        process_tree._win_alive(1)


def test_a_process_that_outlives_the_kill_is_left_after_the_bound_and_not_waited_out(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", lambda argv, **_k: None)
    waited: list[float] = []

    class Stuck:
        pid = 4242

        def wait(self, timeout: float) -> int:
            waited.append(timeout)
            raise subprocess.TimeoutExpired("stuck", timeout)
    process_tree.end_tree(Stuck(), wait_s=0.25)  # type: ignore[arg-type]
    assert waited == [0.25], "one bounded wait, then it is left"
