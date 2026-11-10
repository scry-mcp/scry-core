"""The account of a list of steps, judged on its own: compact rows that keep what makes a stop
one, the machine's count of the stops numbered in the list, and the pair of files or neither."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scry_core import sequence_account as sa
from scry_core.reply_contract import Invalid

SHAPE = sa.Shape(kept=("stop_seq", "pc"),
                 cause_key=lambda stop: str(stop.get("cause", "?")).upper(),
                 extra=lambda reply, cut: cut.update(hit=reply["hit"]) if "hit" in reply
                 else None)


def stop(seq: int, cause: str = "bp", **more: Any) -> dict[str, Any]:
    return {"summary": f"stop {seq}", "status": "ok", "stop_seq": seq, "pc": "0x10", "cause": cause,
            "regs": {"A": "0x1"}, **more}


def test_without_summaries_the_steps_are_whole() -> None:
    ran = [{"op": "step", "reply": stop(1)}]
    assert sa.account(ran, False, True, 0, 0, SHAPE, lambda: Path("/never"), rows_shown=24) \
        == {"ran": ran}


def test_a_compact_row_keeps_what_makes_a_stop_one_and_the_entrys_own_fields() -> None:
    row = sa.brief({"op": "run", "cpu": "main", "reply": stop(3, hit="w")}, 5, SHAPE)
    assert row == {"step": 5, "op": "run", "cpu": "main",
                   "reply": {"summary": "stop 3", "status": "ok", "stop_seq": 3, "pc": "0x10",
                             "hit": "w"}}
    plain = sa.brief({"op": "read", "reply": {"summary": "read", "status": "ok",
                                               "stopped_on_its_own": stop(4)}}, 0, SHAPE)
    assert plain["reply"]["stopped_on_its_own"]["stop_seq"] == 4 and "pc" not in plain["reply"]


def test_the_stops_counted_name_the_range_and_what_no_reply_surveyed() -> None:
    replies = [stop(2, "bp"), stop(3, "watch"), {"status": "ok", "stopped_on_its_own": stop(4)},
               stop(9)]
    got = sa.stops(replies, 2, 5, SHAPE)
    assert got == {"stop_seq_first": 2, "stop_seq_last": 5, "surveyed": 3,
                   "by_cause": {"BP": 2, "WATCH": 1}, "unaccounted": 1}
    none = sa.stops([], 3, 2, SHAPE)
    assert none["stop_seq_first"]["available"] is False and none["unaccounted"] == 0


def test_a_long_list_shows_its_first_rows_writes_the_files_and_keeps_the_last(
        tmp_path: Path) -> None:
    ran = [{"op": "step", "reply": stop(i + 1)} for i in range(30)]
    got = sa.account(ran, True, True, 0, 30, SHAPE, lambda: tmp_path / "batch-1", rows_shown=5)
    assert got["steps_total"] == 30 and got["truncated"] is True
    assert len(got["ran"]) == 5 + 1 and got["ran"][-1]["reply"]["regs"], got["ran"][-1]
    assert all("regs" not in row["reply"] for row in got["ran"][:5]), "shown rows are compact"
    assert got["ran_path"] == str(tmp_path / "batch-1-ran.jsonl")
    assert got["replies_path"] == str(tmp_path / "batch-1-replies.jsonl")
    compact = [json.loads(line) for line in Path(got["ran_path"]).read_text().splitlines()]
    assert len(compact) == 30 and all("regs" not in row["reply"] for row in compact)
    lines = Path(got["replies_path"]).read_text().splitlines()
    assert len(lines) == 30 and json.loads(lines[0])["reply"]["regs"] == {"A": "0x1"}
    assert got["stops"]["surveyed"] == 30 and got["stops"]["stop_seq_last"] == 30


@pytest.mark.parametrize(("steps", "truncated"), [(5, False), (6, True)])
def test_the_ceiling_is_the_callers_and_only_a_list_past_it_is_truncated(
        tmp_path: Path, steps: int, truncated: bool) -> None:
    ran = [{"op": "step", "reply": stop(i + 1)} for i in range(steps)]
    got = sa.account(ran, True, False, 0, 0, SHAPE, lambda: tmp_path / "b", rows_shown=5)
    assert got["truncated"] is truncated and len(got["ran"]) == 5, got["ran"]
    assert all("regs" not in row["reply"] for row in got["ran"]), "keep_last off: none whole"


def test_a_stop_the_tail_carries_is_counted_once(tmp_path: Path) -> None:
    """`also` carries the failed step's reply or the stop the tail waited for, which may be a
    stop a row already shows: counted once, and one only `also` carries extends the range."""
    ran = [{"op": "step", "reply": stop(2)}]
    got = sa.account(ran, True, True, 1, 0, SHAPE, lambda: tmp_path / "b",
                     also=[stop(2), stop(3, "watch")], rows_shown=24)
    assert got["stops"] == {"stop_seq_first": 2, "stop_seq_last": 3, "surveyed": 2,
                            "by_cause": {"BP": 1, "WATCH": 1}, "unaccounted": 0}


def test_rows_are_written_with_jsons_own_escapes(tmp_path: Path) -> None:
    """A step can echo what the caller typed, and a lone surrogate does not encode as UTF-8:
    the rows are written with JSON's escapes, so every one lands."""
    path = tmp_path / "rows.jsonl"
    sa.write_jsonl(path, [{"summary": "log \ud800"}])
    assert json.loads(path.read_text(encoding="ascii")) == {"summary": "log \ud800"}


