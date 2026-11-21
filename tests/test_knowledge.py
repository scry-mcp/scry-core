"""`scry_core.knowledge`: the key spellings, the entry format and its digest, the database's
lookups, and the text search through FTS5 and through the index of our own."""

from __future__ import annotations

import copy
import gc
import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, an_entry, write_dictionary

from scry_core import knowledge
from scry_core.knowledge import KeyFault, check, keys, sources, text
from scry_core.knowledge import entry as fmt
from scry_core.knowledge.support import Chip, Device, Scope, Support

NULL = KNOWLEDGE / "null"


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
    ("device", "vga-seq", "vga-seq")])
def test_a_key_has_one_spelling(kind: str, typed: str, canonical: str) -> None:
    assert keys.canonical(kind, typed) == canonical


@pytest.mark.parametrize(("kind", "typed"), [
    ("port", "3C8"), ("port", "0x"), ("port", " 0x3C8"), ("irq", "0x7"), ("irq", "07"),
    ("call", "0x21"), ("call", "0x21/0x4C/0x01/0x02"), ("call", "0x121/0x4C"),
    ("memory", "0x9000..0x8000"), ("device", "VGA"), ("device", ""), ("vector", "0x"),
    ("nothing", "1"), ("port", "0x" + "F" * 13), ("input", "x" * 65), ("input", "a\x00b"),
    ("irq", "9" * 20), ("irq", str(2**48)), ("error", "9" * 5000), ("vector", "9" * 17)])
def test_a_key_that_is_none_of_its_kind_is_refused(kind: str, typed: str) -> None:
    with pytest.raises(KeyFault):
        keys.canonical(kind, typed)


def test_a_key_covers_the_numbers_it_stands_for() -> None:
    assert keys.span("call", "0x21/0x4C") == keys.Span(0x21, 0x21, (0x21, 0x4C))
    assert keys.span("memory", "0040:0049").lo == 0x449
    assert keys.span("memory", "0x9000..0x9FFF") == keys.Span(0x9000, 0x9FFF)
    assert keys.span("input", "space") == keys.Span(None, None)
    assert keys.span("vector", "2").lo == 2 and keys.span("vector", "0x02").lo == 2


@pytest.mark.parametrize(("kind", "typed"), [("call", "0x121"), ("port", " "), ("port", "")])
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
]


@pytest.mark.parametrize(("change", "says"), ENTRY_FAULTS)
def test_an_entry_with_a_fault_says_what_it_is(change: dict[str, Any], says: str) -> None:
    got, faults = parsed({**valid(), **change})
    assert got is None and any(says in f for f in faults), faults


def test_two_sources_of_one_role_are_refused() -> None:
    raw = valid()
    raw["sources"] = raw["sources"] * 2
    assert any("two sources of one role" in f for f in parsed(raw)[1])


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


def test_the_digest_of_a_reworded_checked_entry_no_longer_matches_but_the_entry_loads(
        tmp_path: Path) -> None:
    raw = stamp(valid())
    raw["behaviour"] = "Reworded after the check."
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [raw])
    base = knowledge.Base.load(tmp_path)
    [only] = base.entries()
    assert base.faults() == [] and only.checked is not None
    assert only.checked.digest != only.digest


def test_a_header_is_judged_whole() -> None:
    got, faults = fmt.parse_header({"format": "scry-knowledge/2", "kind": "nope", "entries": 1,
                                    "left_out": [{"key": "1"}], "reached": {"x": "1"},
                                    "both": 1, "odd": 0}, "t.json")
    assert got is None
    for says in ("`format`", "`kind`", "`dictionary` is text", "`entries` is a list",
                 "`left_out`", "`reached`", "`both`", "unknown field `odd`"):
        assert any(says in f for f in faults), (says, faults)
    assert fmt.parse_header([], "t.json")[0] is None


