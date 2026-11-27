"""`scry_core.knowledge`: the key spellings, the entry format and its digest, the source index,
and the text search through FTS5 and through the index of our own."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, a_row, an_entry, write_rows

from scry_core.knowledge import KeyFault, check, keys, sources, text
from scry_core.knowledge import base as rows_base
from scry_core.knowledge import entry as fmt
from scry_core.knowledge.support import Chip, Device, Scope, Support


def header(kind: str = "port", scope: str = "ibm-pc") -> fmt.Header:
    return fmt.Header("t.json", "t", kind, scope, "covers", "list", (), None, False)


def parsed(raw: dict[str, Any], kind: str = "port") -> tuple[fmt.Entry | None, list[str]]:
    return fmt.parse_entry(raw, header(kind))


@pytest.mark.parametrize(("kind", "typed", "canonical"), [
    ("port", "0x3c8", "0x3C8"), ("port", "0X5", "0x05"), ("register", "0x4", "0x04"),
    ("vector", "2", "2"), ("vector", "0x21", "0x21"), ("irq", "7", "7"),
    ("error", "0", "0"), ("call", "0x21/0x4c", "0x21/0x4C"),
    ("call", "0x33/0x0/0x3", "0x33/0x00/0x03"), ("memory", "0040:0049", "0040:0049"),
    ("memory", "0040:00ab", "0040:00AB".upper()), ("memory", "0x9000", "0x9000"),
    ("memory", "0x9000..0x9fff", "0x9000..0x9FFF"), ("input", ":IN1/Coin 1", ":IN1/Coin 1"),
    ("register", "0x20..0x35", "0x20..0x35"), ("register", "0x2a..0x2B", "0x2A..0x2B"),
    ("command", "0xe0..0xe3", "0xE0..0xE3"), ("device", "vga-seq", "vga-seq"),
    ("port", "0x20..0x3f", "0x20..0x3F")])
def test_a_key_has_one_spelling(kind: str, typed: str, canonical: str) -> None:
    assert keys.canonical(kind, typed) == canonical


@pytest.mark.parametrize(("kind", "typed"), [
    ("port", "3C8"), ("port", "0x"), ("port", " 0x3C8"), ("irq", "0x7"), ("irq", "07"),
    ("call", "0x21"), ("call", "0x21/0x4C/0x01/0x02"), ("call", "0x121/0x4C"),
    ("memory", "0x9000..0x8000"), ("device", "VGA"), ("device", ""), ("vector", "0x"),
    ("nothing", "1"), ("port", "0x" + "F" * 13), ("input", "x" * 65), ("input", "a\x00b"),
    ("irq", "9" * 20), ("irq", str(2**48)), ("error", "9" * 5000), ("vector", "9" * 17),
    ("register", "0x35..0x20"), ("register", "0x20.."), ("command", "..0x20"),
    ("register", "0x20..0x35..0x40"), ("vector", "0x1..0x2")])
def test_a_key_that_is_none_of_its_kind_is_refused(kind: str, typed: str) -> None:
    with pytest.raises(KeyFault):
        keys.canonical(kind, typed)


def test_a_key_covers_the_numbers_it_stands_for() -> None:
    assert keys.span("call", "0x21/0x4C") == keys.Span(0x21, 0x21, (0x21, 0x4C))
    assert keys.span("memory", "0040:0049").lo == 0x449
    assert keys.span("memory", "0x9000..0x9FFF") == keys.Span(0x9000, 0x9FFF)
    assert keys.span("input", "space") == keys.Span(None, None)
    assert keys.span("register", "0x20..0x35") == keys.Span(0x20, 0x35)
    assert keys.span("command", "0xE0..0xE3") == keys.Span(0xE0, 0xE3)
    assert keys.span("port", "0x20..0x3F") == keys.Span(0x20, 0x3F)
    assert keys.span("vector", "2").lo == 2 and keys.span("vector", "0x02").lo == 2


@pytest.mark.parametrize(("kind", "typed"), [
    ("call", "0x121"), ("port", " "), ("port", ""), ("register", "0x20..0x30..0x40"),
    ("command", "0x20..0x30..0x40"), ("register", "0x20..0x30..")])
def test_a_query_that_is_no_key_is_refused(kind: str, typed: str) -> None:
    with pytest.raises(KeyFault):
        keys.query(kind, typed)


def test_a_query_is_read_by_number_and_a_call_by_its_leading_parts() -> None:
    assert keys.query("port", "0x3c0..0x3cf") == ("0x3C0..0x3CF", keys.Span(0x3C0, 0x3CF))
    assert keys.query("call", "0x21")[1].parts == (0x21,)
    with pytest.raises(KeyFault):
        keys.query("port", "0x3CF..0x3C0")


def valid() -> dict[str, Any]:
    return an_entry("0x3C8", "DAC write address", device="vga-dac")


def test_a_whole_entry_loads_with_its_id_and_its_numbers() -> None:
    got, faults = parsed(valid())
    assert faults == [] and got is not None
    assert (got.id, got.lo, got.hi) == ("ibm-pc:port:0x3C8", 0x3C8, 0x3C8)


ENTRY_FAULTS: list[tuple[dict[str, Any], str]] = [
    ({"nothing": 1}, "unknown field `nothing`"),
    ({"key": "0x3c8"}, "is spelled '0x3C8'"),
    ({"name": "x" * 25}, "`name` is 1 to 24"),
    ({"name": "naïve"}, "`name` is 1 to 24"),
    ({"aliases": ["a"] * 7}, "`aliases` are at most 6"),
    ({"description": "word " * 31}, "`description` is 31 words"),
    ({"behaviour": "One. Two. Three. Four."}, "at most 3 sentences"),
    ({"behaviour": "word " * 61}, "`behaviour` is 61 words"),
    ({"differs": "word " * 41}, "`differs` is 41 words"),
    ({"sources": []}, "no source"),
    ({"sources": [{"role": "emulator", "ref": "lore:x y", "cites": "c"}]}, "known scheme"),
    ({"sources": [{"role": "emulator", "ref": "mame:nofile symbol", "cites": "c"}]}, "locator"),
    ({"sources": [{"role": "emulator", "ref": "datasheet:x", "cites": " "}]}, "`cites`"),
    ({"sources": [{"role": "friend", "ref": "datasheet:x", "cites": "c"}]}, "`role`"),
    ({"access": "both"}, "`access` is `read` or `write`"),
    ({"address": 1, "length": 1}, "`address` and `length` are for"),
    ({"ports": [{"base": "0x3C4", "length": 2}]}, "belong to a `device` entry"),
    ({"device": "VGA"}, "device key"),
    ({"address": "1"}, "`address` is a whole number"),
    ({"aliases": [1]}, "`aliases` is a list of text"),
    ({"sources": [5]}, "source 1 is `role`, `ref` and `cites`"),
    ({"access": None}, "`access` is `read` or `write`"),
    ({"access": 0}, "`access` is `read` or `write`"),
    ({"device": None}, "a key is text"),
    ({"device": []}, "a key is text"),
    ({"key": 5}, "`key`: a key is text"),
    ({"name": ""}, "`name` is text"),
]


@pytest.mark.parametrize(("change", "says"), ENTRY_FAULTS)
def test_an_entry_with_a_fault_says_what_it_is(change: dict[str, Any], says: str) -> None:
    got, faults = parsed({**valid(), **change})
    assert got is None and any(says in f for f in faults), faults


def test_two_sources_of_one_role_are_refused() -> None:
    raw = valid()
    raw["sources"] = raw["sources"] * 2
    assert any("`dosbox-x:` and `mame:`" in f for f in parsed(raw)[1])


DOC = {"role": "documentation", "ref": "datasheet:MC6845 data sheet, table 3", "cites": "R12"}
DOSBOX = {"role": "emulator", "ref": "dosbox-x:src/hardware/vga_other.cpp write_crtc",
          "cites": "case 0x0c:"}
MAME = {"role": "emulator", "ref": "mame:src/devices/video/mc6845.cpp mc6845_device::register_w",
        "cites": "case 0x0c:"}


@pytest.mark.parametrize("listed", [
    [DOC, DOSBOX, MAME], [DOSBOX, MAME], [MAME, DOSBOX], [DOC, MAME], [DOC, DOSBOX], [DOC]])
def test_an_entry_cites_a_documentation_and_the_two_emulators_that_model_the_chip(
        listed: list[dict[str, str]]) -> None:
    got, faults = parsed({**valid(), "sources": listed})
    assert faults == [] and got is not None and [s.ref for s in got.sources] == [
        s["ref"] for s in listed]


@pytest.mark.parametrize(("listed", "says"), [
    ([DOC, DOC], "at most one `documentation`"),
    ([DOC, {**DOC, "ref": "datasheet:other"}, DOSBOX], "at most one `documentation`"),
    ([DOSBOX, {**DOSBOX, "ref": "dosbox-x:src/other.cpp other"}], "`dosbox-x:` and `mame:`"),
    ([MAME, {**MAME, "ref": "mame:src/other.cpp other"}], "`dosbox-x:` and `mame:`"),
    ([DOSBOX, {**DOC, "role": "emulator"}], "`dosbox-x:` and `mame:`"),
    ([DOC, DOSBOX, MAME, {**DOC, "ref": "datasheet:third"}], "no source"),
    ([DOC, DOSBOX, MAME, {**MAME, "ref": "mame:src/other.cpp other"}], "no source")])
def test_what_is_not_a_documentation_and_the_two_emulators_is_refused(
        listed: list[dict[str, str]], says: str) -> None:
    got, faults = parsed({**valid(), "sources": listed})
    assert got is None and any(says in f for f in faults), faults


def stamp(raw: dict[str, Any], by: str = "checker", writer: str = "writer") -> dict[str, Any]:
    raw = copy.deepcopy(raw)
    raw["checked"] = {"by": by, "writer": writer, "digest": "",
                      "against": [{"ref": s["ref"], "line": s["cites"]} for s in raw["sources"]]}
    raw["checked"]["digest"] = fmt.digest("ibm-pc", "port", raw)
    return raw


def test_a_checked_entry_holds_the_digest_of_its_text() -> None:
    got, faults = parsed(stamp(valid()))
    assert faults == [] and got is not None and got.checked is not None
    assert got.checked.digest == got.digest


def test_the_digest_covers_the_text_and_the_check_and_ignores_only_its_own_stamp() -> None:
    raw = valid()
    base = fmt.digest("ibm-pc", "port", raw)
    assert fmt.digest("ibm-pc", "port", {**raw, "behaviour": raw["behaviour"] + " "}) != base
    assert fmt.digest("ibm-pc", "port", {**raw, "name": "DAC"}) != base
    assert fmt.digest("m68000", "port", raw) != base and fmt.digest("ibm-pc", "call", raw) != base
    checked = stamp(raw)
    assert fmt.digest("ibm-pc", "port", checked) != base
    sealed = checked["checked"]["digest"]
    for change in ({"by": "another checker"}, {"writer": "another writer"},
                   {"against": [{"ref": checked["sources"][0]["ref"], "line": "another line"}]}):
        record = {**checked["checked"], **change}
        assert fmt.digest("ibm-pc", "port", {**checked, "checked": record}) != sealed
    record = {**checked["checked"], "digest": "x"}
    assert fmt.digest("ibm-pc", "port", {**checked, "checked": record}) == sealed


@pytest.mark.parametrize(("change", "says"), [
    ({"by": "writer"}, "cannot check it"),
    ({"by": ""}, "names the session"),
    ({"against": []}, "names each source `ref` once"),
    ({"against": [{"ref": "datasheet:other x", "line": "l"}]}, "names each source `ref` once"),
    ({"against": [{"ref": "x", "line": " "}]}, "the line compared"),
    ({"extra": 1}, "`by`, `writer`, `against` and `digest`"),
])
def test_a_check_record_that_is_not_a_check_is_refused(change: dict[str, Any], says: str) -> None:
    raw = stamp(valid())
    raw["checked"] = {**raw["checked"], **change}
    got, faults = parsed(raw)
    assert got is None and any(says in f for f in faults), faults


def test_a_header_is_judged_whole() -> None:
    got, faults = fmt.parse_header({"format": "scry-knowledge/2", "kind": "nope", "entries": 1,
                                    "left_out": [{"key": "1"}], "reached": {"x": "1"},
                                    "both": 1, "odd": 0}, "t.json")
    assert got is None
    for says in ("`format`", "`kind`", "`dictionary` is text", "`entries` is a list",
                 "`left_out`", "`reached`", "`both`", "unknown field `odd`"):
        assert any(says in f for f in faults), (says, faults)
    assert fmt.parse_header([], "t.json")[0] is None


def test_words_are_letters_and_digits_without_accents() -> None:
    assert text.words("Sound-Blaster 2.0, über_café 0x3C8") == [
        "sound", "blaster", "2", "0", "uber", "cafe", "0x3c8"]
    assert text.terms("timer* a*b c d*") == [
        text.Term("timer", True), text.Term("a", False), text.Term("b", False),
        text.Term("c", False), text.Term("d", True)]
    assert text.terms('"; DROP * --') == [text.Term("drop", False)] and text.terms("*") == []


def test_a_source_names_a_scheme_and_a_locator_that_fits_it() -> None:
    assert sources.split("rbil61:INTERRUP.G D-214C") == ("rbil61", "INTERRUP.G D-214C")
    assert sources.split("datasheet:MC6845 data sheet, table 3")[0] == "datasheet"
    for bad in ("rbil61:ports", "nothing", "mame:file symbol", "lore:a b.c d"):
        with pytest.raises(ValueError, match="scheme|locator"):
            sources.split(bad)


def test_a_reader_is_given_where_to_open_a_source() -> None:
    assert sources.url("rbil61:INTERRUP.G D-214C", {}).startswith("https://www.cs.cmu.edu")
    ref = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"
    assert sources.url(ref, {}) == ""
    assert sources.url(ref, {"dosbox-x": "abc123"}) == (
        "https://github.com/joncampbell123/dosbox-x/blob/abc123/src/dos/dos.cpp")
    assert sources.url("datasheet:MC6845 data sheet", {}) == ""


def test_the_index_a_tool_wrote_is_read_or_refused_by_name() -> None:
    index = sources.read_index(KNOWLEDGE / "null-sources.json")
    assert len(index.rows) == 6 and index.lists and index.rows[
        "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"].key == "0x21/0x4C"
    good = json.loads((KNOWLEDGE / "null-sources.json").read_text(encoding="utf-8"))
    for broken, says in (("{", "not JSON"), ('{"format": "x"}', "is not a"),
                         (json.dumps({**good, "rows": {"r": {}}}), "no `line`"),
                         (json.dumps({**good, "rows": []}), "`rows` is an object"),
                         (json.dumps({**good, "lists": {"l": [1]}}), "list of key texts")):
        with pytest.raises(ValueError, match=says):
            sources.parse_index(broken)


def test_a_declaration_names_what_it_claims_and_what_it_only_names() -> None:
    support = Support(scopes=(Scope("m68000", written=("vector",)),
                              Scope("z80", written=("vector",), support="named")),
                      devices=(Device("sb", inside=("sb-dsp",)),),
                      chips=(Chip("ym2151", written=("register",)),))
    assert support.held() == ["m68000", "z80"]
    assert support.claims("m68000") and not support.claims("z80") and not support.claims("sb")
    assert support.names() == {"m68000", "z80", "sb", "ym2151", "chip"}
    assert support.faults() == []


def test_a_declaration_with_a_fault_is_told_so() -> None:
    support = Support(scopes=(Scope("a", written=("vectors",), support="maybe"), Scope("a")),
                      devices=(Device("a", written=("register", "nothing")),), live=("hmm",))
    faults = support.faults()
    for says in ("a is declared twice", "support is supported or named", "'vectors' is not a kind",
                 "'nothing' is not a kind", "live: 'hmm'"):
        assert any(says in f for f in faults), (says, faults)


def test_more_faults_an_entry_can_have_are_each_named() -> None:
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("call", {"key": "0x21/0x4C", "device": "x"}, "`device` is for port, irq, memory"),
        ("device", {"key": "sb", "irq": ["5"]}, "`irq` is a list of whole numbers"),
        ("device", {"key": "sb", "ports": [{"base": "0x3C4"}]}, "`ports`: a port range is"),
        ("device", {"key": "sb", "ports": [{"base": "3C4", "length": 2}]}, "`ports`: "),
        ("device", {"key": "sb", "handlers": {"a": 1}}, "`handlers` maps a handler"),
        ("vector", {"key": "2", "address": 8}, "come together"),
        ("memory", {"key": "0040:0049", "length": 2}, "come together"),
        ("memory", {"key": "0x10", "address": 10**30, "length": 1}, "`address` is a whole number"),
    ]
    for kind, change, says in cases:
        raw = {**an_entry("0x3C8", "n"), **change}
        got, faults = parsed(raw, kind)
        assert got is None and any(says in f for f in faults), (says, faults)




def test_the_comparison_of_the_two_paths_runs_on_every_base_of_rows(tmp_path: object) -> None:
    write_rows(tmp_path, "errors", "error", "ibm-pc", [  # type: ignore[arg-type]
        {"key": str(n), "name": f"error {n} alpha beta", "regions": [], "closed": [],
         "rows": [a_row(1, "is", f"The error {n}.")]} for n in range(150)])
    assert check.fallback_differs(
        lambda fts5: rows_base.Base((tmp_path,), None, fts5=fts5)) == []  # type: ignore[arg-type]


def a_placed(key: str, name: str, **fields: Any) -> dict[str, Any]:
    """One entry of the sample with the rows its kind owes; `place` is an emulator's row."""
    rows = [a_row(1, "is", f"The {name}.")]
    if fields.pop("placed", False):
        rows.append({**a_row(2, "place", "The emulator reaches it here.", of="dosbox-x"),
                     "vs": "place"})
    return {"key": key, "name": name, "regions": [], "closed": [], **fields, "rows": rows}


