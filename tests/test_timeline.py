"""A run's timeline: the frames each call spanned, the input it fired, and what a reader refuses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scry_core import demo as d
from scry_core import timeline, transcript
from scry_core.verdict import Invalid

#: Calls 1, 3, 9 and 11 of scry-mame's LineUp demo's committed `TRANSCRIPT.md`, verbatim.
RUN = Path(__file__).resolve().parent / "fixtures" / "timeline" / "lineup-calls.md"


def _built(*calls: tuple[str, str, dict[str, Any], str, tuple[int | None, int | None],
                         list[timeline.Event]]) -> timeline.Builder:
    made = timeline.Builder("x")
    for call in calls:
        made.add(*call)
    return made


def test_the_frames_of_a_recorded_run_are_the_ones_its_replies_counted() -> None:
    """Each call of a real run: start (frame 0), a run to a stop (251), a coin held 4 frames
    (261 to 266, set at 261 and let go at 265) and a wait (266 to 267)."""
    made = timeline.Builder("lineup")
    for n, record in enumerate(transcript.records(RUN.read_text(encoding="utf-8"), "lineup")):
        reply = d.Reply(record["reply"])
        events = [timeline.key(reply["name"], True, reply["frame_set"]),
                  timeline.key(reply["name"], False, reply["frame_released"])] \
            if record["tool"] == "input" else []
        made.add(f"step {n}", record["tool"], record["args"], "ok", d.counted(reply), events)
    calls = timeline.loads(made.dumps())["calls"]
    assert [(c["tool"], c["before"], c["after"]) for c in calls] == [
        ("start", None, 0), ("run_to", 0, 251), ("input", 261, 266), ("screen_wait", 266, 267)]
    assert calls[2]["args"] == {"port": ":P1", "field": "Coin 1", "frames": 4}
    assert calls[2]["events"] == [
        {"kind": "key", "name": "Coin 1", "down": True, "frame": 261},
        {"kind": "key", "name": "Coin 1", "down": False, "frame": 265}]


def test_a_symbol_the_agent_gave_reaches_the_timeline_as_given() -> None:
    made = _built(("go", "run_to", {"ref": "Draw_High_Scores_Screen"}, "ok", (None, 10), []))
    assert timeline.loads(made.dumps())["calls"][0]["args"] == {"ref": "Draw_High_Scores_Screen"}


def test_a_call_that_counts_no_frame_stays_where_the_machine_was() -> None:
    made = _built(("a", "start", {}, "ok", (None, None), []),
                  ("b", "run_to", {}, "ok", (None, 40), []),
                  ("c", "read_memory", {}, "ok", (None, None), []),
                  ("d", "close", {}, "ended", (None, None), []))
    assert [(c["before"], c["after"]) for c in timeline.loads(made.dumps())["calls"]] == [
        (None, None), (None, 40), (40, 40), (40, 40)]


def test_an_event_with_no_frame_takes_the_frame_its_call_ended_at() -> None:
    made = _built(("a", "send_mouse", {"x": 1}, "ok", (5, 9), [timeline.pointer(3, 4)]))
    event = timeline.loads(made.dumps())["calls"][0]["events"][0]
    assert event == {"kind": "pointer", "x": 3, "y": 4, "frame": 9}


def test_the_document_is_the_same_bytes_every_time_it_is_written() -> None:
    def one() -> str:
        return _built(("a", "press", {"key": "A"}, "ok", (1, 6),
                       [timeline.button("left", True, 2)])).dumps()

    assert one() == one() and one().endswith("}\n")
    assert list(json.loads(one())) == ["version", "demo", "calls"]


def _document(**call: Any) -> str:
    base: dict[str, Any] = {"n": 1, "step": "a", "tool": "t", "args": {}, "status": "ok",
                            "before": 1, "after": 5, "events": []}
    return json.dumps({"version": timeline.VERSION, "demo": "x", "calls": [{**base, **call}]})


@pytest.mark.parametrize(("text", "why"), [
    ("not json", "is not JSON"),
    (json.dumps({"version": 0, "demo": "x", "calls": []}), "not a version 1 document"),
    (json.dumps({"version": True, "demo": "x", "calls": []}), "not a version 1 document"),
    (json.dumps({"version": 1, "demo": "x"}), "not \\['calls', 'demo', 'version'\\]"),
    (json.dumps({"version": 1, "demo": "x", "calls": [], "more": 1}), "holds \\['calls'"),
    (_document(n=2), "call 1 of the timeline is not numbered 1"),
    (_document(n=1.0), "is not numbered 1"),
    (_document(n=True), "is not numbered 1"),
    (_document(extra=1), "does not hold exactly"),
    (_document(tool=3), "has no `tool` text"),
    (_document(args=[]), "no `args` object or `events` list"),
    (_document(after=None), "began at frame 1 and names no end"),
    (_document(before=-1), "not a frame number or null"),
    (_document(events=[{"kind": "wheel"}]), "an event of kind 'wheel'"),
    (_document(events=[{"kind": "key", "name": "A", "frame": 2}]), "holds \\['frame', 'kind', "
                                                                    "'name'\\]"),
    (_document(events=[{"kind": "key", "name": "A", "down": 1, "frame": 2}]),
     "wrong type for down"),
    (_document(events=[{"kind": "pointer", "x": 1, "y": 2, "frame": 6}]),
     "event is at frame 6, outside the call's 1 to 5"),
    (_document(before=9, after=5, events=[{"kind": "pointer", "x": 1, "y": 2, "frame": 4}]),
     "event is at frame 4, outside the call's 9 to 5"),
    (_document(before=None, after=5, events=[{"kind": "pointer", "x": 1, "y": 2, "frame": 4}]),
     "event is at frame 4, outside the call's None to 5"),
    (_document(events=[{"kind": "pointer", "x": 1, "y": 2, "frame": None}]),
     "has no frame in a call that counted them"),
])
def test_a_document_the_writer_never_writes_is_refused(text: str, why: str) -> None:
    with pytest.raises(Invalid, match=why):
        timeline.loads(text)


def test_a_document_the_writer_writes_is_read_back_whole() -> None:
    text = _document(events=[{"kind": "button", "name": "left", "down": True, "frame": 3}])
    assert timeline.loads(text)["calls"][0]["events"][0]["name"] == "left"


def test_a_state_load_that_rewinds_the_machine_is_a_call_that_ends_before_it_began() -> None:
    """Real replies do it: a `state_write` load in scry-mame's Gridlee demo answers frame 702
    right after a call that counted 1186."""
    made = _built(("look", "screen_view", {}, "ok", (None, 1186), []),
                  ("load", "state_write", {"method": "load"}, "ok", (None, 702), []))
    calls = timeline.loads(made.dumps())["calls"]
    assert (calls[1]["before"], calls[1]["after"]) == (1186, 702)


def test_the_first_call_that_counts_a_frame_may_fire_input_with_no_frame_before_it() -> None:
    made = _built(("a", "start", {}, "ok", (None, None), []),
                  ("b", "point", {}, "ok", (None, 3), [timeline.pointer(1, 2)]))
    event = timeline.loads(made.dumps())["calls"][1]["events"][0]
    assert event["frame"] == 3