def sample(tmp_path: Path) -> knowledge.Base:
    """Ports with ranges and devices, calls, a vector and a memory area, in two scopes."""
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x3C4", "sequencer index", aliases=["SEQ index"], device="vga-seq"),
        an_entry("0x3C5", "sequencer data", device="vga-seq"),
        an_entry("0x3C8", "DAC write address", aliases=["PEL address"], device="vga-dac",
                 description="Selects the palette entry the next data write sets.",
                 behaviour="Write the entry, then three values for red, green and blue."),
        an_entry("0x3C9", "DAC data", device="vga-dac"),
        an_entry("0x21", "PIC mask", description="The mask of the interrupt controller."),
        an_entry("0x226", "reset", access="write", device="sb"),
        an_entry("0x226", "reset status", access="read", device="sb")])
    write_dictionary(tmp_path, "calls", "call", "ibm-pc", [
        an_entry("0x21/0x4C", "exit", aliases=["terminate"]),
        an_entry("0x21/0x4D", "get return code"),
        an_entry("0x33/0x00", "mouse reset"),
        an_entry("0x33/0x00/0x03", "mouse reset subfunction")])
    write_dictionary(tmp_path, "vectors", "vector", "ibm-pc", [
        an_entry("0x21", "DOS", address=0x84, length=4)])
    write_dictionary(tmp_path, "irqs", "irq", "ibm-pc", [an_entry("0", "system timer",
                                                                    device="pit8253")])
    write_dictionary(tmp_path, "memory", "memory", "ibm-pc", [
        an_entry("0040:0049", "video mode", address=0x449, length=1),
        an_entry("0x400..0x4FF", "BIOS data area", address=0x400, length=0x100)])
    write_dictionary(tmp_path, "devices", "device", "ibm-pc", [
        an_entry("sb", "Sound Blaster", contains=["sb-dsp"], irq=[5, 7], dma=[1],
                 ports=[{"base": "0x220", "length": 16}]),
        an_entry("sb-dsp", "Sound Blaster DSP"),
        an_entry("pit8253", "8253 timer", irq=[0], ports=[{"base": "0x40", "length": 4}]),
        an_entry("vga-seq", "VGA sequencer"), an_entry("vga-dac", "VGA DAC")])
    write_dictionary(tmp_path, "sb-dsp", "command", "sb-dsp", [
        an_entry("0xE1", "get DSP version")])
    write_dictionary(tmp_path, "vga-seq", "register", "vga-seq", [
        an_entry("0x04", "memory mode")], reached={"index": "0x3C4", "data": "0x3C5"})
    write_dictionary(tmp_path, "m68000", "vector", "m68000", [
        an_entry("2", "bus error vector", aliases=["BERR"], address=8, length=4)])
    return knowledge.Base.load(tmp_path)


@pytest.fixture
def base(tmp_path: Path) -> knowledge.Base:
    got = sample(tmp_path)
    assert got.faults() == []
    return got


def ids(found: knowledge.Found) -> list[str]:
    return [e.id for e in found.entries]


def test_an_entry_is_found_by_id_by_key_and_by_name(base: knowledge.Base) -> None:
    assert base.by_id("ibm-pc:port:0x3C8") == base.get("port", "0x3C8", "ibm-pc")
    assert base.by_id("ibm-pc:port:0x226:write") != base.by_id("ibm-pc:port:0x226:read")
    assert base.by_id("ibm-pc:port:0x999") is None and base.get("port", "0x3C8", "m68000") is None
    assert [e.id for e in base.by_alias("pel ADDRESS")] == ["ibm-pc:port:0x3C8"]
    assert [e.id for e in base.by_alias("dac write address")] == ["ibm-pc:port:0x3C8"]


def test_a_number_is_exact_or_a_range_and_a_range_overlaps(base: knowledge.Base) -> None:
    assert ids(base.search("port", "0x3c8")) == ["ibm-pc:port:0x3C8"]
    assert ids(base.search("port", "0x3C4..0x3C9")) == [
        "ibm-pc:port:0x3C4", "ibm-pc:port:0x3C5", "ibm-pc:port:0x3C8", "ibm-pc:port:0x3C9"]
    assert ids(base.search("memory", "0x449")) == ["ibm-pc:memory:0x400..0x4FF",
                                                   "ibm-pc:memory:0040:0049"]
    assert "ibm-pc:memory:0040:0049" in ids(base.search("memory", "0040:0049", scopes=("ibm-pc",)))


def test_a_call_is_asked_by_its_leading_parts(base: knowledge.Base) -> None:
    assert ids(base.search("call", "0x21")) == ["ibm-pc:call:0x21/0x4C", "ibm-pc:call:0x21/0x4D"]
    assert ids(base.search("call", "0x33/0x00")) == ["ibm-pc:call:0x33/0x00",
                                                      "ibm-pc:call:0x33/0x00/0x03"]
    assert ids(base.search("call", "0x33/0x00/0x03")) == ["ibm-pc:call:0x33/0x00/0x03"]


