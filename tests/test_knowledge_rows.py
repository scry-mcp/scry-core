"""`scry_core.knowledge.rows` and its closure: an entry as rows that carry their evidence, the
command that stamps, lists, checks and reads them, and what each of its refusals is red on."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rows_world import DICTIONARIES, World, build

from scry_core.knowledge import closure, quote, rows, shared
from scry_core.knowledge.quote import Invalid

ITEMS = {"command": 14, "register": 11, "call": 32, "family": 8}
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


def entry_doc(doc: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = doc["entries"][0]
    return entry


def result(world: World, name: str = "command") -> closure.Report:
    dictionary = world.dictionary(name)
    return closure.check(dictionary, dictionary.entries[0], world.sources(), world.callees(),
                         {e.id: e for e in dictionary.entries})


@pytest.mark.parametrize("name", DICTIONARIES)
def test_each_fixture_entry_closes_with_the_items_the_lister_gives(world: World, name: str) -> None:
    report = result(world, name)
    assert (len(report.results), report.open, report.faults) == (ITEMS[name], 0, [])


@pytest.mark.parametrize("name", DICTIONARIES)
def test_the_command_line_closes_each_fixture_entry_with_exit_zero(cli: Cli, world: World,
                                                                    name: str) -> None:
    code, out, _ = cli("check", str(world.root / f"{name}.json"))
    assert code == 0
    assert f"items {ITEMS[name]}, open 0, faults 0" in out


def test_the_default_regions_are_the_headers_handlers_with_the_keys_own_value(
        world: World) -> None:
    dictionary = world.dictionary("command")
    got = dictionary.regions(dictionary.entries[0])
    assert [(r.function, r.case, r.value) for r in got] == [
        ("chipx_device::write", ("0",), "data=224..231"), ("write_command", (), "val=224..231")]


def test_a_region_the_entry_names_replaces_the_headers_handler_of_that_function(
        world: World) -> None:
    def named(doc: dict[str, Any]) -> None:
        entry_doc(doc)["regions"] = [{"ref": "mame:src/devices/machine/chipx.cpp",
                                      "function": "chipx_device::write", "case": ["1"]}]
    path = world.edit("command", named)
    dictionary, faults = rows.read(path)
    assert dictionary is not None and not faults
    got = dictionary.regions(dictionary.entries[0])
    assert [(r.function, r.case) for r in got] == [("write_command", ()),
                                                   ("chipx_device::write", ("1",))]


# What a dictionary must keep, each refusal named.
def drop_row(n: str) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["rows"] = [r for r in entry_doc(doc)["rows"] if r["n"] != n]
    return change


def drop_subject(subject: str) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["rows"] = [r for r in entry_doc(doc)["rows"] if r["on"] != subject]
    return change


def set_row(which: str, **fields: Any) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        for r in entry_doc(doc)["rows"]:
            if r["n"] == which:
                r.update(fields)
    return change


def set_entry(**fields: Any) -> Callable[[dict[str, Any]], None]:
    return lambda doc: entry_doc(doc).update(fields)


def set_head(**fields: Any) -> Callable[[dict[str, Any]], None]:
    return lambda doc: doc.update(fields)


WORDS = " ".join(["word"] * 31)
QUOTE = {"ref": "mame:src/devices/machine/chipx.cpp", "lines": "10"}


@pytest.mark.parametrize(("change", "fault"), [
    (set_row("1", text=WORDS), "31 words, over 30"),
    (set_row("1", text="tab\there"), "printable ASCII"),
    (set_row("1", text="café"), "printable ASCII"),
    (set_row("1", text=" padded "), "no space around it"),
    (set_row("1", n="toolong7"), "1 to 6 letters or digits"),
    (set_row("2", n="1"), "two rows share a label"),
    (set_row("1", on="shouts"), "not a subject of a command"),
    (set_row("1", of=[]), "one to three of"),
    (set_row("1", of=["mame", "mame"]), "one to three of"),
    (set_row("1", of=["gcc"]), "one to three of"),
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
    (set_entry(address=1), "a command has no placement field (address)"),
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
    (set_head(stores={"mame": "("}), "no pattern"),
    (set_head(defines={"gcc": []}), "`defines` maps a party"),
    (set_head(engine="x"), "`engine` is a list"),
    (set_head(format="scry-knowledge/1"), "is not a `scry-knowledge/2` document"),
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
        return json.dumps({"format": "scry-knowledge/2", "dictionary": "p", "kind": "port",
                           "scope": "chipx", "covers": "c", "entries": [
                               {"key": "0x20", "name": "port", "address": 32, "rows": rows_}]})
    mine = {"n": "1", "on": "is", "of": ["mame"], "text": "A port.", "quotes": [QUOTE]}
    place = {**mine, "n": "2", "on": "place", "text": "At 0x20."}
    assert rows.parse(port([mine, place]))[1] == []
    assert any("needs a row on place" in f for f in rows.parse(port([mine]))[1])


# What `rows check` is red on: each breaks one line the entry covers.
def test_a_row_removed_leaves_its_item_open(world: World) -> None:
    world.edit("command", drop_row("2"))
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


def test_a_row_that_speaks_for_a_party_it_does_not_quote_is_a_fault(world: World) -> None:
    world.edit("command", set_row("1", of=["mame", "dosbox-x"]))
    assert "row 1 speaks for dosbox-x and quotes nothing of it" in result(world).faults


def test_a_row_that_quotes_a_party_it_does_not_speak_for_is_a_fault(world: World) -> None:
    world.edit("call", set_row("1", of=["doc"]))
    assert "row 1 quotes dosbox-x and does not speak for it" in result(world, "call").faults


def test_a_closure_that_closes_no_item_is_a_fault(world: World) -> None:
    def extra(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].append({"ref": "mame:src/devices/machine/chipx.cpp",
                                         "lines": "3", "as": "structure"})
    world.edit("command", extra)
    assert "closed mame:src/devices/machine/chipx.cpp:3 closes no listed item" in result(
        world).faults


def test_a_closure_over_a_line_a_row_claims_closes_nothing_either(world: World) -> None:
    def extra(doc: dict[str, Any]) -> None:
        entry_doc(doc)["closed"].append({"ref": "mame:src/devices/machine/chipx.cpp",
                                         "lines": "17", "as": "structure"})
    world.edit("command", extra)
    assert any("closes no listed item" in f for f in result(world).faults)


def test_a_line_a_closure_covers_is_closed_with_its_reason(world: World) -> None:
    report = result(world, "register")
    assert {r.by for r in report.results if r.item.line in (41, 44)} == {
        "closed: decode", "closed: dead"}


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
                                     if r["function"] != "chipx_device::tick"]
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
    world.edit("command", drop_row("2"))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and "OPEN mame:src/devices/machine/chipx.cpp:17" in out
    assert "open 1, faults" in out


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
    code, out, _ = cli("check", str(world.root / "command.json"), "chipx:command:0xE0..0xE7")
    assert code == 0 and out.count("rows 6") == 1


def test_cover_prints_each_item_with_what_closes_it(cli: Cli, world: World) -> None:
    code, out, _ = cli("cover", str(world.root / "command.json"))
    assert code == 0
    assert "17 branch  if (m_state == state_t::READY)" in out and "<- row 2" in out
    assert "<- the key" in out and "<- callee: none:log" in out and "<- callee: engine" in out


def test_cover_marks_an_open_item_and_exits_one(cli: Cli, world: World) -> None:
    world.edit("command", drop_row("2"))
    code, out, _ = cli("cover", str(world.root / "command.json"))
    assert code == 1 and "<- OPEN" in out


def test_review_prints_each_row_with_the_text_of_its_lines(cli: Cli, world: World) -> None:
    code, out, _ = cli("review", str(world.root / "command.json"))
    assert code == 0
    assert "row 2  when  of mame   [only]" in out
    assert "      17 | else if (m_state == state_t::READY)" in out
    assert "row 6  write  of dosbox-x   [undetermined]" in out
    assert "subjects with several parties: is, write" in out


def test_review_names_the_subjects_several_parties_speak_on_and_the_closures(
        cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "call.json"))
    assert "subjects with several parties: is, in DS:DX, out CF=0" in out
    assert "closed dosbox-x:src/ints/call.cpp 7 as unseen (no program can see the flag)" in out
    assert "callee decisions used:" in out and "create_file shared:dos:call:0x21/0x3C" in out


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
    assert code == 0 and "stamped 2 quotes, 4 already held a digest" in out
    code, out, _ = cli("check", str(path))
    assert code == 0
    code, out, _ = cli("quote", "--stamp", str(path), callees=False)
    assert "stamped 0 quotes, 6 already held" in out


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


def test_stores_that_are_not_a_mapping_of_patterns_are_refused(world: World) -> None:
    _, faults = rows.read(world.edit("command", set_head(stores=["x"])))
    assert any("`stores` maps a party" in f for f in faults)


def test_a_handler_of_a_key_with_no_numbers_gets_no_value(tmp_path: Path) -> None:
    doc = {"format": "scry-knowledge/2", "dictionary": "d", "kind": "device", "scope": "chipx",
           "covers": "c", "handlers": [{"ref": "mame:x.cpp", "function": "f", "value": "v"}],
           "entries": [{"key": "chipx", "name": "chip", "rows": [
               {"n": "1", "on": "is", "of": ["mame"], "text": "A chip.", "quotes": [QUOTE]},
               {"n": "2", "on": "reset", "of": ["mame"], "text": "Resets.", "quotes": [QUOTE]}]}]}
    dictionary, faults = rows.parse(json.dumps(doc))
    assert dictionary is not None and faults == []
    assert dictionary.regions(dictionary.entries[0])[0].value == ""


def test_a_dictionary_with_a_fault_prints_it_beside_the_reports(cli: Cli, world: World) -> None:
    world.edit("command", set_row("1", text=WORDS))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and "- chipx:command:0xE0..0xE7, row 1: `text` is 31 words" in out


def test_a_check_without_a_callee_table_leaves_the_calls_open(cli: Cli, world: World) -> None:
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
        return json.dumps({"format": "scry-knowledge/2", "dictionary": "v", "kind": "vector",
                           "scope": "chipx", "covers": "c", "entries": [
                               {"key": "0x08", "name": "tick", "address": 8, "length": 4,
                                "rows": rows_}]})
    mine = {"n": "1", "on": "is", "of": ["mame"], "text": "A vector.", "quotes": [QUOTE]}
    assert any("needs a row on place" in f for f in rows.parse(vector([mine]))[1])
    assert rows.parse(vector([mine, {**mine, "n": "2", "on": "place"}]))[1] == []


def test_review_leaves_out_what_an_entry_has_none_of(cli: Cli, world: World) -> None:
    _, out, _ = cli("review", str(world.root / "family.json"))
    assert "subjects with several parties" not in out and "callee decisions" not in out


def test_a_row_with_two_quotes_over_one_line_claims_it_once(world: World) -> None:
    both = {"quotes": [{**QUOTE, "lines": "10-11", "sha": "a" * 64},
                       {**QUOTE, "lines": "11-12", "sha": "a" * 64}]}
    world.edit("command", set_row("1", **both))
    dictionary = world.dictionary("command")
    claims = closure._claims(dictionary.entries[0])
    assert claims["mame:src/devices/machine/chipx.cpp"][11] == ["1"]


def test_an_owner_that_has_a_row_on_the_lines_closes_it(world: World) -> None:
    world.edit("call", lambda doc: entry_doc(doc)["rows"].append(
        {"n": "11", "on": "when", "of": ["dosbox-x"], "text": "The guard returns.",
         "quotes": [{"ref": "dosbox-x:src/ints/call.cpp", "lines": "43", "sha": "a" * 64}]}))
    owner = world.dictionary("call").entries[0]
    dictionary = world.dictionary("family")
    report = closure.check(dictionary, dictionary.entries[0], world.sources(), world.callees(),
                           {"video:call:0x10": owner})
    assert report.faults == [] and report.owed == 0


@pytest.mark.parametrize(("change", "fault"), [
    (set_row("1", of=[["mame"]]), "`of` is one to three"),
    (set_entry(regions=[{"ref": 5, "function": "f"}]), "is `ref` with `function`"),
    (set_entry(regions=5), "`regions` is a list"),
    (set_entry(closed=5), "`closed` is a list"),
    (set_head(handlers=5), "`handlers` is a list")])
def test_a_value_of_the_wrong_type_is_a_fault_and_never_a_traceback(
        world: World, change: Callable[[dict[str, Any]], None], fault: str) -> None:
    _, faults = rows.read(world.edit("command", change))
    assert any(fault in f for f in faults), faults


def test_a_stores_pattern_that_does_not_compile_is_a_fault_and_the_check_still_runs(
        cli: Cli, world: World) -> None:
    world.edit("command", set_head(stores={"mame": "("}))
    code, out, _ = cli("check", str(world.root / "command.json"))
    assert code == 1 and "`stores` of mame is no pattern" in out and "faults 1" in out


@pytest.mark.parametrize("command", ["cover", "review"])
def test_cover_and_review_over_a_dictionary_with_no_entry_are_invalid(
        cli: Cli, world: World, command: str) -> None:
    world.edit("command", set_head(entries=[]))
    code, out, err = cli(command, str(world.root / "command.json"))
    assert (code, out) == (3, "") and err.startswith("INVALID: nothing was examined")


def test_an_entry_that_no_code_answers_is_a_fault(cli: Cli, world: World) -> None:
    world.edit("command", lambda d: d.update(handlers=[]))
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
            if r["function"] == "chipx_device::tick":
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
        code = rows.main(["check", str(world.root / "command.json")])
    finally:
        sys.stderr = keep
    return code, "", err.getvalue()


def test_a_sweeping_word_next_to_punctuation_is_still_marked(cli: Cli, world: World) -> None:
    world.edit("command", set_row("2", text="MAME accepts it always, and never twice."))
    _, out, _ = cli("review", str(world.root / "command.json"))
    assert "row 2  when  of mame   [always, never]" in out
