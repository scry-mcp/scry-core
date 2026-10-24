"""The account of a list of steps run in one call, the one `perform` and `drive` hand back with
`summaries`: every step but the one that matters cut to a compact row, the first rows shown and
every row and every full reply written to two JSON Lines files, and the machine's own count of
the stops it numbered while the list ran.

WHY: a series of captures a frame apart is a run and a capture per frame, and each run carries
registers, a listing and the watches, so the reply crossed the client's ceiling and had to be
saved and queried for the few fields that mattered; cut to a summary line, it lost every stop's
cause, and the count a reader then assembled was the number that came out wrong.

What a stop keeps in its compact row and the key its `cause` is counted under are each server's
own: both are handed in as a `Shape`.

Beside it, the rest a sequence's reply shares on both servers: the fields its model names
(`SequenceFields`), `summaries`' own description (`summaries_argument`) and its one check
(`check_summaries`), and the LOOK `drive` takes after its act (`looked`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typing_extensions import TypedDict

from scry_core import vocabulary as vocab
from scry_core.reply_contract import unavailable


def _nothing(reply: dict[str, Any], cut: dict[str, Any]) -> None:
    """A stop that keeps nothing beyond its `kept` keys."""


@dataclass(frozen=True)
class Shape:
    """A server's half of the account: the keys a stop's compact row keeps besides its summary
    line (`kept`), what else it keeps from the reply (`extra`, writing into the row), and the
    key a stop is counted under (`cause_key`: its `cause` with what varies from one stop to the
    next, an address or a writer's pc, taken off)."""
    kept: tuple[str, ...]
    cause_key: Callable[[dict[str, Any]], str]
    extra: Callable[[dict[str, Any], dict[str, Any]], None] = field(default=_nothing)


def is_stop(reply: dict[str, Any]) -> bool:
    """Whether `reply` is a stop's: every one carries the number its survey gave it."""
    return isinstance(reply.get("stop_seq"), int)


def stops_in(reply: dict[str, Any]) -> list[dict[str, Any]]:
    """Every stop `reply` surveys: its own, and the one the machine reached on its own that
    this contact found and recorded (`stopped_on_its_own`), which carries its number too."""
    found = reply.get("stopped_on_its_own")
    return [r for r in (reply, found) if isinstance(r, dict) and is_stop(r)]


def brief(entry: dict[str, Any], step: int, shape: Shape) -> dict[str, Any]:
    """A step's COMPACT ROW: its index in the list, the entry's own fields beside its reply (the
    op, and a server's others), and the reply cut to the line the client paints and its `status`;
    a stop keeps what makes it one."""
    reply = entry["reply"]
    cut = {"summary": reply.get("summary"), "status": reply.get("status")}
    if is_stop(reply):
        cut.update({k: reply.get(k) for k in shape.kept})
        shape.extra(reply, cut)
    if "stopped_on_its_own" in reply:
        cut["stopped_on_its_own"] = reply["stopped_on_its_own"]
    return {"step": step, **{k: v for k, v in entry.items() if k != "reply"}, "reply": cut}


def stops(replies: list[dict[str, Any]], first: int, last: int, shape: Shape) -> dict[str, Any]:
    """THE MACHINE'S COUNT OF THE STOPS it numbered from `first` to `last`: the range, the stops
    the replies surveyed in it, a count per cause, and `unaccounted`, the stops numbered in the
    range that no reply surveyed (a stop a refusing reader took is real, so it is reported and
    never refused)."""
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
    """`rows` as JSON Lines at `path`, one row a line, and the path as a reply names it. JSON's
    own escapes keep every row ASCII, so a lone surrogate a caller typed lands as `\\ud800`
    rather than failing the encoding half-way through the file."""
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="ascii")
    return str(path)


def files(stem: Callable[[], Path], rows: list[dict[str, Any]],
          replies: list[dict[str, Any]]) -> dict[str, Any]:
    """The two files of a list with summaries, named off `stem`. They are written after every
    step ran, so the machine has already moved: a scratch that refuses them costs the files,
    said where each path would be, and never the account beside them. The pair or neither."""
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
    """The fields a sequence's reply names on both servers (`perform`'s, and `drive`'s `act`),
    beside each server's envelope and its own. `typing_extensions`' class, as the envelope's
    (`reply_schema.ReplyEnvelope`): a reply model is built on both and one metaclass serves
    them."""

    errors: list[Any]
    failed: dict[str, Any]
    failed_at: int | dict[str, Any]
    field: str
    got: Any
    held: int
    note: str
    ran: list[Any]
    ran_path: str | dict[str, Any]
    recorded: Any
    replies_path: str | dict[str, Any]
    steps_completed: int
    steps_total: int
    still_running: bool
    stopped: dict[str, Any]
    stops: dict[str, Any]
    truncated: bool
    verdict: str


def looked(channel: str, since: list[str], mark: int, rx: re.Pattern[str],
           limit: int) -> dict[str, Any]:
    """`drive`'s LOOK after its act: `channel`'s lines since the mark matching `rx`, cut to the
    last `limit`, with the counts that say what was cut, in `log`'s own words."""
    kept = [ln for ln in since if rx.search(ln)]
    return {channel: {"available": True, "since_mark": mark, "lines_written": len(since),
                      "lines_total": len(kept), "truncated": len(kept) > limit,
                      "lines": kept[-limit:], "pattern": rx.pattern}}


def check_summaries(summaries: object) -> None:
    """`summaries` is a yes or a no, in the one sentence both batch tools of both servers use."""
    vocab.check_bool("summaries", summaries)


def summaries_argument(rows_shown: int) -> str:
    """`summaries`' own description on both servers' `perform` and `drive`, the argument's
    half of what `account` does with it."""
    return (f"True (of the call, never of a step) makes each step but the last a compact row; "
            f"`ran` shows the first {rows_shown} (`truncated`), `ran_path` and `replies_path` "
            f"hold all.")


def account(ran: list[dict[str, Any]], summaries: bool, keep_last: bool, since: int,
            recorded_last: int, shape: Shape, stem: Callable[[], Path],
            also: list[dict[str, Any]] | None = None, *, rows_shown: int) -> dict[str, Any]:
    """`ran` as the reply carries it: whole without `summaries`; with it, every step cut to its
    compact row but the last one that ran when `keep_last`, the first `rows_shown` rows shown
    (the server's own ceiling for a table)
    with `steps_total` and `truncated`, every row and every full reply in the two files, and
    `stops`, the count of the stops numbered since `since`, read off the steps' replies and
    `also`'s (the step that failed, the stop the tail waited for). The range ends at the newest
    stop any reply carries, or at `recorded_last`, the session's own record, if that is newer:
    a session buried mid-list clears the record, and a range read off it alone would hide the
    stops the rows above still show."""
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