def test_a_number_with_no_kind_is_every_kind_that_has_it(base: knowledge.Base) -> None:
    assert ids(base.search(key="0x21")) == ["ibm-pc:port:0x21", "ibm-pc:vector:0x21"]
    assert ids(base.search(key="0x21/0x4C")) == ["ibm-pc:call:0x21/0x4C"]
    assert ids(base.search(key="vga-seq")) == ["ibm-pc:device:vga-seq"]
    assert ids(base.search(key="0")) == ["ibm-pc:irq:0"]
    assert ids(base.search(key="0x3C4..0x3C5")) == ["ibm-pc:port:0x3C4", "ibm-pc:port:0x3C5"]


def test_an_address_finds_the_narrowest_thing_that_sits_there(base: knowledge.Base) -> None:
    assert [(e.id, d) for e, d in [base.at(0x449) or (None, 0)] if e] == [
        ("ibm-pc:memory:0040:0049", 0)]
    found = base.at(0x44A, "ibm-pc")
    assert found is not None and found[0].name == "BIOS data area" and found[1] == 0x4A
    assert base.at(0x86, "ibm-pc") is not None and base.at(0x86, "ibm-pc")[0].name == "DOS"  # type: ignore[index]
    assert base.at(10, "m68000") is not None and base.at(10, "m68000")[1] == 2  # type: ignore[index]
    assert base.at(0x86, "m68000") is None and base.at(0x5000) is None


def test_a_search_by_words_puts_the_name_first_and_breaks_ties_by_number(
        base: knowledge.Base) -> None:
    assert ids(base.search(words="dac")) == ["ibm-pc:device:vga-dac", "ibm-pc:port:0x3C8",
                                             "ibm-pc:port:0x3C9"]
    assert ids(base.search(words="palette"))[0] == "ibm-pc:port:0x3C8"
    assert ids(base.search(words="pel address")) == ["ibm-pc:port:0x3C8"]
    assert ids(base.search(words="sequ*", kind="port")) == ["ibm-pc:port:0x3C4",
                                                            "ibm-pc:port:0x3C5"]
    assert ids(base.search(words="red green blue")) == ["ibm-pc:port:0x3C8"]
    assert base.search(words="zebra").total == 0


def test_a_hit_in_the_name_outranks_one_in_the_behaviour(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x10", "alpha", behaviour="Mentions the zulu timer."),
        an_entry("0x11", "bravo", description="A zulu timer."),
        an_entry("0x12", "zulu timer"), an_entry("0x13", "charlie", aliases=["zulu timer"])])
    for fts5 in (None, False):
        found = knowledge.Base.load(tmp_path, fts5=fts5).search(words="zulu timer")
        assert [e.name for e in found.entries] == ["zulu timer", "charlie", "bravo", "alpha"]


def test_a_device_is_everything_of_it_and_of_what_it_holds(base: knowledge.Base) -> None:
    assert ids(base.search(device="sb")) == [
        "ibm-pc:port:0x226:read", "ibm-pc:port:0x226:write", "sb-dsp:command:0xE1"]
    assert ids(base.search(device="vga-seq", kind="register")) == ["vga-seq:register:0x04"]
    assert ids(base.search(device="vga-dac")) == ["ibm-pc:port:0x3C8", "ibm-pc:port:0x3C9"]
    assert base.search(device="sb-dsp", words="version").total == 1


def test_nothing_found_says_how_much_was_searched_and_what_is_near(base: knowledge.Base) -> None:
    found = base.search("port", "0x3C6", scopes=("ibm-pc",))
    assert found.total == 0 and found.examined == 7
    assert ids(knowledge.Found(entries=found.nearest)) == ["ibm-pc:port:0x3C5",
                                                           "ibm-pc:port:0x3C8"]
    assert [e.name for e in base.search(words="sequel").nearest] == [
        "VGA sequencer", "sequencer index", "sequencer data"]
    assert base.search(words="*").total == 0
    with pytest.raises(KeyFault):
        base.search("port", "nothing")


def test_a_search_lists_the_first_limit_and_says_it_cut(base: knowledge.Base) -> None:
    found = base.search("port", limit=3)
    assert (len(found.entries), found.total, found.truncated) == (3, 7, True)
    assert not base.search("port", limit=7).truncated


