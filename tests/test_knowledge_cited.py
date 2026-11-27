"""`scry_core.knowledge.cited`: an `agrees` cites an effect, a call with several bodies is judged
in each, an `unfollowed` closes a call the table does not follow, an `absent` cites a whole body;
and a `doc` row quotes its entry's official region."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from rows_world import World, build, drop_row, entry_doc, git_repo, result, set_row

from scry_core.knowledge import closure, cover, review, rows

MAME = "mame:src/devices/machine/chipx.cpp"
DOSBOX = "dosbox-x:src/hardware/chipx.cpp"
DRIVE = "src/devices/machine/drive.cpp"
TAKE = "dosbox-x:src/ints/take.cpp"
SHEET = "datasheet:chipx.raw.txt"
Change = Callable[[dict[str, Any]], None]
NO_EFFECT = ": its lines hold no effect, only "


@pytest.fixture
def world(tmp_path: Any) -> World:
    return build(tmp_path)


def agrees(ref: str, lines: str, row: str, reason: str = "agrees") -> dict[str, str]:
    return {"ref": ref, "lines": lines, "as": reason, "row": row}


def closed_with(*closures: dict[str, str]) -> Change:
    return lambda doc: entry_doc(doc)["closed"].extend(closures)


def without_agrees(*closures: dict[str, str]) -> Change:
    def change(doc: dict[str, Any]) -> None:
        kept = [c for c in entry_doc(doc)["closed"] if c["as"] != "agrees"]
        entry_doc(doc)["closed"] = [*kept, *closures]
    return change


def faults(world: World, name: str = "command") -> list[str]:
    return result(world, name).faults


@pytest.mark.parametrize(("lines", "only"), [("24", "branch"), ("13", "key"), ("10", "path")])
def test_an_agrees_whose_lines_are_a_condition_a_decode_or_a_label_is_red(
        world: World, lines: str, only: str) -> None:
    world.edit("command", without_agrees(agrees(MAME, lines, "3")))
    assert f"agrees {MAME}:{lines} on row 3{NO_EFFECT}{only}:" in " ".join(faults(world))


def test_an_agrees_that_cites_the_branch_and_its_body_holds(world: World) -> None:
    world.edit("command", without_agrees(agrees(MAME, "24-27", "3")))
    assert faults(world) == []


def test_an_agrees_over_a_call_the_table_does_not_follow_is_red(world: World) -> None:
    world.edit("command", set_row("8", vs="extra", row=""))
    world.edit("command", closed_with(agrees(DOSBOX, "12", "3")))
    assert any(f.startswith(f"agrees {DOSBOX}:12 on row 3{NO_EFFECT}call:")
               for f in faults(world)), faults(world)


def test_an_agrees_that_returns_the_value_holds(world: World) -> None:
    world.edit("register", without_agrees(agrees(MAME, "43", "2")))
    assert faults(world, "register") == []


def opened(*closures: dict[str, str]) -> Change:
    def change(doc: dict[str, Any]) -> None:
        drop_row("3")(doc)
        drop_row("4")(doc)
        entry_doc(doc)["closed"].extend(closures)
    return change


def test_a_followed_call_counts_only_when_the_verdict_cites_an_effect_in_its_body(
        world: World) -> None:
    world.edit("register", opened(agrees(MAME, "55", "2"),
                                  {"ref": MAME, "lines": "49-50", "as": "structure"}))
    assert any(f.startswith(f"agrees {MAME}:55 on row 2{NO_EFFECT}") for f in faults(
        world, "register"))
    world.edit("register", lambda doc: entry_doc(doc).update(closed=[
        c for c in entry_doc(doc)["closed"] if c["as"] != "structure"]))
    world.edit("register", closed_with(agrees(MAME, "49-50", "2")))
    assert faults(world, "register") == []


# A call with several bodies: a drive's open reaches one of two file systems.
DRIVE_SOURCE = """// synthetic source for the tests of the row tools: it is not MAME code

void drive_device::open(uint8_t data)
{
	m_drive->file_open(data);
}

int local_drive::file_open(uint8_t data)
{
	m_opened = data;
	return 1;
}