def a_call(key: str, name: str) -> dict[str, Any]:
    return {"key": key, "name": name, "regions": [], "closed": [],
            "rows": [a_row(1, "is", f"The function {name}."),
                     a_row(2, "out AX", "The result.")]}


@pytest.fixture
def base(tmp_path: Path) -> rows_base.Base:
    """Ports with a range, an access and an alias, a vector, a memory area, a device and calls,
    in two scopes."""
    write_rows(tmp_path, "ports", "port", "ibm-pc", [
        a_placed("0x3C4", "sequencer index", aliases=["SEQ index"], device="vga-seq",
                 placed=True),
        a_placed("0x3C5", "sequencer data", device="vga-seq", placed=True),
        a_placed("0x3C8", "DAC write address", access="write", placed=True),
        a_placed("0x3C8", "DAC address, read back", access="read", placed=True),
        a_placed("0x3D0..0x3D7", "VGA misc", placed=True),
        a_placed("0x61", "speaker control", placed=True)])
    write_rows(tmp_path, "devices", "device", "ibm-pc", [
        {"key": "vga-seq", "name": "VGA sequencer", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The sequencer."), a_row(2, "reset", "It comes up at 0.")]}])
    write_rows(tmp_path, "vectors", "vector", "ibm-pc", [
        a_placed("0x21", "DOS"), a_placed("0x10", "video BIOS")])
    write_rows(tmp_path, "memory", "memory", "ibm-pc", [
        a_placed("0x449", "video mode", placed=True),
        a_placed("0x400..0x4FF", "BIOS data area", placed=True)])
    write_rows(tmp_path, "calls", "call", "ibm-pc", [
        a_call("0x21/0x4C", "exit"), a_call("0x21/0x4D", "get return code"),
        a_call("0x10/0x12", "alternate select"), a_call("0x10/0x12/BL=0x36", "video refresh")])
    write_rows(tmp_path, "vga-seq", "register", "vga-seq", [
        {"key": "0x04", "name": "memory mode", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The memory mode register."), a_row(2, "read", "Readable.")]}])
    loaded = rows_base.Base((tmp_path,), None)
    assert loaded.faults() == []
    return loaded


def test_an_entry_is_found_by_id_by_key_and_by_name(base: rows_base.Base) -> None:
    got = base.by_id("ibm-pc:port:0x3C4")
    assert got is not None and got.name == "sequencer index"
    assert base.get("port", "0x3C4", "ibm-pc") == got
    write = base.get("port", "0x3C8", "ibm-pc", "write")
    assert write is not None and write.name == "DAC write address"
    assert [e.id for e in base.by_alias("SEQ index")] == ["ibm-pc:port:0x3C4"]


def test_a_number_is_exact_or_a_range_and_a_range_overlaps(base: rows_base.Base) -> None:
    assert [e.key for e in base.search("port", "0x3D2").entries] == ["0x3D0..0x3D7"]
    assert [e.key for e in base.search("port", "0x3D0..0x3D3").entries] == ["0x3D0..0x3D7"]
    assert [e.key for e in base.search("port", "0x3C4").entries] == ["0x3C4"]


def test_a_call_is_asked_by_its_leading_parts(base: rows_base.Base) -> None:
    assert [e.key for e in base.search("call", "0x21").entries] == ["0x21/0x4C", "0x21/0x4D"]
    assert [e.key for e in base.search("call", "0x10/0x12").entries] == [
        "0x10/0x12", "0x10/0x12/BL=0x36"]


def test_a_number_with_no_kind_is_every_kind_that_has_it(base: rows_base.Base) -> None:
    assert [e.kind for e in base.search(key="0x21", limit=50).entries] == ["vector"]
    assert [e.kind for e in base.search(key="0x21/0x4C", limit=50).entries] == ["call"]


def test_an_address_finds_the_narrowest_thing_that_sits_there(base: rows_base.Base) -> None:
    found = base.at(0x449, "ibm-pc")
    assert found is not None and (found[0].name, found[1]) == ("video mode", 0)
    found = base.at(0x450, "ibm-pc")
    assert found is not None and (found[0].name, found[1]) == ("BIOS data area", 0x50)
    assert base.at(0x999, "ibm-pc") is None


def test_a_search_by_words_puts_the_name_first_and_breaks_ties_by_number(
        base: rows_base.Base) -> None:
    assert [e.key for e in base.search(words="sequencer", limit=10).entries] == [
        "vga-seq", "0x3C4", "0x3C5"]
    found = base.search(words="DAC", limit=10)
    assert [e.key for e in found.entries] == ["0x3C8", "0x3C8"]


def test_a_device_is_itself_and_the_entries_of_its_scope(base: rows_base.Base) -> None:
    assert {e.key for e in base.search(device="vga-seq", limit=20).entries} == {"vga-seq", "0x04"}
    assert base.device_keys() == ["vga-seq"]


def test_nothing_found_says_how_much_was_searched_and_what_is_near(
        base: rows_base.Base) -> None:
    found = base.search("port", "0x3CF")
    assert found.total == 0 and found.examined == 6 and found.entries == []
    assert [e.key for e in found.nearest] == ["0x3C8", "0x3D0..0x3D7"]


def test_a_search_lists_the_first_limit_and_says_it_cut(base: rows_base.Base) -> None:
    found = base.search("port", limit=1)
    assert len(found.entries) == 1 and found.total == 6


def test_the_scopes_and_the_kinds_held_are_listed(base: rows_base.Base) -> None:
    assert base.scopes() == ["ibm-pc", "vga-seq"]
    assert base.kinds() == ["vector", "call", "port", "memory", "device", "register"]
    assert base.kinds("vga-seq") == ["register"]


def test_a_missing_directory_is_a_fault_not_a_crash(tmp_path: Path) -> None:
    loaded = rows_base.Base((tmp_path / "none", "scry_core_absent_package"), None)
    assert len(loaded) == 0 and len(loaded.file_faults) == 2


def a_register(key: str, name: str, **fields: Any) -> dict[str, Any]:
    return {"key": key, "name": name, "regions": [], "closed": [], **fields,
            "rows": [a_row(1, "is", f"The {name}."), a_row(2, "read", "Readable.")]}


def a_device(key: str, name: str, **fields: Any) -> dict[str, Any]:
    return {"key": key, "name": name, "regions": [], "closed": [], **fields,
            "rows": [a_row(1, "is", f"The {name}."), a_row(2, "reset", "It resets.")]}


@pytest.mark.parametrize(("broken", "says"), [
    ("by_id", "did not load by id"), ("get", "is not found by its kind, key and scope"),
    ("by_alias", "is not found by its name"), ("search", "is not found by the words of its name")])
def test_a_database_that_lost_an_entry_is_told_so(
        base: rows_base.Base, monkeypatch: pytest.MonkeyPatch, broken: str, says: str) -> None:
    lost: dict[str, Any] = {"by_id": None, "get": None, "by_alias": [],
                            "search": rows_base.Found()}
    monkeypatch.setattr(rows_base.Base, broken, lambda self, *a, **k: lost[broken])
    assert any(says in fault for fault in check.held(base))


def test_an_entry_the_base_cannot_find_by_its_key_is_told_so(
        base: rows_base.Base, monkeypatch: pytest.MonkeyPatch) -> None:
    real = rows_base.Base.search

    def search(self: rows_base.Base, kind: str = "", key: str = "", words: str = "",
               device: str = "", scopes: object = (), limit: int = 10) -> rows_base.Found[Any]:
        if key and not words:
            return rows_base.Found()
        return real(self, kind, key, words, device, scopes, limit)  # type: ignore[arg-type]
    monkeypatch.setattr(rows_base.Base, "search", search)
    assert any("not found by its key" in fault for fault in check.held(base))


def test_the_words_a_comparison_asks_are_bounded_and_cover_a_name_of_one_word(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_rows(tmp_path, "errors", "error", "ibm-pc", [
        {"key": str(n), "name": name, "regions": [], "closed": [],
         "rows": [a_row(1, "is", "An error.")]}
        for n, name in ((1, "alpha"), (2, "beta gamma delta"), (3, "epsilon zeta"))])
    base_ = rows_base.Base((tmp_path,), None)
    asked = check._asked(base_)
    assert "alpha" in asked and any(" " in a for a in asked)
    monkeypatch.setattr(check, "WORDS_ASKED", 1)
    assert len(check._asked(base_)) < len(asked)


def test_a_comparison_that_cannot_tell_the_paths_apart_says_so(tmp_path: Path) -> None:
    write_rows(tmp_path, "errors", "error", "ibm-pc", [
        {"key": str(n), "name": f"error {n}", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "An error.")]} for n in range(3)])
    if not rows_base.Base((tmp_path,), None).uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    assert check.fallback_differs(
        lambda fts5: rows_base.Base((tmp_path,), None, fts5=True)) == [
            "the base asked for no FTS5 and used it"]
    assert check.fallback_differs(
        lambda fts5: rows_base.Base((tmp_path,), None, fts5=False)) == []


def test_two_registers_of_one_dictionary_may_not_overlap(tmp_path: Path) -> None:
    write_rows(tmp_path, "regs", "register", "ym", [
        a_register("0x10..0x13", "a"), a_register("0x11..0x12", "b")])
    loaded = rows_base.Base((tmp_path,), None)
    assert len(loaded) == 1 and any("overlaps" in f for f in loaded.load_faults)


def test_two_registers_that_overlap_are_both_kept_when_access_tells_them_apart(
        tmp_path: Path) -> None:
    write_rows(tmp_path, "regs", "register", "ym", [
        a_register("0x10..0x13", "a", access="read"),
        a_register("0x11..0x12", "b", access="write")])
    loaded = rows_base.Base((tmp_path,), None)
    assert len(loaded) == 2 and loaded.load_faults == []


def test_a_device_is_resolved_from_its_own_scope_then_the_shared_one(tmp_path: Path) -> None:
    write_rows(tmp_path, "own", "device", "ibm-pc", [a_device("ym3812", "OPL2")])
    write_rows(tmp_path, "shared", "device", "chip", [a_device("ym3812", "OPL2")])
    write_rows(tmp_path, "solo", "device", "m6809", [a_device("solo", "Solo")])
    write_rows(tmp_path, "pair", "device", "board", [a_device("pair", "Pair")])
    write_rows(tmp_path, "pair2", "device", "board2", [a_device("pair", "Pair")])
    loaded = rows_base.Base((tmp_path,), None)
    own = loaded.device_entry("ibm-pc", "ym3812")
    assert own is not None and own.scope == "ibm-pc"
    shared = loaded.device_entry("other", "ym3812")
    assert shared is not None and shared.scope == "chip"
    solo = loaded.device_entry("other", "solo")
    assert solo is not None and solo.scope == "m6809"
    assert loaded.device_entry("other", "pair") is None


def test_a_search_for_no_word_answers_nothing_and_examines_everything(
        base: rows_base.Base) -> None:
    found = base.search(words="***")
    assert found.total == 0 and found.examined == len(base)


def test_the_neighbours_of_a_missed_call_are_the_nearest_below_and_above(
        base: rows_base.Base) -> None:
    found = base.search("call", "0x22/0x00")
    assert found.total == 0 and [e.key for e in found.nearest] == ["0x21/0x4D"]
    missed = base.search("call", "0x10/0x12/BL=0x99")
    assert [e.key for e in missed.nearest] == ["0x10/0x12", "0x10/0x12/BL=0x36"]


def test_a_key_with_no_kind_may_be_a_name_a_memory_address_or_a_range(
        base: rows_base.Base) -> None:
    assert base.search(key="speaker").total == 0
    assert [e.key for e in base.search(key="0040:0049").entries] == ["0x400..0x4FF", "0x449"]
    assert base.search(key="0x10..0x20..0x30").total == 0
    assert base.search(key="0x10..speaker").total == 0
    assert base.search(key="0xZZ").total == 0


def test_a_search_that_cut_its_list_says_so(base: rows_base.Base) -> None:
    assert base.search("port", limit=1).truncated is True
    assert base.search("port", limit=50).truncated is False


def test_a_folder_holding_a_file_that_is_not_a_dictionary_loads_the_rest(
        tmp_path: Path) -> None:
    write_rows(tmp_path, "errors", "error", "ibm-pc", [
        {"key": "1", "name": "one", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "An error.")]}])
    (tmp_path / "notes.txt").write_text("not a dictionary", encoding="utf-8")
    loaded = rows_base.Base((tmp_path,), None)
    assert len(loaded) == 1


def test_a_non_object_entry_is_refused() -> None:
    assert fmt.parse_entry([], header()) == (None, ["an entry is an object"])


def test_an_entry_may_sit_at_an_address_and_a_memory_key_places_itself() -> None:
    vector = {k: v for k, v in valid().items() if k != "device"}
    got, faults = parsed({**vector, "address": 0x100, "length": 2}, "vector")
    assert faults == [] and got is not None and (got.a_lo, got.a_hi) == (0x100, 0x101)
    memory, faults = parsed(an_entry("0040:0049", "video mode"), "memory")
    assert faults == [] and memory is not None and (memory.a_lo, memory.a_hi) == (0x449, 0x449)