def test_a_relation_leads_from_a_thing_to_its_hardware(base: knowledge.Base) -> None:
    port = base.by_id("ibm-pc:port:0x3C8")
    assert port is not None
    assert base.related(port).device == base.by_id("ibm-pc:device:vga-dac")
    sb = base.by_id("ibm-pc:device:sb")
    assert sb is not None
    related = base.related(sb)
    assert [d.id for d in related.contains] == ["ibm-pc:device:sb-dsp"]
    assert [u.id for u in related.used_by] == ["ibm-pc:port:0x226:read", "ibm-pc:port:0x226:write"]
    register = base.by_id("vga-seq:register:0x04")
    assert register is not None
    shown = base.related(register)
    assert shown.device == base.by_id("ibm-pc:device:vga-seq")
    assert dict(shown.reached) == {"index": ("ibm-pc:port:0x3C4",), "data": ("ibm-pc:port:0x3C5",)}
    seven = base.by_id("ibm-pc:irq:0")
    assert seven is not None and [d.key for d in base.related(seven).used_by] == ["pit8253"]
    pit_port = base.get("port", "0x21", "ibm-pc")
    assert pit_port is not None and base.related(pit_port).used_by == ()


def test_a_device_is_resolved_from_its_own_scope_then_the_shared_one(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "chips", "device", "chip", [an_entry("ym2151", "YM2151 OPM")])
    write_dictionary(tmp_path, "pc", "device", "ibm-pc", [an_entry("opl", "OPL"),
                                                           an_entry("ym2151", "PC YM2151")])
    base = knowledge.Base.load(tmp_path)
    assert base.device_entry("ibm-pc", "ym2151") == base.by_id("ibm-pc:device:ym2151")
    assert base.device_entry("m6809", "ym2151") == base.by_id("chip:device:ym2151")
    assert base.device_entry("", "ym2151") == base.by_id("chip:device:ym2151")
    assert base.device_entry("", "opl") == base.by_id("ibm-pc:device:opl")
    assert base.device_entry("", "none") is None


def test_the_scopes_and_the_kinds_held_are_listed(base: knowledge.Base) -> None:
    assert base.scopes() == ["ibm-pc", "m68000", "sb-dsp", "vga-seq"]
    assert base.scopes("vector") == ["ibm-pc", "m68000"]
    assert base.kinds("m68000") == ["vector"] and base.kinds()[0] == "vector"
    assert len(base) == len(list(base.entries()))


def test_a_run_skips_what_it_cannot_read_and_counts_it(tmp_path: Path) -> None:
    entries: list[Any] = [an_entry("0x10", "ok"), an_entry("0x10", "twice"), {"key": "0x11"}, 5]
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", entries)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "other.json").write_text('{"format": "scry-knowledge/2"}', encoding="utf-8")
    base = knowledge.Base.load(tmp_path)
    assert [e.name for e in base.entries()] == ["ok"]
    assert any("not JSON" in f for f in base.file_faults)
    assert any("`format`" in f for f in base.file_faults)
    assert any("is already an entry" in f for f in base.load_faults)
    assert any("`name` is text" in f for f in base.entry_faults)
    assert any("an entry is an object" in f for f in base.entry_faults)


def test_a_missing_directory_is_a_fault_not_a_crash(tmp_path: Path) -> None:
    base = knowledge.Base.load(tmp_path / "none", "scry_core_absent_package")
    assert len(base) == 0 and len(base.file_faults) == 2


def test_a_base_from_the_fixture_directory_answers_what_the_checks_hold() -> None:
    base = knowledge.Base.load(NULL)
    assert len(base) == 6
    assert knowledge.Base.load(NULL, fts5=False).uses_fts5 is False


def test_words_are_letters_and_digits_without_accents() -> None:
    assert text.words("Sound-Blaster 2.0, über_café 0x3C8") == [
        "sound", "blaster", "2", "0", "uber", "cafe", "0x3c8"]
    assert text.terms("timer* a*b c d*") == [
        text.Term("timer", True), text.Term("a", False), text.Term("b", False),
        text.Term("c", False), text.Term("d", True)]
    assert text.terms('"; DROP * --') == [text.Term("drop", False)] and text.terms("*") == []


