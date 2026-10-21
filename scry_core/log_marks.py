"""`since_mark`, the position `log` and `log_wait` read after, and the `mark` `state_load` answers:
the descriptions, the schema bound and the refusals both servers give in the same words; and the
log block every stop reply carries, which hands over the mark its lines start at."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scry_core.reply_contract import Invalid

#: The argument's description, said once for both servers' tools.
SINCE_MARK_DOC = ("`since_mark`, a byte position in the channel's log (the `mark` a "
                  "`state_load` or a stop's log block gives for it): only what was written after "
                  "it is read; 0, the default, reads the whole log")
#: `state_load`'s `mark`, said once for both servers' descriptions.
MARK_DOC = ("`mark` (where each log channel ended as the load was sent: `log`/`log_wait`'s "
            "`since_mark` for that channel reads what came after it; a position in the file, "
            "not a moment, so a line written before the load and not yet flushed lands after)")
#: The descriptions' placeholders, filled by each server's `docs`.
DOC_VALUES = {"SINCE_MARK": SINCE_MARK_DOC, "MARK": MARK_DOC}
#: Its schema half: a position is never negative; the end it may not pass is the log's, now.
SINCE_MARK_BOUND: Any = Field(json_schema_extra={"minimum": 0})


def check_position(since_mark: int, channel: str) -> None:
    """The half that needs no log, run before anything is read: a position is a whole number, 0
    or more (a bool is no position, though Python counts it as one)."""
    if isinstance(since_mark, bool) or since_mark < 0:
        raise Invalid("bad_argument",
                      f"since_mark={since_mark} is a byte position in the log, 0 or more: the "
                      f"`mark` a `state_load` or a stop's log block gives for the {channel} "
                      f"channel")


def check_since_mark(since_mark: int, end: int, channel: str) -> None:
    """Refuse a `since_mark` that names no position of the `channel` log as it stands, `end`
    bytes long (0 when it does not exist yet): a negative one, and one past its end, which no
    mark of this session can be."""
    check_position(since_mark, channel)
    if since_mark > end:
        raise Invalid("bad_argument",
                      f"since_mark={since_mark} is past where the {channel} log ends now ({end} "
                      f"bytes): a mark is where the log ended when it was taken, so it is never "
                      f"past the end. One from another session, or a log rewritten shorter, "
                      f"names nothing here")


#: How many of the newest lines a stop's log block shows: its count is always whole.
STOP_LINES_SHOWN = 8


def stop_block(lines: list[str], mark: int, channel: str, limit_max: int) -> dict[str, Any]:
    """What `channel`'s log gained since the previous stop, as every stop reply shows it: the
    count, whether the newest `STOP_LINES_SHOWN` cut it, those lines, and `mark`, the byte
    position they start at, which `since_mark` takes. A cut block's `how` is the `log` call, as
    it can be sent, that reads them: all of them, or the newest `limit_max` (`log`'s ceiling)
    when there are more."""
    cut = len(lines) > STOP_LINES_SHOWN
    block: dict[str, Any] = {"lines_total": len(lines), "truncated": cut,
                             "lines": lines[-STOP_LINES_SHOWN:], "mark": mark}
    if cut:
        limit = min(len(lines), limit_max)
        block["how"] = (f'`log(pattern=".", channel="{channel}", since_mark={mark}, '
                        f'limit={limit})` reads ' + ("them all" if limit == len(lines)
                                                     else f"the newest {limit}"))
    return block
