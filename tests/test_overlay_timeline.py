"""`scry_core.overlay_timeline`: a call captioned at the instant it begins with nothing queued, a
later call replacing it at once, one of the same tool joining it (`x<n>`) while it is up, a
call's inner calls captioned one by one and the wrapper never, the tint by kind and outcome, the
exit after the hold, and a keycap or a button's mark kept for its minimum time; all with time
passed in."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import abbreviation as ab
from scry_core import overlay_timeline as tl
from scry_core import presence
from scry_core.naming import Named

TINTS = tl.Tints(write=0xFF8C00, read=0x5AC8FA, refused=0xFF453A)
HOLD_S = 3.0


def _captions() -> tl.Captions:
    return tl.Captions(TINTS, HOLD_S)


def _call(c: tl.Captions, tool: str, now: float, end: float | None = None,
          read_only: bool = False, refused: bool = False, **given: Any) -> None:
    c.began(tool, given, read_only, False, now)
    c.ended(refused, now if end is None else end)


def _text(c: tl.Captions, now: float) -> str | None:
    shown = c.shown(now)
    return shown.text if shown is not None else None


def test_a_call_is_captioned_at_once_and_tinted_by_its_kind() -> None:
    c = _captions()
    c.began("run_for", {"seconds": 2}, False, False, 0.0)
    shown = c.shown(0.0)
    assert shown == tl.Caption("run_for(seconds=2)", "write", TINTS.write, 1)
    c.ended(False, 0.5)
    _call(c, "registers", 2.0, read_only=True)
    assert c.shown(2.0) == tl.Caption("registers()", "read", TINTS.read, 2)


def test_a_caption_made_before_is_shown_as_made_and_its_burst_still_joins() -> None:
    c = _captions()
    c.began("run_to", {"ref": "0x10"}, False, False, 0.0, text="run_to Draw_Title (0x10)")
    c.began("run_to", {"ref": "0x20"}, False, False, 0.5, text="run_to Draw_Board (0x20)")
    assert c.shown(0.5) == tl.Caption("run_to Draw_Board (0x20) x2", "write", TINTS.write, 1)


def test_a_call_that_did_not_answer_ok_turns_its_caption_refused() -> None:
    c = _captions()
    _call(c, "write", 0.0, refused=True, ref="0x10", data_hex="00")
    assert c.shown(0.1) == tl.Caption("write(ref=0x10, data_hex=00)", "refused",
                                       TINTS.refused, 1)


def test_a_new_call_replaces_the_shown_caption_at_once_and_nothing_waits() -> None:
    """A call made before the shown caption's time is up is not held back: it is what is shown,
    at the instant its call began."""
    c = _captions()
    _call(c, "run_for", 0.0, seconds=1)
    _call(c, "registers", 0.2, read_only=True)
    _call(c, "disassemble", 0.4, read_only=True, ref="0x100")
    assert c.next_change(0.4) == 0.4 + HOLD_S
    shown = c.shown(0.4)
    assert shown is not None and (shown.text, shown.serial) == ("disassemble(ref=0x100)", 3)


def test_a_burst_of_one_tool_joins_the_caption_with_a_count_and_its_latest_values() -> None:
    c = _captions()
    for i, now in enumerate((0.0, 0.1, 0.2)):
        _call(c, "read_memory", now, read_only=True, ref=f"0x{i}0", length=4)
    shown = c.shown(0.3)
    assert shown is not None and \
        (shown.text, shown.serial) == ("read_memory(ref=0x20, length=4) x3", 1)


def test_one_of_another_tool_breaks_the_burst_and_a_new_caption_is_drawn() -> None:
    c = _captions()
    _call(c, "registers", 0.0, read_only=True)
    _call(c, "read_memory", 0.1, read_only=True, ref="0x10")
    _call(c, "registers", 0.2, read_only=True)
    shown = c.shown(0.2)
    assert shown is not None and (shown.text, shown.serial) == ("registers()", 3)


def test_a_call_s_steps_are_captioned_one_by_one_and_the_wrapper_never() -> None:
    c = _captions()
    c.began("perform", {"steps": [{"op": "send_keys"}]}, False, False, 0.0)
    c.began("send_keys", {"keys": ["A"]}, False, True, 0.1)
    assert _text(c, 0.1) == "send_keys(keys=[A])"
    c.ended(False, 0.2)
    c.began("run_for", {"seconds": 2}, False, True, 0.3)
    assert _text(c, 0.3) == "run_for(seconds=2)"
    c.ended(False, 1.0)
    c.ended(False, 1.1)
    assert _text(c, 1.1) == "run_for(seconds=2)", "the wrapper is not restored when it ends"


def test_two_steps_of_one_wrapper_with_the_same_tool_count_on_the_step() -> None:
    """The count is the step's, twice over, and the wrapper never takes it: it is not shown."""
    c = _captions()
    c.began("perform", {}, False, False, 0.0)
    for now in (0.1, 0.2):
        c.began("send_mouse", {"x": 2}, False, True, now)
        c.ended(False, now)
    c.ended(False, 0.3)
    assert _text(c, 0.3) == "send_mouse(x=2) x2"