def synthetic(folder: Path, count: int) -> None:
    pool = ["timer", "counter", "palette", "index", "status", "latch", "channel", "volume",
            "sprite", "vector", "mask", "reset", "clock", "buffer", "cursor", "noise", "sample",
            "select", "plane", "colour"]
    entries = [an_entry(f"0x{0x100 + n:X}", f"{pool[n % 20]} {pool[(n * 7) % 20]} {n}",
                        aliases=[pool[(n * 3) % 20].upper()],
                        description=f"{pool[(n * 5) % 20]} {pool[(n * 11) % 20]} of {n}.",
                        behaviour=f"Sets the {pool[(n * 13) % 20]} and the {pool[(n * 17) % 20]}.")
               for n in range(count)]
    write_dictionary(folder, "ports", "port", "ibm-pc", entries)


@pytest.mark.parametrize("asked", ["timer", "timer counter", "tim*", "reset clo*", "colour 7",
                                   "nothingatall", "SAMPLE", "plane* sprite*"])
def test_the_fallback_answers_what_fts5_answers_in_the_same_order(
        tmp_path: Path, asked: str) -> None:
    synthetic(tmp_path, 200)
    ours, host = knowledge.Base.load(tmp_path, fts5=False), knowledge.Base.load(tmp_path)
    if not host.uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    assert ids(ours.search(words=asked, limit=50)) == ids(host.search(words=asked, limit=50))
    assert ours.search(words=asked).total == host.search(words=asked).total


def test_an_entry_built_from_its_row_is_the_entry_the_file_parsed(tmp_path: Path) -> None:
    device = an_entry("sb", "Sound Blaster", aliases=["SB", "SB16"], differs="The list says more.",
                      contains=["sb-dsp"], irq=[5, 7], dma=[1, 5], classes=["sound"],
                      ports=[{"base": "0x220", "length": 16}, {"base": "0x388", "length": 4}],
                      handlers={"write+0": "register select"})
    area = an_entry("0040:0049", "video mode", address=0x449, length=1)
    port = stamp(an_entry("0x3C4", "sequencer index", device="vga-seq"))
    register = an_entry("0x04", "memory mode")
    plan = [("devices", "device", "ibm-pc", [device], None), ("memory", "memory", "ibm-pc",
                                                              [area], None),
            ("ports", "port", "ibm-pc", [port], None),
            ("vga-seq", "register", "vga-seq", [register], {"index": "0x3C4", "data": "0x3C5"})]
    for dictionary, kind, scope, raws, reached in plan:
        write_dictionary(tmp_path, dictionary, kind, scope, raws, **(
            {"reached": reached} if reached else {}))
    base = knowledge.Base.load(tmp_path)
    assert base.faults() == []
    for dictionary, kind, scope, raws, reached in plan:
        made = fmt.Header("t.json", dictionary, kind, scope, "covers", "list", (), reached, False)
        for raw in raws:
            want, faults = fmt.parse_entry(raw, made)
            assert faults == [] and want is not None
            assert base.by_id(want.id) == want
    got = base.by_id("ibm-pc:port:0x3C4")
    assert got is not None and got.checked is not None and got.checked.digest == got.digest


def sized(folder: Path, count: int) -> None:
    """`count` entries the size a real dictionary's are: two aliases, a description and a
    behaviour of a few dozen words, a device and a source, in files of sixty."""
    pool = ["register", "port", "timer", "counter", "palette", "index", "status", "write", "read",
            "latch", "channel", "volume", "sprite", "vector", "interrupt", "mask", "enable",
            "reset", "data", "address", "control", "mode", "clock"]

    def sentence(n: int, words: int) -> str:
        return " ".join(pool[(n * k + k * k) % len(pool)] for k in range(1, words + 1)) + "."

    for first in range(0, count, 60):
        write_dictionary(folder, f"d{first // 60:03d}", "port", f"scope{first // 60}", [
            an_entry(f"0x{0x100 + n:X}",
                     f"{pool[n % len(pool)]} {pool[(n * 7) % len(pool)]} {n}"[:24],
                     aliases=[f"A{n}", f"R{n}"], description=sentence(n, 22),
                     behaviour=sentence(n, 18) + " " + sentence(n + 1, 14), device="dev0")
            for n in range(first, min(first + 60, count))])


