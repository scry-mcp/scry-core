"""The omission note and the section list, on known answers: a short reply names what it left
out and how to ask, a whole one says nothing, and a section list is refused before anything is
read when it names nothing or names what is not there."""

from __future__ import annotations

import pytest

from scry_core import narrowing
from scry_core.reply_contract import Invalid

#: Not in alphabetical order, so an answer sorted by name instead of by `KNOWN` is caught.
KNOWN = ("mcbs", "devs", "paging", "vga")
EVERY = "there are: mcbs, devs, paging, vga; the default is mcbs"


def test_a_short_reply_names_what_it_left_out_and_how_to_ask() -> None:
    left = ("paging", "vga")
    note = narrowing.omission(left, "pass sections=[...]")
    assert note == {"omitted": ["paging", "vga"], "how": "pass sections=[...]"}
    assert isinstance(note["omitted"], list)


@pytest.mark.parametrize(("clean", "detail", "kept"), [
    (True, False, False), (True, True, True), (False, False, True), (False, True, True)])
def test_the_last_words_of_a_close_are_kept_unless_the_quit_was_clean_and_none_were_asked(
        clean: bool, detail: bool, kept: bool) -> None:
    tails = {"stdout_tail": "out", "errorlog_tail": "err"}
    got = narrowing.last_words(tails, clean=clean, detail=detail, how="close(detail=True)")
    assert got == (tails if kept else {"omitted": ["stdout_tail", "errorlog_tail"],
                                       "how": "close(detail=True)"})


def test_a_whole_reply_carries_no_omission() -> None:
    assert narrowing.omission([], "pass sections=[...]") == {}


@pytest.mark.parametrize("omitted", [["vga"], []])
def test_an_omission_with_no_way_to_ask_is_a_bug_on_either_path(omitted: list[str]) -> None:
    with pytest.raises(ValueError, match="how to ask"):
        narrowing.omission(omitted, "  ")


def test_a_bare_string_is_not_a_list_of_names() -> None:
    with pytest.raises(ValueError, match="list of names"):
        narrowing.omission("vga", "pass sections=[...]")


def test_the_default_and_the_named_sections_come_back_in_the_known_order_once() -> None:
    assert narrowing.sections(None, KNOWN, ("vga", "devs")) == ["devs", "vga"]
    assert narrowing.sections(["vga", "devs", "vga"], KNOWN, {"mcbs"}) == ["devs", "vga"]
    assert narrowing.sections(("paging",), KNOWN, {"mcbs"}) == ["paging"]
    assert narrowing.sections(["devs", "mcbs"], KNOWN, {"vga"}) == ["mcbs", "devs"]


NOT_A_LIST = (f"`sections` is a list naming at least one section, or left out for the default; "
              f"{EVERY}")


@pytest.mark.parametrize("asked, said", [
    ([], NOT_A_LIST),
    ((), NOT_A_LIST),
    ("mcbs", NOT_A_LIST),
    (["mcbs", "gdt", "nope", "gdt"],
     f"`sections` names 'gdt', 'nope', none of them a section; {EVERY}"),
])
def test_a_section_list_naming_nothing_or_what_is_not_there_is_refused(
        asked: list[str], said: str) -> None:
    with pytest.raises(Invalid) as e:
        narrowing.sections(asked, KNOWN, {"mcbs"})
    assert e.value.code == "bad_argument" and str(e.value) == said


@pytest.mark.parametrize("default", [{"mcbs", "gdt"}, set()])
def test_a_default_empty_or_outside_the_known_sections_is_a_bug_whatever_is_asked(
        default: set[str]) -> None:
    for asked in (None, ["mcbs"]):
        with pytest.raises(ValueError, match="empty or not all known"):
            narrowing.sections(asked, KNOWN, default)
