"""`scry_core.overlay_timeline`: a caption's minimum time, the latest call waiting, a burst of one
tool and a call's steps joined into one caption with a count, the tint by kind and outcome, the
exit after the hold, and a keycap kept for its minimum time; all with time passed in."""

from __future__ import annotations

from typing import Any

from scry_core import abbreviation as ab
from scry_core import overlay_timeline as tl
from scry_core.naming import Named

TINTS = tl.Tints(write=0xFF8C00, read=0x5AC8FA, refused=0xFF453A)
MIN_S, HOLD_S = 1.0, 3.0


def _captions() -> tl.Captions:
    return tl.Captions(TINTS, MIN_S, HOLD_S)


def _call(c: tl.Captions, tool: str, now: float, end: float | None = None,
          read_only: bool = False, refused: bool = False, **given: Any) -> None:
    c.began(tool, given, read_only, False, now)
    c.ended(False, refused, now if end is None else end)


def _text(c: tl.Captions, now: float) -> str | None:
    shown = c.shown(now)
    return shown.text if shown is not None else None


def test_a_call_is_captioned_at_once_and_tinted_by_its_kind() -> None:
    c = _captions()
    c.began("run_for", {"seconds": 2}, False, False, 0.0)
    shown = c.shown(0.0)
    assert shown == tl.Caption("run_for 2", "write", TINTS.write, 1)
    c.ended(False, False, 0.5)
    _call(c, "registers", 2.0, read_only=True)
    assert c.shown(2.0) == tl.Caption("registers", "read", TINTS.read, 2)


def test_a_caption_made_before_is_shown_as_made_and_its_burst_still_joins() -> None:
    c = tl.Captions(TINTS, 1.0, 3.0)
    c.began("run_to", {"ref": "0x10"}, False, False, 0.0, text="run_to Draw_Title (0x10)")
    c.began("run_to", {"ref": "0x20"}, False, False, 0.5, text="run_to Draw_Board (0x20)")
    assert c.shown(0.5) == tl.Caption("run_to Draw_Board (0x20) x2", "write", TINTS.write, 1)


def test_a_call_that_did_not_answer_ok_turns_its_caption_refused() -> None:
    c = _captions()
    _call(c, "write", 0.0, refused=True, ref="0x10", data_hex="00")
    assert c.shown(0.1) == tl.Caption("write 0x10 00", "refused", TINTS.refused, 1)


def test_a_caption_stays_its_minimum_and_only_the_latest_call_waits() -> None:
    c = _captions()
    _call(c, "run_for", 0.0, seconds=1)
    _call(c, "registers", 0.2, read_only=True)
    _call(c, "disassemble", 0.4, read_only=True, ref="0x100")
    assert _text(c, 0.9) == "run_for 1"
    assert c.next_change(0.9) == MIN_S
    shown = c.shown(MIN_S)
    assert shown is not None and (shown.text, shown.serial) == ("disassemble 0x100", 2)


def test_a_burst_of_one_tool_joins_the_caption_with_a_count_and_its_latest_values() -> None:
    c = _captions()
    for i, now in enumerate((0.0, 0.1, 0.2)):
        _call(c, "read_memory", now, read_only=True, ref=f"0x{i}0", length=4)
    shown = c.shown(0.3)
    assert shown is not None and (shown.text, shown.serial) == ("read_memory 0x20 4 x3", 1)


def test_a_burst_joins_the_waiting_caption_when_one_waits() -> None:
    c = _captions()
    _call(c, "run_for", 0.0, seconds=1)
    _call(c, "registers", 0.1, read_only=True)
    _call(c, "registers", 0.2, read_only=True)
    assert _text(c, 0.5) == "run_for 1"
    assert _text(c, MIN_S) == "registers x2"


def test_a_call_s_steps_join_its_caption_as_a_count() -> None:
    c = _captions()
    c.began("perform", {"steps": [{"tool": "run_for"}]}, False, False, 0.0)
    for _ in range(3):
        c.began("send_keys", {"keys": ["A"]}, False, True, 0.1)
        c.ended(True, False, 0.1)
    c.ended(False, False, 0.2)
    assert _text(c, 0.3) == "perform: run_for"


def test_a_step_that_was_refused_leaves_its_caller_s_tint_to_its_caller() -> None:
    c = _captions()
    c.began("perform", {}, False, False, 0.0)
    c.began("write", {}, False, True, 0.1)
    c.ended(True, True, 0.1)
    c.ended(False, False, 0.2)
    shown = c.shown(0.3)
    assert shown is not None and shown.kind == "write"


def test_a_caption_leaves_its_hold_after_its_call_ended_and_never_before_its_minimum() -> None:
    c = _captions()
    c.began("run_for", {}, False, False, 0.0)
    assert c.next_change(10.0) is None, "a call in flight keeps its caption"
    c.ended(False, False, 10.0)
    assert c.next_change(10.0) == 10.0 + HOLD_S
    assert _text(c, 10.0 + HOLD_S - 0.01) == "run_for"
    assert c.shown(10.0 + HOLD_S) is None and c.next_change(20.0) is None
    quick = _captions()
    _call(quick, "status", 0.0, read_only=True)
    assert quick.next_change(0.0) == HOLD_S


def test_the_same_tool_after_the_minimum_is_a_new_caption() -> None:
    c = _captions()
    _call(c, "step", 0.0)
    _call(c, "step", 1.5)
    shown = c.shown(1.5)
    assert shown is not None and (shown.text, shown.serial) == ("step", 2)


def test_a_key_released_at_once_is_kept_for_its_minimum_and_one_held_until_released() -> None:
    k = tl.Keycaps(0.4)
    k.down("Enter", 0.0)
    k.up("Enter", 0.01)
    k.down("LShift", 0.1)
    assert k.shown(0.2) == ("Enter", "LShift")
    assert k.next_change(0.2) == 0.4
    assert k.shown(0.4) == ("LShift",) and k.next_change(0.4) is None
    k.up("LShift", 5.0)
    assert k.shown(5.0) == ()


def test_a_key_pressed_again_goes_to_the_end_and_its_time_starts_again() -> None:
    k = tl.Keycaps(0.4)
    k.down("A", 0.0)
    k.up("A", 0.0)
    k.down("B", 0.1)
    k.down("A", 0.3)
    assert k.shown(0.5) == ("B", "A")
    k.up("A", 0.5)
    assert k.next_change(0.5) == 0.7
    k.up("missing", 0.5)
    assert k.shown(0.5) == ("B", "A")


def test_a_call_s_names_reach_its_caption() -> None:
    c = _captions()
    c.began("read_memory", {"ref": "score"}, True, False, 0.0,
            named={"ref": Named("symbol", "score", "0x9405")})
    assert _text(c, 0.0) == "read_memory score (0x9405)"


def test_the_count_a_burst_and_its_steps_add_never_pushes_a_caption_past_the_wire_s_limit(
        ) -> None:
    c = _captions()
    long = {f"a{i}": "v" * 20 for i in range(12)}
    c.began("perform", long, False, False, 0.0)
    for _ in range(12):
        c.began("step", {}, False, True, 0.0)
    c.began("perform", long, False, False, 0.5)
    text = _text(c, 0.5)
    assert text is not None and text.endswith(" x2 (12 steps)") and \
        len(text) == ab.MAX_BYTES and "v.. x2" in text
