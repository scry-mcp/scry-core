"""The log wait both servers drive, judged on its own: a log read whole lines at a time from a
mark, and a wait that answers what the log already holds before it waits, reads once more
before every ending, and names how it ended."""

from __future__ import annotations

import codecs
import re
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from scry_core import log_wait
from scry_core import progress as mprogress


def test_lines_since_reads_whole_lines_from_a_mark(tmp_path: Path) -> None:
    log = tmp_path / "x.log"
    assert log_wait.lines_since(log, 7) == ([], 0), "a log not there yet is read from its start"
    log.write_bytes(codecs.BOM_UTF8 + b"one\r\ntwo\nthr")
    lines, mark = log_wait.lines_since(log, 0)
    assert lines == ["one", "two"] and mark == len(codecs.BOM_UTF8) + 9
    with open(log, "ab") as fh:
        fh.write(b"ee\n")
    assert log_wait.lines_since(log, mark) == (["three"], mark + 6)
    log.write_bytes(b"new\n")                       # rewritten SHORTER than the mark
    assert log_wait.lines_since(log, mark) == (["new"], 4)


def feed(*reads: list[str]) -> Callable[[], list[str]]:
    """`fresh` as a log that gains each list in turn, then nothing."""
    queue = list(reads)
    return lambda: queue.pop(0) if queue else []


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(log_wait, "POLL_S", 0.001)


def wait(fresh: Callable[[], list[str]], seconds: float = 0.2,
         stopped: Callable[[], bool] = lambda: False,
         alive: Callable[[], bool] = lambda: True) -> log_wait.Found | log_wait.Ended:
    return log_wait.wait(re.compile("GO"), fresh, seconds=seconds, stopped=stopped, alive=alive)


def test_a_line_already_in_the_log_is_answered_at_once() -> None:
    got = wait(feed(["a", "GO 1", "GO 2"]))
    assert got == log_wait.Found("GO 1", True, 2, 1, 0, 0.0, 3)
    assert got.fields() == {"line": "GO 1", "already": True, "lines_total": 2,
                            "lines_before": 1, "arrived_during": 0, "waited_s": 0.0,
                            "lines_examined": 3}, "a server spreads these into its reply"


def test_a_line_that_arrives_is_found_with_what_arrived_before_it() -> None:
    got = wait(feed(["a"], ["b", "c"], ["d", "GO"]))
    assert isinstance(got, log_wait.Found) and not got.already, got
    assert (got.line, got.lines_before, got.arrived_during, got.lines_examined) == ("GO", 4, 4, 5)


def test_a_bound_that_runs_out_is_a_timeout_with_its_counts() -> None:
    got = wait(feed(["a"], ["b"]), seconds=0.05)
    assert isinstance(got, log_wait.Ended) and got.ending == "TIMEOUT", got
    assert (got.arrived_during, got.lines_examined) == (1, 2) and got.waited_s >= 0.0


@pytest.mark.parametrize(("stopped", "alive", "how"), [
    (lambda: True, lambda: True, "STOPPED"), (lambda: False, lambda: False, "GONE")])
def test_a_stop_or_a_death_ends_the_wait_after_one_last_read(
        stopped: Callable[[], bool], alive: Callable[[], bool], how: str) -> None:
    got = wait(feed(["a"], ["b"]), stopped=stopped, alive=alive)
    assert isinstance(got, log_wait.Ended) and got.ending == how, got
    assert got.lines_examined == 2, "the last read looked at what the log gained"
    late = wait(feed(["a"], ["GO late"]), stopped=stopped, alive=alive)
    assert isinstance(late, log_wait.Found) and late.line == "GO late", late


def test_a_stop_that_lands_as_the_bound_runs_out_is_the_stop(
        monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]                          # a clock only the wait's own sleeps advance
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    lands = now[0] + 0.03                              # the bound's own instant
    got = log_wait.wait(re.compile("GO"), feed(["a"]), seconds=0.03,
                        stopped=lambda: now[0] >= lands, alive=lambda: True)
    assert isinstance(got, log_wait.Ended) and got.ending == "STOPPED", got
    assert got.at_bound, got
    inside = wait(feed(["a"]), stopped=lambda: True)
    assert isinstance(inside, log_wait.Ended) and not inside.at_bound, inside


