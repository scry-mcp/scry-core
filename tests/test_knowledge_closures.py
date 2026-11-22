"""What a verdict and an owned closure close (`rows check`): a callee decided per entry, a note and
a verdict of another row on one line, an `agrees` that does nothing, a callee that writes the
guest, an `unfollowed` that is only the call, and an owner that has to be written."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from rows_world import World, build, git_repo

from scry_core.knowledge import cited, closure, quote, review, rows, shared

KEEP = """// synthetic source for the tests of the row tools: it is not DOSBox-X code

static Bitu Keep(void) {
	switch (reg_ah) {
	case 0x10:
		if (!has_ega)
			break;
		reg_bh = 0;
		set_size();
		break;
	case 0x20:
		break;
	case 0x30:
		if (!has_ega) {
			reg_bh = 1;
			break;
		}
		real_writeb(0x40, 0x89, reg_al);
		CALLBACK_SCF(false);
		set_size();
		break;
	}
	return CBRET_NONE;
}

static void set_size(void) {
	reg_bl = 3;
}
"""
LIST = """INT 77 - SYNTHETIC - REPORT MEMORY
	AH = 10h
Return: BH = 00h, BL = memory size
Note: BH is unchanged when no EGA is present
INT 77 - SYNTHETIC - NOTHING
	AH = 20h
Return: nothing
INT 77 - SYNTHETIC - SET SWITCH
	AH = 30h
Return: CF clear, the switch byte at 0040h:0089h written
	BL = memory size