def test_a_nested_call_that_was_refused_tints_its_own_caption() -> None:
    c = _captions()
    c.began("perform", {}, False, False, 0.0)
    c.began("write", {}, False, True, 0.1)
    c.ended(True, 0.1)
    shown = c.shown(0.1)
    assert shown is not None and shown.kind == "refused"


def test_a_caption_leaves_its_hold_after_its_call_ended() -> None:
    c = _captions()
    c.began("run_for", {}, False, False, 0.0)
    assert c.next_change(10.0) is None, "a call in flight keeps its caption"
    c.ended(False, 10.0)
    assert c.next_change(10.0) == 10.0 + HOLD_S
    assert _text(c, 10.0 + HOLD_S - 0.01) == "run_for()"
    assert c.shown(10.0 + HOLD_S) is None and c.next_change(20.0) is None
    quick = _captions()
    _call(quick, "status", 0.0, read_only=True)
    assert quick.next_change(0.0) == HOLD_S


def test_the_same_tool_after_its_caption_left_is_a_new_caption() -> None:
    c = _captions()
    _call(c, "step", 0.0)
    _call(c, "step", HOLD_S + 0.1)
    shown = c.shown(HOLD_S + 0.1)
    assert shown is not None and (shown.text, shown.serial) == ("step()", 2)


def test_a_key_released_at_once_is_kept_for_its_minimum_until_the_next_press() -> None:
    k = tl.Keycaps(0.4)
    k.down("Enter", 0.0)
    k.up("Enter", 0.01)
    assert k.shown(0.2) == ("Enter",) and k.next_change(0.2) == 0.4
    k.down("LShift", 0.1)
    assert k.shown(0.2) == ("LShift",) and k.next_change(0.2) is None
    k.up("LShift", 5.0)
    assert k.shown(5.0) == ()


def test_a_mark_let_go_fades_over_the_tail_of_its_stay_and_is_gone_at_its_end() -> None:
    k = tl.Keycaps(1.0, 0.4)
    k.down("Enter", 0.0)
    k.up("Enter", 0.01)
    assert k.marks(0.5) == (("Enter", 1.0),), "the whole mark until the fade begins"
    assert k.marks(0.8)[0][0] == "Enter" and k.marks(0.8)[0][1] == pytest.approx(0.5)
    assert k.next_change(0.8) == 0.8 + 0.4 / tl.FADE_LEVELS
    assert k.marks(1.0) == (), "the mark is gone when its stay ends"


def test_a_new_press_ends_a_mark_that_is_still_fading() -> None:
    k = tl.Keycaps(1.0, 0.4)
    k.down("a", 0.0)
    k.up("a", 0.01)
    assert k.marks(0.9)[0][1] < 1.0, "the mark is fading"
    k.down("b", 0.9)
    assert k.shown(0.9) == ("b",)


def test_a_key_held_past_its_minimum_still_fades_after_it_is_let_go() -> None:
    k = tl.Keycaps(0.4, 0.4)
    k.down("A", 0.0)
    k.up("A", 2.0)
    assert k.shown(1.0) == ("A",), "held, however long"
    assert k.alphas(2.2)[0] == pytest.approx(0.5)
    assert k.shown(2.4) == ()


def test_a_button_s_mark_is_kept_for_its_minimum_like_a_key() -> None:
    """A click's mark is up for `min_s` even when the button was released sooner, so it is seen."""
    k = tl.Keycaps(0.4)
    k.down("LMB", 0.0)
    k.up("LMB", 0.01)
    assert k.shown(0.2) == ("LMB",) and k.next_change(0.2) == 0.4
    assert k.shown(0.4) == ()