#: What the base may keep in Python objects per entry, in bytes. The loader keeps the rows in
#: SQLite and builds an `Entry` when asked, so what stays is a header per file and a few
#: constants: a few dozen bytes an entry at this size. The bound sits above that and below the
#: size of one `Entry` (a frozen dataclass of dozens of fields), so keeping even one object per
#: entry fails it.
KEPT_PER_ENTRY = 64


def test_a_loaded_base_keeps_no_python_object_per_entry(tmp_path: Path) -> None:
    count = 2000
    sized(tmp_path, count)
    if not knowledge.Base.load(tmp_path).uses_fts5:
        pytest.skip("this host's SQLite has no FTS5, so the index of our own is built in Python")
    gc.collect()
    tracemalloc.start()
    try:
        base = knowledge.Base.load(tmp_path)
        gc.collect()
        kept, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(base) == count and base.faults() == []
    assert kept / count < KEPT_PER_ENTRY, f"{kept / count:.0f} bytes kept an entry"


def test_the_comparison_of_the_two_paths_runs_on_every_base(tmp_path: Path) -> None:
    synthetic(tmp_path, 60)
    from scry_core.knowledge import check
    assert check.fallback_differs(lambda fts5: knowledge.Base.load(tmp_path, fts5=fts5)) == []
    assert len(check._asked(knowledge.Base.load(tmp_path))) > 20


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


def test_a_memory_area_sits_where_its_key_says_and_a_device_holds_its_ranges() -> None:
    got, faults = parsed(an_entry("0x400..0x4FF", "BIOS data"), "memory")
    assert faults == [] and got is not None and (got.a_lo, got.a_hi) == (0x400, 0x4FF)
    device, _ = parsed(an_entry("sb", "Sound Blaster", ports=[{"base": "0x220", "length": 16}],
                                handlers={"write+0": "register select"}, classes=["ym"]), "device")
    assert device is not None and device.ports == ((0x220, 16),) and device.handlers


