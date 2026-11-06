"""`since_mark` names a position of the log as it stands: 0 and the end itself are taken, a
negative one and one past the end are refused naming the channel."""

from __future__ import annotations

from pathlib import Path

import pytest

from scry_core import log_marks
from scry_core.log_marks import check_since_mark
from scry_core.reply_contract import Invalid


@pytest.mark.parametrize("mark", [0, 1, 99, 100])
def test_a_mark_from_zero_to_the_end_is_taken(mark: int) -> None:
    check_since_mark(mark, 100, "guest")


def test_a_negative_mark_is_refused() -> None:
    with pytest.raises(Invalid) as e:
        check_since_mark(-1, 100, "guest")
    assert e.value.code == "bad_argument" and "0 or more" in str(e.value)


@pytest.mark.parametrize(("mark", "end"), [(101, 100), (1, 0)])
def test_a_mark_past_the_end_is_refused_naming_the_channel_and_its_end(mark: int,
                                                                        end: int) -> None:
    with pytest.raises(Invalid) as e:
        check_since_mark(mark, end, "emulator")
    assert e.value.code == "bad_argument"
    assert f"past where the emulator log ends now ({end} bytes)" in str(e.value)


def test_the_descriptions_both_servers_fill_name_the_argument_and_the_mark() -> None:
    from scry_core.log_marks import DOC_VALUES
    assert set(DOC_VALUES) == {"SINCE_MARK", "MARK"}
    assert "`since_mark`" in DOC_VALUES["SINCE_MARK"] and "`mark`" in DOC_VALUES["MARK"]
    assert "0, the default, reads the whole log" in DOC_VALUES["SINCE_MARK"], "the caller's cue"
    assert "only what was written after it" in DOC_VALUES["SINCE_MARK"]


def test_a_bool_is_no_position() -> None:
    with pytest.raises(Invalid, match="0 or more"):
        check_since_mark(True, 100, "guest")


def test_a_stops_block_shows_the_newest_lines_and_the_mark_they_start_at() -> None:
    """At the cut and one past it: whole up to `STOP_LINES_SHOWN`, then the newest ones with
    `truncated` and a `how` that names the channel and the mark."""
    n = log_marks.STOP_LINES_SHOWN
    whole = log_marks.stop_block([f"l{i}" for i in range(n)], 120, "guest", 400)
    assert whole == {"lines_total": n, "truncated": False,
                     "lines": [f"l{i}" for i in range(n)], "mark": 120}
    cut = log_marks.stop_block([f"l{i}" for i in range(n + 1)], 120, "guest", 400)
    assert cut["truncated"] and cut["lines"] == [f"l{i}" for i in range(1, n + 1)]
    assert cut["how"] == (f'`log(pattern=".", channel="guest", since_mark=120, limit={n + 1})` '
                          "reads them all")
    many = log_marks.stop_block(["x"] * 401, 0, "guest", 400)
    assert many["how"].endswith("limit=400)` reads the newest 400"), many["how"]
    assert log_marks.stop_block([], 0, "emulator", 400) == {"lines_total": 0, "truncated": False,
                                                            "lines": [], "mark": 0}


def test_a_logs_tail_is_its_last_characters_and_a_short_log_is_whole(tmp_path: Path) -> None:
    short = tmp_path / "short.log"
    short.write_bytes(b"boot\nfatal\n")     # the tail is bytes: text mode would write \r\n here
    assert log_marks.tail(short) == "boot\nfatal\n"
    long = tmp_path / "long.log"
    long.write_text("a" * 5000 + "é" * 2000 + "end", encoding="utf-8")
    assert log_marks.tail(long) == ("é" * 2000 + "end")[-log_marks.TAIL_CHARS:]
    assert log_marks.tail(long, 10) == "ééééééé" + "end"


def test_a_log_that_cannot_be_read_raises_for_its_caller_to_say_why(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        log_marks.tail(tmp_path / "missing.log")