Note: BH is unchanged when no EGA is present
"""
REF = "dosbox-x:src/ints/keep.cpp"
LIST_REF = "rbil61:KEEP.A"
Change = Callable[[dict[str, Any]], None]


def doc(n: str, on: str, text: str, lines: str) -> dict[str, Any]:
    return {"n": n, "on": on, "of": "doc", "text": text,
            "quotes": [{"ref": LIST_REF, "lines": lines}]}


def shut(lines: str, row: str, reason: str = "agrees", **more: Any) -> dict[str, Any]:
    return {"ref": REF, "lines": lines, "as": reason, "row": row, **more}


def entry(key: str, case: str, lines: str, rows_: list[dict[str, Any]],
          closed: list[dict[str, Any]], *more: dict[str, str]) -> dict[str, Any]:
    return {"key": key, "name": f"call {key}", "regions": [
        {"ref": REF, "function": "Keep", "case": [case]}, *more,
        {"ref": LIST_REF, "lines": lines}],
        "rows": rows_, "closed": [{"ref": REF, "lines": "4", "as": "key"}, *closed]}


def dictionary() -> dict[str, Any]:
    return {"format": rows.FORMAT, "dictionary": "keep", "title": "A synthetic call that keeps",
            "kind": "call", "scope": "dos", "covers": "c", "source": "official", "entries": [
                entry("0x77/0x10", "0x10", "1-4", [
                    doc("1", "is", "Reports memory.", "1-2"),
                    doc("2", "out BH", "BH is 00h and BL the memory size.", "3"),
                    doc("3", "when", "BH is unchanged when no EGA is present.", "4")],
                    [shut("8-9", "2"), shut("27", "2"), shut("6-7", "3", nothing=True)],
                    {"ref": REF, "function": "set_size"}),
                entry("0x77/0x20", "0x20", "5-7", [
                    doc("1", "is", "Does nothing.", "5-6"),
                    doc("2", "out none", "Nothing is returned.", "7")],
                    [shut("11-12", "2", nothing=True)]),
                entry("0x77/0x30", "0x30", "8-12", [
                    doc("1", "is", "Sets the switch.", "8-9"),
                    doc("2", "out CF=0", "CF is clear and the switch byte is written.", "10"),
                    doc("3", "out BL", "BL holds the memory size.", "11"),
                    doc("4", "when", "BH is unchanged when no EGA is present.", "12"),
                    {"n": "5", "on": "when", "of": "dosbox-x", "vs": "differs", "row": "4",
                     "text": "With no EGA BH is set to 01h.",
                     "quotes": [{"ref": REF, "lines": "14-17"}]}],
                    [shut("18", "2"), shut("20", "3", "unfollowed")])]}


def keep_world(tmp_path: Any, change: Change | None = None,
               callees: dict[str, Any] | None = None, source: str = KEEP) -> World:
    world = build(tmp_path)
    (world.dosbox / "src/ints/keep.cpp").write_text(source, encoding="utf-8")
    (world.rbil / "KEEP.A").write_text(LIST, encoding="utf-8")
    world = World(world.root, git_repo(world.dosbox))
    table = json.loads((world.root / "callees.json").read_text(encoding="utf-8"))
    table["callees"].update({"dosbox-x:set_size": "open", "dosbox-x:real_writeb": "writes",
                             **(callees or {})})
    (world.root / "callees.json").write_text(json.dumps(table), encoding="utf-8")
    doc_ = dictionary()
    if change:
        change(doc_)
    path = world.root / "keep.json"
    path.write_text(json.dumps(doc_), encoding="utf-8")
    rows._stamp_file(path, world.sources())
    return world


def check(world: World, key: str, *, partial: bool = True) -> closure.Report:
    got = world.dictionary("keep")
    mine = next(e for e in got.entries if e.key == key)
    return closure.check(got, mine, world.sources(), world.callees(),
                         {e.id: e for e in got.entries}, partial=partial)


def of(key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda doc_: next(e for e in doc_["entries"] if e["key"] == key)


def edit(key: str, **fields: Any) -> Change:
    return lambda doc_: of(key)(doc_).update(fields)


def closures(key: str, *closed: dict[str, Any]) -> Change:
    return edit(key, closed=[{"ref": REF, "lines": "4", "as": "key"}, *closed])


KEYS = ("0x77/0x10", "0x77/0x20", "0x77/0x30")


@pytest.mark.parametrize("key", KEYS)
def test_the_world_closes_every_entry(tmp_path: Any, key: str) -> None:
    assert check(keep_world(tmp_path), key).faults == []


# A callee is decided per entry.

def test_an_open_callee_is_open_where_its_body_is_a_region_and_owed_to_that_entry_elsewhere(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path)
    report = check(world, "0x77/0x30")
    assert {r.by for r in report.results if r.item.line == 20} == {
        "callee: shared:dos:call:0x77/0x10"}
    report = check(world, "0x77/0x10")
    assert {r.by for r in report.results if r.item.line == 9} == {"callee: open"}


def test_an_open_callee_no_entry_holds_as_a_region_is_open(tmp_path: Any) -> None:
    def no_body(doc_: dict[str, Any]) -> None:
        mine = of("0x77/0x10")(doc_)
        mine["regions"] = [r for r in mine["regions"] if r.get("function") != "set_size"]
        mine["closed"] = [c for c in mine["closed"] if c["lines"] != "27"]
    got = check(keep_world(tmp_path, no_body), "0x77/0x30").faults
    assert f"OPEN {REF}:20 call set_size" in got


# A line may serve a note and a verdict of another row.

def test_a_line_a_note_claims_may_close_a_verdict_of_another_row(tmp_path: Any) -> None:
    note = {"n": "6", "on": "out BH", "of": "dosbox-x", "vs": "extra",
            "text": "BH is cleared before the size is set.", "quotes": [{"ref": REF, "lines": "8"}]}
    world = keep_world(tmp_path, lambda d: of("0x77/0x10")(d)["rows"].append(note))
    assert check(world, "0x77/0x10").faults == []


def test_a_note_and_a_verdict_of_its_own_row_on_one_line_are_two_classes(tmp_path: Any) -> None:
    note = {"n": "6", "on": "out BH", "of": "dosbox-x", "vs": "differs", "row": "2",
            "text": "BH is cleared before the size is set.", "quotes": [{"ref": REF, "lines": "8"}]}
    world = keep_world(tmp_path, lambda d: of("0x77/0x10")(d)["rows"].append(note))
    assert any("row 2 has verdicts of dosbox-x of 2 classes" in f
               for f in check(world, "0x77/0x10").faults)


# An `agrees` that does nothing.

@pytest.mark.parametrize(("key", "lines", "row"), [("0x77/0x10", "6", "3"),
                                                   ("0x77/0x10", "6-8", "3"),
                                                   ("0x77/0x20", "12", "2")])
def test_an_agrees_marked_nothing_over_lines_that_are_not_one_whole_body_is_red(
        tmp_path: Any, key: str, lines: str, row: str) -> None:
    kept = [c for c in dictionary()["entries"][KEYS.index(key)]["closed"]
            if c.get("row") != row and c["as"] != "key"]
    world = keep_world(tmp_path, closures(key, *kept, shut(lines, row, nothing=True)))
    assert any(f.startswith(f"agrees {REF}:{lines} on row {row}, marked `nothing`: it cites one "
                            "whole body") for f in check(world, key).faults)


def test_an_agrees_marked_nothing_over_a_body_that_stores_what_its_row_names_is_red(
        tmp_path: Any) -> None:
    def instead(doc_: dict[str, Any]) -> None:
        mine = of("0x77/0x30")(doc_)
        mine["rows"] = [r for r in mine["rows"] if r["n"] != "5"]
        mine["closed"].append(shut("14-17", "4", nothing=True))
    got = check(keep_world(tmp_path, instead), "0x77/0x30").faults
    assert any(f.startswith(f"agrees {REF}:14-17 on row 4, marked `nothing`: line 15 stores BH")
               for f in got), got


def test_an_agrees_marked_nothing_holds_over_a_body_that_stores_another_register(
        tmp_path: Any) -> None:
    def instead(doc_: dict[str, Any]) -> None:
        mine = of("0x77/0x30")(doc_)
        mine["rows"][3]["text"] = "AH is unchanged when no EGA is present."
        mine["rows"][4].update(vs="extra", row="")
        mine["closed"].append(shut("14-17", "4", nothing=True))
    assert check(keep_world(tmp_path, instead), "0x77/0x30").faults == []


def test_an_agrees_marked_nothing_closes_none_of_the_stores_its_body_holds(tmp_path: Any) -> None:
    def instead(doc_: dict[str, Any]) -> None:
        mine = of("0x77/0x30")(doc_)
        mine["rows"] = [r for r in mine["rows"] if r["n"] != "5"]
        mine["rows"][-1]["text"] = "AH is unchanged when no EGA is present."
        mine["closed"].append(shut("14-17", "4", nothing=True))
    assert check(keep_world(tmp_path, instead), "0x77/0x30").faults == [
        f"OPEN {REF}:15 store reg_bh ="]


def test_an_agrees_marked_nothing_over_a_body_that_calls_what_the_table_does_not_read_is_red(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path, lambda d: of("0x77/0x10")(d)["closed"].__setitem__(
        slice(None), [{"ref": REF, "lines": "4", "as": "key"}, shut("27", "2"),
                      shut("6-7", "3", nothing=True), shut("5-10", "2", nothing=True)]))
    assert any(f.startswith(f"agrees {REF}:5-10 on row 2, marked `nothing`: it calls set_size "
                            "(line 9), whose effect") for f in check(world, "0x77/0x10").faults)


@pytest.mark.parametrize(("named", "stored", "changed"), [
    ("al", "ax", True), ("ah", "eax", True), ("ax", "al", True), ("al", "ah", False),
    ("ds", "dx", False), ("di", "dx", False), ("bp", "bx", False), ("si", "esi", True)])
def test_a_store_changes_a_register_it_holds_or_that_holds_it(named: str, stored: str,
                                                            changed: bool) -> None:
    assert cited._overlaps(named, stored) is changed


def test_an_agrees_marked_nothing_on_a_row_that_names_no_register_holds_no_write(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path, closures("0x77/0x30", shut("13-21", "2", nothing=True),
                                          shut("20", "3", "unfollowed")))
    got = check(world, "0x77/0x30").faults
    assert any(f.startswith(f"agrees {REF}:13-21 on row 2, marked `nothing`: line 15, 18 stores "
                            "anything") for f in got), got


def test_nothing_goes_on_an_agrees_only(tmp_path: Any) -> None:
    world = keep_world(tmp_path, closures("0x77/0x20", shut("11-12", "2", "unfollowed",
                                                            nothing=True)))
    got, faults = rows.read(world.root / "keep.json")
    assert any("`nothing` is `true` on an `agrees`, or absent" in f for f in faults)


def test_review_prints_an_agrees_marked_nothing_as_doing_nothing(tmp_path: Any) -> None:
    world = keep_world(tmp_path)
    got = world.dictionary("keep")
    mine = got.entries[1]
    text = review.entry_text(got, mine, check(world, mine.key), world.sources())
    assert ("dosbox-x agrees with row 2 by doing nothing: the whole body below stores nothing "
            "of what the row names (1 place)") in text


# A callee that writes the guest's state.

def test_a_call_to_a_callee_that_writes_is_an_effect(tmp_path: Any) -> None:
    world = keep_world(tmp_path, callees={"dosbox-x:real_writeb": "none:accessor"})
    assert any(f.startswith(f"agrees {REF}:18 on row 2: its lines hold no effect, only call")
               for f in check(world, "0x77/0x30").faults)


def test_a_call_to_a_callee_that_writes_is_owed_as_a_store_is(tmp_path: Any) -> None:
    world = keep_world(tmp_path, closures("0x77/0x30", shut("20", "3", "unfollowed"),
                                          {"ref": REF, "lines": "19", "as": "structure"}))
    faults = check(world, "0x77/0x30").faults
    assert f"OPEN {REF}:18 call real_writeb" in faults


# `unfollowed` is the call and nothing else.

def test_an_unfollowed_whose_lines_hold_an_effect_of_the_entry_beside_the_call_is_red(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path, closures("0x77/0x30", shut("18", "2"),
                                          shut("18-20", "3", "unfollowed")))
    assert any(f.startswith(f"unfollowed {REF}:18-20 on row 3: line 18 holds an effect of the "
                            "entry's own code (call)") for f in check(world, "0x77/0x30").faults)


# What a region reaches: a member another function reads, a table it indexes.

REACHED = KEEP.replace("\treg_bl = 3;\n}\n", """\treg_bl = 3;
	memsize = sizes[reg_al & 1];
}

