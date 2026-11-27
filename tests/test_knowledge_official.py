"""The official source of an entry and of a dictionary: the region every official entry has, the
document table it names, and the lines of the declared programming model that exactly one entry
or one closure of the dictionary holds."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rows_world import (
    SEARCHED,
    World,
    build,
    result,
    set_entry,
    set_head,
    set_row,
)

from scry_core.knowledge import official, quote, rows, shared
from scry_core.knowledge.quote import Invalid

SHEET = "datasheet:chipx.raw.txt"
Change = Callable[[dict[str, Any]], None]
Cli = Callable[..., tuple[int, str, str]]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build(tmp_path)


@pytest.fixture
def cli(world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Cli:
    monkeypatch.setitem(shared.PINS, "dosbox-x", world.pin)
    monkeypatch.setattr(quote, "default_datasheets", lambda: world.sources().table)

    def run(*argv: str) -> tuple[int, str, str]:
        code = rows.main([*world.options(), "--callees", str(world.root / "callees.json"),
                          *argv])
        got = capsys.readouterr()
        return code, got.out, got.err
    return run


def declared(world: World, partial: bool = False) -> official.Report:
    return official.check(world.dictionary("command"), world.sources(), partial=partial)


def ranges(*given: str) -> Change:
    return set_head(official={"chipx.raw.txt": list(given)})


def test_every_non_blank_line_of_the_declared_ranges_has_one_holder(world: World) -> None:
    got = declared(world)
    assert got.faults == []
    assert (got.lines, got.owned, got.closed, got.owed, got.unowned) == (9, 6, 2, 1, 0)


def test_a_line_no_entry_and_no_closure_holds_is_red(world: World) -> None:
    world.edit("command", ranges("10-16", "31-34"))
    got = declared(world)
    assert got.faults == [f"{SHEET}:34 is a line of the declared programming model that no "
                          "entry and no closure holds"]
    assert got.unowned == 1


def test_a_dictionary_still_being_written_counts_the_lines_nobody_holds(world: World) -> None:
    world.edit("command", ranges("10-16", "31-36"))
    got = declared(world, partial=True)
    assert got.faults == [] and got.unowned == 3


def test_a_header_closure_removed_leaves_its_line_red(world: World) -> None:
    world.edit("command", set_head(closed=[{"ref": SHEET, "lines": "32", "as": "layout"}]))
    assert any(f.startswith(f"{SHEET}:33 is a line of the declared") for f in declared(
        world).faults)


def test_a_line_in_the_regions_of_two_entries_is_red(world: World) -> None:
    dictionary = world.dictionary("command")
    first = dictionary.entries[0]
    second = dataclasses.replace(first, id="chipx:command:0xE8..0xEF")
    twice = dataclasses.replace(dictionary, entries=(first, second))
    faults = official.check(twice, world.sources()).faults
    assert f"{SHEET}:10 is in the regions of 2 entries (chipx:command:0xE0..0xE7, " \
        "chipx:command:0xE8..0xEF): one owns a line, the others link to it" in faults


def test_a_line_an_entry_closes_as_elsewhere_is_not_its_own(world: World) -> None:
    dictionary = world.dictionary("command")
    first = dictionary.entries[0]
    second = dataclasses.replace(first, id="chipx:command:0xE8..0xEF", closed=())
    both = dataclasses.replace(dictionary, entries=(first, second))
    got = official.check(both, world.sources())
    assert not any(f"{SHEET}:14 " in f for f in got.faults)


def test_an_elsewhere_whose_owner_is_in_the_dictionary_needs_the_owners_region_to_hold_it(
        world: World) -> None:
    dictionary = world.dictionary("command")
    first = dictionary.entries[0]
    owner = dataclasses.replace(
        first, id="chipx:command:0xE8..0xEF", closed=(),
        regions=(rows.Region(SHEET, lines="20-30"),),
        rows=(dataclasses.replace(first.rows[0], quotes=(quote.Quote(SHEET, "14"),)),))
    closing = dataclasses.replace(first, closed=tuple(
        dataclasses.replace(c, owner=owner.id) if c.reason == "elsewhere" else c
        for c in first.closed))
    both = dataclasses.replace(dictionary, entries=(closing, owner))
    assert (f"{SHEET}:14 is closed elsewhere for chipx:command:0xE8..0xEF, whose region does "
            "not hold it") in official.check(both, world.sources()).faults


def test_a_line_both_in_a_region_and_closed_by_the_dictionary_is_red(world: World) -> None:
    world.edit("command", set_head(closed=[
        {"ref": SHEET, "lines": "32", "as": "layout"}, {"ref": SHEET, "lines": "33",
                                                       "as": "electrical"},
        {"ref": SHEET, "lines": "10", "as": "layout"}]))
    assert f"{SHEET}:10 is in a region and closed by the dictionary" in declared(world).faults


def test_a_header_closure_that_closes_no_line_of_the_ranges_is_red(world: World) -> None:
    world.edit("command", set_head(closed=[
        {"ref": SHEET, "lines": "32", "as": "layout"}, {"ref": SHEET, "lines": "33",
                                                       "as": "electrical"},
        {"ref": SHEET, "lines": "20-22", "as": "layout"}]))
    assert f"header closed {SHEET}:20-22 closes no line of a declared range" in declared(
        world).faults


def test_ranges_that_run_past_the_capture_make_the_check_invalid(world: World) -> None:
    world.edit("command", ranges("10-16", "31-99"))
    with pytest.raises(Invalid, match="runs past its capture, which has 36 lines"):
        declared(world)


def test_a_document_the_table_lacks_is_red(world: World) -> None:
    world.edit("command", lambda d: d.update(
        documents=[{"name": "ghost.raw.txt", "variant": "g"}], official={
            "ghost.raw.txt": ["1-2"]}))
    assert "document ghost.raw.txt is not in the document table" in declared(world).faults


def test_the_command_counts_the_lines_it_does_not_own_when_the_dictionary_is_partial(
        cli: Cli, world: World) -> None:
    world.edit("command", ranges("10-16", "31-36"))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and f"{SHEET}:34 is a line of the declared" in out
    code, out, _ = cli("check", "--partial", str(world.root / "command.json"))
    assert code == 0 and "owned by none 3" in out and "faults 0" in out


def test_a_dictionary_with_no_declared_range_prints_no_official_line(cli: Cli,
                                                                      world: World) -> None:
    code, out, _ = cli("check", str(world.root / "call.json"), "--partial")
    assert code == 0 and "official:" not in out


def test_a_header_closure_with_no_range_to_close_is_red_and_says_so(cli: Cli,
                                                                     world: World) -> None:
    world.edit("command", lambda d: d.update(documents=[], official={}))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and f"header closed {SHEET}:32 closes no line of a declared range" in out


@pytest.mark.parametrize("reason", ["dead", "log", "decode", "structure", "build", "unseen",
                                     "preamble", "parent", "agrees"])
def test_a_line_of_an_official_document_is_closed_by_a_reason_that_is_about_a_document(
        world: World, reason: str) -> None:
    closed = {"ref": SHEET, "lines": "15", "as": reason}
    closed.update({"reason": "w", "owner": "x:y:z"} if reason in ("unseen", "parent", "preamble")
                  else {})
    _, faults = rows.read(world.edit("command", set_entry(closed=[closed])))
    assert any("closes a line of an emulator" in f or "closes lines of an emulator" in f
               or "is about an emulator's code" in f for f in faults), faults


# What an entry of an official source has.
def test_an_official_entry_without_an_official_region_is_red(world: World) -> None:
    world.edit("command", set_entry(regions=[]))
    assert any(f.startswith("an `official` entry has an official region")
               for f in result(world).faults)


def test_an_entry_that_says_it_has_no_official_source_needs_none(world: World) -> None:
    got = result(world, "family")
    assert got.faults == [] and world.dictionary("family").header.source == "emulator"


def test_a_line_of_the_official_region_no_row_claims_is_open(world: World) -> None:
    world.edit("command", set_row("1", quotes=[world.sources().stamped(SHEET, "10").as_json()]))
    assert f"OPEN {SHEET}:11 list synthetic datasheet line 11: the control register holds the " \
        "mode in bits 3 to 1" in result(world).faults


@pytest.mark.parametrize(("change", "fault"), [
    (set_head(documents=[], official={}),
     f"region {SHEET} is a document the dictionary does not name"),
    (ranges("10-15", "31-33"),
     f"region {SHEET}:10-16 is outside the lines of chipx.raw.txt declared as its programming "
     "model"),
    (set_row("3", variant="chipx9"), "row 3: variant chipx9 is none of the dictionary's")])
def test_an_entry_that_leaves_the_declared_documents_is_red(world: World, change: Change,
                                                            fault: str) -> None:
    path = world.edit("command", change)
    dictionary, _ = rows.read(path)
    assert dictionary is not None
    assert fault in official.entry_faults(dictionary, dictionary.entries[0])


def test_a_row_that_quotes_a_document_the_dictionary_does_not_name_is_red(world: World) -> None:
    dictionary = world.dictionary("command")
    named = dataclasses.replace(dictionary.header, documents=(
        rows.Document("other.raw.txt", "chipx"),), official={})
    got = official.entry_faults(dataclasses.replace(dictionary, header=named),
                                dictionary.entries[0])
    assert f"row 1 quotes {SHEET}, a document the dictionary does not name" in got


def test_a_row_of_one_variant_may_not_quote_a_document_named_for_another(world: World) -> None:
    dictionary = world.dictionary("command")
    named = dataclasses.replace(dictionary.header, documents=(
        rows.Document("chipx.raw.txt", "chipx"), rows.Document("other.raw.txt", "chipx2")))
    got = official.entry_faults(dataclasses.replace(dictionary, header=named),
                                dictionary.entries[0])
    assert "row 3 is of the chipx2 and quotes chipx.raw.txt, which the dictionary names for " \
        "another variant" in got


def test_an_emulator_dictionary_with_a_doc_row_is_red(world: World) -> None:
    path = world.edit("command", set_head(source="emulator", searched=SEARCHED))
    _, faults = rows.read(path)
    assert any("an `emulator` source has no `doc` row" in f for f in faults)


def test_with_no_official_document_a_note_is_an_extra_or_a_place(world: World) -> None:
    _, faults = rows.read(world.edit("family", set_row("0", vs="differs", row="1")))
    assert any("with no official document a note is `extra` or `place`" in f for f in faults)


def test_an_emulator_dictionary_that_says_where_it_looked_reads_clean(world: World) -> None:
    _, faults = rows.read(world.root / "family.json")
    assert faults == []


@pytest.mark.parametrize(("searched", "fault"), [
    (SEARCHED[:-1], "`searched` has each place once"),
    ([*SEARCHED, SEARCHED[0]], "`searched` has each place once"),
    ([{**SEARCHED[0], "gave": ""}, *SEARCHED[1:]], "what `mame-header` gave is printable ASCII"),
    ([{**SEARCHED[0], "gave": "w " * 31}, *SEARCHED[1:]], "of 1 to 30 words"),
    ([{**SEARCHED[0], "gave": "café"}, *SEARCHED[1:]], "printable ASCII"),
    ([{"where": "a", "gave": "b", "extra": 1}], "`searched` lists `where` and `gave`")])
def test_a_search_that_is_not_the_fixed_list_with_what_each_place_gave_is_red(
        world: World, searched: list[dict[str, str]], fault: str) -> None:
    _, faults = rows.read(world.edit("family", set_head(searched=searched)))
    assert any(fault in f for f in faults), faults
