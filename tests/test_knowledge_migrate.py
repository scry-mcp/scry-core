"""`rows migrate`: a draft in the new shape from an old entry and the evidence its check gathered,
with every statement it could not anchor to lines marked and none guessed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rows_world import World, build

from scry_core.knowledge import migrate, quote, rows, shared
from scry_core.knowledge.quote import Invalid

ID = "chipx:command:0xE0..0xE7"
MAME = "mame:src/devices/machine/chipx.cpp"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build(tmp_path)


def draft(world: World, evidence: str, wanted: str = ID) -> migrate.Draft:
    return migrate.draft(world.root / "old" / "command.json", wanted,
                         world.root / "old" / f"evidence-{evidence}.json", world.sources())


def body(got: migrate.Draft) -> dict[str, Any]:
    entry: dict[str, Any] = got.document["entries"][0]
    return entry


def test_the_shared_checks_evidence_is_drafted_row_by_row(world: World) -> None:
    got = draft(world, "shared")
    assert (got.anchored, got.marked, got.omissions) == (3, 4, 1)
    drafted = body(got)["rows"]
    assert [(r["on"], r["of"], r["text"]) for r in drafted] == [
        ("is", ["mame"], "The command rotates the priority."),
        ("", ["mame"], "A set in-service bit is cleared."),
        ("is", ["doc"], "The datasheet names the mode."),
        ("", ["mame"], "MAME acts only in its ready state.")]


def test_a_drafted_quote_is_stamped_from_the_source_and_not_taken_from_the_evidence(
        world: World) -> None:
    quotes = [q for r in body(draft(world, "shared"))["rows"] for q in r["quotes"]]
    assert all(world.sources().faults(quote.Quote(q["ref"], q["lines"], q["sha"])) == []
               for q in quotes)
    assert {q["lines"] for q in quotes if q["ref"] == MAME} == {"24", "26", "17"}


def test_a_quote_whose_text_is_not_at_its_line_is_dropped_and_said(world: World) -> None:
    got = draft(world, "shared")
    assert any(MAME in d and ":26 (behaviour" in d for d in got.dropped)
    assert body(got)["dropped"] == got.dropped


def test_a_statement_whose_only_quote_is_on_another_line_is_marked_and_not_moved(
        world: World) -> None:
    marks = {m["statement"]: m["why"] for m in body(draft(world, "shared"))["unanchored"]}
    assert marks["Only a wrong line is quoted."] == "none of its quotes is at the line the " \
        "evidence names"


def test_a_statement_the_check_found_unsupported_is_marked_with_its_verdict(world: World) -> None:
    marks = {m["statement"]: m["why"] for m in body(draft(world, "shared"))["unanchored"]}
    assert marks["The base becomes the level plus one."] == "the check found it unsupported"


def test_a_datasheet_quote_is_found_in_the_capture_where_its_text_occurs_once(
        world: World) -> None:
    rows_ = body(draft(world, "shared"))["rows"]
    doc = [q for r in rows_ if r["of"] == ["doc"] for q in r["quotes"]]
    assert [q["lines"] for q in doc] == ["4"]


def test_a_datasheet_text_that_occurs_many_times_is_marked_and_never_picked(
        world: World) -> None:
    marks = [m["statement"] for m in body(draft(world, "shared"))["unanchored"]]
    assert "The mode appears in every line." in marks


def test_a_piece_of_the_old_text_no_statement_holds_is_marked(world: World) -> None:
    marks = [(m["field"], m["statement"]) for m in body(draft(world, "shared"))["unanchored"]]
    assert ("behaviour", "A sentence nobody checked") in marks


def test_an_omission_the_check_needed_is_a_draft_row_and_one_it_did_not_is_left(
        world: World) -> None:
    got = body(draft(world, "shared"))["rows"]
    assert [r["text"] for r in got if r["from"] == "omission"] == [
        "MAME acts only in its ready state."]


def test_the_region_of_the_header_is_derived(world: World) -> None:
    assert body(draft(world, "shared"))["regions"] == [
        {"ref": MAME, "function": "chipx_device::write"}]


def test_the_entrys_own_fields_are_copied(world: World) -> None:
    got = body(draft(world, "shared"))
    assert (got["key"], got["name"], got["aliases"]) == ("0xE0..0xE7", "rotate on specific EOI",
                                                         ["rot"])


def test_the_dosbox_x_evidence_is_drafted_and_its_opened_callees_become_regions(
        world: World) -> None:
    got = draft(world, "calls")
    assert (got.anchored, got.marked, got.omissions) == (2, 3, 0)
    assert body(got)["regions"][1] == {"ref": "dosbox-x:src/ints/call.cpp",
                                       "function": "make_temp"}
    parties = [r["of"] for r in body(got)["rows"]]
    assert parties == [["dosbox-x"], ["dosbox-x", "doc"]] or parties == [
        ["dosbox-x"], ["doc", "dosbox-x"]]


def test_the_mame_evidence_is_drafted_with_its_line_ranges_and_its_omissions(
        world: World) -> None:
    got = draft(world, "mame")
    assert (got.anchored, got.omissions) == (2, 1)
    lines = [q["lines"] for r in body(got)["rows"] for q in r["quotes"]]
    assert lines == ["24-28", "42-43", "26-27"]


def test_the_draft_is_not_a_valid_dictionary_until_a_person_resolves_it(world: World) -> None:
    text = json.dumps(draft(world, "shared").document)
    dictionary, faults = rows.parse(text)
    assert any("no field" in f and "unanchored" in f for f in faults)
    assert any("an object of" in f for f in faults)


def test_the_summary_counts_what_was_anchored_and_what_was_marked(world: World) -> None:
    assert draft(world, "shared").summary() == (
        "0xE0..0xE7: 3 statements anchored, 4 marked unanchored, 1 omissions as rows, 4 draft "
        "rows, 3 quotes dropped")


def test_an_entry_the_old_dictionary_lacks_is_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="no entry chipx:command:0x99"):
        draft(world, "shared", "chipx:command:0x99")


def test_evidence_with_no_statements_is_invalid_and_never_an_empty_draft(
        world: World, tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text('{"statements": []}', encoding="utf-8")
    with pytest.raises(Invalid, match="no statements"):
        migrate.read_evidence(empty)


def test_a_missing_source_is_invalid_and_not_a_mark_on_every_statement(
        world: World) -> None:
    (world.mame / "src/devices/machine/chipx.cpp").unlink()
    with pytest.raises(Invalid, match="not a file"):
        draft(world, "shared")


def test_the_command_writes_the_draft_and_says_what_it_anchored(
        world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(shared.PINS, "dosbox-x", world.pin)
    monkeypatch.setattr(quote, "default_datasheets", lambda: world.sources().table)
    out = world.root / "draft.json"
    code = rows.main([*world.options(), "migrate", str(world.root / "old/command.json"), ID,
                      "--evidence", str(world.root / "old/evidence-shared.json"),
                      "--out", str(out)])
    assert code == 0
    assert "3 statements anchored, 4 marked unanchored" in capsys.readouterr().out
    assert json.loads(out.read_text())["entries"][0]["key"] == "0xE0..0xE7"


def test_the_command_without_evidence_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        rows.main(["migrate", "x.json", ID])
    assert stop.value.code == 2
    capsys.readouterr()


def test_the_command_with_a_missing_entry_exits_three(
        world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(shared.PINS, "dosbox-x", world.pin)
    code = rows.main([*world.options(), "migrate", str(world.root / "old/command.json"),
                      "--evidence", str(world.root / "old/evidence-shared.json")])
    assert code == 3 and "INVALID" in capsys.readouterr().err


def _old(world: World, **changes: object) -> Path:
    path = world.root / "old" / "variant.json"
    doc = json.loads((world.root / "old" / "command.json").read_text(encoding="utf-8"))
    doc.pop("complete_against", None)
    doc["entries"][0].update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _evidence(world: World, statements: list[dict[str, Any]], **more: Any) -> Path:
    path = world.root / "old" / "variant-evidence.json"
    path.write_text(json.dumps({"statements": statements, **more}), encoding="utf-8")
    return path


def _statement(field: str, text: str, *quotes: dict[str, Any]) -> dict[str, Any]:
    return {"field": field, "text": text, "supported": True, "support": list(quotes)}


def _cite(line: int, quote_text: str) -> dict[str, Any]:
    return {"file": "src/hardware/chipx.cpp", "line": line, "quote": quote_text}


def test_a_header_with_no_handler_gives_no_region_and_an_access_is_copied(world: World) -> None:
    got = migrate.draft(_old(world, access="write"), "chipx:command:0xE0..0xE7:write",
                        _evidence(world, [_statement("name", "n", _cite(4, "Block * blk"))]),
                        world.sources())
    assert body(got)["regions"] == [] and body(got)["access"] == "write"


def test_a_quote_with_no_text_or_a_line_outside_the_file_is_dropped(world: World) -> None:
    cites = [_cite(4, ""), _cite(0, "Block * blk"), _cite(900, "Block * blk")]
    got = migrate.draft(_old(world), ID, _evidence(world, [_statement("name", "n", *cites)]),
                        world.sources())
    assert (got.anchored, len(got.dropped)) == (0, 3)
    assert "n" in [m["statement"] for m in body(got)["unanchored"]]


def test_two_quotes_that_land_on_the_same_lines_make_one(world: World) -> None:
    cites = [_cite(4, "Block * blk"), _cite(4, "blocks[(port == 0x20)")]
    got = migrate.draft(_old(world), ID, _evidence(world, [_statement("name", "n", *cites)]),
                        world.sources())
    assert [len(r["quotes"]) for r in body(got)["rows"]] == [1]


def test_a_placement_statement_becomes_a_place_row_and_an_unfound_omission_is_marked(
        world: World) -> None:
    omission = {"fact": "A lost fact.", "needed": True, "src": "dosbox-x:src/hardware/chipx.cpp",
                "line": 4, "quote": "text that is not there"}
    got = migrate.draft(_old(world), ID, _evidence(
        world, [_statement("handlers.read", "h", _cite(4, "Block * blk"))], omissions=[omission]),
        world.sources())
    assert [r["on"] for r in body(got)["rows"]] == ["place"]
    assert any(m["field"] == "omission" for m in body(got)["unanchored"])


@pytest.mark.parametrize("raw", [
    {"statements": [{"field": "name"}]},
    {"statements": [{"field": "name", "text": "n", "supported": True,
                     "support": [{"file": "a", "line": "x", "quote": "q"}]}]},
    {"statements": [{"field": "name", "claim": "n", "status": "supported", "support": 5}]}])
def test_evidence_of_another_shape_is_invalid_and_never_a_traceback(
        world: World, raw: dict[str, Any]) -> None:
    path = world.root / "old" / "odd.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(Invalid, match="not the evidence of any of the three checks"):
        migrate.read_evidence(path)


def test_a_quote_cited_at_a_blank_line_is_not_anchored_there(world: World) -> None:
    got = migrate.draft(_old(world), ID, _evidence(world, [
        _statement("name", "n", _cite(2, "static void write_command"))]), world.sources())
    assert got.anchored == 0
