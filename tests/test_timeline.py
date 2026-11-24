"""A run's timeline: the frames each call spanned, the input it fired, and what a reader refuses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scry_core import demo as d
from scry_core import timeline, transcript
from scry_core.naming import Named
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


def test_a_call_carries_its_caption_tinted_by_what_the_tool_does_and_how_it_answered() -> None:
    made = timeline.Builder("x")
    made.add("a", "run_to", {"ref": "Draw_Title", "dest": "/tmp/run/a.png"}, "ok", (1, 9))
    made.add("b", "read_memory", {"ref": "0x10", "length": 4}, "ok", (9, 9), read_only=True)
    made.add("c", "read_memory", {}, "INVALID", (9, 9), read_only=True)
    made.add("d", "close", {}, "ended", (None, None))
    assert [c["caption"] for c in timeline.loads(made.dumps())["calls"]] == [
        {"text": "run_to(ref=Draw_Title, dest=a.png)", "tint": "write"},
        {"text": "read_memory(ref=0x10, length=4)", "tint": "read"},
        {"text": "read_memory()", "tint": "refused"},
        {"text": "close()", "tint": "refused"}]


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


def test_a_wrapper_is_one_entry_per_call_it_ran_at_that_call_s_own_frames() -> None:
    """A `perform` of three calls is three entries in order, each captioned as itself at the
    frames it ran for; the wrapper is not an entry at all."""
    made = timeline.Builder("x")
    steps = [{"op": "run_for", "seconds": 2}, {"op": "read_memory", "ref": "0x10"},
             {"op": "send_keys", "keys": ["Enter"]}]
    rows = [{"op": "run_for", "frame_before": 10, "frame_after": 20,
             "reply": {"status": "ok"}},
            {"op": "read_memory", "frame_before": 20, "frame_after": 20,
             "reply": {"status": "ok"}},
            {"op": "send_keys", "frame_before": 20, "frame_after": 24,
             "reply": {"status": "INVALID"}}]
    made.add("go", "perform", {"steps": steps}, "ok", (10, 24), rows=rows,
             readers=("read_memory",))
    calls = timeline.loads(made.dumps())["calls"]
    assert [(c["tool"], c["before"], c["after"]) for c in calls] == [
        ("run_for", 10, 20), ("read_memory", 20, 20), ("send_keys", 20, 24)]
    assert [c["caption"] for c in calls] == [
        {"text": "run_for(seconds=2)", "tint": "write"},
        {"text": "read_memory(ref=0x10)", "tint": "read"},
        {"text": "send_keys(keys=[Enter])", "tint": "refused"}]
    assert [c["args"] for c in calls] == [
        {"seconds": 2}, {"ref": "0x10"}, {"keys": ["Enter"]}]


def test_a_wrapper_s_row_that_counted_no_frame_is_still_the_entry_not_the_wrapper() -> None:
    """A step sent while the machine ran answers no frame: the step is still the entry, placed
    where the machine was, because a wrapper is never what the timeline shows."""
    made = timeline.Builder("x")
    rows = [{"op": "resume", "frame_before": None, "frame_after": None,
             "reply": {"status": "ok"}},
            {"op": "status", "frame_before": None, "frame_after": None,
             "reply": {"status": "ok"}}]
    made.add("go", "drive", {"act": [{"op": "resume"}, {"op": "status"}]}, "ok", (None, 7),
             rows=rows, events=[timeline.pointer(1, 1)])
    calls = timeline.loads(made.dumps())["calls"]
    assert [c["tool"] for c in calls] == ["resume", "status"]
    assert [(c["before"], c["after"]) for c in calls] == [(None, None), (None, None)]
    assert [c["events"] for c in calls] == [[], [{"kind": "pointer", "x": 1, "y": 1,
                                                  "frame": None}]]


def test_a_wrapper_whose_reply_names_no_row_stays_one_entry() -> None:
    made = _built(("go", "perform", {"steps": [{"op": "run_for"}]}, "ok", (3, 9), []))
    assert [c["tool"] for c in timeline.loads(made.dumps())["calls"]] == ["perform"]


def test_a_wrapper_s_events_go_to_the_row_whose_frames_hold_them() -> None:
    """Input a wrapper fired is the input of the step it fell inside, and one that names no
    frame stays with the last row that counted frames."""
    made = timeline.Builder("x")
    rows = [{"op": "send_mouse", "frame_before": 10, "frame_after": 14,
             "reply": {"status": "ok"}},
            {"op": "send_mouse", "frame_before": 14, "frame_after": 20,
             "reply": {"status": "ok"}}]
    events = [timeline.pointer(1, 1, 12), timeline.pointer(2, 2, 18), timeline.pointer(3, 3)]
    made.add("go", "perform", {"steps": [{"op": "send_mouse", "x": 1},
                                          {"op": "send_mouse", "x": 2}]}, "ok", (10, 20),
             events, rows=rows)
    calls = timeline.loads(made.dumps())["calls"]
    assert [[e["x"] for e in c["events"]] for c in calls] == [[1], [2, 3]]
    assert [c["events"][-1]["frame"] for c in calls] == [12, 20]
    assert [c["args"] for c in calls] == [{"x": 1}, {"x": 2}]


def test_a_wrapper_whose_arguments_name_no_step_still_places_its_rows() -> None:
    """A reply can name its rows where the arguments name no step: each row is still an entry,
    with no arguments of its own."""
    made = timeline.Builder("x")
    rows = [{"op": "run_for", "frame_before": 1, "frame_after": 5, "reply": {"status": "ok"}}]
    made.add("go", "perform", {}, "ok", (1, 5), rows=rows)
    calls = timeline.loads(made.dumps())["calls"]
    assert [(c["tool"], c["args"]) for c in calls] == [("run_for", {})]


def test_a_wrapper_s_row_with_no_op_or_reply_is_refused() -> None:
    made = timeline.Builder("x")
    with pytest.raises(Invalid, match="step 1 of the `perform` in the run's timeline names no"):
        made.add("go", "perform", {}, "ok", (1, 5), rows=[{"frame_before": 1,
                                                           "frame_after": 5}])


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
                            "caption": {"text": "t", "tint": "write"}, "before": 1, "after": 5,
                            "events": []}
    return json.dumps({"version": timeline.VERSION, "demo": "x", "calls": [{**base, **call}]})


@pytest.mark.parametrize(("text", "why"), [
    ("not json", "is not JSON"),
    (json.dumps({"version": 1, "demo": "x", "calls": []}), "not a version 2 document"),
    (json.dumps({"version": True, "demo": "x", "calls": []}), "not a version 2 document"),
    (json.dumps({"version": 2, "demo": "x"}), "not \\['calls', 'demo', 'version'\\]"),
    (json.dumps({"version": 2, "demo": "x", "calls": [], "more": 1}), "holds \\['calls'"),
    (_document(n=2), "call 1 of the timeline is not numbered 1"),
    (_document(n=1.0), "is not numbered 1"),
    (_document(n=True), "is not numbered 1"),
    (_document(extra=1), "does not hold exactly"),
    (_document(tool=3), "has no `tool` text"),
    (_document(args=[]), "no `args` object or `events` list"),
    (_document(caption="t"), "caption is not a `text` and a `tint`"),
    (_document(caption={"text": "t", "tint": "blue"}), "caption is not a `text` and a `tint`"),
    (_document(caption={"text": 3, "tint": "read"}), "caption is not a `text` and a `tint`"),
    (_document(caption={"text": "t"}), "caption is not a `text` and a `tint`"),
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


def test_a_caption_names_what_the_calls_reply_called_its_arguments() -> None:
    made = timeline.Builder("x")
    made.add("look", "read_memory", {"ref": "score", "length": 2}, "ok", (1, 2), read_only=True,
             named={"ref": Named("symbol", "score", "0x9405")})
    made.add("bare", "read_memory", {"ref": "score"}, "ok", (2, 3))
    first, second = timeline.loads(made.dumps())["calls"]
    assert first["caption"] == {"text": "read_memory(ref=score (0x9405), length=2)", "tint": "read"}
    assert second["caption"]["text"] == "read_memory(ref=score)"
