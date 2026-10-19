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
    assert isinstance(got, log_wait.Ended) and got.how == "TIMEOUT", got
    assert (got.arrived_during, got.lines_examined) == (1, 2) and got.waited_s >= 0.0


@pytest.mark.parametrize(("stopped", "alive", "how"), [
    (lambda: True, lambda: True, "STOPPED"), (lambda: False, lambda: False, "GONE")])
def test_a_stop_or_a_death_ends_the_wait_after_one_last_read(
        stopped: Callable[[], bool], alive: Callable[[], bool], how: str) -> None:
    got = wait(feed(["a"], ["b"]), stopped=stopped, alive=alive)
    assert isinstance(got, log_wait.Ended) and got.how == how, got
    assert got.lines_examined == 2, "the last read looked at what the log gained"
    late = wait(feed(["a"], ["GO late"]), stopped=stopped, alive=alive)
    assert isinstance(late, log_wait.Found) and late.line == "GO late", late


def test_a_stop_that_lands_as_the_bound_runs_out_is_the_stop() -> None:
    lands = time.monotonic() + 0.03                    # the bound's own instant
    got = log_wait.wait(re.compile("GO"), feed(["a"]), seconds=0.03,
                        stopped=lambda: time.monotonic() >= lands, alive=lambda: True)
    assert isinstance(got, log_wait.Ended) and got.how == "STOPPED", got
    assert got.at_bound, got
    inside = wait(feed(["a"]), stopped=lambda: True)
    assert isinstance(inside, log_wait.Ended) and not inside.at_bound, inside


def test_an_emulator_that_died_as_the_bound_ran_out_is_gone_not_a_timeout() -> None:
    """The bound's own instant is asked about the emulator too: one that died in the last poll
    is GONE, never a TIMEOUT saying the machine still runs."""
    dies = time.monotonic() + 0.03
    got = log_wait.wait(re.compile("GO"), feed(["a"]), seconds=0.03,
                        stopped=lambda: False, alive=lambda: time.monotonic() < dies)
    assert isinstance(got, log_wait.Ended) and got.how == "GONE", got


def test_the_wait_reports_its_progress_under_its_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mprogress, "PROGRESS_EVERY_S", 0.0)
    said: list[str] = []
    log_wait.wait(re.compile("GO"), feed(["a"], ["b {x}"]), seconds=0.05,
                  stopped=lambda: False, alive=lambda: True,
                  progress=lambda done, total, line: said.append(line), label="log_wait /G{O}/")
    assert said and said[-1].startswith("log_wait /G{O}/: "), said
    assert "1 lines arrived, last: b {x}" in said[0], said