static void Tick(void) {
	if (memsize > 0)
		reg_cx = memsize;
}

static const int sizes[2] = {
	1, 2
};
""")
TICK = (32, 33)
SIZES = (36, 37, 38)


def reached(report: closure.Report) -> dict[str, str]:
    return {r.item.kind: r.by for r in report.results if r.item.kind in ("state", "lookup")}


def note(n: str, lines: str) -> Change:
    row = {"n": n, "on": "out BL", "of": "dosbox-x", "vs": "extra",
           "text": "The size comes from a table and a later tick reads it.",
           "quotes": [{"ref": REF, "lines": lines}]}
    return lambda d: of("0x77/0x10")(d)["rows"].append(row)


def test_a_member_another_function_reads_and_a_table_the_region_indexes_are_owed(
        tmp_path: Any) -> None:
    faults = check(keep_world(tmp_path, source=REACHED), "0x77/0x10").faults
    assert f"OPEN {REF}:{TICK[0]} state memsize read by Tick" in faults
    assert f"OPEN {REF}:{SIZES[0]} lookup sizes[reg_al & 1]" in faults


@pytest.mark.parametrize("line", [*TICK, SIZES[1]])
def test_a_row_over_any_line_of_what_a_region_reaches_closes_it(tmp_path: Any, line: int) -> None:
    report = check(keep_world(tmp_path, note("6", str(line)), source=REACHED), "0x77/0x10")
    kind = "lookup" if line in SIZES else "state"
    assert reached(report)[kind] == "row 6"


def test_a_closure_with_a_reason_closes_what_a_region_reaches(tmp_path: Any) -> None:
    kept = [c for c in dictionary()["entries"][0]["closed"] if c["as"] != "key"]
    world = keep_world(tmp_path, closures(
        "0x77/0x10", *kept, {"ref": REF, "lines": "33", "as": "unseen",
                             "reason": "the tick copies the size into a scratch register"}),
        source=REACHED)
    assert reached(check(world, "0x77/0x10"))["state"] == "closed: unseen"


def test_a_closure_over_a_later_line_of_an_item_a_row_closes_is_still_used(
        tmp_path: Any) -> None:
    kept = [c for c in dictionary()["entries"][0]["closed"] if c["as"] != "key"]
    unseen = {"ref": REF, "lines": "33", "as": "unseen", "reason": "a scratch copy"}

    def both(doc_: dict[str, Any]) -> None:
        closures("0x77/0x10", *kept, unseen)(doc_)
        note("6", "32")(doc_)
    report = check(keep_world(tmp_path, both, source=REACHED), "0x77/0x10")
    assert reached(report)["state"] == "row 6"
    assert not [f for f in report.faults if "closes no listed item" in f]


def test_a_member_whose_readers_are_regions_of_the_entry_owes_nothing(tmp_path: Any) -> None:
    def tick(doc_: dict[str, Any]) -> None:
        of("0x77/0x10")(doc_)["regions"].insert(0, {"ref": REF, "function": "Tick"})
    report = check(keep_world(tmp_path, tick, source=REACHED), "0x77/0x10")
    assert "state" not in reached(report) and "lookup" in reached(report)


# An owner that has to be written.

def owned(owner: str) -> Change:
    """Entry 0x20 closes the dispatch on line 4 as its parent's instead of as the key."""
    return edit("0x77/0x20", closed=[shut("11-12", "2", nothing=True),
                                     {"ref": REF, "lines": "4", "as": "parent", "owner": owner}])