def test_a_new_press_clears_the_mark_of_the_key_let_go_before_it() -> None:
    """The caption of the next call is up while the key of the previous one still lingers: the
    new press ends it, so the two never name different calls."""
    k = tl.Keycaps(0.4)
    k.down("left", 0.0)
    k.up("left", 0.01)
    assert k.shown(0.05) == ("left",)
    k.down("right", 0.1)
    assert k.shown(0.1) == ("right",)
    assert k.next_change(0.1) is None


def test_the_key_let_go_last_is_the_one_that_lingers_not_the_last_pressed() -> None:
    """Two keys held together and released in the reverse order of their presses: the mark kept
    is the one let go last, because that is the last thing the overlay saw happen."""
    k = tl.Keycaps(0.4)
    k.down("A", 0.0)
    k.down("B", 0.1)
    k.up("B", 0.2)
    k.up("A", 0.3)
    assert k.shown(0.35) == ("A",)
    assert k.next_change(0.35) == 0.4


def test_a_key_let_go_before_the_last_one_does_not_come_back_when_it_drops() -> None:
    """Two keys let go in turn: only the last keeps its mark, and when its minimum ends none of
    the earlier ones returns."""
    k = tl.Keycaps(0.4)
    k.down("A", 0.0)
    k.down("B", 0.1)
    k.up("B", 0.3)
    k.up("A", 0.35)
    assert k.shown(0.35) == ("A",)
    assert k.next_change(0.35) == 0.40
    assert k.shown(0.40) == ()


def test_the_marks_a_snapshot_holds_are_restored_whole() -> None:
    """A call's marks can be taken back: the set it found comes back as it was, whatever the
    call did to it."""
    k = tl.Keycaps(0.4)
    k.down("A", 0.0)
    saved = k.snapshot()
    k.up("A", 0.1)
    k.down("C", 0.2)
    assert k.shown(0.2) == ("C",)
    k.restore(saved)
    assert k.shown(0.2) == ("A",)


def test_a_burst_shows_every_key_held_and_lets_only_the_last_one_linger() -> None:
    """Eight keys pressed in one call are eight marks while they are held, and after they are
    let go only the most recent is kept for its minimum: a burst does not pile up."""
    k = tl.Keycaps(0.4)
    names = ("f12", "f11", "end", "home", "delete", "insert", "pagedown", "pageup")
    for name in names:
        k.down(name, 0.0)
    assert k.shown(0.1) == names
    for name in names:
        k.up(name, 0.1)
    assert k.shown(0.2) == ("pageup",)
    assert k.next_change(0.2) == 0.4
    assert k.shown(0.4) == ()


def test_a_call_that_ends_with_nothing_open_shows_nothing() -> None:
    c = _captions()
    c.ended(False, 1.0)
    assert c.shown(1.0) is None and c.next_change(1.0) is None


def test_a_key_pressed_while_it_is_already_down_keeps_its_own_time() -> None:
    k = tl.Keycaps(0.4)
    k.down("A", 0.0)
    k.down("A", 0.3)
    k.up("A", 0.35)
    assert k.next_change(0.35) == 0.4


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
    assert _text(c, 0.0) == "read_memory(ref=score (0x9405))"


def test_the_count_a_burst_adds_never_pushes_a_caption_past_the_wire_s_limit() -> None:
    c = _captions()
    long = {f"a{i}": "v" * 20 for i in range(12)}
    c.began("perform", long, False, False, 0.0)
    c.ended(False, 0.1)
    c.began("perform", long, False, False, 0.5)
    text = _text(c, 0.5)
    assert text is not None and text.endswith(" x2") and \
        len(text) == ab.MAX_BYTES and text[:-3].endswith(ab.CUT)


def test_a_click_s_mark_goes_at_its_release_where_a_key_s_lingers() -> None:
    """A click is not a held key: its mark is gone the frame it is let go, while a key keeps the
    look's minimum, so a burst of clicks cannot leave the button lit."""
    caps = tl.Keycaps(presence.LOOK.keycap_min_s)
    caps.down("LMB", 0.0)
    caps.up("LMB", 0.1, linger=False)
    assert caps.snapshot() == {}
    caps.down("right", 0.0)
    caps.up("right", 0.1)
    assert set(caps.snapshot()) == {"right"}
