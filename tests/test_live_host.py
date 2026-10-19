"""`scry_core.live_host` on fake emulators, Python processes of the test's own: the canary's
verdict on a host, the ledger's proof that nothing outlived a run, and a run's scratch."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from scry_core import live_host as host

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="process groups and `ps` are "
                                "POSIX, and the live tiers run on POSIX hosts only")
#: How long a case waits for a fake to reach a state it signals by a file.
READY_S = 10.0


def _py(code: str) -> list[str]:
    """A fake emulator: a Python that runs `code`."""
    return [sys.executable, "-c", code]


def _waited(path: Path) -> str:
    """What a fake wrote to `path`, waited for up to `READY_S`."""
    deadline = time.monotonic() + READY_S
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return path.read_text()


def _gone(pid: int) -> bool:
    """Whether `pid` is gone or a zombie, polled up to `READY_S` (`_alive`'s own wait)."""
    return not host._alive({pid}, READY_S)


@pytest.fixture
def launched() -> Iterator[list[subprocess.Popen[bytes]]]:
    """The fakes a case starts, killed whatever the case did."""
    procs: list[subprocess.Popen[bytes]] = []
    yield procs
    for proc in procs:
        proc.kill()         # a no-op on one already waited for
        proc.wait(5)


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Short leaving bounds, nothing a run sets left in the environment, and the host's
    temporary directory the case's own, so a canary's working directory never lands outside."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(host, "LEAVE_S", 2.0)
    monkeypatch.delenv(host.LEDGER_VAR, raising=False)
    monkeypatch.delenv(host.SCRATCH_VAR, raising=False)


# ================================================================ the canary


def test_a_canary_that_ends_by_itself_answers_nothing_and_leaves_no_directory(
        tmp_path: Path) -> None:
    # It writes where it runs, as an emulator writes its configuration.
    assert host.canary(_py("open('emulator.cfg', 'w').close()")) == ""
    assert list(tmp_path.iterdir()) == []


def test_a_canary_that_never_returns_is_refused_naming_the_host_and_its_group_is_killed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "CANARY_S", 3.0)
    pid_file = tmp_path / "pid"
    # The child it starts stands for an emulator's helper: the GROUP is what has to go.
    code = ("import os, subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
            f"open({str(pid_file)!r}, 'w').write(f'{{os.getpid()}} {{c.pid}}')\n"
            "time.sleep(600)")
    why = host.canary(_py(code))
    leader, helper = (int(x) for x in pid_file.read_text().split())
    assert f"(pid {leader}) did not return within 3 s" in why
    assert "the host cannot start this emulator" in why and "SIGKILL" not in why
    assert _gone(helper)


def test_a_canary_whose_group_survives_kill_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "CANARY_S", 0.5)
    real = host._alive
    monkeypatch.setattr(host, "_alive", lambda pids, within_s: set(pids))
    why = host.canary(_py("import time; time.sleep(600)"))
    monkeypatch.setattr(host, "_alive", real)
    assert "survived SIGKILL (state U: read it with `sample" in why


