"""`scry_core.live_pool`: real child processes of this interpreter, each writing (or failing to
write) its summary, merged by the pool; the refusals before anything starts; the worker bound
proved by a rendezvous of the children themselves; the stop on an interrupt; and the worker
count the host gives."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scry_core import live_pool as lp

VAR = "SCRY_TEST_SUMMARY"
# Bounds on waits that end as soon as their condition holds; only a broken pool reaches them.
RENDEZVOUS_S = 20.0


def _child(body: str) -> list[str]:
    """A child that runs `body` with `summary` (its summary's path) and `lp` in scope."""
    prelude = ("import os, sys, time, json\nfrom pathlib import Path\n"
               "from scry_core import live_pool as lp\n"
               f"summary = Path(os.environ[{VAR!r}])\n")
    return [sys.executable, "-c", prelude + body]


def _writes(labels: tuple[str, ...], outcome: str = "OK", before: str = "",
            reasons: dict[str, str] | None = None) -> list[str]:
    return _child(before + f"lp.write_summary(summary, lp.Summary({labels!r}, "
                  f"{{l: {outcome!r} for l in {labels!r}}}, {reasons or {}!r}, 'tx', 0.5))\n")


def _until(path: Path) -> str:
    """Child code that waits for `path` to exist."""
    return (f"t = time.monotonic()\nwhile not Path({str(path)!r}).exists() and "
            f"time.monotonic() - t < {RENDEZVOUS_S}:\n    time.sleep(0.02)\n")


def _wait_for(path: Path) -> None:
    deadline = time.monotonic() + RENDEZVOUS_S
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_two_jobs_merge_in_declared_order_and_each_is_reported_as_it_ends(
        tmp_path: Path) -> None:
    seen: list[str] = []
    gate = tmp_path / "fast-reported"

    def report(jr: lp.JobResult) -> None:
        # THE POOL'S OWN REPORT OPENS THE GATE, so the slow job ends after the pool reported the
        # fast one: a gate the fast child wrote lets the slow child end, in its own worker
        # thread, before the fast one's report has run.
        seen.append(jr.job.name)
        if jr.job.name == "fast":
            gate.write_text("y")
    jobs = [lp.Job("slow", _writes(("a1", "a2"), before=_until(gate)), planned=("a1", "a2")),
            lp.Job("fast", _writes(("b1",), "BLOCKED", reasons={"b1": "no bench"}),
                   planned=("b1",))]
    r = lp.run_pool(jobs, 2, tmp_path, VAR, on_done=report)
    assert r.invalid == ""
    assert [x.job.name for x in r.results] == ["slow", "fast"]
    assert seen == ["fast", "slow"]
    assert r.outcomes == {"a1": "OK", "a2": "OK", "b1": "BLOCKED"}
    assert r.reasons == {"b1": "no bench"}
    assert all(x.rc == 0 and x.summary is not None and x.elapsed_s > 0 for x in r.results)
    assert r.results[0].log == tmp_path.resolve() / "slow.log"


def test_the_job_env_reaches_the_child_over_the_inherited_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRY_TEST_WHICH", "parent")
    monkeypatch.setenv("SCRY_TEST_INHERITED", "kept")
    body = ("e = os.environ\nok = (e['SCRY_TEST_WHICH'] == 'D' and e['SCRY_TEST_INHERITED'] == "
            "'kept' and e['PYTHONUTF8'] == '1' and e['PYTHONUNBUFFERED'] == '1')\n"
            "lp.write_summary(summary, lp.Summary(('d',), {'d': 'OK' if ok else 'FAIL'}, {}, "
            "'', 0))\n")
    r = lp.run_pool([lp.Job("D", _child(body), env={"SCRY_TEST_WHICH": "D"}, planned=("d",))],
                    1, tmp_path, VAR)
    assert r.outcomes == {"d": "OK"}


def test_a_child_that_dies_without_its_summary_fails_every_label_it_planned(
        tmp_path: Path) -> None:
    r = lp.run_pool([lp.Job("dead", _child("print('boom'); print('err', file=sys.stderr); "
                                           "sys.exit(7)\n"), planned=("x", "y"))], 1, tmp_path, VAR)
    assert r.outcomes == {"x": "FAIL", "y": "FAIL"}
    why = r.reasons["x"]
    assert "rc=7" in why and str(tmp_path.resolve() / "dead.log") in why
    assert (tmp_path / "dead.log").read_text(encoding="utf-8").split() == ["boom", "err"]


def test_a_summary_left_by_an_earlier_run_is_never_read_as_this_ones(tmp_path: Path) -> None:
    lp.run_pool([lp.Job("j", _writes(("x",)), planned=("x",))], 1, tmp_path, VAR)
    r = lp.run_pool([lp.Job("j", _child("sys.exit(7)\n"), planned=("x",))], 1, tmp_path, VAR)
    assert r.outcomes == {"x": "FAIL"}, r


def test_a_job_that_cannot_start_fails_alone(tmp_path: Path) -> None:
    jobs = [lp.Job("a", [str(tmp_path / "no-such-program")], planned=("l",)),
            lp.Job("b", _writes(("m",)), planned=("m",))]
    r = lp.run_pool(jobs, 2, tmp_path, VAR)
    assert r.outcomes == {"l": "FAIL", "m": "OK"}
    assert "could not start" in r.reasons["l"] and r.results[0].rc is None


@pytest.mark.parametrize("doc, says", [
    ({"format": "other"}, "is not a scry-live-summary"),
    ({"version": 2}, "is version 2"),
    ({"outcomes": {"x": "OK"}}, "judges ['y']"),
    ({"outcomes": {"x": "OK", "y": "OK", "w": "OK"}}, "judges ['w']"),
    ({"outcomes": {"x": "OK", "y": "PASS"}}, "carries outcomes ['PASS']"),
    ({"outcomes": {"x": ["OK"], "y": "OK"}}, "wrong type"),
    ({"outcomes": {"x": None, "y": "PASS"}}, "wrong type"),
    ({"reasons": {"q": "why"}}, "reasons for ['q']"),
    ({"reasons": {"x": 1}}, "wrong type"),
    ({"planned": "xy"}, "wrong type"),
    ({"transcript": None}, "wrong type"),
    ({"elapsed_s": "soon"}, "wrong type"),
    ({"elapsed_s": True}, "wrong type"),
    ({"elapsed_s": float("nan")}, "wrong type"),
])
def test_a_summary_that_is_not_one_fails_the_job(tmp_path: Path, doc: dict[str, object],
                                                 says: str) -> None:
    whole = {"format": "scry-live-summary", "version": 1, "planned": ["x", "y"],
             "outcomes": {"x": "OK", "y": "OK"}, "reasons": {}, "transcript": "",
             "elapsed_s": 1, **doc}
    body = f"summary.write_text({json.dumps(whole)!r})\n"
    r = lp.run_pool([lp.Job("bad", _child(body), planned=("x", "y"))], 1, tmp_path, VAR)
    assert r.outcomes == {"x": "FAIL", "y": "FAIL"}
    assert says in r.reasons["x"], r.reasons["x"]


@pytest.mark.parametrize("text", ["", "[]", "null", "{not json"])
def test_a_summary_that_is_no_document_fails_the_job(tmp_path: Path, text: str) -> None:
    r = lp.run_pool([lp.Job("bad", _child(f"summary.write_text({text!r})\n"), planned=("x",))],
                    1, tmp_path, VAR)
    assert r.outcomes == {"x": "FAIL"}


def test_a_child_that_planned_other_labels_makes_the_merge_invalid_and_merges_none_of_it(
        tmp_path: Path) -> None:
    jobs = [lp.Job("odd", _writes(("x", "z")), planned=("x", "y")),
            lp.Job("short", _writes(("p",)), planned=("p", "q")),
            lp.Job("good", _writes(("g",)), planned=("g",))]
    r = lp.run_pool(jobs, 3, tmp_path, VAR)
    assert "job odd its summary planned ['z'] and not ['y']" in r.invalid
    assert "job short its summary planned [] and not ['q']" in r.invalid
    assert r.outcomes == {"x": "FAIL", "y": "FAIL", "p": "FAIL", "q": "FAIL", "g": "OK"}


@pytest.mark.parametrize("jobs, workers, says", [
    ([], 1, "no job"),
    ([lp.Job("a", ["x"], planned=("1",))], 0, "workers is 0"),
    ([lp.Job("a", ["x"], planned=("1",)), lp.Job("a", ["x"], planned=("2",))], 1, "share a name"),
    ([lp.Job("A", ["x"], planned=("1",)), lp.Job("a", ["x"], planned=("2",))], 1, "case aside"),
    ([lp.Job("../esc", ["x"], planned=("1",))], 1, "one plain word"),
    ([lp.Job("a b", ["x"], planned=("1",))], 1, "one plain word"),
    ([lp.Job("a", ["x"], planned=())], 1, "could never fail"),
    ([lp.Job("a", ["x"], planned=("1",)), lp.Job("b", ["x"], planned=("1",))], 1, "planned twice"),
    ([lp.Job("a", ["x"], planned=("1", "1"))], 1, "planned twice"),
])
def test_refused_before_anything_starts(tmp_path: Path, jobs: list[lp.Job], workers: int,
                                        says: str) -> None:
    with pytest.raises(ValueError, match=says):
        lp.run_pool(jobs, workers, tmp_path / "out", VAR)
    assert not (tmp_path / "out").exists()


def test_never_more_children_at_once_than_workers_and_as_many_as_it_may(tmp_path: Path) -> None:
    """Each child marks itself in, waits until two are in (the lower bound: two must run at
    once or the wait runs out), keeps the most it sees in for a while, and marks itself out.
    Four jobs under two workers: every child counts exactly two."""
    room = tmp_path / "room"
    room.mkdir()
    body = (f"room = Path({str(room)!r}); me = room / summary.stem; me.write_text('in')\n"
            f"t = time.monotonic()\nwhile len(list(room.iterdir())) < 2 and "
            f"time.monotonic() - t < {RENDEZVOUS_S}:\n    time.sleep(0.02)\n"
            "n = 0; t = time.monotonic()\nwhile time.monotonic() - t < 0.3:\n"
            "    n = max(n, len(list(room.iterdir()))); time.sleep(0.02)\nme.unlink()\n"
            "lp.write_summary(summary, lp.Summary((summary.stem,), {summary.stem: 'OK'}, {}, "
            "str(n), 0))\n")
    jobs = [lp.Job(f"j{i}", _child(body), planned=(f"j{i}",)) for i in range(4)]
    r = lp.run_pool(jobs, 2, tmp_path, VAR)
    counts = [x.summary.transcript for x in r.results if x.summary is not None]
    assert counts == ["2", "2", "2", "2"], counts


def test_on_done_is_called_one_at_a_time(tmp_path: Path) -> None:
    inside: list[int] = []
    most = [0]

    def report(jr: lp.JobResult) -> None:
        inside.append(1)
        most[0] = max(most[0], len(inside))
        time.sleep(0.2)
        inside.pop()
    jobs = [lp.Job(f"j{i}", _writes((f"l{i}",)), planned=(f"l{i}",)) for i in range(4)]
    lp.run_pool(jobs, 4, tmp_path, VAR, on_done=report)
    assert most[0] == 1


def _interrupt_after(tmp_path: Path, started: Path) -> object:
    def interrupt(jr: lp.JobResult) -> None:
        if jr.job.name == "fast":
            _wait_for(started)
            raise KeyboardInterrupt
    return interrupt


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGINT for one process")
def test_an_interrupt_lets_each_running_child_unwind_through_its_cleanup(tmp_path: Path) -> None:
    started, cleaned = tmp_path / "started", tmp_path / "cleaned"
    slow = _child(f"Path({str(started)!r}).write_text('y')\ntry:\n    time.sleep(60)\n"
                  f"finally:\n    Path({str(cleaned)!r}).write_text('y')\n")
    jobs = [lp.Job("slow", slow, planned=("s",)), lp.Job("fast", _writes(("f",)), planned=("f",))]
    began = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        lp.run_pool(jobs, 2, tmp_path, VAR, on_done=_interrupt_after(tmp_path, started))  # type: ignore[arg-type]
    assert time.monotonic() - began < lp.STOP_GRACE_S
    assert cleaned.exists(), "the child was stopped without running its own cleanup"


def test_an_interrupt_kills_a_child_that_will_not_stop(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A child that ignores the interrupt is killed once the grace runs out; the pool waits for
    its threads, which wait for their children, so returning at all means the child is gone."""
    monkeypatch.setattr(lp, "STOP_GRACE_S", 1.0)
    started = tmp_path / "started"
    stubborn = _child("import signal\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                      "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                      f"Path({str(started)!r}).write_text('y')\ntime.sleep(60)\n")
    jobs = [lp.Job("stubborn", stubborn, planned=("s",)),
            lp.Job("fast", _writes(("f",)), planned=("f",))]
    began = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        lp.run_pool(jobs, 2, tmp_path, VAR, on_done=_interrupt_after(tmp_path, started))  # type: ignore[arg-type]
    assert time.monotonic() - began < 30


def test_an_interrupt_starts_no_job_still_queued(tmp_path: Path) -> None:
    ran = tmp_path / "queued-ran"

    def interrupt(jr: lp.JobResult) -> None:
        raise KeyboardInterrupt
    jobs = [lp.Job("first", _writes(("a",)), planned=("a",)),
            lp.Job("queued", _child(f"Path({str(ran)!r}).write_text('y')\n"), planned=("b",))]
    with pytest.raises(KeyboardInterrupt):
        lp.run_pool(jobs, 1, tmp_path, VAR, on_done=interrupt)
    assert not ran.exists()


@pytest.mark.parametrize("cpus, workers", [(1, 1), (2, 1), (3, 1), (10, 5), (32, 16), (None, 1)])
def test_default_workers_is_half_the_cpus_this_process_may_use(
        monkeypatch: pytest.MonkeyPatch, cpus: int | None, workers: int) -> None:
    monkeypatch.setattr(os, "process_cpu_count", lambda: cpus, raising=False)
    assert lp.default_workers() == workers


def test_default_workers_before_process_cpu_count_reads_the_machine(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(os, "process_cpu_count", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert lp.default_workers() == 4


def test_default_workers_on_this_host_is_at_least_one() -> None:
    assert lp.default_workers() >= 1


def test_a_summary_round_trips_with_non_ascii_text(tmp_path: Path) -> None:
    s = lp.Summary(("a", "b→c"), {"a": "OK", "b→c": "FAIL"}, {"b→c": "señal"}, "/t.jsonl", 2.5)
    lp.write_summary(tmp_path / "s.json", s)
    assert lp.read_summary(tmp_path / "s.json") == s


def test_a_summary_is_renamed_into_place_whole(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    moves: list[tuple[str, str, str]] = []
    real = os.replace

    def replace(src: str, dst: str) -> None:
        moves.append((Path(src).name, Path(dst).name, Path(src).read_text(encoding="utf-8")))
        real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    lp.write_summary(tmp_path / "s.json", lp.Summary(("a",), {"a": "OK"}, {}, "", 0))
    assert [(a, b) for a, b, _ in moves] == [("s.json.part", "s.json")]
    assert json.loads(moves[0][2])["outcomes"] == {"a": "OK"}


_CHILD_REPORTING_SIGINT = _child(
    "import signal\nh = signal.getsignal(signal.SIGINT)\n"
    "lp.write_summary(summary, lp.Summary(('h',), {'h': 'OK' if h is signal.default_int_handler "
    "else 'FAIL'}, {}, repr(h), 0))\n")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGINT for one process")
@pytest.mark.parametrize("launcher", ["default", "ignored"])
def test_a_child_unwinds_on_the_sigint_the_pool_sends_whatever_its_launcher_ignored(
        tmp_path: Path, launcher: str) -> None:
    """The stop's premise, in the child: Python's handler, the one that raises KeyboardInterrupt,
    whether the pool itself runs with SIGINT at its default or ignored, as a background job of a
    non-interactive shell runs it (an ignored signal survives exec)."""
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import signal, sys\nfrom pathlib import Path\nfrom scry_core import live_pool as lp\n"
        "signal.signal(signal.SIGINT, "
        f"{'signal.SIG_IGN' if launcher == 'ignored' else 'signal.default_int_handler'})\n"
        f"r = lp.run_pool([lp.Job('h', {_CHILD_REPORTING_SIGINT!r}, planned=('h',))], 1, "
        f"Path({str(tmp_path / 'o')!r}), {VAR!r})\n"
        "print(r.outcomes['h'], r.results[0].summary.transcript if r.results[0].summary else "
        "r.reasons)\n", encoding="utf-8")
    (tmp_path / "o").mkdir()
    run = subprocess.run([sys.executable, str(parent)], capture_output=True, text=True,
                         timeout=60, check=False)
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("OK "), run.stdout


class _Recorded:
    """A child that records how it was stopped and stops when asked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def terminate(self) -> None:
        self.calls.append("terminate")

    def send_signal(self, sig: int) -> None:
        self.calls.append(f"signal {sig}")

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.calls.append("kill")


@pytest.mark.parametrize("platform, how", [("win32", "terminate"),
                                           ("darwin", f"signal {signal.SIGINT}"),
                                           ("linux", f"signal {signal.SIGINT}")])
def test_the_stop_is_the_interrupt_where_the_platform_has_one(
        monkeypatch: pytest.MonkeyPatch, platform: str, how: str) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    children, child = lp._Children(), _Recorded()
    children._live.add(child)  # type: ignore[arg-type]
    children.stop()
    assert child.calls == [how]
    assert children.start(["x"], {}, None) is None  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
def test_each_child_leads_a_process_group_of_its_own(tmp_path: Path) -> None:
    body = ("g = f'{os.getpgid(0)} {os.getpid()} {os.getpgid(os.getppid())}'\n"
            "lp.write_summary(summary, lp.Summary(('g',), {'g': 'OK'}, {}, g, 0))\n")
    r = lp.run_pool([lp.Job("g", _child(body), planned=("g",))], 1, tmp_path, VAR)
    assert r.results[0].summary is not None
    group, pid, parents_group = map(int, r.results[0].summary.transcript.split())
    assert group == pid != parents_group


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT to one process is POSIX")
def test_a_second_interrupt_during_the_stop_kills_the_children_left(tmp_path: Path) -> None:
    """An impatient second Ctrl-C while the stop waits out its grace must not abandon a child
    that ignores the first: it is killed there and then. The child beats a file while alive."""
    beat, started = tmp_path / "beat", tmp_path / "started"
    stubborn = _child("import signal\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                      f"Path({str(started)!r}).write_text('y')\n"
                      f"while True:\n    Path({str(beat)!r}).write_text(str(time.time()))\n"
                      "    time.sleep(0.05)\n")
    parent = tmp_path / "parent.py"
    parent.write_text(
        # A pool at a terminal, which takes Ctrl-C whatever this suite's own launcher ignored.
        "import signal, sys\nfrom pathlib import Path\nfrom scry_core import live_pool as lp\n"
        "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
        f"argv = {stubborn!r}\n"
        "try:\n"
        f"    lp.run_pool([lp.Job('s', argv, planned=('s',))], 1, Path({str(tmp_path / 'o')!r}),"
        f" {VAR!r})\n"
        "except KeyboardInterrupt:\n    sys.exit(130)\n", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(parent)])
    try:
        _wait_for(started)
        proc.send_signal(signal.SIGINT)
        time.sleep(1.0)                    # inside the stop's grace
        proc.send_signal(signal.SIGINT)
        proc.wait(lp.STOP_GRACE_S / 2)     # back well before the grace runs out
    finally:
        if proc.poll() is None:
            proc.kill()
    last = beat.read_text()
    time.sleep(0.5)
    assert beat.read_text() == last, "the child is still alive after the parent left"


def test_an_interrupt_while_the_stop_waits_kills_every_child_and_goes_on() -> None:
    class Waiting(_Recorded):
        def wait(self, timeout: float | None = None) -> int:
            raise KeyboardInterrupt

    children, first, second = lp._Children(), Waiting(), _Recorded()
    children._live.update({first, second})  # type: ignore[arg-type]
    with pytest.raises(KeyboardInterrupt):
        children.stop()
    assert "kill" in first.calls and "kill" in second.calls


@pytest.mark.skipif(sys.platform == "win32", reason="SIGPIPE is POSIX")
def test_a_child_that_is_not_python_starts_with_sigpipe_at_its_default(tmp_path: Path) -> None:
    """A writer to a closed pipe dies quietly by SIGPIPE, as it does at a shell: the trampoline
    is a Python, which ignores SIGPIPE for itself, and an ignored signal survives exec."""
    body = "yes | head -n 1 > /dev/null; echo done"
    r = lp.run_pool([lp.Job("p", ["/bin/sh", "-c", body], planned=("p",))], 1, tmp_path, VAR)
    assert (tmp_path / "p.log").read_text(encoding="utf-8").split("\n") == ["done", ""], \
        "the writer saw a broken pipe instead of dying of it"
    assert r.outcomes == {"p": "FAIL"}         # no summary: only its log is the point here


@pytest.mark.skipif(sys.platform == "win32", reason="the trampoline is POSIX")
def test_a_signal_module_in_the_pools_directory_is_not_the_trampolines(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "signal.py").write_text("raise SystemExit('the project signal.py ran')\n")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "o").mkdir()
    isolated = _writes(("j",))
    isolated.insert(1, "-I")                   # the job itself keeps out of the directory too
    r = lp.run_pool([lp.Job("j", isolated, planned=("j",))], 1, tmp_path / "o", VAR)
    assert r.outcomes == {"j": "OK"}, r.reasons
