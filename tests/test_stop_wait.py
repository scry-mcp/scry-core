"""A screen wait judged at a declared stop means the same on both servers."""
from __future__ import annotations

import pytest

from scry_core import stop_wait
from scry_core.reply_contract import CODES, Invalid


def test_no_stop_named_is_no_stop_wait() -> None:
    assert stop_wait.check("", "", 0, "") is None
    assert stop_wait.check("", "", 7, "") is None


def test_a_breakpoint_or_a_watch_is_named_by_its_ref() -> None:
    got = stop_wait.check("draw_done", "", 0, "")
    assert got == stop_wait.StopWait("breakpoint", "draw_done", ())
    watch = stop_wait.check("", "0x1234", 0, "")
    assert watch is not None and watch.kind == "watch"


@pytest.mark.parametrize(("bp", "watch", "every", "cond", "said"), [
    ("a", "b", 0, "", "one of"),
    ("a", "", 7, "", "every"),
    ("", "w", 1, "", "every"),
    ("", "", 0, "AX==1", "condition"),
    ("  ", "", 0, "", "empty"),
])
def test_what_cannot_go_together_is_refused_before_anything_runs(
        bp: str, watch: str, every: int, cond: str, said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        stop_wait.check(bp, watch, every, cond)
    assert e.value.code == "bad_argument"


def test_a_condition_is_terms_joined_by_and_on_registers_or_memory() -> None:
    terms = stop_wait.parse_condition("AX==3B && b@0x1234 != 0 && w@level>=0x10")
    assert terms == (stop_wait.Term("AX", 0, "==", 0x3B),
                     stop_wait.Term("0x1234", 1, "!=", 0),
                     stop_wait.Term("level", 2, ">=", 0x10))
    assert stop_wait.parse_condition("") == ()


@pytest.mark.parametrize("text", ["AX=1", "AX==", "==1", "AX==1 || BX==2", "q@1==1",
                                  "AX==1 && BX==1 && CX==1 && DX==1 && SI==1", "AX==zz"])
def test_a_condition_outside_the_grammar_is_refused(text: str) -> None:
    with pytest.raises(Invalid) as e:
        stop_wait.parse_condition(text)
    assert e.value.code == "bad_argument"


def test_a_condition_holds_only_when_every_term_does() -> None:
    terms = stop_wait.parse_condition("AX==3B && b@10>1")
    regs = {"AX": 0x3B}
    mem = {("10", 1): 2}
    assert stop_wait.holds(terms, regs.__getitem__, lambda ref, size: mem[(ref, size)])
    mem[("10", 1)] = 1
    assert not stop_wait.holds(terms, regs.__getitem__, lambda ref, size: mem[(ref, size)])
    assert stop_wait.holds((), regs.__getitem__, lambda ref, size: 0)


def test_changed_ends_on_a_named_screen_other_than_the_first() -> None:
    judge = stop_wait.Changed({"matched": True, "screen": "title"})
    assert not judge.judge({"matched": True, "screen": "title"})
    assert not judge.judge({"matched": False, "screens_tried": 3, "screens_unjudged": 0})
    assert judge.judge({"matched": True, "screen": "menu"})
    assert judge.started_on == "title"


def test_changed_from_a_screen_the_map_did_not_name_ends_on_any_named_one() -> None:
    judge = stop_wait.Changed({"matched": False, "screens_tried": 2, "screens_unjudged": 0})
    assert judge.started_on is None
    assert judge.judge({"matched": True, "screen": "title"})


@pytest.mark.parametrize("found", [
    {"matched": False, "screens_tried": 0, "screens_unjudged": 2},
    {"matched": False, "view_fits": False},
])
def test_a_frame_the_map_cannot_judge_is_refused_not_passed_over(found: dict[str, object]) -> None:
    with pytest.raises(Invalid) as e:
        stop_wait.Changed({"matched": True, "screen": "title"}).judge(found)
    assert e.value.code == "no_channel"


def test_never_fired_is_a_code_both_servers_share() -> None:
    assert "never_fired" in CODES
    spec = stop_wait.StopWait("breakpoint", "draw_done", ())
    e = stop_wait.never_fired(spec, 5.0)
    assert e.code == "never_fired" and "draw_done" in str(e) and "5 s" in str(e)
    assert e.fields["waited_on"] == {"kind": "breakpoint", "ref": "draw_done"}


def test_the_reply_names_the_row_and_counts_firings_and_frames() -> None:
    spec = stop_wait.check("", "0x1234", 0, "AX==1")
    assert spec is not None
    got = stop_wait.fields(spec, firings=4, examined=2, fired_line=120)
    assert got == {"waited_on": {"kind": "watch", "ref": "0x1234", "condition": "AX==1"},
                   "firings": 4, "frames_examined": 2, "fired_line": 120}


def test_a_summary_counts_firings_under_on_and_nothing_else() -> None:
    spec = stop_wait.check("draw_done", "", 0, "")
    assert spec is not None
    reply = stop_wait.fields(spec, firings=3, examined=1, fired_line=0)
    assert stop_wait.summary_after(reply) == "after 3 firings of breakpoint 'draw_done'"
    assert stop_wait.summary_after({"polls": 4}) is None