def test_a_canary_interrupted_while_it_waits_kills_its_group(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid_file = tmp_path / "pid"

    real = subprocess.Popen.communicate

    def interrupted(self: subprocess.Popen[bytes], input: bytes | None = None,
                    timeout: float | None = None) -> tuple[bytes, bytes]:
        # Only the canary's own wait is interrupted: `ps` afterwards waits as it always does.
        monkeypatch.setattr(subprocess.Popen, "communicate", real)
        _waited(pid_file)
        raise KeyboardInterrupt
    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        host.canary(_py(f"import os, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))"
                        "\ntime.sleep(600)"))
    assert _gone(int(pid_file.read_text()))


def test_a_canary_that_fails_proved_nothing_and_says_its_code() -> None:
    why = host.canary(_py("import sys; print('no rom'); sys.exit(3)"))
    assert "rc=3" in why and "proved nothing" in why and "no rom" in why


def test_a_canary_that_cannot_be_launched_says_so(tmp_path: Path) -> None:
    assert "could not be launched" in host.canary([str(tmp_path / "no-such-emulator")])


def test_a_canary_is_launched_behind_whatever_the_caller_inherited(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(host.BACKGROUND_VAR, "0")
    monkeypatch.setenv("SCRY_TEST_MARK", "seen")
    code = (f"import os, sys; sys.exit(os.environ.get({host.BACKGROUND_VAR!r}) != '1' "
            "or os.environ.get('SCRY_TEST_MARK') != 'seen')")
    assert host.canary(_py(code)) == ""


# ================================================================ the ledger


def _launch(code: str, ledger: host.EmulatorLedger, launched: list[subprocess.Popen[bytes]],
            own_group: bool = True) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(_py(code), start_new_session=own_group)
    launched.append(proc)
    ledger.record(proc.pid, sys.executable)
    return proc


SLEEPS = "import time; time.sleep(600)"


def test_a_run_that_left_nothing_behind_finds_nothing_and_counts_what_it_recorded(
        tmp_path: Path, launched: list[subprocess.Popen[bytes]]) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    _launch("pass", ledger, launched).wait(10)
    # Ended and not yet waited for: a zombie is gone too.
    zombie = _launch("pass", ledger, launched)
    assert _gone(zombie.pid)
    gone = ledger.reap()
    assert gone == host.Leftovers(2) and gone.line() == ""


def test_every_emulator_left_alive_is_killed_and_counted(
        tmp_path: Path, launched: list[subprocess.Popen[bytes]]) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    first, second = (_launch(SLEEPS, ledger, launched) for _ in range(2))
    gone = ledger.reap()
    assert first.wait(5) == second.wait(5) == -signal.SIGTERM
    assert gone == host.Leftovers(2, 2)
    assert gone.line().startswith("FAIL  2 emulator(s) outlived the run")


def test_an_emulators_whole_group_goes_with_it(
        tmp_path: Path, launched: list[subprocess.Popen[bytes]]) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    pid_file = tmp_path / "helper"
    _launch("import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
            f"open({str(pid_file)!r}, 'w').write(str(c.pid))\ntime.sleep(600)", ledger, launched)
    helper = int(_waited(pid_file))
    assert ledger.reap().found == 1
    assert _gone(helper)


def test_an_emulator_that_ignores_sigterm_is_killed(
        tmp_path: Path, launched: list[subprocess.Popen[bytes]]) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ready = tmp_path / "ready"
    proc = _launch("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                   f"open({str(ready)!r}, 'w').close()\ntime.sleep(600)", ledger, launched)
    _waited(ready)
    assert ledger.reap() == host.Leftovers(1, 1)
    assert proc.wait(5) == -signal.SIGKILL


def test_an_emulator_in_the_runs_own_group_is_signalled_alone(
        tmp_path: Path, launched: list[subprocess.Popen[bytes]]) -> None:
    # MAME runs in its server's group, which in process is this run's: the group is never hit.
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    proc = _launch(SLEEPS, ledger, launched, own_group=False)
    assert ledger.reap() == host.Leftovers(1, 1)
    assert proc.wait(5) == -signal.SIGTERM


def _faked(monkeypatch: pytest.MonkeyPatch, rows: dict[int, tuple[int, str, str]],
           started: str = "Mon Oct 19 10:00:00 2026") -> list[int]:
    """The host's process list replaced by `rows`, each started at `started`; answers the pids
    signalled, none for real."""
    signalled: list[int] = []
    monkeypatch.setattr(host, "_processes", lambda: rows)
    monkeypatch.setattr(host, "_started", lambda pid: started)
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signalled.append(pid))
    monkeypatch.setattr(os, "kill", lambda pid, sig: signalled.append(pid))
    return signalled


def test_a_process_that_survives_kill_is_named_with_its_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # What a process stuck in the kernel looks like from here: SIGKILL lands and it stays.
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(4242, "/opt/dosbox-x")
    monkeypatch.setattr(host, "LEAVE_S", 0.2)
    _faked(monkeypatch, {4242: (4242, "U", "/opt/dosbox-x")})
    gone = ledger.reap()
    assert gone == host.Leftovers(1, 1, ((4242, "U"),))
    assert gone.line().endswith("still alive after SIGKILL: pid 4242 state U")


def test_a_pid_the_same_program_took_later_is_never_signalled(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    monkeypatch.setattr(host, "_started", lambda pid: "Mon Oct 19 10:00:00 2026")
    ledger.record(4242, "/opt/mamed")
    signalled = _faked(monkeypatch, {4242: (4242, "S", "/opt/mamed")},
                       started="Mon Oct 19 11:30:00 2026")
    assert ledger.reap() == host.Leftovers(1) and signalled == []


def test_a_pid_another_program_took_is_never_signalled(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(4242, "/opt/mamed")
    signalled = _faked(monkeypatch, {4242: (4242, "S", "/usr/bin/vim")})
    assert ledger.reap() == host.Leftovers(1) and signalled == []


def test_a_long_name_linux_cut_is_still_the_emulator(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(4242, "/builds/multicpu-9c28def3")
    monkeypatch.setattr(host, "LEAVE_S", 0.2)
    signalled = _faked(monkeypatch, {4242: (4242, "S", "multicpu-9c28de")})
    assert ledger.reap().found == 1 and signalled


def test_a_ledger_line_that_is_not_one_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "ledger").write_text("7\tdosbox-x\nnot a row\nx\tmamed\n8\t\t\n"
                                     "9\tmamed\tMon Oct 19 10:00:00 2026\n")
    assert host.EmulatorLedger(tmp_path / "ledger").recorded() == {7: "dosbox-x", 9: "mamed"}


def test_a_launch_is_recorded_with_when_it_started(tmp_path: Path) -> None:
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(os.getpid(), "/usr/bin/python3")
    [line] = (tmp_path / "ledger").read_text().splitlines()
    pid, name, started = line.split("\t")
    assert (int(pid), name) == (os.getpid(), "python3") and started == host._started(os.getpid())
    assert len(started.split()) == 5, started     # `ps`'s lstart: day, month, date, time, year


def test_a_ledger_no_launch_wrote_records_nothing(tmp_path: Path) -> None:
    assert host.EmulatorLedger(tmp_path / "never-written").recorded() == {}


def test_a_ledger_that_cannot_be_written_never_fails_the_launch(tmp_path: Path) -> None:
    host.EmulatorLedger(tmp_path / "gone" / "ledger").record(7, "dosbox-x")


def test_the_ledger_a_run_named_reaches_its_jobs(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    assert host.EmulatorLedger.from_environment() is None
    monkeypatch.setenv(host.LEDGER_VAR, str(tmp_path / "ledger"))
    job = host.EmulatorLedger.from_environment()
    assert job is not None
    job.record(7, "/a/b/dosbox-x")
    assert host.EmulatorLedger(tmp_path / "ledger").recorded() == {7: "dosbox-x"}


def test_a_ps_that_fails_is_an_error_never_an_empty_host(monkeypatch: pytest.MonkeyPatch) -> None:
    done = subprocess.CompletedProcess(["ps"], 1, "", "ps: no such option")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: done)
    with pytest.raises(OSError, match="ps answered rc=1: ps: no such option"):
        host._processes()


def test_a_ps_row_that_is_not_one_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    done = subprocess.CompletedProcess(["ps"], 0, "  12  12 Ss   /bin/zsh\nnot a row\n", "")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: done)
    assert host._processes() == {12: (12, "Ss", "/bin/zsh")}


# ================================================================ a run


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> host.LiveRun:
    """A run whose host's temporary directory is the test's, saying into a list."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    said: list[str] = []
    r = host.LiveRun.for_process("x-live-", job=False)
    r.say = said.append
    return r


def _said(run: host.LiveRun) -> list[str]:
    return run.say.__self__  # type: ignore[attr-defined,no-any-return]


def test_a_run_names_its_scratch_under_the_temporary_directory_and_makes_nothing_yet(
        run: host.LiveRun, tmp_path: Path) -> None:
    assert run.scratch.parent == tmp_path and run.scratch.name.startswith("x-live-")
    assert list(tmp_path.iterdir()) == []


def test_a_host_refused_by_the_canary_makes_nothing_and_names_no_ledger(
        run: host.LiveRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "dosbox-x (pid 5) did not return")
    assert run.begin(["dosbox-x"], "DOSBox-X") == "host canary: dosbox-x (pid 5) did not return"
    assert list(tmp_path.iterdir()) == [] and host.LEDGER_VAR not in os.environ
    run.unfinished(lambda: None)
    assert list(tmp_path.iterdir()) == []


def test_a_run_that_starts_names_its_ledger_for_every_launch(
        run: host.LiveRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "")
    assert run.begin(["/opt/mamed", "circus"], "MAME") == ""
    assert os.environ[host.LEDGER_VAR] == str(run.scratch / host.LEDGER_NAME)
    assert _said(run) == ["host canary: mamed started and ended by itself"]


def test_a_host_with_no_emulator_runs_no_canary_and_says_so(run: host.LiveRun) -> None:
    assert run.begin(None, "MAME") == ""
    assert _said(run) == ["host canary: not run, no MAME resolves on this host"]


def test_a_job_runs_no_canary_names_no_ledger_and_proves_nothing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: pytest.fail("a second canary"))
    monkeypatch.setenv(host.LEDGER_VAR, str(tmp_path / "the parents"))
    job = host.LiveRun(tmp_path / "job", job=True)
    assert job.begin(["x"], "MAME") == ""
    monkeypatch.setattr(host.EmulatorLedger, "reap", lambda _s: pytest.fail("a job reaped"))
    assert job.close(lambda: None) == ""


def test_a_jobs_scratch_is_the_one_its_parent_handed_it_inside_its_own(
        run: host.LiveRun, monkeypatch: pytest.MonkeyPatch) -> None:
    env = run.job_env("A")
    assert Path(env[host.SCRATCH_VAR]).parent.parent == run.scratch
    monkeypatch.setenv(host.SCRATCH_VAR, env[host.SCRATCH_VAR])
    assert host.LiveRun.for_process("x-live-", job=True).scratch == Path(env[host.SCRATCH_VAR])
    # Outside a job the variable is somebody else's, never this run's scratch.
    assert host.LiveRun.for_process("x-live-", job=False).scratch != Path(env[host.SCRATCH_VAR])


def test_a_green_run_removes_its_scratch_with_its_jobs(run: host.LiveRun, tmp_path: Path) -> None:
    Path(run.job_env("A")[host.SCRATCH_VAR]).mkdir(parents=True)
    run.finished = True
    run.leave(kept=False)
    assert list(tmp_path.iterdir()) == []
    assert _said(run) == ["scratch removed, the transcript with it"]


def test_a_red_run_keeps_its_scratch_and_names_it(run: host.LiveRun) -> None:
    run.made()
    run.leave(kept=True)
    assert run.scratch.is_dir() and _said(run) == [f"kept: {run.scratch}"]


def test_a_job_leaves_its_scratch_to_its_parent(tmp_path: Path) -> None:
    job = host.LiveRun(tmp_path / "job", job=True)
    job.made()
    job.leave(kept=False)
    assert job.scratch.is_dir()


def test_a_run_that_never_finished_closes_proves_and_keeps(
        run: host.LiveRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "")
    run.begin(["x"], "MAME")
    order: list[str] = []

    def reap(_self: host.EmulatorLedger) -> host.Leftovers:
        order.append("reap")
        return host.Leftovers(1, 1)
    monkeypatch.setattr(host.EmulatorLedger, "reap", reap)
    run.unfinished(lambda: order.append("close"))
    assert order == ["close", "reap"]
    assert _said(run)[-2:] == [host.Leftovers(1, 1).line(), f"kept: {run.scratch}"]
    run.unfinished(lambda: pytest.fail("closed twice"))
    assert _said(run).count(f"kept: {run.scratch}") == 1


def test_a_finished_run_leaves_unfinished_nothing_to_do(run: host.LiveRun) -> None:
    run.finished = True
    run.unfinished(lambda: pytest.fail("closed after the verdict"))


def test_a_close_that_raises_still_proves_and_a_proof_that_cannot_read_the_host_fails(
        run: host.LiveRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "")
    run.begin(["x"], "MAME")

    def broken(_self: host.EmulatorLedger) -> host.Leftovers:
        raise OSError("ps answered rc=1")
    monkeypatch.setattr(host.EmulatorLedger, "reap", broken)

    def raises() -> None:
        raise RuntimeError("stub hung")
    line = run.close(raises)
    assert line.startswith("FAIL  the end check could not read this host's processes")
    assert any("closing the machine raised RuntimeError: stub hung" in s for s in _said(run))


def test_an_end_whose_ledger_recorded_nothing_is_invalid_not_clean(
        run: host.LiveRun, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "")
    run.begin(["x"], "MAME")
    assert run.close(lambda: None).startswith("INVALID  the ledger recorded no emulator launch")


def test_a_clean_end_says_how_many_it_recorded(run: host.LiveRun,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "canary", lambda _argv: "")
    run.begin(["x"], "MAME")
    assert run.ledger is not None
    run.ledger.record(99999999, "mamed")
    assert run.close(lambda: None) == ""
    assert _said(run)[-1] == "emulators launched: 1, none left alive"


def test_a_run_that_never_began_reaps_no_ledger_the_environment_carries(
        run: host.LiveRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(host.LEDGER_VAR, str(tmp_path / "a stale export"))
    monkeypatch.setattr(host.EmulatorLedger, "reap", lambda _s: pytest.fail("reaped"))
    assert run.close(lambda: None) == ""


def test_a_run_is_closed_once(run: host.LiveRun) -> None:
    closed: list[bool] = []
    assert run.close(lambda: closed.append(True)) == ""
    assert run.close(lambda: pytest.fail("closed twice")) == "" and closed == [True]


def test_a_start_time_ps_cannot_give_never_fails_the_launch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: object, **_k: object) -> None:
        raise OSError("no ps on this host")
    monkeypatch.setattr(subprocess, "run", broken)
    ledger = host.EmulatorLedger(tmp_path / "ledger")
    ledger.record(7, "/opt/dosbox-x")
    assert (tmp_path / "ledger").read_text() == "7\tdosbox-x\t\n"