int fat_drive::file_open(uint8_t data)
{
	if (data & 0x80)
		return 0;
	m_opened = data;
	return 1;
}
"""


def drive_world(world: World, closed: list[dict[str, str]],
                change: Change | None = None) -> closure.Report:
    (world.mame / DRIVE).write_text(DRIVE_SOURCE, encoding="utf-8")
    table = json.loads((world.root / "callees.json").read_text(encoding="utf-8"))
    table["callees"]["mame:file_open"] = [f"{DRIVE} local_drive::file_open",
                                          f"{DRIVE} fat_drive::file_open"]
    (world.root / "callees.json").write_text(json.dumps(table), encoding="utf-8")
    doc = {"format": rows.FORMAT, "dictionary": "drive", "title": "A synthetic drive",
           "kind": "command", "scope": "chipx", "covers": "c", "source": "official",
           "documents": [{"name": "chipx.raw.txt", "variant": "chipx"}],
           "official": {"chipx.raw.txt": ["10-11"]},
           "entries": [{"key": "0xE0..0xE7", "name": "open", "regions": [
               {"ref": SHEET, "lines": "10-11"},
               {"ref": f"mame:{DRIVE}", "function": "drive_device::open"}],
               "rows": [{"n": "1", "on": "is", "of": "doc", "text": "Opens.",
                         "quotes": [{"ref": SHEET, "lines": "10"}]},
                        {"n": "2", "on": "write", "of": "doc", "text": "Opens a file.",
                         "quotes": [{"ref": SHEET, "lines": "11"}]}],
               "closed": closed}]}
    if change:
        change(doc)
    path = world.root / "drive.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    rows._stamp_file(path, world.sources())
    return result(world, "drive")


def test_an_agrees_through_a_call_with_several_bodies_cites_an_effect_in_each(
        world: World) -> None:
    got = drive_world(world, [agrees(f"mame:{DRIVE}", "5", "2"),
                              agrees(f"mame:{DRIVE}", "10", "2"),
                              agrees(f"mame:{DRIVE}", "18", "2")])
    assert got.faults == []


@pytest.mark.parametrize("fat", ["16", ""])
def test_an_agrees_through_a_call_with_several_bodies_missing_one_is_red(
        world: World, fat: str) -> None:
    closed = [agrees(f"mame:{DRIVE}", "5", "2"), agrees(f"mame:{DRIVE}", "10", "2")]
    got = drive_world(world, closed + ([agrees(f"mame:{DRIVE}", fat, "2")] if fat else []))
    assert any(f"goes through m_drive->file_open, which has several bodies, and cites no effect "
               f"in {DRIVE} fat_drive::file_open" in f for f in got.faults), got.faults
    assert (any(f.startswith(f"agrees mame:{DRIVE}:16 on row 2{NO_EFFECT}branch")
                for f in got.faults)) == (fat == "16")


def test_an_unfollowed_closes_a_call_the_table_does_not_follow_and_review_says_so(
        world: World) -> None:
    got = drive_world(world, [agrees(f"mame:{DRIVE}", "5", "2", "unfollowed")])
    assert got.faults == []
    dictionary = world.dictionary("drive")
    text = review.entry_text(dictionary, dictionary.entries[0], got, world.sources())
    assert ("mame leaves row 2 unfollowed: what it does there was not established (1 place)"
            in text and "as documented" not in text)


def test_an_unfollowed_over_lines_that_hold_no_such_call_is_red(world: World) -> None:
    world.edit("command", without_agrees(agrees(MAME, "26", "3", "unfollowed")))
    assert any(f.startswith(f"unfollowed {MAME}:26 on row 3: its lines hold no call")
               for f in faults(world))


def test_a_closure_in_a_body_no_call_of_the_entry_reaches_closes_nothing(world: World) -> None:
    got = drive_world(world, [agrees(f"mame:{DRIVE}", "5", "2"),
                              agrees(f"mame:{DRIVE}", "10", "2"),
                              agrees(f"mame:{DRIVE}", "18", "2")])
    assert got.faults == []
    table = json.loads((world.root / "callees.json").read_text(encoding="utf-8"))
    table["callees"]["mame:file_open"] = "engine"
    (world.root / "callees.json").write_text(json.dumps(table), encoding="utf-8")
    again = result(world, "drive").faults
    assert f"closed mame:{DRIVE}:10 closes no listed item" in again


@pytest.mark.parametrize(("lines", "whole"), [
    (["5-8"], True), (["3-14"], True), (["9-13"], True), (["5-7"], False), (["6"], False),
    (["3-8", "9-14"], True), (["3-8", "10-14"], False)])
def test_an_absent_note_cites_one_whole_body(world: World, lines: list[str], whole: bool) -> None:
    world.edit("command", set_row("7", quotes=[{"ref": DOSBOX, "lines": x} for x in lines]))
    rows._stamp_file(world.root / "command.json", world.sources())
    red = [f for f in faults(world) if "an `absent` note cites the whole body" in f]
    assert (red == []) == whole, red


def test_an_absent_note_claims_none_of_the_lines_it_cites(world: World) -> None:
    world.edit("command", drop_row("6"))
    world.edit("command", set_row("7", quotes=[{"ref": DOSBOX, "lines": "3-14"}]))
    rows._stamp_file(world.root / "command.json", world.sources())
    assert any(f.startswith(f"OPEN {DOSBOX}:4 branch") for f in faults(world)), faults(world)


def test_the_bodies_of_a_function_are_its_own_its_blocks_and_its_cases(world: World) -> None:
    source = (world.mame / "src/devices/machine/chipx.cpp").read_text(encoding="utf-8")
    got = cover.bodies(source, "chipx_device::write")
    assert {(8, 37), (9, 37), (10, 36), (12, 31), (33, 35), (14, 16), (20, 29)} <= set(got)
    assert (12, 30) not in got


def test_a_doc_row_that_quotes_outside_its_entrys_official_region_is_red(world: World) -> None:
    world.edit("command", set_row("3", quotes=[{"ref": SHEET, "lines": "31"}]))
    rows._stamp_file(world.root / "command.json", world.sources())
    assert any(f"row 3 quotes {SHEET}:31, outside the entry's official region" in f
               for f in faults(world))


def test_a_region_the_header_gives_every_entry_counts_as_its_official_region(
        world: World) -> None:
    def to_header(doc: dict[str, Any]) -> None:
        doc["handlers"].append(entry_doc(doc)["regions"].pop())
    world.edit("command", to_header)
    assert not any("outside the entry's official region" in f for f in faults(world))
    world.edit("command", set_row("3", quotes=[{"ref": SHEET, "lines": "31"}]))
    rows._stamp_file(world.root / "command.json", world.sources())
    assert any("outside the entry's official region" in f for f in faults(world))


# The dodges a writer could take with a trivial change to the cited range.
def test_an_agrees_wider_than_a_quote_is_red(world: World) -> None:
    world.edit("command", without_agrees(agrees(MAME, "20-34", "3")))
    assert any(f.startswith(f"agrees {MAME}:20-34 on row 3: 15 lines") for f in faults(world))


def test_the_return_of_a_dosbox_callback_is_no_effect(world: World) -> None:
    world.edit("call", lambda doc: entry_doc(doc)["closed"].append(
        agrees("dosbox-x:src/ints/call.cpp", "5", "4")))
    assert any(f.startswith(f"agrees dosbox-x:src/ints/call.cpp:5 on row 4{NO_EFFECT}")
               and "exit" in f for f in faults(world, "call")), faults(world, "call")


def test_an_unfollowed_over_a_call_the_table_says_does_nothing_is_red(world: World) -> None:
    world.edit("command", set_row("8", vs="extra", row=""))
    world.edit("command", closed_with(agrees(DOSBOX, "10", "3", "unfollowed")))
    assert any(f.startswith(f"unfollowed {DOSBOX}:10 on row 3: its lines hold no call")
               for f in faults(world))


def test_a_call_with_several_bodies_no_verdict_or_note_covers_is_open(world: World) -> None:
    got = drive_world(world, [agrees(f"mame:{DRIVE}", "4", "2")])
    assert any(f.startswith(f"OPEN mame:{DRIVE}:5 call m_drive->file_open") for f in got.faults)


def test_a_closure_over_the_call_and_one_body_still_owes_the_other_body(world: World) -> None:
    def own_body(doc: dict[str, Any]) -> None:
        entry_doc(doc)["regions"].append({"ref": f"mame:{DRIVE}",
                                          "function": "local_drive::file_open"})
    got = drive_world(world, [agrees(f"mame:{DRIVE}", "5-10", "2"),
                              {"ref": f"mame:{DRIVE}", "lines": "11", "as": "structure"}],
                      own_body)
    assert any("cites no effect in " + f"{DRIVE} fat_drive::file_open" in f
               for f in got.faults), got.faults


def test_an_absent_note_with_a_quote_in_a_second_file_is_red(world: World) -> None:
    elsewhere = "dosbox-x:src/ints/call.cpp"
    world.edit("command", set_row("7", quotes=[{"ref": DOSBOX, "lines": "5-8"},
                                               {"ref": elsewhere, "lines": "1"}]))
    rows._stamp_file(world.root / "command.json", world.sources())
    assert any("an `absent` note cites the whole body" in f for f in faults(world))


def test_an_absent_note_cites_a_body_inside_the_region_not_elsewhere_in_the_function(
        world: World) -> None:
    world.edit("command", set_row("5", vs="absent", quotes=[{"ref": MAME, "lines": "33-35"}]))
    rows._stamp_file(world.root / "command.json", world.sources())
    assert any(f.startswith("row 5: an `absent` note cites the whole body") for f in faults(world))


def test_a_followed_call_into_another_file_counts_with_the_effect_cited_there(
        world: World) -> None:
    other = "src/devices/machine/drive_local.cpp"
    (world.mame / other).write_text(DRIVE_SOURCE, encoding="utf-8")

    def follow(doc: dict[str, Any]) -> None:
        entry_doc(doc)["regions"].append({"ref": f"mame:{other}",
                                          "function": "local_drive::file_open"})
    closed = [agrees(f"mame:{DRIVE}", "5", "2"), agrees(f"mame:{other}", "10", "2"),
              {"ref": f"mame:{other}", "lines": "11", "as": "structure"}]
    drive_world(world, closed, follow)
    table = json.loads((world.root / "callees.json").read_text(encoding="utf-8"))
    table["callees"]["mame:file_open"] = "open:local_drive::file_open"
    (world.root / "callees.json").write_text(json.dumps(table), encoding="utf-8")
    assert result(world, "drive").faults == []


def test_a_verdict_that_cites_more_places_than_a_row_quotes_is_red(world: World) -> None:
    places = [agrees(MAME, str(n), "3") for n in (24, 25, 26, 27, 28, 29, 30)]
    world.edit("command", without_agrees(*places))
    assert any(f.startswith(f"agrees of mame on row 3 cites 7 places, over {rows.QUOTES_PER_ROW}")
               for f in faults(world)), faults(world)


# What the lines of an `agrees` show on a row about an input register and on one that is not.
TAKE_SOURCE = """// synthetic source for the tests of the row tools: it is not DOSBox-X code