def test_a_closure_whose_owner_is_its_own_entry_is_red(tmp_path: Any) -> None:
    world = keep_world(tmp_path, owned("dos:call:0x77/0x20"))
    assert (f"closed {REF}:4 as parent for the entry itself: an owner is another entry"
            in check(world, "0x77/0x20").faults)


def test_a_call_the_table_gives_to_an_entry_not_written_is_owed_while_partial_and_red_when_whole(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path, callees={"dosbox-x:set_size": "shared:dos:call:0x77/0x40"})
    assert check(world, "0x77/0x30").faults == []
    assert (f"{REF}:20 calls set_size, which the callee table gives to dos:call:0x77/0x40, no "
            "entry of the dictionary or beside it: write it, or check with --partial while it is "
            "not written") in check(world, "0x77/0x30", partial=False).faults


def test_a_closure_for_an_owner_not_written_is_owed_while_partial_and_red_when_whole(
        tmp_path: Any) -> None:
    world = keep_world(tmp_path, owned("dos:call:0x77"))
    assert check(world, "0x77/0x20").owed == 1 and check(world, "0x77/0x20").faults == []
    assert (f"closed {REF}:4 as parent for dos:call:0x77, which is no entry of the "
            "dictionary: write it, or check with --partial while the dictionary is not whole"
            ) in check(world, "0x77/0x20", partial=False).faults


