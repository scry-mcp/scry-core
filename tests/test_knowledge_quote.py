"""`scry_core.knowledge.quote`: a quote is a location and a digest, read from the source at its
pin and never kept as text."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from rows_world import FIXTURES, World, build

from scry_core.knowledge import quote
from scry_core.knowledge.quote import Invalid, Quote, Sources

MAME = "mame:src/devices/machine/chipx.cpp"
DOSBOX = "dosbox-x:src/hardware/chipx.cpp"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build(tmp_path)


def test_a_digest_ignores_the_white_space_of_the_lines() -> None:
    assert quote.stamp(["\tif (a)  {", "  b();"]) == quote.stamp(["if (a) { b();"])
    assert quote.stamp(["if (a)"]) != quote.stamp(["if (b)"])


@pytest.mark.parametrize(("text", "want"), [("5", (5, 5)), ("3-9", (3, 9)), ("12-12", (12, 12))])
def test_a_span_is_a_line_or_two_lines_joined_by_a_dash(text: str, want: tuple[int, int]) -> None:
    assert quote.span(text) == want


@pytest.mark.parametrize("text", ["", "0", "-3", "9-3", "a-b", "1-2-3", "1 - 2"])
def test_a_span_that_is_not_one_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="lines"):
        quote.span(text)


def test_a_span_is_written_one_way() -> None:
    assert quote.spelled(7, 7) == "7"
    assert quote.spelled(7, 9) == "7-9"


@pytest.mark.parametrize("ref", ["", "mame", "gcc:x.c", "mame:", "mame: x.cpp"])
def test_a_ref_without_a_scheme_of_the_set_and_a_file_is_refused(ref: str) -> None:
    with pytest.raises(ValueError, match="scheme"):
        quote.split_ref(ref)


def test_each_scheme_names_the_party_it_speaks_for() -> None:
    got = {s: Quote(f"{s}:f", "1").party for s in ("mame", "dosbox-x", "rbil61", "datasheet")}
    assert got == {"mame": "mame", "dosbox-x": "dosbox-x", "rbil61": "doc", "datasheet": "doc"}


def test_the_lines_of_a_source_are_numbered_as_an_editor_does(world: World) -> None:
    held = world.sources().lines(MAME)
    assert held[0].startswith("// synthetic source")
    assert held[-1] == "}"


@pytest.mark.parametrize("ref", [MAME, DOSBOX, "rbil61:INTER.A", "datasheet:chipx.raw.txt"])
def test_every_scheme_is_read_at_its_own_source(world: World, ref: str) -> None:
    assert world.sources().stamped(ref, "1-2").sha == quote.stamp(world.sources().lines(ref)[:2])


def test_dosbox_x_is_read_at_the_pin_and_not_at_the_working_tree(world: World) -> None:
    before = world.sources().stamped(DOSBOX, "4").sha
    world.rewrite("dosbox", "src/hardware/chipx.cpp", "(port == 0x20)", "(port == 0x21)")
    assert world.sources().stamped(DOSBOX, "4").sha == before


def test_a_dosbox_file_the_pin_lacks_is_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="git show"):
        world.sources().lines("dosbox-x:src/none.cpp")


def test_a_mame_file_the_tree_lacks_is_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="not a file"):
        world.sources().lines("mame:src/none.cpp")


def test_a_scheme_without_its_option_is_invalid() -> None:
    with pytest.raises(Invalid, match="--mame"):
        Sources().lines(MAME)


def test_the_list_is_read_from_its_archives_too(world: World, tmp_path: Path) -> None:
    folder = tmp_path / "archives"
    folder.mkdir()
    with zipfile.ZipFile(folder / "inter61a.zip", "w") as z:
        z.writestr("ZIPPED.A", "first\r\nsecond\r\n")
    got = Sources(rbil=folder).lines("rbil61:ZIPPED.A")
    assert got == ["first", "second"]
    with pytest.raises(Invalid, match="neither a file"):
        Sources(rbil=folder).lines("rbil61:MISSING.A")


def test_a_capture_that_is_not_the_one_the_table_records_is_invalid(world: World) -> None:
    (world.datasheets / "chipx.raw.txt").write_text("another capture\n", encoding="utf-8")
    with pytest.raises(Invalid, match="not the capture"):
        Sources(datasheets=world.datasheets, table={
            "chipx.raw.txt": quote.Datasheet("t", "", "0" * 64, "1" * 64)}
        ).lines("datasheet:chipx.raw.txt")


def test_a_datasheet_outside_the_table_is_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="no datasheet of the table"):
        world.sources().lines("datasheet:other.raw.txt")


def test_a_capture_that_is_missing_says_how_to_rebuild_it(world: World) -> None:
    (world.datasheets / "chipx.raw.txt").unlink()
    with pytest.raises(Invalid, match="pdftotext -raw"):
        world.sources().lines("datasheet:chipx.raw.txt")


def test_the_last_newline_of_a_file_does_not_make_a_line(world: World) -> None:
    (world.mame / "end.cpp").write_text("one\ntwo\n", encoding="utf-8")
    assert world.sources().lines("mame:end.cpp") == ["one", "two"]


def test_a_quote_is_stamped_with_what_the_source_holds_there(world: World) -> None:
    got = world.sources().stamped(MAME, "10-11")
    assert (got.ref, got.lines) == (MAME, "10-11")
    assert got.sha == hashlib.sha256(" ".join(" ".join(
        world.sources().lines(MAME)[9:11]).split()).encode()).hexdigest()


def test_lines_the_file_lacks_are_invalid(world: World) -> None:
    with pytest.raises(Invalid, match="outside the file"):
        world.sources().stamped(MAME, "500")


def test_a_good_quote_has_no_fault(world: World) -> None:
    assert world.sources().faults(world.sources().stamped(MAME, "10-11")) == []


def test_a_quote_over_twelve_lines_is_a_fault(world: World) -> None:
    sources = world.sources()
    got = sources.faults(sources.stamped(MAME, "8-20"))
    assert got == [f"{MAME}:8-20 is 13 lines, over 12"]


def test_a_blank_quote_is_a_fault(world: World) -> None:
    got = world.sources().faults(world.sources().stamped(MAME, "2"))
    assert got == [f"{MAME}:2 is blank"]


def test_a_quote_with_no_digest_is_a_fault_that_names_the_command(world: World) -> None:
    got = world.sources().faults(Quote(MAME, "10"))
    assert "rows quote --stamp" in got[0]


def test_a_digest_that_no_longer_matches_is_a_fault(world: World) -> None:
    sources = world.sources()
    stale = sources.stamped(MAME, "10")
    world.rewrite("mame", "src/devices/machine/chipx.cpp", "switch (offset)", "switch (offset + 1)")
    got = world.sources().faults(stale)
    assert len(got) == 1 and "no longer gives its digest" in got[0]


def test_a_quote_outside_the_file_is_a_fault_and_not_a_crash(world: World) -> None:
    got = world.sources().faults(Quote(MAME, "900", "a" * 64))
    assert "outside the file" in got[0]


def test_the_datasheet_table_of_the_package_holds_the_four_datasheets_by_identity() -> None:
    table = quote.default_datasheets()
    assert sorted(table) == ["8237A.raw.txt", "8254.raw.txt", "8259A.raw.txt", "z80cpu_um.raw.txt"]
    assert all(d.url.startswith("http") and len(d.pdf) == len(d.capture) == 64
               for d in table.values())


@pytest.mark.parametrize("doc", [
    "not json", "[]", '{"format": "scry-knowledge-datasheets/1"}',
    '{"format": "scry-knowledge-datasheets/1", "datasheets": {"a": {"title": "t"}}}',
    '{"format": "scry-knowledge-datasheets/1", "datasheets": {"a": {"title": "t", "url": "u", '
    '"pdf": "xx", "capture": "yy"}}}', '{"format": "other"}'])
def test_a_datasheet_table_that_is_not_one_is_refused(doc: str) -> None:
    with pytest.raises(ValueError, match="datasheets"):
        quote.parse_datasheets(doc)


def test_the_fixture_captures_are_the_ones_the_tests_hash() -> None:
    assert (FIXTURES / "datasheets" / "chipx.raw.txt").read_text().startswith(
        "synthetic datasheet line 1")
    assert json.loads((FIXTURES / "callees.json").read_text())["format"].startswith("scry-")


def test_lines_that_are_not_a_span_are_a_fault_and_not_a_crash(world: World) -> None:
    got = world.sources().faults(Quote(MAME, "ten", "a" * 64))
    assert got and "lines" in got[0]


def test_a_corrupt_archive_is_invalid(tmp_path: Path) -> None:
    (tmp_path / "inter61a.zip").write_bytes(b"not a zip")
    with pytest.raises(Invalid, match="not a zip archive"):
        Sources(rbil=tmp_path).lines("rbil61:ANY.A")


def test_a_source_that_cannot_be_read_is_invalid_and_not_a_fault_of_the_quote() -> None:
    with pytest.raises(Invalid, match="no source for mame"):
        Sources().faults(Quote(MAME, "10", "a" * 64))