static void Take(uint32_t length) {
	uint8_t drive;
	MEM_StrCopy(SegPhys(ds) + reg_dx, name1, DOSNAMEBUF);
	uint32_t handle = RealHandle(reg_bx);
	if (reg_dx > 1) {
		return;
	}
	if (reg_cl & 1) drive |= 8;
	length &= 3;
}
"""


def take_world(world: World, closed: list[dict[str, str]],
               change: Change | None = None) -> closure.Report:
    (world.dosbox / "src/ints/take.cpp").write_text(TAKE_SOURCE, encoding="utf-8")
    again = World(world.root, git_repo(world.dosbox))

    def take(doc: dict[str, Any]) -> None:
        entry = entry_doc(doc)
        entry["regions"] = [{"ref": TAKE, "function": "Take"}, entry["regions"][-1]]
        entry["closed"] = closed
    again.edit("call", take)
    if change:
        again.edit("call", change)
    return result(again, "call")


def red(got: closure.Report, lines: str, row: str) -> list[str]:
    return [f for f in got.faults if f.startswith(f"agrees {TAKE}:{lines} on row {row}{NO_EFFECT}")]


@pytest.mark.parametrize(("row", "holds"), [("3", True), ("2", False), ("4", False)])
def test_an_agrees_that_hands_a_register_on_holds_on_the_in_row_of_that_register_only(
        world: World, row: str, holds: bool) -> None:
    got = red(take_world(world, [agrees(TAKE, "5", row)]), "5", row)
    assert (got == []) == holds, got


def test_an_agrees_that_hands_a_register_on_shows_nothing_on_a_row_about_an_output(
        world: World) -> None:
    got = take_world(world, [agrees(TAKE, "5", "4")], set_row("4", on="out DX"))
    assert red(got, "5", "4")


def test_an_agrees_that_only_tests_a_register_shows_nothing_even_on_an_in_row(
        world: World) -> None:
    assert red(take_world(world, [agrees(TAKE, "7", "3")]), "7", "3")


def test_an_agrees_that_sets_a_local_holds_on_any_row(world: World) -> None:
    assert red(take_world(world, [agrees(TAKE, "10", "4")]), "10", "4") == []


def test_an_agrees_over_the_result_of_a_call_kept_in_a_local_shows_nothing(world: World) -> None:
    got = take_world(world, [agrees(TAKE, "6", "4")])
    assert red(got, "6", "4"), got.faults


def test_a_closure_over_the_assignment_to_a_parameter_alone_closes_no_listed_item(
        world: World) -> None:
    got = take_world(world, [agrees(TAKE, "11", "4")])
    assert f"closed {TAKE}:11 closes no listed item" in got.faults
    assert red(got, "11", "4") == []


def test_a_local_and_an_input_are_owed_no_row(world: World) -> None:
    got = take_world(world, [])
    assert [f for f in got.faults if f.startswith("OPEN") and ("local" in f or "input" in f)] == []
    assert any(f.startswith(f"OPEN {TAKE}:6 call RealHandle") for f in got.faults)