def test_the_range_ends_at_the_newest_of_the_record_and_the_replies(tmp_path: Path) -> None:
    ran = [{"op": "step", "reply": stop(2)}]
    got = sa.account(ran, True, True, 1, 0, SHAPE, lambda: tmp_path / "b", rows_shown=24)
    assert got["stops"]["stop_seq_last"] == 2, "the record cleared mid-list"
    later = sa.account(ran, True, True, 1, 5, SHAPE, lambda: tmp_path / "c", rows_shown=24)
    assert later["stops"]["stop_seq_last"] == 5 and later["stops"]["unaccounted"] == 3


@pytest.mark.parametrize("fails_at", ["stem", "second", "bare"])
def test_a_scratch_that_refuses_costs_the_pair_and_never_the_account(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails_at: str) -> None:
    def stem() -> Path:
        if fails_at == "stem":
            raise OSError("no scratch")
        if fails_at == "bare":
            raise OSError()                          # no message: the why still has one
        return tmp_path / "batch-1"
    real = sa.write_jsonl

    def second_refused(path: Path, rows: list[dict[str, Any]]) -> str:
        out = real(path, rows)                       # a write that fails HALF WAY leaves its file
        if path.name.endswith("-replies.jsonl"):
            raise OSError("disk full")
        return out
    monkeypatch.setattr(sa, "write_jsonl", second_refused)
    got = sa.account([{"op": "step", "reply": stop(1)}], True, False, 0, 1, SHAPE, stem,
                     rows_shown=24)
    assert got["ran_path"]["available"] is False and got["replies_path"]["available"] is False
    assert got["ran_path"]["why"].strip(), got["ran_path"]
    assert not list(tmp_path.iterdir()), "the pair or neither"
    assert got["stops"]["surveyed"] == 1, "the account stands without the files"


def test_the_look_cuts_to_the_last_lines_and_says_what_it_cut() -> None:
    got = sa.looked("guest", ["a1", "b", "a2", "a3"], 7, re.compile("a"), 2)
    assert got == {"guest": {"available": True, "since_mark": 7, "lines_written": 4,
                             "lines_total": 3, "truncated": True, "lines": ["a2", "a3"],
                             "pattern": "a"}}


@pytest.mark.parametrize("value", [1, "yes", None])
def test_summaries_is_true_or_false_in_one_sentence(value: object) -> None:
    with pytest.raises(Invalid, match="summaries is true or false"):
        sa.check_summaries(value)
    sa.check_summaries(True)


def test_the_summaries_argument_names_the_rows_shown() -> None:
    said = sa.summaries_argument(24)
    assert "the first 24" in said and "never of a step" in said


def test_a_sequence_run_requires_what_a_run_always_counts_and_the_rest_stays_optional() -> None:
    from scry_core import reply_schema

    class Run(reply_schema.ReplyEnvelope, sa.SequenceFields, sa.SequenceRun, total=False):
        pass

    assert reply_schema.own_required(Run) == {"failed_at", "held", "ran", "steps_completed"}
    assert not {"ran", "held"} & set(sa.SequenceFields.__annotations__)
