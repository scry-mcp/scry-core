"""`scry_core.knowledge.rows` and its closure: an entry as rows that carry their evidence, the
command that stamps, lists, checks and reads them, and what each of its refusals is red on."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rows_world import (
    DICTIONARIES,
    SEARCHED,
    World,
    build,
    drop_row,
    drop_subject,
    entry_doc,
    result,
    set_entry,
    set_head,
    set_row,
)

from scry_core.knowledge import closure, quote, rows, shared
from scry_core.knowledge.quote import Invalid

ITEMS = {"command": 21, "register": 13, "call": 32, "family": 8}
Cli = Callable[..., tuple[int, str, str]]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build(tmp_path)


@pytest.fixture
def cli(world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Cli:
    monkeypatch.setitem(shared.PINS, "dosbox-x", world.pin)
    monkeypatch.setattr(quote, "default_datasheets", lambda: world.sources().table)

    def run(*argv: str, callees: bool = True) -> tuple[int, str, str]:
        extra = ["--callees", str(world.root / "callees.json")] if callees else []
        code = rows.main([*world.options(), *extra, *argv])
        got = capsys.readouterr()
        return code, got.out, got.err
    return run


@pytest.mark.parametrize("name", DICTIONARIES)
def test_each_fixture_entry_closes_with_the_items_the_lister_gives(world: World, name: str) -> None:
    report = result(world, name)
    assert (len(report.results), report.open, report.faults) == (ITEMS[name], 0, [])


@pytest.mark.parametrize("name", DICTIONARIES)
def test_the_command_line_closes_each_fixture_entry_with_exit_zero(cli: Cli, world: World,
                                                                    name: str) -> None:
    code, out, _ = cli("check", str(world.root / f"{name}.json"), "--partial")
    assert code == 0
    assert f"items {ITEMS[name]}, open 0, faults 0" in out


def test_the_default_regions_are_the_headers_handlers_with_the_keys_own_value(
        world: World) -> None:
    dictionary = world.dictionary("command")
    got = dictionary.regions(dictionary.entries[0])
    assert [(r.function, r.case, r.value) for r in got] == [
        ("chipx_device::write", ("0",), "data=224..231"), ("write_command", (), "val=224..231"),
        ("", (), "")]


def test_a_region_the_entry_names_replaces_the_headers_handler_of_that_function(
        world: World) -> None:
    def named(doc: dict[str, Any]) -> None:
        entry_doc(doc)["regions"] = [{"ref": "mame:src/devices/machine/chipx.cpp",
                                      "function": "chipx_device::write", "case": ["1"]},
                                     *entry_doc(doc)["regions"]]
    path = world.edit("command", named)
    dictionary, faults = rows.read(path)
    assert dictionary is not None and not faults
    got = dictionary.regions(dictionary.entries[0])
    assert [(r.function, r.case) for r in got] == [("write_command", ()),
                                                   ("chipx_device::write", ("1",)), ("", ())]


# What a dictionary must keep, each refusal named.
DOCS = [{"name": "chipx.raw.txt", "variant": "chipx"},
        {"name": "chipx.raw.txt", "variant": "chipx2"}]
WORDS = " ".join(["word"] * 31)
QUOTE = {"ref": "mame:src/devices/machine/chipx.cpp", "lines": "10"}


@pytest.mark.parametrize(("change", "fault"), [
    (lambda doc: doc.pop("title"), "`title` names what the dictionary covers"),
    (set_head(title=" ".join(["word"] * 11)), "`title` names what the dictionary covers"),
    (set_row("1", text=WORDS), "31 words, over 30"),
    (set_row("1", text="tab\there"), "printable ASCII"),
    (set_row("1", text="café"), "printable ASCII"),
    (set_row("1", text=" padded "), "no space around it"),
    (set_row("1", n="toolong7"), "1 to 6 letters or digits"),
    (set_row("2", n="1"), "two rows share a label"),
    (set_row("1", on="shouts"), "not a subject of a command"),
    (set_row("1", of=[]), "`of` is one party"),
    (set_row("1", of=["doc"]), "`of` is one party"),
    (set_row("1", of="gcc"), "`of` is one party"),
    (set_row("1", state="maybe"), "`state` is absent or one of undetermined"),
    (set_row("1", links=["a:b:c"] * 5), "at most 4 entry ids"),
    (set_row("1", quotes=[]), "1 to 6 `quotes`"),
    (set_row("1", quotes=[QUOTE] * 7), "1 to 6 `quotes`"),
    (set_row("1", quotes=[{"ref": QUOTE["ref"], "lines": "1-13"}]), "is 13 lines, over 12"),
    (set_row("1", quotes=[{"ref": "nowhere", "lines": "1"}]), "scheme"),
    (set_row("1", quotes=[{"ref": QUOTE["ref"], "lines": "9-3"}]), "runs downward"),
    (set_row("1", quotes=[{"ref": QUOTE["ref"], "lines": "1", "text": "x"}]),
     "`ref`, `lines` and `sha`"),
    (set_row("1", surprise=1), "an object of"),
    (set_entry(rows=[]), "at least one row"),
    (set_entry(name="x" * 25), "at most 24 characters"),
    (set_entry(aliases=["a"] * 7), "at most 6 names"),
    (set_entry(key="0xe0..0xe7"), "the key is written 0xE0..0xE7"),
    (set_entry(key="zz"), "hex"),
    (set_entry(surprise=1), "no field surprise"),
    (set_entry(regions=[{"ref": "mame:x.cpp"}]), "a function or a section of a list"),
    (set_entry(regions=[{"ref": "mame:x.cpp", "function": "f", "lines": "1"}]),
     "a function or a section of a list"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "10", "as": "because"}]),
     "no reason of the set"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "10", "as": "unseen"}]),
     "`unseen` needs a `reason` of at most 16 words"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "10", "as": "unseen",
                        "reason": " ".join(["w"] * 17)}]), "at most 16 words"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "10", "as": "preamble"}]),
     "names the entry that owns the line"),
    (drop_subject("is"), "needs a row on is"),
    (drop_subject("write"), "needs a row on write"),
    (set_head(kind="widget"), "`kind` is one of"),
    (set_head(extra=1), "no header field extra"),
    (set_head(stores={"mame": "real_writeb"}), "no header field stores"),
    (set_head(defines={"gcc": []}), "`defines` maps a party"),
    (set_head(engine="x"), "`engine` is a list"),
    (set_head(format="scry-knowledge/1"), "is not a `scry-knowledge/2` document"),
    # what an official entry has a row on is what the document says, not what an emulator does
    (set_row("1", of="mame", vs="extra", quotes=[QUOTE]), "a command needs a row on is"),
    (set_row("3", of="mame", vs="extra", quotes=[QUOTE]), "a command needs a row on write"),
    # the verdict of an emulator beside an official row
    (set_row("1", vs="extra"), "a `doc` row has no `vs`"),
    (set_row("1", on="place"), "`place` is how an emulator reaches the thing"),
    (set_row("1", variant=3), "`variant` is text"),
    (set_row("4", vs=None), "a note of an emulator has `vs`"),
    (set_row("4", vs="odd"), "a note of an emulator has `vs`"),
    (set_row("5", row=""), "`differs` names the `doc` row it is about"),
    (set_row("7", row=""), "`absent` names the `doc` row it is about"),
    (set_row("4", row="1"), "`row` goes with `differs` or `absent`, not with place"),
    (set_row("9", row="1"), "`row` goes with `differs` or `absent`, not with extra"),
    (set_row("1", row="1"), "`row` goes with `differs` or `absent`, not with a doc"),
    (set_row("4", on="is"), "`vs` place is on `place`"),
    (set_row("4", variant="chipx"), "only a `doc` row has a `variant`"),
    # the closures that name a row, an official line or an owner
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "24-27", "as": "agrees"}]),
     "`agrees` closes lines of an emulator and names the `doc` row"),
    (set_entry(closed=[{"ref": "datasheet:chipx.raw.txt", "lines": "10", "as": "agrees",
                        "row": "1"}]), "`agrees` closes lines of an emulator"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "24", "as": "structure", "row": "1"}]),
     "`row` goes with `agrees` or `unfollowed` only"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "24", "as": "layout"}]),
     "`layout` closes a line of an official document"),
    (set_entry(closed=[{"ref": QUOTE["ref"], "lines": "24", "as": "electrical"}]),
     "`electrical` closes a line of an official document"),
    (set_entry(closed=[{"ref": "datasheet:chipx.raw.txt", "lines": "14", "as": "elsewhere"}]),
     "names the entry that owns the line"),
    # the header: its source, its documents and the lines that are the programming model
    (set_head(source="both"), "`source` is one of official, emulator"),
    (set_head(documents=[{"name": "chipx.raw.txt"}]), "is `name` and `variant`"),
    (set_head(documents=DOCS + DOCS[:1]), "names a document and variant twice"),
    (set_head(documents=[]), "`official` names chipx.raw.txt, which `documents` does not"),
    (set_head(official={}), "`documents` names chipx.raw.txt and `official` gives it no range"),
    (set_head(official={"chipx.raw.txt": ["10-16", "16-17"]}), "has ranges that overlap"),
    (set_head(official={"chipx.raw.txt": ["10-x"]}), "is a list of `a-b` ranges"),
    (set_head(official={"chipx.raw.txt": []}), "is a list of `a-b` ranges"),
    (set_head(official=["10-16"]), "`official` maps a document"),
    (set_head(closed=[{"ref": QUOTE["ref"], "lines": "24", "as": "log"}]),
     "a dictionary closes lines of an official document"),
    # an entry or a dictionary that has no official source says where it looked
    (set_head(source="emulator"), "an `emulator` source has no `doc` row"),
    (set_head(source="emulator"), "an `emulator` source says where it searched"),
    (set_entry(source="emulator", searched=SEARCHED), "an `emulator` source has no `doc` row"),
    (set_entry(source="emulator"), "an `emulator` source says where it searched"),
    (set_entry(source="official", searched=SEARCHED), "`searched` goes with an `emulator`"),
    (set_entry(source="free"), "`source` is one of official, emulator"),
    (set_head(searched="nowhere"), "`searched` lists `where` and `gave`"),
])
def test_a_dictionary_that_breaks_a_limit_is_refused_by_name(
        world: World, change: Callable[[dict[str, Any]], None], fault: str) -> None:
    dictionary, faults = rows.read(world.edit("command", change))
    assert any(fault in f for f in faults), faults


def test_two_entries_of_one_id_are_a_fault(world: World) -> None:
    def twice(doc: dict[str, Any]) -> None:
        doc["entries"].append(doc["entries"][0])
    _, faults = rows.read(world.edit("command", twice))
    assert "two entries share an id" in faults


def test_a_file_that_is_not_json_is_a_fault_and_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{", encoding="utf-8")
    dictionary, faults = rows.read(path)
    assert dictionary is None and "not JSON" in faults[0]


def test_an_entry_that_holds_a_placement_field_needs_a_row_on_place() -> None:
    def port(rows_: list[dict[str, Any]]) -> str:
        return json.dumps({"format": "scry-knowledge/2", "dictionary": "p", "title": "t",
                           "kind": "port", "scope": "chipx", "covers": "c", "source": "emulator",
                           "searched": SEARCHED, "entries": [
                               {"key": "0x20", "name": "port", "address": 32, "rows": rows_}]})
    mine = {"n": "1", "on": "is", "of": "mame", "vs": "extra", "text": "A port.",
            "quotes": [QUOTE]}
    place = {**mine, "n": "2", "on": "place", "vs": "place", "text": "At 0x20."}
    assert rows.parse(port([mine, place]))[1] == []
    assert any("needs a row on place" in f for f in rows.parse(port([mine]))[1])


# What `rows check` is red on: each breaks one line the entry covers.
def test_a_row_removed_leaves_its_item_open(world: World) -> None:
    world.edit("command", drop_row("5"))
    report = result(world)
    assert report.open == 1
    assert "OPEN mame:src/devices/machine/chipx.cpp:17 branch if (m_state == state_t::READY)" \
        in report.faults


def test_lines_outside_the_file_are_a_fault(world: World) -> None:
    world.edit("command", set_row("2", quotes=[{**QUOTE, "lines": "900", "sha": "a" * 64}]))
    assert any("outside the file" in f for f in result(world).faults)


def test_a_digest_that_no_longer_matches_makes_the_row_a_fault(world: World) -> None:
    world.rewrite("mame", "src/devices/machine/chipx.cpp", "state_t::READY", "state_t::BUSY")
    report = result(world)
    assert any("no longer gives its digest" in f for f in report.faults)


MAME_LINES = {"ref": QUOTE["ref"], "lines": "10-12"}
DOSBOX_LINE = {"ref": "dosbox-x:src/hardware/chipx.cpp", "lines": "4"}
SHEET_LINE = {"ref": "datasheet:chipx.raw.txt", "lines": "10"}


@pytest.mark.parametrize(("row", "quotes", "fault"), [
    ("1", [MAME_LINES], "row 1 speaks for doc and quotes mame: a row quotes its own party only"),
    ("1", [SHEET_LINE, DOSBOX_LINE], "row 1 speaks for doc and quotes dosbox-x"),
    ("4", [DOSBOX_LINE], "row 4 speaks for mame and quotes dosbox-x"),
    ("6", [MAME_LINES], "row 6 speaks for dosbox-x and quotes mame"),
    ("6", [SHEET_LINE], "row 6 speaks for dosbox-x and quotes doc")])
def test_a_row_quotes_its_own_party_only(world: World, row: str, quotes: list[dict[str, str]],
                                         fault: str) -> None:
    world.edit("command", set_row(row, quotes=quotes))
    assert any(f.startswith(fault) for f in result(world).faults)


def test_a_closure_that_closes_no_item_is_a_fault(world: World) -> None:
    def extra(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].append({"ref": "mame:src/devices/machine/chipx.cpp",
                                         "lines": "3", "as": "structure"})
    world.edit("command", extra)
    assert "closed mame:src/devices/machine/chipx.cpp:3 closes no listed item" in result(
        world).faults


def test_an_item_both_claimed_and_closed_is_a_fault(world: World) -> None:
    def extra(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].append({"ref": "mame:src/devices/machine/chipx.cpp",
                                         "lines": "17", "as": "dead"})
    world.edit("command", extra)
    assert ("mame:src/devices/machine/chipx.cpp:17 is claimed by row 5 and closed as dead: "
            "one of the two") in result(world).faults


def test_a_structure_closure_may_lie_over_a_line_a_note_claims(world: World) -> None:
    def extra(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].append({"ref": "mame:src/devices/machine/chipx.cpp",
                                         "lines": "17", "as": "structure"})
    world.edit("command", extra)
    assert result(world).faults == []


def test_a_line_a_closure_covers_is_closed_with_its_reason(world: World) -> None:
    report = result(world, "register")
    assert {r.by for r in report.results if r.item.line == 44} == {"closed: dead"}


def test_a_function_the_source_lacks_makes_the_check_invalid(world: World) -> None:
    def renamed(doc: dict[str, Any]) -> None:
        doc["handlers"][0]["function"] = "chipx_device::gone"
    world.edit("command", renamed)
    with pytest.raises(Invalid, match="no definition of chipx_device::gone"):
        result(world)


def test_a_call_nobody_decided_is_open(world: World) -> None:
    (world.root / "callees.json").write_text(json.dumps(
        {"format": "scry-knowledge-callees/1", "callees": {}}), encoding="utf-8")
    report = closure.check(world.dictionary("command"), world.dictionary("command").entries[0],
                           world.sources(), world.callees(), {})
    assert report.open == 3 and any("call LOG_CMD" in f for f in report.faults)


def test_an_engine_function_the_header_does_not_name_is_open(world: World) -> None:
    world.edit("command", set_head(engine=[]))
    report = result(world)
    assert report.open == 1 and any("call blk->check_after_eoi" in f for f in report.faults)


def test_an_opened_function_with_no_region_is_open(world: World) -> None:
    def without(doc: dict[str, Any]) -> None:
        entry_doc(doc)["regions"] = [r for r in entry_doc(doc)["regions"]
                                     if r.get("function") != "chipx_device::tick"]
        entry_doc(doc)["rows"] = [r for r in entry_doc(doc)["rows"] if r["n"] != "4"]
    world.edit("register", without)
    assert any("call chipx_device::tick" in f for f in result(world, "register").faults)


def test_a_shared_function_is_held_to_the_entry_that_owns_it(world: World) -> None:
    owner = world.dictionary("register").entries[0]
    dictionary = world.dictionary("call")
    mine = dictionary.entries[0]
    wrong = {"dos:call:0x21/0x3C": owner}
    report = closure.check(dictionary, mine, world.sources(), world.callees(), wrong)
    assert any("call create_file" in f for f in report.faults)
    assert report.owed == 0


def test_a_shared_function_nobody_holds_yet_is_owed_and_not_open(world: World) -> None:
    assert result(world, "call").owed == 1


def test_an_owner_that_has_no_row_on_the_lines_is_a_fault(world: World) -> None:
    dictionary = world.dictionary("family")
    mine = dictionary.entries[0]
    owner = world.dictionary("command").entries[0]
    report = closure.check(dictionary, mine, world.sources(), world.callees(),
                           {"video:call:0x10": owner})
    assert any("has no row on those lines" in f for f in report.faults)


def test_a_link_to_an_entry_of_this_dictionary_that_is_not_there_is_a_fault(
        world: World) -> None:
    world.edit("command", set_row("1", links=["chipx:command:0x99", "chipx:register:0x99",
                                              "other:port:0x20"]))
    faults = result(world).faults
    assert ["chipx:command:0x99" in f for f in faults].count(True) == 1
    assert len(faults) == 1


def test_a_link_that_is_not_an_entry_id_is_a_fault(world: World) -> None:
    world.edit("command", set_row("1", links=["nothing"]))
    assert any("is an entry id" in f for f in result(world).faults)


# The command line.
def test_a_run_that_examined_nothing_prints_invalid_and_exits_three(
        cli: Cli, world: World) -> None:
    world.edit("command", set_head(entries=[]))
    code, out, err = cli("check", str(world.root / "command.json"))
    assert (code, out) == (3, "")
    assert err.startswith("INVALID: nothing was examined")


def test_a_check_with_an_open_item_exits_one_and_names_it(cli: Cli, world: World) -> None:
    world.edit("command", drop_row("5"))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and "OPEN mame:src/devices/machine/chipx.cpp:17" in out
    assert "open 1, owed" in out


def test_a_missing_function_exits_three_and_says_invalid(cli: Cli, world: World) -> None:
    world.edit("command", lambda d: d["handlers"][0].update(function="chipx_device::gone"))
    code, _, err = cli("check", str(world.root / "command.json"))
    assert code == 3 and err.startswith("INVALID: no definition of chipx_device::gone")


def test_an_unreadable_dictionary_is_invalid_for_the_commands_that_list(
        cli: Cli, world: World) -> None:
    world.edit("command", set_head(format="x"))
    code, _, err = cli("cover", str(world.root / "command.json"))
    assert code == 3 and "is not a `scry-knowledge/2` document" in err


@pytest.mark.parametrize("argv", [["--nope", "check", "x"], ["check", "--nope", "x"],
                                  ["frobnicate"], [], ["quote", "--stamp"]])
def test_an_unknown_option_or_command_exits_two(argv: list[str], capsys: pytest.CaptureFixture[str]
                                                ) -> None:
    with pytest.raises(SystemExit) as stop:
        rows.main(argv)
    assert stop.value.code == 2
    capsys.readouterr()


def test_an_entry_the_dictionary_lacks_is_invalid(cli: Cli, world: World) -> None:
    code, _, err = cli("check", str(world.root / "command.json"), "chipx:command:0x99")
    assert code == 3 and "no entry chipx:command:0x99" in err


def test_the_entry_chosen_is_the_one_checked(cli: Cli, world: World) -> None:
    code, out, _ = cli("check", str(world.root / "command.json"), "chipx:command:0xE0..0xE7",
                       "--partial")
    assert code == 0 and out.count("rows 9") == 1


def test_cover_prints_each_item_with_what_closes_it(cli: Cli, world: World) -> None:
    code, out, _ = cli("cover", str(world.root / "command.json"))
    assert code == 0
    assert "17 branch  if (m_state == state_t::READY)" in out and "<- row 5" in out
    assert "<- the key" in out and "<- callee: none:log" in out and "<- callee: engine" in out


def test_cover_marks_an_open_item_and_exits_one(cli: Cli, world: World) -> None:
    world.edit("command", drop_row("5"))
    code, out, _ = cli("cover", str(world.root / "command.json"))
    assert code == 1 and "<- OPEN" in out


def test_review_prints_the_entry_in_the_order_of_a_reply(cli: Cli, world: World) -> None:
    code, out, _ = cli("review", str(world.root / "command.json"))
    assert code == 0
    marks = ["official rows (the entry)", "notes of dosbox-x", "notes of mame",
             "mame agrees with row 3", "official region whole", "notes of several emulators",
             "  closed datasheet:chipx.raw.txt 14 as elsewhere"]
    at = [out.index(m) for m in marks]
    assert at == sorted(at)
    assert out.index("  row 1  is  of doc") < out.index("  row 6  place  of dosbox-x place")


def test_review_names_each_note_with_its_vs_and_the_row_it_is_about(cli: Cli,
                                                                      world: World) -> None:
    _, out, _ = cli("review", str(world.root / "command.json"))
    assert "row 5  when  of mame differs row 2   [only]" in out
    assert "row 7  when  of dosbox-x absent row 2   [absent: nothing observable may happen in " \
        "its place]" in out
    assert "row 9  write  of dosbox-x extra   [undetermined]" in out
    assert "row 3  write  of doc  variant chipx2" in out
    assert "      17 | else if (m_state == state_t::READY)" in out


def test_review_shows_an_agrees_with_the_lines_the_row_and_the_rows_lines(
        cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "command.json"))
    block = out.split("mame agrees with row 3, as documented (1 place)\n"
                      "      mame:src/devices/machine/chipx.cpp 24-27\n")[1]
    assert block.startswith("            24 | if (m_isr & mask)\n")
    assert "            27 | m_base = (level + 1) & 7;\n  row 3  write  of doc" in block
    assert "      datasheet:chipx.raw.txt 13\n            13 | synthetic datasheet line 13" in block
    assert "as agrees" not in out


def test_review_shows_the_official_region_whole_for_an_extra_note(cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "command.json"))
    block = out.split("official region whole, to read for each extra note (dosbox-x 9)")[1]
    assert [f"{n} | synthetic datasheet line {n}" in block for n in range(10, 17)] == [True] * 7


def test_review_shows_the_notes_of_two_emulators_on_one_subject_together(
        cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "command.json"))
    assert ("notes of several emulators on place, together\n"
            "      mame 4 place: MAME takes it on a write at offset 0.\n"
            "      dosbox-x 6 place: The port written picks the block") in out


def test_review_says_an_entry_with_no_official_source_is_the_emulators_and_where_it_looked(
        cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "family.json"))
    assert out.splitlines()[1] == "  according to the emulator's source; no official document found"
    assert "    searched archive-org: " in out and "official region whole" not in out
    assert "official rows" not in out


def test_review_names_the_closures_and_the_callee_decisions(cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "call.json"))
    assert "closed dosbox-x:src/ints/call.cpp 7 as unseen (no program can see the flag)" in out
    assert "callee decisions used:" in out and "create_file shared:dos:call:0x21/0x3C" in out
    assert ("dosbox-x agrees with row 4, as documented (1 place)\n"
            "      dosbox-x:src/ints/call.cpp 12-14") in out


def test_quote_prints_the_lines_with_their_digest_and_no_more(cli: Cli, world: World) -> None:
    code, out, _ = cli("quote", "mame:src/devices/machine/chipx.cpp", "10-11", callees=False)
    lines = out.splitlines()
    sha = world.sources().stamped("mame:src/devices/machine/chipx.cpp", "10-11").sha
    assert code == 0 and lines[0] == f"mame:src/devices/machine/chipx.cpp 10-11 sha {sha}"
    assert lines[1] == "  10 | \tswitch (offset)" and len(lines) == 3


def test_quote_json_is_the_quote_ready_for_a_row(cli: Cli, world: World) -> None:
    code, out, _ = cli("quote", "--json", "dosbox-x:src/hardware/chipx.cpp", "4", callees=False)
    got = json.loads(out)
    assert code == 0 and set(got) == {"ref", "lines", "sha"} and got["lines"] == "4"


def test_quote_without_its_arguments_is_invalid(cli: Cli) -> None:
    code, _, err = cli("quote", callees=False)
    assert code == 3 and "takes a ref and its lines" in err


def test_quote_of_lines_the_file_lacks_is_invalid(cli: Cli) -> None:
    code, _, err = cli("quote", "mame:src/devices/machine/chipx.cpp", "900", callees=False)
    assert code == 3 and "outside the file" in err


def test_stamp_writes_the_missing_digests_and_leaves_the_held_ones(cli: Cli, world: World) -> None:
    def bare(doc: dict[str, Any]) -> None:
        for r in entry_doc(doc)["rows"][:2]:
            del r["quotes"][0]["sha"]
    path = world.edit("command", bare)
    code, out, _ = cli("quote", "--stamp", str(path), callees=False)
    assert code == 0 and "stamped 2 quotes, 7 already held a digest" in out
    code, out, _ = cli("check", str(path), "--partial")
    assert code == 0
    code, out, _ = cli("quote", "--stamp", str(path), callees=False)
    assert "stamped 0 quotes, 9 already held" in out


def test_stamp_never_rewrites_a_digest_that_is_held(cli: Cli, world: World) -> None:
    path = world.edit("command", set_row("1", quotes=[{**QUOTE, "lines": "10", "sha": "f" * 64}]))
    cli("quote", "--stamp", str(path), callees=False)
    assert entry_doc(json.loads(path.read_text()))["rows"][0]["quotes"][0]["sha"] == "f" * 64


def test_stamp_over_a_file_with_no_quote_is_invalid(cli: Cli, world: World) -> None:
    path = world.edit("command", set_head(entries=[]))
    code, _, err = cli("quote", "--stamp", str(path), callees=False)
    assert code == 3 and "nothing was examined" in err


@pytest.mark.parametrize(("region", "fault"), [
    ("text", "is `ref` with `function`"),
    ({"function": "f"}, "is `ref` with `function`"),
    ({"ref": "mame:x.cpp", "lines": "0"}, "lines"),
    ({"ref": "nowhere", "function": "f"}, "scheme"),
    ({"ref": "mame:x.cpp", "function": "f", "case": "0"}, "`case` is a list of labels"),
    ({"ref": "mame:x.cpp", "function": "f", "case": [""]}, "`case` is a list of labels")])
def test_a_region_that_is_not_one_is_refused(world: World, region: Any, fault: str) -> None:
    _, faults = rows.read(world.edit("command", set_entry(regions=[region])))
    assert any(fault in f for f in faults), faults


@pytest.mark.parametrize(("closed", "fault"), [
    ("text", "`ref`, `lines`, `as`"),
    ({"ref": "mame:x.cpp", "lines": "0", "as": "log"}, "lines"),
    ({"ref": "nowhere", "lines": "1", "as": "log"}, "scheme")])
def test_a_closure_that_is_not_one_is_refused(world: World, closed: Any, fault: str) -> None:
    _, faults = rows.read(world.edit("command", set_entry(closed=[closed])))
    assert any(fault in f for f in faults), faults


def test_an_entry_that_is_not_an_object_and_a_header_without_text_are_refused(
        world: World) -> None:
    _, faults = rows.read(world.edit("command", set_head(entries=["x"])))
    assert any("is an object" in f for f in faults)
    dictionary, faults = rows.read(world.edit("command", set_head(covers=3)))
    assert dictionary is None and "`dictionary`, `scope` and `covers` are text" in faults[0]
    dictionary, faults = rows.read(world.edit("command", set_head(entries="x")))
    assert dictionary is None and "`entries` is a list" in faults[-1]


def test_a_handler_of_a_key_with_no_numbers_gets_no_value(tmp_path: Path) -> None:
    doc = {"format": "scry-knowledge/2", "dictionary": "d", "title": "t", "kind": "device",
           "scope": "chipx",
           "covers": "c", "source": "emulator", "searched": SEARCHED,
           "handlers": [{"ref": "mame:x.cpp", "function": "f", "value": "v"}],
           "entries": [{"key": "chipx", "name": "chip", "rows": [
               {"n": "1", "on": "is", "of": "mame", "vs": "extra", "text": "A chip.",
                "quotes": [QUOTE]},
               {"n": "2", "on": "reset", "of": "mame", "vs": "extra", "text": "Resets.",
                "quotes": [QUOTE]}]}]}
    dictionary, faults = rows.parse(json.dumps(doc))
    assert dictionary is not None and faults == []
    assert dictionary.regions(dictionary.entries[0])[0].value == ""


def test_a_dictionary_with_a_fault_prints_it_beside_the_reports(cli: Cli, world: World) -> None:
    world.edit("command", set_row("1", text=WORDS))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and "- chipx:command:0xE0..0xE7, row 1: `text` is 31 words" in out


def test_a_check_with_no_callee_table_named_reads_the_one_beside_the_dictionary(
        cli: Cli, world: World) -> None:
    code, out, _ = cli("check", str(world.root / "command.json"), "--partial", callees=False)
    assert code == 0 and "OPEN" not in out


def test_a_check_with_no_callee_table_beside_the_dictionary_leaves_the_calls_open(
        cli: Cli, world: World) -> None:
    (world.root / "callees.json").unlink()
    code, out, _ = cli("check", str(world.root / "command.json"), callees=False)
    assert code == 1 and "OPEN mame:src/devices/machine/chipx.cpp:19 call LOG_CMD" in out


def test_migrate_without_an_output_file_prints_the_draft_and_says_the_summary_apart(
        cli: Cli, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = cli("migrate", str(world.root / "old/command.json"),
                         "chipx:command:0xE0..0xE7", "--evidence",
                         str(world.root / "old/evidence-mame.json"), callees=False)
    assert code == 0 and json.loads(out)["entries"][0]["key"] == "0xE0..0xE7"
    assert "2 statements anchored" in err


def test_a_vector_that_holds_an_address_needs_a_row_on_place() -> None:
    def vector(rows_: list[dict[str, Any]]) -> str:
        return json.dumps({"format": "scry-knowledge/2", "dictionary": "v", "title": "t",
                           "kind": "vector", "scope": "chipx", "covers": "c", "source": "emulator",
                           "searched": SEARCHED, "entries": [
                               {"key": "0x08", "name": "tick", "address": 8, "length": 4,
                                "rows": rows_}]})
    mine = {"n": "1", "on": "is", "of": "mame", "vs": "extra", "text": "A vector.",
            "quotes": [QUOTE]}
    assert any("needs a row on place" in f for f in rows.parse(vector([mine]))[1])
    assert rows.parse(vector([mine, {**mine, "n": "2", "on": "place", "vs": "place"}]))[1] == []


def test_review_leaves_out_what_an_entry_has_none_of(cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "family.json"))
    assert "several emulators" not in out and "callee decisions" not in out


def test_a_row_with_two_quotes_over_one_line_claims_it_once(world: World) -> None:
    both = {"quotes": [{**QUOTE, "lines": "10-11", "sha": "a" * 64},
                       {**QUOTE, "lines": "11-12", "sha": "a" * 64}]}
    world.edit("command", set_row("4", **both))
    dictionary = world.dictionary("command")
    claims = closure._claims(dictionary.entries[0])
    assert claims["mame:src/devices/machine/chipx.cpp"][11] == ["4"]


def test_an_owner_that_has_a_row_on_the_lines_closes_it(world: World) -> None:
    world.edit("call", lambda doc: entry_doc(doc)["rows"].append(
        {"n": "D", "on": "when", "of": "dosbox-x", "vs": "extra", "text": "The guard returns.",
         "quotes": [{"ref": "dosbox-x:src/ints/call.cpp", "lines": "43", "sha": "a" * 64}]}))
    owner = world.dictionary("call").entries[0]
    dictionary = world.dictionary("family")
    report = closure.check(dictionary, dictionary.entries[0], world.sources(), world.callees(),
                           {"video:call:0x10": owner})
    assert report.faults == [] and report.owed == 0


@pytest.mark.parametrize(("change", "fault"), [
    (set_row("1", of=[["mame"]]), "`of` is one party"),
    (set_entry(regions=[{"ref": 5, "function": "f"}]), "is `ref` with `function`"),
    (set_entry(regions=5), "`regions` is a list"),
    (set_entry(closed=5), "`closed` is a list"),
    (set_head(handlers=5), "`handlers` is a list")])
def test_a_value_of_the_wrong_type_is_a_fault_and_never_a_traceback(
        world: World, change: Callable[[dict[str, Any]], None], fault: str) -> None:
    _, faults = rows.read(world.edit("command", change))
    assert any(fault in f for f in faults), faults


@pytest.mark.parametrize("command", ["cover", "review"])
def test_cover_and_review_over_a_dictionary_with_no_entry_are_invalid(
        cli: Cli, world: World, command: str) -> None:
    world.edit("command", set_head(entries=[]))
    code, out, err = cli(command, str(world.root / "command.json"))
    assert (code, out) == (3, "") and err.startswith("INVALID: nothing was examined")


def test_an_entry_that_no_code_answers_is_a_fault(cli: Cli, world: World) -> None:
    def bare(doc: dict[str, Any]) -> None:
        doc["handlers"] = []
        entry_doc(doc)["regions"] = []
    world.edit("command", bare)
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert "no region answers this entry" in out and code == 3


def test_a_header_handler_keeps_its_preamble_and_its_section(world: World) -> None:
    world.edit("call", lambda d: d.update(handlers=[
        {"ref": "dosbox-x:src/ints/call.cpp", "function": "Handler", "case": ["0x5a"],
         "preamble": True},
        {"ref": "rbil61:INTER.A", "lines": "1-7"}]))
    dictionary = world.dictionary("call")
    got = dictionary.regions(replace_regions(dictionary))
    assert [(r.preamble, r.lines) for r in got] == [(True, ""), (False, "1-7")]


def replace_regions(dictionary: rows.Dictionary) -> rows.Entry:
    import dataclasses
    return dataclasses.replace(dictionary.entries[0], regions=())


def test_a_function_is_held_by_the_emulator_it_belongs_to(world: World) -> None:
    def other(doc: dict[str, Any]) -> None:
        for r in entry_doc(doc)["regions"]:
            if r.get("function") == "chipx_device::tick":
                r["ref"] = "dosbox-x:src/hardware/chipx.cpp"
    path = world.edit("register", other)
    dictionary, _ = rows.read(path)
    assert dictionary is not None
    got = closure._regions_of(dictionary, dictionary.entries[0])
    assert ("dosbox-x", "tick") in got and ("mame", "tick") not in got


def test_a_source_option_that_is_missing_makes_the_check_invalid_and_not_a_fault(
        cli: Cli, world: World) -> None:
    code, _, err = rows_main_without_mame(world)
    assert code == 3 and "no source for mame" in err


def rows_main_without_mame(world: World) -> tuple[int, str, str]:
    import io
    import sys
    err = io.StringIO()
    keep, sys.stderr = sys.stderr, err
    try:
        code = rows.main(["--datasheets", str(world.datasheets), "check",
                          str(world.root / "command.json")])
    finally:
        sys.stderr = keep
    return code, "", err.getvalue()


def test_a_sweeping_word_next_to_punctuation_is_still_marked(cli: Cli, world: World) -> None:
    world.edit("command", set_row("5", text="MAME accepts it always, and never twice."))
    _, out, _ = cli("review", str(world.root / "command.json"))
    assert "row 5  when  of mame differs row 2   [always, never]" in out
