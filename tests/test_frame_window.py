"""`until_frame`'s window: its arguments, its list, and when it ends."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import frame_window as fw
from scry_core import sequence
from scry_core.progress import no_progress
from scry_core.reply_contract import Invalid

RUN = {"op": "run_for", "frames": 1}


def _stop(frame: Any, seq: int = 1) -> dict[str, Any]:
    return {"stop_seq": seq, "frame": frame}


@pytest.mark.parametrize("value", [-1, True, 1.5, "3"])
def test_a_frame_that_is_no_natural_number_is_refused(value: Any) -> None:
    with pytest.raises(Invalid, match="is a frame number, 0 for none"):
        fw.check_arguments(value, summaries=True)


def test_a_window_needs_summaries_and_none_is_no_window() -> None:
    with pytest.raises(Invalid, match="needs summaries=True"):
        fw.check_arguments(5, summaries=False)
    fw.check_arguments(0, summaries=False)


def test_a_list_with_no_run_for_cannot_reach_a_frame() -> None:
    with pytest.raises(Invalid, match="needs a `run_for` step"):
        fw.check_until([{"op": "registers"}], 9, here=3, running=False)
    fw.check_until([{"op": "registers"}], 0, here=3, running=False)


def test_a_frame_the_stopped_machine_already_passed_is_refused_but_not_a_running_one() -> None:
    with pytest.raises(Invalid, match="stands at frame 9"):
        fw.check_until([RUN], 9, here=9, running=False)
    fw.check_until([RUN], 9, here=9, running=True)
    fw.check_until([RUN], 10, here=9, running=False)
    fw.check_until([RUN], 10, here=None, running=False)


def test_the_window_ends_at_the_first_stop_at_or_past_its_frame() -> None:
    window = fw.Window(12, start=10, blind=False, progress=no_progress)
    assert window.after({"status": "ok"}, 1, "step 1") is False, "no stop, no verdict"
    assert window.after(_stop(11), 2, "step 2") is False
    assert window.after(_stop(13, 2), 3, "step 3") is True
    assert window.short(3) is None
    assert window.fields() == {"until_frame": 12, "frame_reached": 13}


def test_the_newest_frame_of_a_reply_counts_its_stop_on_its_own() -> None:
    reply = {**_stop(4), "stopped_on_its_own": _stop(7, 2)}
    assert fw.frame_of(reply) == 7
    assert fw.frame_of({"status": "ok"}) is None


def test_a_stop_with_no_frame_ends_the_list() -> None:
    window = fw.Window(12, start=10, blind=False, progress=no_progress)
    ended = window.after(_stop({"available": False}), 1, "step 1")
    assert isinstance(ended, sequence.Stop) and ended.code == "unexpected_answer", ended


def test_a_running_machine_whose_first_stop_is_past_walked_nothing() -> None:
    window = fw.Window(12, start=99, blind=True, progress=no_progress)
    assert window.start is None, "a running machine's frame is not known"
    ended = window.after(_stop(15), 1, "step 1")
    assert isinstance(ended, sequence.Stop) and ended.code == "bad_argument", ended


def test_a_window_left_short_is_a_timeout_naming_the_last_frame() -> None:
    window = fw.Window(50, start=None, blind=True, progress=no_progress)
    assert window.after(_stop(20), 1, "step 1") is False
    short = window.short(1)
    assert short is not None and short.fields["verdict"] == "TIMEOUT", short
    assert "the last frame read was 20" in short.fields["note"]
    assert fw.Window(5, None, True, no_progress).fields()["frame_reached"]["available"] is False
