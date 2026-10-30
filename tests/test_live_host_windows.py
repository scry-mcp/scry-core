"""`live_host` on a Windows host, judged on any host: the process list read off a real `tasklist`
listing (captured on one, `fixtures/live_host/tasklist.csv`), the image name matched to the
program a launch named, and every end a pid at a time, since Windows has no process groups."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from scry_core import live_host as host

LISTING = (Path(__file__).parent / "fixtures" / "live_host" / "tasklist.csv").read_text()


def test_a_real_tasklist_listing_is_read_each_process_its_own_group() -> None:
    rows = host._tasklist_rows(LISTING)
    assert rows[4] == (4, "R", "System") and rows[1248] == (1248, "R", "smss.exe")
    assert len(rows) == LISTING.count("\n"), "every row read, none skipped"


def test_an_image_name_is_the_program_a_launch_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "WINDOWS", True)
    assert host._same_program("mamed", "mamed.exe")
    assert host._same_program("dosbox-x.exe", "DOSBOX-X.EXE")
    assert not host._same_program("mamed", "vim.exe")


def test_a_reap_on_windows_ends_each_pid_and_never_a_group(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(host, "LEAVE_S", 0.2)
    monkeypatch.setattr(host, "_started", lambda pid: "")
    alive = {4242: (4242, "R", "mamed.exe")}
    killed: list[tuple[int, int]] = []

    def kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        alive.clear()
    monkeypatch.setattr(host, "_processes", lambda: dict(alive))
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "killpg", lambda *_a: pytest.fail("a group signalled"), raising=False)
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(4242, "C:/mame/mamed.exe")
    assert ledger.reap() == host.Leftovers(1, 1) and killed == [(4242, signal.SIGTERM)]


def test_a_listing_tasklist_cannot_give_is_an_error_never_an_empty_host(
        monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    done = subprocess.CompletedProcess(["tasklist"], 1, "", "ERROR: Access denied")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: done)
    with pytest.raises(OSError, match="tasklist answered rc=1: ERROR: Access denied"):
        host._tasklist()


def test_the_host_is_listed_by_tasklist_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    asked: list[list[str]] = []

    def run(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        asked.append(argv)
        return subprocess.CompletedProcess(argv, 0, LISTING, "")
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(subprocess, "run", run)
    assert host._processes() == host._tasklist_rows(LISTING) and asked[0][0] == "tasklist"


def test_a_listing_row_that_is_not_a_process_is_skipped() -> None:
    assert host._tasklist_rows('INFO: No tasks are running.\r\n"mamed.exe","77","Console"\r\n') == {
        77: (77, "R", "mamed.exe")}


@pytest.mark.parametrize(("polled", "taskkills"), [(None, 1), (1, 0)])
def test_a_canary_is_ended_with_its_tree_on_windows_only_while_it_still_runs(
        monkeypatch: pytest.MonkeyPatch, polled: int | None, taskkills: int) -> None:
    """A canary already reaped (an interrupt landing after `communicate`) has a pid another
    program may hold now: its tree is not looked for."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(host, "LEAVE_S", 0.01)
    monkeypatch.setattr(host, "_alive", lambda pids, within_s: set())
    monkeypatch.setattr(os, "killpg", lambda *_a: pytest.fail("a group signalled"), raising=False)
    ran: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **_k: ran.append(argv))

    class Proc:
        pid = 4242

        def poll(self) -> int | None:
            return polled

        def wait(self, timeout: float) -> int:
            return 1
    assert host._end_group(Proc()) is False  # type: ignore[arg-type]
    assert ran == [["taskkill", "/F", "/T", "/PID", "4242"]] * taskkills