def test_an_emulator_that_died_as_the_bound_ran_out_is_gone_not_a_timeout(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The bound's own instant is asked about the emulator too: one that died in the last poll
    is GONE, never a TIMEOUT saying the machine still runs."""
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    dies = now[0] + 0.03
    got = log_wait.wait(re.compile("GO"), feed(["a"]), seconds=0.03,
                        stopped=lambda: False, alive=lambda: now[0] < dies)
    assert isinstance(got, log_wait.Ended) and got.ending == "GONE", got


def test_the_wait_reports_its_progress_under_its_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    log_wait.wait(re.compile("GO"), feed(["a"], ["b {x}"]), seconds=0.05,
                  stopped=lambda: False, alive=lambda: True,
                  progress=lambda done, total, line: said.append(line), label="log_wait /G{O}/")
    assert said and said[-1].startswith("log_wait /G{O}/: "), said
    assert "1 lines arrived, last: b {x}" in said[0], said


def test_a_timeouts_note_says_what_arrived_and_a_silent_writer() -> None:
    quiet = log_wait.Ended("TIMEOUT", 0, 4, 2.0)
    note = log_wait.timeout_note("GO", quiet, "since the mark", "guest")
    assert note.startswith("nothing matched /GO/ in 2.0 s: 0 lines arrived DURING the wait (4 "
                           "since the mark)"), note
    assert "The guest wrote NOTHING" in note and note.endswith("The machine is still running")
    busy = log_wait.timeout_note("GO", log_wait.Ended("TIMEOUT", 3, 7, 2.0), "in the log", "x")
    assert "3 lines arrived" in busy and "NOTHING" not in busy


def test_a_timeouts_note_closes_on_the_run_state_its_caller_knows() -> None:
    """A caller whose own question about the machine went unanswered says that instead."""
    ended = log_wait.Ended("TIMEOUT", 1, 4, 2.0)
    unknown = "Whether the machine is running or stopped is not known"
    said = log_wait.timeout_note("GO", ended, "in the log", "guest", run_state=unknown)
    assert said.endswith(f". {unknown}") and "still running" not in said, said
    default = log_wait.timeout_note("GO", ended, "in the log", "guest")
    assert default == said.removesuffix(unknown) + log_wait.STILL_RUNNING, default


def test_a_gone_emulator_is_said_with_the_bound() -> None:
    said = log_wait.gone_message("GO", log_wait.Ended("GONE", 0, 0, 1.5), 30.0)
    assert said.startswith("the emulator is GONE, 1.5 s into a 30 s wait for /GO/"), said


def test_a_mark_inside_a_line_leaves_that_lines_rest_out(tmp_path: Path) -> None:
    """A mark taken while the writer was mid-line: the rest of that line is not a line of what
    came after it, and a line still unfinished there yields nothing until it ends."""
    log = tmp_path / "e.log"
    log.write_bytes(b"one\nhalf")
    mark = log.stat().st_size
    assert log_wait.lines_since(log, mark) == ([], mark), "no newline yet: nothing whole"
    with log.open("ab") as fh:
        fh.write(b" done\nafter\n")
    lines, nxt = log_wait.lines_since(log, mark)
    assert lines == ["after"] and nxt == log.stat().st_size, (lines, nxt)
    assert log_wait.lines_since(log, 4)[0] == ["half done", "after"], "a mark on a line's start"


@pytest.mark.parametrize(("parked", "at_bound", "said"), [
    (True, False, "is STOPPED at the debugger"), (False, True, "STOPPED as the bound expired"),
    (False, False, "STOPPED during the wait")])
def test_a_wait_the_machine_stopped_under_says_when_and_what_arrived(
        parked: bool, at_bound: bool, said: str) -> None:
    got = log_wait.stopped_message("BOOT", 1, 2.5, parked=parked, at_bound=at_bound)
    assert got.startswith(f"the machine {said}: a stopped machine logs nothing"), got
    assert "1 line arrived during 2.5 s" in got and "/BOOT/" in got