def test_a_package_names_its_dictionaries_and_a_folder_of_none_is_not_a_crash(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "fixturepkg" / "knowledge" / "deeper"
    write_dictionary(package, "ports", "port", "ibm-pc", [an_entry("0x10", "ok")])
    (tmp_path / "fixturepkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "fixturepkg" / "knowledge" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    base = knowledge.Base.load("fixturepkg")
    assert [e.id for e in base.entries()] == ["ibm-pc:port:0x10"] and base.faults() == []


def test_a_host_with_no_fts5_answers_through_the_index_of_our_own(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synthetic(tmp_path, 40)
    wanted = knowledge.Base.load(tmp_path, fts5=False)
    monkeypatch.setattr("scry_core.knowledge.database._FTS", "CREATE VIRTUAL TABLE entry_text "
                        "USING nosuchmodule (name)")
    host = knowledge.Base.load(tmp_path)
    assert host.uses_fts5 is False
    assert ids(host.search(words="timer*", limit=50)) == ids(wanted.search(words="timer*",
                                                                          limit=50))


def test_a_base_whose_load_failed_is_still_released() -> None:
    knowledge.Base.__new__(knowledge.Base).__del__()
    knowledge.Base().close()


def test_a_cycle_of_devices_holding_each_other_ends(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "devices", "device", "ibm-pc", [
        an_entry("a", "A", contains=["b"]), an_entry("b", "B", contains=["a"])])
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [an_entry("0x10", "p", device="b")])
    assert ids(knowledge.Base.load(tmp_path).search(device="a")) == ["ibm-pc:port:0x10"]


def test_a_number_with_no_kind_may_be_a_segment_an_odd_range_or_a_name(
        base: knowledge.Base) -> None:
    assert ids(base.search(key="0040:0049")) == ["ibm-pc:memory:0x400..0x4FF",
                                                 "ibm-pc:memory:0040:0049"]
    assert base.search(key="0x10..0x5").total == 0 and base.search(key="1..zz").total == 0


def test_a_register_reached_by_handlers_names_them_and_not_ports(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "devices", "device", "chip", [an_entry("ym", "YM")])
    write_dictionary(tmp_path, "ym", "register", "ym", [an_entry("0x14", "timer")],
                     reached={"index": "address_w", "data": ["register_r", "register_w"]})
    base = knowledge.Base.load(tmp_path)
    [register] = [e for e in base.entries() if e.kind == "register"]
    assert dict(base.related(register).reached) == {
        "index": ("address_w",), "data": ("register_r", "register_w")}
    assert check.relations(base) == []



def test_a_datasheet_is_not_held_to_the_index_and_a_missing_list_is_named(
        tmp_path: Path) -> None:
    datasheet = {"role": "documentation", "ref": "datasheet:MC6845 data sheet, table 3",
                 "cites": "R12 start address high"}
    write_dictionary(tmp_path, "regs", "register", "mc6845", [
        {**an_entry("0x0C", "start address high"), "sources": [datasheet]}], complete_against="x")
    base = knowledge.Base.load(tmp_path)
    assert check.against_sources(base, sources.SourceIndex()) == []
    assert check.covered(base, sources.SourceIndex()) == [
        "regs must cover 'x' and the source index has no such list"]


def test_a_source_row_whose_key_is_no_key_is_compared_as_it_stands(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [an_entry("0x10", "p")])
    base = knowledge.Base.load(tmp_path)
    ref = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"
    line = base.by_id("ibm-pc:port:0x10").sources[0].cites  # type: ignore[union-attr]
    index = sources.SourceIndex(rows={ref: sources.Row(line, "garbage")})
    assert check.against_sources(base, index) == [
        f"ports 0x10: {ref} is the source of garbage, not of 0x10"]


def test_a_declared_device_that_holds_one_with_no_entry_is_told_so() -> None:
    from null_server import NullKnowledge
    subject = NullKnowledge(declared=Support(
        scopes=(Scope("ibm-pc", written=("call", "port", "device")),),
        devices=(Device("vga-seq", written=("register",), inside=("vga-core",)),)))
    assert check.owed_dictionaries(subject.base(), subject.support()) == [
        "vga-seq holds vga-core, which has no `device` entry"]


def test_a_contains_that_names_no_device_fails_the_relations(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "devices", "device", "ibm-pc", [an_entry("a", "A",
                                                                       contains=["zz"])])
    assert check.relations(knowledge.Base.load(tmp_path)) == [
        "device a: contains 'zz', which is no device entry"]


@pytest.mark.parametrize(("broken", "says"), [
    ("by_id", "did not load by id"), ("get", "is not found by its kind, key and scope"),
    ("by_alias", "is not found by its name"), ("search", "is not found by the words of its name")])
def test_a_database_that_lost_an_entry_is_told_so(
        base: knowledge.Base, monkeypatch: pytest.MonkeyPatch, broken: str, says: str) -> None:
    lost: dict[str, Any] = {"by_id": None, "get": None, "by_alias": [],
                            "search": knowledge.Found()}
    monkeypatch.setattr(knowledge.Base, broken, lambda self, *a, **k: lost[broken])
    assert any(says in fault for fault in check.held(base))


def test_the_words_a_comparison_asks_are_bounded_and_cover_a_name_of_one_word(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x10", "alpha"), an_entry("0x11", "beta gamma delta"),
        an_entry("0x12", "epsilon zeta")])
    base = knowledge.Base.load(tmp_path)
    asked = check._asked(base)
    assert "alpha" in asked and any(" " in a for a in asked)
    monkeypatch.setattr(check, "WORDS_ASKED", 1)
    assert len(check._asked(base)) < len(asked)


def test_a_comparison_that_cannot_tell_the_paths_apart_says_so(tmp_path: Path) -> None:
    synthetic(tmp_path, 5)
    if not knowledge.Base.load(tmp_path).uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    assert check.fallback_differs(lambda fts5: knowledge.Base.load(tmp_path)) == [
        "the base asked for no FTS5 and used it"]
    assert check.fallback_differs(lambda fts5: knowledge.Base.load(tmp_path, fts5=False)) == []


def test_a_number_too_wide_to_hold_is_a_fault_or_a_miss_and_never_a_crash(
        tmp_path: Path) -> None:
    entries = [an_entry("9" * 20, "wide"), an_entry("5", "ok", address=10**30, length=1)]
    write_dictionary(tmp_path, "irqs", "irq", "ibm-pc", entries)
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [an_entry("0x10", "p", device=None)])
    base = knowledge.Base.load(tmp_path)
    assert len(base) == 0 and len(base.entry_faults) == 3
    for wide in ("9" * 25, "0xFFFFFFFFFFFFFFFFFFFF", "9" * 5000):
        assert base.search(key=wide).total == 0


