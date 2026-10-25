"""`since_mark` and `mark` wording, bound and refusals shared by both servers, and the stop reply's
log block."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scry_core.reply_contract import Invalid

SINCE_MARK_DOC = ("`since_mark`, a byte position in the channel's log (the `mark` a "
                  "state load or a stop's log block gives for it): only what was written after "
                  "it is read; 0, the default, reads the whole log")
MARK_DOC = ("`mark` (where each log channel ended as the load was sent: `log`/`log_wait`'s "
            "`since_mark` for that channel reads what came after it; a position in the file, "
            "not a moment, so a line written before the load and not yet flushed lands after)")
DOC_VALUES = {"SINCE_MARK": SINCE_MARK_DOC, "MARK": MARK_DOC}
SINCE_MARK_BOUND: Any = Field(json_schema_extra={"minimum": 0})


def check_position(since_mark: int, channel: str) -> None:
    """Refuse a non-position without reading the log (a bool is not one)."""
    if isinstance(since_mark, bool) or since_mark < 0:
        raise Invalid("bad_argument",
                      f"since_mark={since_mark} is a byte position in the log, 0 or more: the "
                      f"`mark` a state load or a stop's log block gives for the {channel} "
                      f"channel")


def check_since_mark(since_mark: int, end: int, channel: str) -> None:
    """Refuse a `since_mark` that is negative or past `end`, the log's length now (0 if absent)."""
    check_position(since_mark, channel)
    if since_mark > end:
        raise Invalid("bad_argument",
                      f"since_mark={since_mark} is past where the {channel} log ends now ({end} "
                      f"bytes): a mark is where the log ended when it was taken, so it is never "
                      f"past the end. One from another session, or a log rewritten shorter, "
                      f"names nothing here")


STOP_LINES_SHOWN = 8
#: The last lines are where a fatal error lands; a whole boot log is not.
TAIL_CHARS = 1500


def stop_block(lines: list[str], mark: int, channel: str, limit_max: int) -> dict[str, Any]:
    """What `channel`'s log gained since the previous stop; a cut block's `how` is the `log` call
    that reads the rest, capped at `limit_max`."""
    cut = len(lines) > STOP_LINES_SHOWN
    block: dict[str, Any] = {"lines_total": len(lines), "truncated": cut,
                             "lines": lines[-STOP_LINES_SHOWN:], "mark": mark}
    if cut:
        limit = min(len(lines), limit_max)
        block["how"] = (f'`log(pattern=".", channel="{channel}", since_mark={mark}, '
                        f'limit={limit})` reads ' + ("them all" if limit == len(lines)
                                                     else f"the newest {limit}"))
    return block
