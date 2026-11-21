"""A call key that ends in a selector (`0x10/0x12/BL=0x36`): its spelling, how it sorts and is
asked, and which variant a stop's registers pick."""

from __future__ import annotations

from pathlib import Path

import pytest
from null_server import an_entry, write_dictionary

from scry_core import knowledge, knowledge_tool
from scry_core.knowledge import KeyFault, check, keys, sources
from scry_core.reply_contract import Invalid


@pytest.mark.parametrize(("typed", "canonical"), [
    ("0x10/0x12/bl=0x36", "0x10/0x12/BL=0x36"), ("0x10/0x12/BL=0x6", "0x10/0x12/BL=0x06"),
    ("0x10/0x12/BL=0x31..0x36", "0x10/0x12/BL=0x31..0x36"),
    ("0x2f/0x16/0x84/cx=0x1234", "0x2F/0x16/0x84/CX=0x1234"),
    ("0x21/0x44/dl=0x0..0x3", "0x21/0x44/DL=0x00..0x03")])
def test_a_selector_has_one_spelling(typed: str, canonical: str) -> None:
    assert keys.canonical("call", typed) == canonical


@pytest.mark.parametrize("typed", [
    "0x10/BL=0x36", "0x10/0x12/XX=0x36", "0x10/0x12/BL=36", "0x10/0x12/BL=", "0x10/0x12/BL",
    "0x10/0x12/BL=0x136", "0x10/0x12/DI=0x10000", "0x10/0x12/BL=0x36..0x31",
    "0x10/0x12/0x01/BL=0x36/CL=0x01", "0x10/0x12/BL=0x31..0x32..0x33", "0x10/0x12/=0x36"])
def test_a_selector_that_is_none_is_refused(typed: str) -> None:
    with pytest.raises(KeyFault):
        keys.canonical("call", typed)


@pytest.mark.parametrize("typed", ["0x21/0x44/AL=0x00", "0x21/0x44/al=0x00..0x03",
                                   "0x21/0x44/AH=0x44", "0x21/0x44/AX=0x4400",
                                   "0x21/0x44/0x00/AL=0x00"])
def test_a_register_the_key_already_says_is_not_a_selector(typed: str) -> None:
    said = r"already .* of the key.*INT/AH/AL.*0x21/0x44/0x00"
    with pytest.raises(KeyFault, match=said):
        keys.query("call", typed)
    with pytest.raises(KeyFault, match=said):
        keys.call_selector("", typed)
    with pytest.raises(KeyFault, match="INT/AH/AL"):
        keys.canonical("call", typed)


def test_a_selector_is_for_a_call_alone() -> None:
    with pytest.raises(KeyFault):
        keys.canonical("port", "0x10/0x12/BL=0x36")


def test_a_selector_does_not_move_the_numbers_a_key_covers() -> None:
    got = keys.span("call", "0x10/0x12/BL=0x31..0x36")
    assert (got.lo, got.hi, got.parts) == (0x10, 0x10, (0x10, 0x12))
    assert got.selector == keys.Selector("BL", 0x31, 0x36)
    assert keys.span("call", "0x10/0x12").selector is None


def test_a_query_with_a_selector_is_read_whole_and_a_range_of_calls_takes_none() -> None:
    key, got = keys.query("call", "0x10/0x12/bl=0x36")
    assert key == "0x10/0x12/BL=0x36" and got.selector == keys.Selector("BL", 0x36, 0x36)
    assert keys.call_selector("call", "0x10/0x12/BL=0x31..0x36") == keys.Selector("BL", 0x31, 0x36)
    assert keys.call_selector("", "0x10/0x12") is None
    for typed, says in (("0x10/0x12..0x10/0x14/BL=0x36", "one call"), ("0x10/BL=0x36", "INT/AH")):
        with pytest.raises(KeyFault, match=says):
            keys.query("call", typed)