def test_a_port_range_too_long_to_hold_is_a_fault_and_never_a_crash(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "devices", "device", "ibm-pc", [
        an_entry("sb", "SB", ports=[{"base": "0x220", "length": 10**30}]),
        an_entry("ok", "OK", ports=[{"base": "0x220", "length": 16}])])
    base = knowledge.Base.load(tmp_path)
    assert [e.key for e in base.entries()] == ["ok"] and len(base.entry_faults) == 1
    assert "`ports`" in base.entry_faults[0]


def test_a_name_that_is_also_its_alias_is_found_once(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x10", "exit", aliases=["EXIT", "quit", "Quit"])])
    base = knowledge.Base.load(tmp_path)
    assert ids(knowledge.Found(entries=base.by_alias("exit"))) == ["ibm-pc:port:0x10"]
    assert len(base.by_alias("QUIT")) == 1


def test_text_with_no_ascii_in_it_is_found_the_same_way_on_both_paths(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry("0x10", "timer", description="Stra\u00dfe timer \ufb01ne \u00b2.")])
    host = knowledge.Base.load(tmp_path)
    if not host.uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    ours = knowledge.Base.load(tmp_path, fts5=False)
    for asked in ("Stra\u00dfe", "strasse", "fine", "\ufb01ne", "2", "stra*"):
        assert host.search(words=asked).total == ours.search(words=asked).total == 1, asked


def test_the_neighbours_of_a_missed_call_tie_in_load_order(tmp_path: Path) -> None:
    write_dictionary(tmp_path, "z", "call", "zz", [an_entry("0x21/0x4C", "exit")])
    write_dictionary(tmp_path, "zz", "call", "aa", [an_entry("0x21/0x4C", "exit")])
    base = knowledge.Base.load(tmp_path)
    assert ids(knowledge.Found(entries=base.search("call", "0x21/0x4E").nearest)) == [
        "zz:call:0x21/0x4C"]


def test_a_range_of_calls_is_the_calls_inside_it_and_a_miss_names_its_neighbours(
        base: knowledge.Base) -> None:
    assert ids(base.search("call", "0x21/0x4C..0x21/0x4C")) == ["ibm-pc:call:0x21/0x4C"]
    assert ids(base.search("call", "0x21/0x00..0x21/0x4C")) == ["ibm-pc:call:0x21/0x4C"]
    assert ids(base.search("call", "0x21/0x4D..0x33/0x00")) == [
        "ibm-pc:call:0x21/0x4D", "ibm-pc:call:0x33/0x00", "ibm-pc:call:0x33/0x00/0x03"]
    assert ids(base.search(key="0x21/0x4C..0x21/0x4D")) == ["ibm-pc:call:0x21/0x4C",
                                                            "ibm-pc:call:0x21/0x4D"]
    with pytest.raises(KeyFault, match="runs upward"):
        base.search("call", "0x21/0x4D..0x21/0x4C")
    missed = base.search("call", "0x21/0x4E")
    assert missed.total == 0 and ids(knowledge.Found(entries=missed.nearest)) == [
        "ibm-pc:call:0x21/0x4D", "ibm-pc:call:0x33/0x00"]


def test_what_is_nearest_to_a_word_stays_inside_the_kind_and_scope_asked(
        base: knowledge.Base) -> None:
    assert [e.name for e in base.search(kind="register", words="sequel").nearest] == []
    assert [e.name for e in base.search(kind="port", words="sequel",
                                        scopes=("m68000",)).nearest] == []
    assert [e.id for e in base.search(kind="register", words="memo").nearest] == [
        "vga-seq:register:0x04"]


def test_a_reached_port_that_is_no_number_is_a_fault_and_a_name_is_a_handler(
        tmp_path: Path) -> None:
    write_dictionary(tmp_path, "devices", "device", "ibm-pc", [an_entry("d", "D")])
    write_dictionary(tmp_path, "d", "register", "d", [an_entry("0x04", "r")],
                     reached={"index": "0x3G4", "data": "address_w"})
    assert check.relations(knowledge.Base.load(tmp_path)) == [
        "registers 0x04: reached index names '0x3G4', which is no port entry"]


def test_a_name_asked_for_by_its_words_is_found_whatever_many_others_share_them(
        tmp_path: Path) -> None:
    write_dictionary(tmp_path, "ports", "port", "ibm-pc", [
        an_entry(f"0x{0x100 + n:X}", "status") for n in range(60)])
    assert check.held(knowledge.Base.load(tmp_path)) == []
