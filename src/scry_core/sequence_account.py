"""The account of a list of steps run in one call, shared by both servers."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Required

from typing_extensions import TypedDict

from scry_core import vocabulary as vocab
from scry_core.reply_contract import When, unavailable


def _nothing(reply: dict[str, Any], cut: dict[str, Any]) -> None:
    """Keep nothing."""


@dataclass(frozen=True)
class Shape:
    """A server's half: the keys a stop's row keeps, and the key it is counted under."""
    kept: tuple[str, ...]
    cause_key: Callable[[dict[str, Any]], str]
    extra: Callable[[dict[str, Any], dict[str, Any]], None] = field(default=_nothing)


def is_stop(reply: dict[str, Any]) -> bool:
    """Whether `reply` is a stop's, which every one numbers."""
    return isinstance(reply.get("stop_seq"), int)


def stops_in(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """Every stop `reply` surveys, including `stopped_on_its_own`."""
    found = reply.get("stopped_on_its_own")
    return [r for r in (reply, found) if isinstance(r, dict) and is_stop(r)]


def brief(entry: dict[str, Any], step: int, shape: Shape) -> dict[str, Any]:
    """A step's compact row: the reply cut to summary and status, a stop keeping more."""
    reply = entry["reply"]
    cut = {"summary": reply.get("summary"), "status": reply.get("status")}
    if is_stop(reply):
        cut.update({k: reply.get(k) for k in shape.kept})
        shape.extra(reply, cut)
    if "stopped_on_its_own" in reply:
        cut["stopped_on_its_own"] = reply["stopped_on_its_own"]
    return {"step": step, **{k: v for k, v in entry.items() if k != "reply"}, "reply": cut}


def stops(replies: list[dict[str, Any]], first: int, last: int, shape: Shape) -> dict[str, Any]:
    """The machine's count of the stops numbered `first` to `last`; `unaccounted` are numbered stops
    no reply surveyed (a refusing reader's stop is real, so it is reported, never refused)."""
    seen: dict[int, str] = {}
    for reply in replies:
        for stop in stops_in(reply):
            seq = int(stop["stop_seq"])
            if first <= seq <= last:
                seen[seq] = shape.cause_key(stop)
    by_cause: dict[str, int] = {}
    for cause in seen.values():
        by_cause[cause] = by_cause.get(cause, 0) + 1
    numbered = last >= first
    none = unavailable("no stop was numbered in the list")
    return {"stop_seq_first": first if numbered else none,
            "stop_seq_last": last if numbered else none, "surveyed": len(seen),
            "by_cause": by_cause, "unaccounted": last - first + 1 - len(seen) if numbered else 0}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    """`rows` as JSON Lines at `path`; ASCII escapes keep a lone surrogate from failing the
    write."""
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="ascii")
    return str(path)


def files(stem: Callable[[], Path], rows: list[dict[str, Any]],
          replies: list[dict[str, Any]]) -> dict[str, Any]:
    """The two files of a list with summaries, named off `stem`; written after the steps ran, so
    a refusing scratch costs the files (the pair or neither), never the account."""
    written: list[Path] = []
    try:
        base = stem()
        paths = [base.with_suffix(".ran.jsonl"), base.with_suffix(".replies.jsonl")]
        for path, lines in zip(paths, (rows, replies), strict=True):
            written.append(path)                     # before the write: one can fail half way
            write_jsonl(path, lines)
        return {"ran_path": str(paths[0]), "replies_path": str(paths[1])}
    except OSError as e:
        for path in written:
            path.unlink(missing_ok=True)
        why = str(e) or f"the scratch refused the files ({type(e).__name__})"
        return {"ran_path": unavailable(why), "replies_path": unavailable(why)}


class SequenceFields(TypedDict, total=False):
    """The fields a sequence's reply names on both servers; `typing_extensions`' class, as
    `reply_schema.ReplyEnvelope`, so one metaclass serves both models."""

    errors: list[Any]
    failed: dict[str, Any]
    field: str
    got: Any
    ran_path: str | dict[str, Any]
    recorded: Any
    replies_path: str | dict[str, Any]
    steps_total: int
    still_running: Annotated[bool, When("else")]
    stopped: Annotated[dict[str, Any], When("`TARGET`")]
    stops: dict[str, Any]
    truncated: bool
    verdict: str


class SequenceRun(TypedDict, total=False):
    """What every reply of a tool that runs a sequence carries, beside `SequenceFields`."""

    failed_at: Required[int | dict[str, Any]]
    held: Required[int]
    ran: Required[list[Any]]
    steps_completed: Required[int]


def looked(channel: str, since: list[str], mark: int, rx: re.Pattern[str],
           limit: int) -> dict[str, Any]:
    """`drive`'s look after its act: the last `limit` matching lines since the mark."""
    kept = [ln for ln in since if rx.search(ln)]
    return {channel: {"available": True, "since_mark": mark, "lines_written": len(since),
                      "lines_total": len(kept), "truncated": len(kept) > limit,
                      "lines": kept[-limit:], "pattern": rx.pattern}}


def check_summaries(summaries: object) -> None:
    """`summaries` is a yes or a no."""
    vocab.check_bool("summaries", summaries)


def summaries_argument(rows_shown: int) -> str:
    """`summaries`' description."""
    return (f"True (of the call, never of a step) makes each step but the last a compact row; "
            f"`ran` shows the first {rows_shown} (`truncated`), `ran_path` and `replies_path` "
            f"hold all; `stops` counts the stops.")


def account(ran: list[dict[str, Any]], summaries: bool, keep_last: bool, since: int,
            recorded_last: int, shape: Shape, stem: Callable[[], Path],
            also: list[dict[str, Any]] | None = None, *, rows_shown: int) -> dict[str, Any]:
    """`ran` as the reply carries it: whole without `summaries`; with it, compact rows (the last
    step whole when `keep_last`), the first `rows_shown` shown, both files, and `stops` since
    `since`.
    The range ends at the newest stop any reply carries, or `recorded_last` if newer: a session
    buried mid-list clears the record, which would hide stops the rows still show."""
    if not summaries:
        return {"ran": ran}
    rows = [brief(r, i, shape) for i, r in enumerate(ran)]
    briefed = len(ran) - 1 if keep_last and ran else len(ran)
    shown = rows[:min(briefed, rows_shown)] + [{"step": i, **ran[i]}
                                               for i in range(briefed, len(ran))]
    replies = [r["reply"] for r in ran] + (also or [])
    last = max([recorded_last] + [int(s["stop_seq"]) for r in replies for s in stops_in(r)])
    return {"ran": shown, "steps_total": len(ran), "truncated": briefed > rows_shown,
            **files(stem, rows, [{"step": i, **r} for i, r in enumerate(ran)]),
            "stops": stops(replies, since + 1, last, shape)}
