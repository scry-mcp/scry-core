"""`scry_core.live_ledger`: the selection a run names, the place a section holds, and the tally
that answers for a cell nobody planned."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scry_core import live_host, live_pool
from scry_core import live_ledger as ledger


def _section(block: str, cells: tuple[str, ...] = (), **kw: Any) -> ledger.Section:
    return ledger.Section(block, f"section {block}", [ledger.Cell(c, "test") for c in cells],
                          lambda: None, **kw)


class _Host:
    """The run's host, with a scratch of the test's own and nothing that reaches a machine."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self.finished = False
        self.closed = False
        self.kept: bool | None = None

    def made(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        return self.scratch

    def close(self, on_end: Any) -> None:
        self.closed = True

    def unfinished(self, on_end: Any) -> None:
        pass

    def leave(self, kept: bool) -> None:
        self.kept = kept


@pytest.fixture
def plain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ledger.Ledger:
    """A ledger whose calls never reach a host: the tally and the transcript are what it judges."""
    monkeypatch.setattr(live_host.LiveRun, "for_process",
                        classmethod(lambda cls, prefix, job=False: _Host(tmp_path / "scratch")))
    return ledger.Ledger("test-live-", "TEST_LIVE_SUMMARY")


@pytest.mark.parametrize(("raw", "names"), [
    ("", []),
    ("ab", ["A", "B"]),
    (" AA , B ", ["AA", "B"]),
    ("AA,", ["AA"]),
    ("a,aa", ["A", "AA"]),
])
def test_the_sections_a_run_names(raw: str, names: list[str]) -> None:
    assert ledger.chosen_sections(raw) == names


def test_a_section_that_spans_the_run_comes_last_and_opens_comes_first() -> None:
    chosen = sorted([_section("B", spans=True), _section("Z"), _section("A", opens=True)],
                    key=lambda s: (s.place, s.block))
    assert [s.block for s in chosen] == ["A", "Z", "B"]


def test_a_spanning_section_alone_cannot_judge_what_it_spans() -> None:
    named = ledger.cannot_be_judged([_section("X", ("the run held",), spans=True)])
    assert [label for label, _ in named] == ["the run held"]
    beside = ledger.cannot_be_judged([_section("A", ("a cell",)), _section("X", ("x",),
                                                                         spans=True)])
    assert beside == []


def test_a_cell_nobody_planned_fails_under_its_own_name(plain: ledger.Ledger) -> None:
    made = plain
    made.current = _section("A", ("planned",))
    made.judge("planned", True)
    made.judge("a stranger", True)
    assert made.failed == ["UNPLANNED OR REPEATED: a stranger"]
    assert made.tally == {"OK": 1, "FAIL": 1, "BLOCKED": 0}


def test_a_cell_judged_twice_fails_the_second_time(plain: ledger.Ledger) -> None:
    made = plain
    made.current = _section("A", ("once",))
    made.judge("once", True)
    made.judge("once", True)
    assert made.judge("once", True) is False


def test_blocking_the_rest_leaves_a_judged_cell_alone(plain: ledger.Ledger) -> None:
    made = plain
    made.current = _section("A", ("one", "two"))
    made.judge("one", True)
    made.block_rest("the section could not run")
    assert made.tally == {"OK": 1, "FAIL": 0, "BLOCKED": 1}
    assert made.reasons["two"] == "the section could not run"


def test_a_call_past_the_ceiling_is_blocked_before_it_is_made(plain: ledger.Ledger) -> None:
    made = plain

    def slow(seconds: float) -> dict[str, Any]:
        raise AssertionError("a call above the ceiling is never made")

    with pytest.raises(ledger.Blocked, match="may wait past"):
        made.call(slow, seconds=ledger.WAIT_CEILING_S + 1)


def _run(plain: ledger.Ledger) -> int:
    """Run every section registered, with no pool and nothing to tear down."""
    return plain.run([], {}, lambda: None, lambda _block: None)


def _ask() -> dict[str, Any]:
    return {"status": "ok"}


def _judging(plain: ledger.Ledger, label: str, holds: bool) -> Callable[[], None]:
    """A section that judges one cell and answers nothing."""
    def run() -> None:
        plain.judge(label, holds)
    return run


def _asking(plain: ledger.Ledger, label: str) -> Callable[[], None]:
    """A section that calls once and fails its cell, so the transcript has a row."""
    def run() -> None:
        plain.call(_ask)
        plain.judge(label, False)
    return run


def test_a_run_of_two_sections_answers_by_its_cells(plain: ledger.Ledger) -> None:
    plain.section("A", "the first", [ledger.Cell("a")])(_judging(plain, "a", True))
    plain.section("B", "the second", [ledger.Cell("b")])(_asking(plain, "b"))
    assert _run(plain) == ledger.EXIT_FAIL
    assert plain.tally == {"OK": 1, "FAIL": 1, "BLOCKED": 0}
    rows = [json.loads(line) for line in plain.transcript.read_text().splitlines()]
    assert [(r["label"], r["verdict"], r["tool"]) for r in rows] == [("b", "FAIL", "_ask")]


def test_a_run_with_no_fail_passes(plain: ledger.Ledger) -> None:
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", True))
    assert _run(plain) == ledger.EXIT_PASS


def test_a_run_names_itself_in_its_verdict(plain: ledger.Ledger,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """A script that runs one section of a matrix says which one passed, not the matrix."""
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", True))
    plain.run([], {}, lambda: None, lambda _block: None, name="LIVE MATRIX, SECTION L")
    assert capsys.readouterr().out.rstrip().endswith("==> LIVE MATRIX, SECTION L PASSED")


def test_a_section_that_raises_fails_its_first_cell_and_blocks_the_rest(
        plain: ledger.Ledger) -> None:
    def boom() -> None:
        raise RuntimeError("the board died")
    plain.section("A", "the only", [ledger.Cell("one"), ledger.Cell("two")])(boom)
    assert _run(plain) == ledger.EXIT_FAIL
    assert plain.current is not None
    assert plain.current.judged == {"one": "FAIL", "two": "BLOCKED"}


def test_a_blocked_call_blocks_the_rest_of_its_section(plain: ledger.Ledger) -> None:
    def slow() -> None:
        raise ledger.Blocked("the host could not hold the board")
    plain.section("A", "the only", [ledger.Cell("one"), ledger.Cell("two")])(slow)
    assert _run(plain) == ledger.EXIT_INVALID, "no cell ran, so there is no verdict"
    assert plain.current is not None and plain.current.judged == {
        "one": "BLOCKED", "two": "BLOCKED"}


def test_a_cell_planned_twice_is_an_invalid_run(plain: ledger.Ledger) -> None:
    plain.section("A", "one", [ledger.Cell("same")])(_judging(plain, "same", True))
    plain.section("B", "two", [ledger.Cell("same")])(_judging(plain, "same", True))
    assert _run(plain) == ledger.EXIT_INVALID


def test_a_cell_a_section_never_judged_fails_as_never_reached(plain: ledger.Ledger) -> None:
    plain.section("A", "the empty", [ledger.Cell("never")])(lambda: None)
    assert _run(plain) == ledger.EXIT_FAIL
    assert plain.current is not None and plain.current.judged == {"never": "FAIL"}
    assert plain.reasons["never"].startswith("never reached")


def test_a_run_writes_the_summary_a_pool_reads(plain: ledger.Ledger, tmp_path: Path) -> None:
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", True))
    summary = tmp_path / "a.json"
    plain.section("B", "", [ledger.Cell("b")])(_judging(plain, "b", False))
    plain.run([], {}, lambda: None, lambda _block: None, summary=summary)
    doc = json.loads(summary.read_text())
    assert doc["outcomes"] == {"a": "OK", "b": "FAIL"}


def test_a_fresh_path_and_a_tmp_directory_stay_in_the_run_s_scratch(
        plain: ledger.Ledger) -> None:
    first = Path(plain.fresh(".log"))
    second = Path(plain.fresh(".log"))
    assert first.parent == plain.host.made() and first != second
    assert plain.tmp("work-").is_dir()


def test_a_failed_cell_leaves_the_sessions_conf_and_log_beside_it(
        plain: ledger.Ledger, tmp_path: Path) -> None:
    conf, log = tmp_path / "guest.conf", tmp_path / "guest.log"
    conf.write_text("[cpu]\ncore=normal\n")
    log.write_text("line one\nline two\n")
    plain.session_files = lambda: (conf, log)
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", False))
    _run(plain)
    assert len(plain.kept) == 1
    kept = plain.kept[0]
    assert (kept / "guest.conf").read_text() == "[cpu]\ncore=normal\n"
    assert (kept / "guest.log.tail").read_text() == "line one\nline two\n"


def test_a_call_is_recorded_with_its_reply_and_an_exception_becomes_one(
        plain: ledger.Ledger) -> None:
    def answer(seconds: float = 1.0) -> dict[str, Any]:
        return {"status": "ok"}

    def refuses() -> dict[str, Any]:
        raise ValueError("the stub refused")

    assert plain.call(answer) == {"status": "ok"}
    assert "ValueError" in str(plain.call(refuses)["exception"])
    assert [c["tool"] for c in plain.calls] == ["answer", "refuses"]
    assert plain.calls[0]["wall_s"] >= 0


def test_a_block_outside_a_section_is_the_row_and_the_tally(plain: ledger.Ledger) -> None:
    plain.block("nothing planned", "there is no section here")
    assert plain.tally == {"OK": 0, "FAIL": 0, "BLOCKED": 1}
    assert plain.blocked_why == [("nothing planned", "there is no section here")]


def test_a_fail_with_no_session_says_so_rather_than_keeping_nothing(
        plain: ledger.Ledger, capsys: pytest.CaptureFixture[str]) -> None:
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", False))
    _run(plain)
    assert plain.kept == []
    assert "no session was live" in capsys.readouterr().out


def test_the_cells_of_a_pooled_job_are_adopted_with_its_own_summary(
        plain: ledger.Ledger, tmp_path: Path) -> None:
    section = _section("A", ("one", "two"))
    plain.sections.append(section)
    second = _section("B", ("three",))
    plain.sections.append(second)
    job = live_pool.Job("A", ["true"], planned=("one", "two"))
    summary = live_pool.Summary(("one", "two"), {"one": "OK", "two": "FAIL"},
                                {"two": "the stub refused"}, str(tmp_path / "t.jsonl"), 1.0)
    ran = live_pool.PoolResult(results=[live_pool.JobResult(job, 1, tmp_path / "j.log", 1.0,
                                                            summary)],
                               outcomes={"one": "OK", "two": "FAIL"},
                               reasons={"two": "the stub refused"})
    plain.current = None
    assert plain._adopt([section], ran) == ""
    assert plain.tally == {"OK": 1, "FAIL": 1, "BLOCKED": 0}
    assert plain.reasons["two"] == "the stub refused"


def test_a_step_lists_wait_is_read_by_the_ceiling(plain: ledger.Ledger) -> None:
    def perform(steps: list[dict[str, Any]], settle_seconds: float = 1.0) -> dict[str, Any]:
        return {}

    with pytest.raises(ledger.Blocked, match="steps"):
        plain.call(perform, steps=[{"op": "run_for", "seconds": ledger.WAIT_CEILING_S + 1}])


def test_a_server_call_implementation_answers_instead(monkeypatch: pytest.MonkeyPatch,
                                                      tmp_path: Path) -> None:
    monkeypatch.setattr(live_host.LiveRun, "for_process",
                        classmethod(lambda cls, prefix, job=False: _Host(tmp_path / "s")))
    seen: list[str] = []

    def impl(made: ledger.Ledger, fn: Any, kw: dict[str, Any], exempt: str) -> dict[str, Any]:
        seen.append(exempt)
        return {"status": "ok"}

    made = ledger.Ledger("test-live-", "TEST_LIVE_SUMMARY", call_impl=impl)
    assert made.call(_ask, exempt="a boot") == {"status": "ok"}
    assert seen == ["a boot"]


def test_a_call_past_its_grace_is_blocked_and_the_emulator_ended(
        plain: ledger.Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "CALL_GRACE_S", 0.0)
    hung: list[bool] = []
    plain.on_hang = lambda: hung.append(True)

    def never() -> dict[str, Any]:
        time.sleep(0.05)
        return {}

    with pytest.raises(ledger.Blocked, match="did not return"):
        plain.call(never)
    assert hung == [True]


def test_an_emulator_that_outlived_the_run_is_a_fail(plain: ledger.Ledger) -> None:
    plain.host.close = lambda on_end: "FAIL  an emulator outlived the run"  # type: ignore[method-assign]
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", True))
    assert _run(plain) == ledger.EXIT_FAIL
    assert plain.failed == ["an emulator outlived the run"]


def test_a_cell_judged_outside_a_section_is_a_defect_of_the_matrix(plain: ledger.Ledger) -> None:
    with pytest.raises(RuntimeError, match="outside any section"):
        plain.judge("a", True)
    assert plain._rest() == []


def test_a_standalone_check_prints_and_counts(plain: ledger.Ledger) -> None:
    assert plain.check("holds", True) is True
    assert plain.check("does not", False, "the stub refused") is False
    assert plain.tally == {"OK": 1, "FAIL": 1, "BLOCKED": 0}
    assert plain.reasons["does not"] == "the stub refused"


def test_blocking_a_label_no_section_planned_fails_it(plain: ledger.Ledger) -> None:
    plain.current = _section("A", ("one",))
    plain.block("a stranger", "nothing plans it")
    plain.block("one", "the board would not boot")
    assert plain.tally == {"OK": 0, "FAIL": 1, "BLOCKED": 1}
    assert plain.current.judged == {"UNPLANNED OR REPEATED: a stranger": "FAIL",
                                    "one": "BLOCKED"}


def test_evidence_that_cannot_be_copied_says_so(
        plain: ledger.Ledger, capsys: pytest.CaptureFixture[str]) -> None:
    plain.session_files = lambda: (Path("/nonexistent/conf"), None)

    def boom(label: str) -> None:
        raise OSError("the disk said no")

    plain.keep_evidence = boom  # type: ignore[method-assign]
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", False))
    _run(plain)
    assert plain.kept == []


def test_a_section_whose_variable_is_unset_blocks_its_cells(plain: ledger.Ledger) -> None:
    plain.section("A", "the only", [ledger.Cell("a")], needs="SOME_BOARD_DIR")(lambda: None)
    assert _run(plain) == ledger.EXIT_INVALID
    assert plain.current is not None and plain.current.judged == {"a": "BLOCKED"}
    assert plain.reasons["a"] == "SOME_BOARD_DIR is not set"


def test_a_spanning_section_is_named_when_nothing_else_was_chosen(
        plain: ledger.Ledger, capsys: pytest.CaptureFixture[str]) -> None:
    plain.section("X", "the verdict", [ledger.Cell("the run held")], spans=True)(
        _judging(plain, "the run held", True))
    _run(plain)
    assert "the run held" in capsys.readouterr().out


def test_a_run_that_pools_its_middle_sections_counts_them_where_they_run(
        plain: ledger.Ledger, tmp_path: Path) -> None:
    first = _section("A", ("one",))
    second = _section("B", ("two",))
    plain.sections.extend([first, second])
    job = live_pool.Job("A", ["true"], planned=("one",))
    jobs_transcript = tmp_path / "job.jsonl"
    jobs_transcript.write_text('{"label": "one", "verdict": "OK"}\n')
    summary = live_pool.Summary(("one", "two"), {"one": "OK", "two": "OK"}, {},
                                str(jobs_transcript), 1.0)
    ran = live_pool.PoolResult(results=[live_pool.JobResult(job, 1, tmp_path / "a.log", 1.0,
                                                            summary)],
                               outcomes={"one": "OK", "two": "OK"})
    rc = plain.run([], {}, lambda: None, lambda _block: None, pool=lambda pooled: ran)
    assert rc == ledger.EXIT_FAIL, "the job's exit code explains nothing, so it is a FAIL"
    assert plain.tally["OK"] == 2
    assert any("JOB A EXITED 1" in label for label in plain.failed)
    assert '"one", "verdict": "OK"' in plain.transcript.read_text(), "its own rows came too"


def test_a_run_that_kept_evidence_names_where_it_is(
        plain: ledger.Ledger, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plain.kept.append(tmp_path / "evidence")
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", True))
    _run(plain)
    assert "evidence:" in capsys.readouterr().out


def test_a_step_without_a_wait_is_not_a_wait_of_the_call(plain: ledger.Ledger) -> None:
    def perform(steps: list[dict[str, Any]], seconds: float = 1.0) -> dict[str, Any]:
        return {}

    assert plain.call(perform, steps=[{"op": "run_for"}, {"op": "stop"}]) == {}


def test_evidence_that_cannot_be_written_is_reported(
        plain: ledger.Ledger, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    conf = tmp_path / "guest.conf"
    conf.write_text("[cpu]\n")
    plain.session_files = lambda: (conf, None)
    plain.evidence = tmp_path / "a-file"
    plain.evidence.write_text("not a directory")
    plain.section("A", "the only", [ledger.Cell("a")])(_judging(plain, "a", False))
    _run(plain)
    assert "evidence NOT kept" in capsys.readouterr().out