def parent_with_variants(tmp_path: Path) -> knowledge.Base:
    write_dictionary(tmp_path, "int10", "call", "ibm-pc", [
        an_entry("0x10/0x12/BL=0x36", "video refresh"),
        an_entry("0x10/0x13", "write string"),
        an_entry("0x10/0x12/BL=0x31..0x32", "default palette"),
        an_entry("0x10/0x12", "alternate select"),
        an_entry("0x10/0x12/BL=0x10", "get config"),
        an_entry("0x10/0x11", "character generator")])
    got = knowledge.Base.load(tmp_path)
    assert got.faults() == []
    return got


def ids(found: knowledge.Found) -> list[str]:
    return [e.key for e in found.entries]


def test_a_variant_sorts_and_ranges_with_its_parent(tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    assert ids(base.search("call", "0x10", limit=20)) == [
        "0x10/0x11", "0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32",
        "0x10/0x12/BL=0x36", "0x10/0x13"]
    assert ids(base.search("call", "0x10/0x12..0x10/0x13", limit=20)) == [
        "0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x36",
        "0x10/0x13"]


def test_the_parent_answers_with_its_variants_listed_and_a_selector_answers_the_variant(
        tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    assert ids(base.search("call", "0x10/0x12")) == [
        "0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x36"]
    assert ids(base.search("call", "0x10/0x12/BL=0x36")) == ["0x10/0x12/BL=0x36"]
    assert ids(base.search(key="0x10/0x12/bl=0x36")) == ["0x10/0x12/BL=0x36"]
    assert ids(base.search("call", "0x10/0x12/BL=0x32")) == ["0x10/0x12/BL=0x31..0x32"]
    assert ids(base.search("call", "0x10/0x12/BL=0x30..0x33")) == ["0x10/0x12/BL=0x31..0x32"]
    assert ids(base.search("call", "0x10/0x12/BH=0x36")) == []


def test_a_selector_nobody_holds_names_the_parent_and_its_variants_as_nearest(
        tmp_path: Path) -> None:
    missed = parent_with_variants(tmp_path).search("call", "0x10/0x12/BL=0x99")
    assert missed.total == 0
    assert [e.key for e in missed.nearest] == [
        "0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x36"]


def test_the_variants_of_a_parent_read_one_register_and_do_not_overlap(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "int10", "call", "ibm-pc", [
        an_entry("0x10/0x12/BL=0x31..0x36", "a"), an_entry("0x10/0x12/BL=0x36", "b"),
        an_entry("0x10/0x12/BH=0x01", "c"), an_entry("0x10/0x12/BL=0x37", "d"),
        an_entry("0x10/0x14/BL=0x01", "e")])
    base = knowledge.Base.load(tmp_path)
    assert [e.key for e in base.entries()] == ["0x10/0x12/BL=0x31..0x36", "0x10/0x12/BL=0x37",
                                               "0x10/0x14/BL=0x01"]
    assert len(base.load_faults) == 2
    assert "overlaps ibm-pc:call:0x10/0x12/BL=0x31..0x36" in base.load_faults[0]
    assert "selects on BH" in base.load_faults[1] and "BL" in base.load_faults[1]


def test_variants_of_a_parent_in_two_dictionaries_still_clash(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "a", "call", "ibm-pc", [an_entry("0x10/0x12/BL=0x36", "a")])
    write_dictionary(tmp_path, "b", "call", "ibm-pc", [an_entry("0x10/0x12/BL=0x36..0x37", "b")])
    write_dictionary(tmp_path, "c", "call", "other", [an_entry("0x10/0x12/BL=0x36", "c")])
    base = knowledge.Base.load(tmp_path)
    assert [e.id for e in base.entries()] == ["ibm-pc:call:0x10/0x12/BL=0x36",
                                              "other:call:0x10/0x12/BL=0x36"]
    assert len(base.load_faults) == 1


def test_the_variants_of_a_parent_are_listed_by_the_base(tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    assert [e.key for e in base.variants("ibm-pc", "0x10/0x12")] == [
        "0x10/0x12/BL=0x36", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x10"]
    assert base.variants("ibm-pc", "0x10/0x13") == []
    assert base.variants("other", "0x10/0x12") == []


def test_knowledge_find_answers_the_parent_with_its_variants_and_a_selector_with_the_variant(
        tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    parent = knowledge_tool.find(base, kind="call", key="0x10/0x12")
    assert [e["key"] for e in parent["entries"]] == [
        "0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x36"]
    variant = knowledge_tool.find(base, kind="call", key="0x10/0x12/bl=0x36")
    assert variant["query"]["key"] == "0x10/0x12/BL=0x36"
    assert [e["name"] for e in variant["entries"]] == ["video refresh"]
    assert knowledge_tool.find(base, kind="call", key="0x10/0x12/BL=0x99")["nearest"]
    with pytest.raises(Invalid, match="no key of kind call"):
        knowledge_tool.find(base, kind="call", key="0x10/0x12/XX=0x99")


def test_the_variants_of_a_call_are_not_those_of_a_function_inside_it(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "int10", "call", "ibm-pc", [
        an_entry("0x10/0x12", "parent"), an_entry("0x10/0x12/0x00/CL=0x01", "deep"),
        an_entry("0x10/0x12/BL=0x36", "variant")])
    base = knowledge.Base.load(tmp_path)
    assert base.faults() == []
    assert [e.key for e in base.variants("ibm-pc", "0x10/0x12")] == ["0x10/0x12/BL=0x36"]
    assert [e.key for e in base.variants("ibm-pc", "0x10/0x12/0x00")] == ["0x10/0x12/0x00/CL=0x01"]
    assert ids(base.search("call", "0x10/0x12/BL=0x36")) == ["0x10/0x12/BL=0x36"]


def test_a_selector_query_is_read_the_same_through_search_with_space_around_it(
        tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    assert ids(base.search("call", " 0x10/0x12/BL=0x36 ")) == ["0x10/0x12/BL=0x36"]
    assert ids(base.search("call", "0x10/0x12/ BL=0x36")) == ["0x10/0x12/BL=0x36"]


@pytest.mark.parametrize("kind", ["call", ""])
def test_a_selector_never_goes_with_a_range_of_calls(tmp_path: Path, kind: str) -> None:
    base = parent_with_variants(tmp_path)
    for typed in ("0x10/0x12..0x10/0x13/BL=0x36", "0x10/0x12/BL=0x36..0x10/0x13"):
        with pytest.raises(KeyFault, match="one call"):
            base.search(kind, typed)


def test_a_list_section_of_the_parent_is_the_source_of_the_variants_that_cite_it(
        tmp_path: Path) -> None:
    base = parent_with_variants(tmp_path)
    ref = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"
    line = next(iter(base.entries())).sources[0].cites

    def refused_for(row_key: str) -> set[str]:
        index = sources.SourceIndex(rows={ref: sources.Row(line, row_key)})
        return {problem.rsplit("not of ", 1)[1] for problem in check.against_sources(base, index)}

    family = {"0x10/0x12", "0x10/0x12/BL=0x10", "0x10/0x12/BL=0x31..0x32", "0x10/0x12/BL=0x36"}
    assert refused_for("0x10/0x12") == {"0x10/0x11", "0x10/0x13"}
    assert refused_for("0x10/0x12/BL=0x10") == (family | {"0x10/0x11", "0x10/0x13"}) - {
        "0x10/0x12/BL=0x10"}
    assert refused_for("0x10/0x11") == (family | {"0x10/0x13"})
    assert refused_for("0x10") == family | {"0x10/0x11", "0x10/0x13"}


def test_a_key_with_an_equals_sign_of_another_kind_is_never_read_as_a_selector(
        tmp_path: Path) -> None:
    write_dictionary(tmp_path, "inputs", "input", "ibm-pc", [an_entry(":IN0/Dip=1", "dip")])
    base = knowledge.Base.load(tmp_path)
    ref = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"
    line = next(iter(base.entries())).sources[0].cites
    index = sources.SourceIndex(rows={ref: sources.Row(line, "0x10/0x12")})
    assert check.against_sources(base, index) == [
        f"inputs :IN0/Dip=1: {ref} is the source of 0x10/0x12, not of :IN0/Dip=1"]