def test_an_owner_holds_the_lines_by_a_closure_of_its_own(tmp_path: Any) -> None:
    world = keep_world(tmp_path, owned("dos:call:0x77/0x10"))
    assert check(world, "0x77/0x20", partial=False).faults == []


def test_an_owner_that_hands_the_lines_on_in_turn_holds_none_of_them(tmp_path: Any) -> None:
    def circle(doc_: dict[str, Any]) -> None:
        owned("dos:call:0x77/0x10")(doc_)
        of("0x77/0x10")(doc_)["closed"][0] = {"ref": REF, "lines": "4", "as": "parent",
                                              "owner": "dos:call:0x77/0x20"}
    assert check(keep_world(tmp_path, circle), "0x77/0x20", partial=False).faults == [
        f"closed {REF}:4: dos:call:0x77/0x10 has no row on those lines and closes none of them "
        "itself"]


def test_the_command_line_finds_an_owner_in_a_dictionary_beside_this_one(
        tmp_path: Any, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    world = keep_world(tmp_path, owned("dos:call:0x77/0x40"))
    monkeypatch.setitem(shared.PINS, "dosbox-x", world.pin)
    monkeypatch.setattr(quote, "default_datasheets", lambda: world.sources().table)
    beside = {**dictionary(), "dictionary": "parent", "entries": [
        {"key": "0x77/0x40", "name": "the owner", "regions": [{"ref": REF, "function": "Keep"}],
         "rows": [doc("1", "is", "A synthetic interrupt.", "1"),
                  doc("2", "out none", "Nothing is returned.", "7")],
         "closed": [{"ref": REF, "lines": "4-28", "as": "structure"}]}]}
    asked = [*world.options(), "check", str(world.root / "keep.json"), "dos:call:0x77/0x20"]
    assert rows.main(asked) == 1
    (world.root / "parent.json").write_text(json.dumps(beside), encoding="utf-8")
    rows._stamp_file(world.root / "parent.json", world.sources())
    capsys.readouterr()
    assert rows.main(asked) == 0, capsys.readouterr().out
