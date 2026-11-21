"""`conformance.KnowledgeContract`: a server with a small base of fixture entries passes it, and a
copy of that base broken one rule at a time fails the case that rule belongs to, and only it."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, NullKnowledge

from scry_core import conformance
from scry_core.knowledge import Device, Scope, Support, digest, lock, seal, text

CASES = sorted(n for n in dir(conformance.KnowledgeContract) if n.startswith("test_"))
OWED = "test_every_declared_scope_device_and_chip_has_the_dictionaries_it_owes"
UNDECLARED = "test_every_dictionary_is_of_a_declared_scope_and_the_code_names_no_other"
PARSES = "test_every_dictionary_file_parses"
WHOLE = "test_every_entry_is_whole_and_ids_are_unique"
AGAINST = "test_every_entry_agrees_with_the_source_index"
COVERED = "test_every_key_of_the_list_a_dictionary_covers_is_named_or_left_out"
RELATIONS = "test_every_relation_resolves"
BOTH = "test_two_sources_agree_or_the_entry_says_how_they_differ"
ALIASES = "test_no_alias_is_another_entry_s_name"
FALLBACK = "test_the_fallback_answers_as_fts5_does"
REWORDED = "test_a_checked_entry_is_never_reworded"
LOCKED = "test_every_checked_entry_is_locked_and_stays_as_it_was_locked"
EXAMINED = "test_the_check_examined_something"
EXIT = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"
EXIT_ID = "ibm-pc:call:0x21/0x4C"
SEQ_PORT = "dosbox-x:src/hardware/vga_seq.cpp VGA_SetupSEQ 0x3c4"


class TestNullKnowledge(conformance.KnowledgeContract):
    @pytest.fixture
    def subject(self) -> NullKnowledge:
        return NullKnowledge()


class Copy:
    """The null server's base, copied into a folder of the test's own so a rule can be broken."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "null"
        shutil.copytree(KNOWLEDGE / "null", self.root)
        self.index_path = tmp_path / "sources.json"
        shutil.copy(KNOWLEDGE / "null-sources.json", self.index_path)
        self.lock_path = tmp_path / "lock.json"
        shutil.copy(KNOWLEDGE / "null-lock.json", self.lock_path)
        self.declared: Support | None = None
        self.code: tuple[str, ...] = ("ibm-pc",)

    def edit(self, name: str, change: Callable[[dict[str, Any]], None]) -> None:
        path = self.root / f"{name}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        change(doc)
        path.write_text(lock.dumps(doc), encoding="utf-8")

    def index(self, change: Callable[[dict[str, Any]], None]) -> None:
        doc = json.loads(self.index_path.read_text(encoding="utf-8"))
        change(doc)
        self.index_path.write_text(json.dumps(doc), encoding="utf-8")

    def relock(self, change: Callable[[dict[str, Any]], None]) -> None:
        doc = json.loads(self.lock_path.read_text(encoding="utf-8"))
        change(doc)
        self.lock_path.write_text(json.dumps(doc), encoding="utf-8")

    def subject(self) -> NullKnowledge:
        return NullKnowledge(self.root, self.index_path, self.lock_path, self.declared, self.code)


def run(subject: NullKnowledge) -> set[str]:
    """The cases of the contract that fail on `subject`."""
    contract, failed = conformance.KnowledgeContract(), set()
    for name in CASES:
        try:
            getattr(contract, name)(subject)
        except AssertionError:
            failed.add(name)
        except pytest.skip.Exception:
            continue
    return failed


def entry(doc: dict[str, Any], key: str) -> dict[str, Any]:
    found: dict[str, Any] = next(e for e in doc["entries"] if e["key"] == key)
    return found


def test_the_fixture_base_passes_every_case_and_the_runner_can_tell_a_failure() -> None:
    assert len(CASES) == 15 and run(NullKnowledge()) == set()
    assert run(NullKnowledge(declared=Support())) == {EXAMINED, UNDECLARED}


def key_changed(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4D").update(key="0x21/0x4E"))


def source_missing(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4D").pop("sources"))


def quote_altered(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4D")["sources"][0].update(cites="case 0x4d:"))


def row_missing(c: Copy) -> None:
    c.index(lambda d: d["rows"].pop(SEQ_PORT))


def left_out_forgotten(c: Copy) -> None:
    c.edit("calls", lambda d: d.pop("left_out"))


def left_out_wrongly(c: Copy) -> None:
    c.edit("calls", lambda d: d["left_out"].append({"key": "0x21/0x99", "why": "not on the list"}))


def checked_entry_reworded(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4C").update(
        behaviour="AL is the return code, and the program ends."))


def checked_record_edited(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4C")["checked"].update(by="another checker"))


def checked_record_deleted(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4C").pop("checked"))


def checked_entry_removed(c: Copy) -> None:
    c.edit("calls", lambda d: d["entries"].remove(entry(d, "0x21/0x4C")))


def checked_entry_reworded_and_resealed(c: Copy) -> None:
    def reword(d: dict[str, Any]) -> None:
        raw = entry(d, "0x21/0x4C")
        raw["behaviour"] = "AL is the return code, and the program ends."
        raw["checked"]["digest"] = digest("ibm-pc", "call", raw)
    c.edit("calls", reword)


def checked_entry_left_out_of_the_lock(c: Copy) -> None:
    c.relock(lambda d: d["checked"].clear())


def lock_names_an_entry_that_was_never_checked(c: Copy) -> None:
    c.relock(lambda d: d["checked"].update({"ibm-pc:call:0x21/0x4D": {
        "digest": "0" * 64, "by": "nobody", "against": []}}))


def checked_against_free_text(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4C")["checked"]["against"][0].update(
        line="I read it and it looked right"))
    assert seal.seal(c.root / "calls.json", [EXIT_ID], c.lock_path) == []


def checked_by_its_writer(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4C")["checked"].update(by="fixture writer"))


def scope_without_dictionary(c: Copy) -> None:
    c.declared = Support(scopes=(Scope("ibm-pc", written=("call", "port", "device", "irq")),),
                         devices=(Device("vga-seq", written=("register",)),))


def dictionary_of_an_undeclared_scope(c: Copy) -> None:
    c.code = ("ibm-pc", "z80")


def device_entry_gone(c: Copy) -> None:
    c.edit("devices", lambda d: d["entries"].clear())


def one_source_where_two_exist(c: Copy) -> None:
    c.edit("ports", lambda d: d.update(both=True))


def alias_is_another_name(c: Copy) -> None:
    c.edit("calls", lambda d: entry(d, "0x21/0x4D").update(aliases=["exit"]))


def duplicate_id(c: Copy) -> None:
    c.edit("ports", lambda d: d["entries"].append(dict(d["entries"][0])))


def file_broken(c: Copy) -> None:
    (c.root / "broken.json").write_text("{", encoding="utf-8")


def register_scope_not_a_device(c: Copy) -> None:
    c.edit("vga-seq", lambda d: d.update(scope="vga-sec"))


def reached_port_unknown(c: Copy) -> None:
    c.edit("vga-seq", lambda d: d.update(reached={"index": "0x3C6", "data": "0x3C5"}))


@pytest.mark.parametrize(("break_it", "failed"), [
    (key_changed, {AGAINST, COVERED}),
    (source_missing, {WHOLE, COVERED}),
    (quote_altered, {AGAINST}),
    (row_missing, {AGAINST}),
    (left_out_forgotten, {COVERED}),
    (left_out_wrongly, {COVERED}),
    (checked_entry_reworded, {REWORDED, LOCKED}),
    (checked_against_free_text, {AGAINST}),
    (checked_record_edited, {REWORDED, LOCKED}),
    (checked_record_deleted, {LOCKED}),
    (checked_entry_removed, {COVERED, LOCKED}),
    (checked_entry_reworded_and_resealed, {LOCKED}),
    (checked_entry_left_out_of_the_lock, {LOCKED}),
    (lock_names_an_entry_that_was_never_checked, {LOCKED}),
    (checked_by_its_writer, {WHOLE, COVERED, LOCKED}),
    (scope_without_dictionary, {OWED}),
    (dictionary_of_an_undeclared_scope, {UNDECLARED}),
    (device_entry_gone, {OWED, RELATIONS, COVERED}),
    (one_source_where_two_exist, {BOTH}),
    (alias_is_another_name, {ALIASES}),
    (duplicate_id, {WHOLE}),
    (file_broken, {PARSES}),
    (register_scope_not_a_device, {OWED, UNDECLARED, RELATIONS}),
    (reached_port_unknown, {RELATIONS}),
], ids=lambda value: getattr(value, "__name__", "") or "")
def test_a_rule_broken_fails_its_own_case_and_only_the_cases_it_touches(
        tmp_path: Path, break_it: Callable[[Copy], None], failed: set[str]) -> None:
    copy = Copy(tmp_path)
    assert run(copy.subject()) == set(), "the copy is the control and passes"
    break_it(copy)
    assert run(copy.subject()) == failed


def test_two_sources_that_mark_a_port_differently_need_a_sentence_saying_so(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    doc = "rbil61:PORTS.B P03C403C5 03C4"
    copy.index(lambda d: d["rows"].update({
        doc: {"line": "03C4  RW  VGA sequencer index", "key": "0x3C4", "marks": "RW"}}))
    copy.index(lambda d: d["rows"][SEQ_PORT].update(marks="W"))

    def second_source(d: dict[str, Any]) -> None:
        entry(d, "0x3C4")["sources"].insert(0, {
            "role": "documentation", "ref": doc, "cites": "03C4  RW  VGA sequencer index"})
    copy.edit("ports", second_source)
    assert run(copy.subject()) == {BOTH}
    copy.edit("ports", lambda d: entry(d, "0x3C4").update(
        differs="The documentation gives it as read and write; the emulator takes writes."))
    assert run(copy.subject()) == set()


def test_the_two_emulators_that_mark_a_port_differently_need_a_sentence_saying_so(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    ref = "mame:src/devices/video/mc6845.cpp mc6845_device::register_w"
    line = "\tcase 0x0c:"
    copy.index(lambda d: d["rows"].update({ref: {"line": line, "key": "0x3C4", "marks": "RW"}}))
    copy.index(lambda d: d["rows"][SEQ_PORT].update(marks="RW"))

    def second_emulator(d: dict[str, Any]) -> None:
        entry(d, "0x3C4")["sources"].append({"role": "emulator", "ref": ref, "cites": line})
    copy.edit("ports", second_emulator)
    assert run(copy.subject()) == set(), "two emulators that agree need no sentence"
    copy.index(lambda d: d["rows"][SEQ_PORT].update(marks="W"))
    assert run(copy.subject()) == {BOTH}
    copy.edit("ports", lambda d: entry(d, "0x3C4").update(
        differs="DOSBox-X takes writes only; MAME also answers reads."))
    assert run(copy.subject()) == set()


def test_text_searched_through_both_paths_that_differ_fails_the_fallback_case(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subject = Copy(tmp_path).subject()
    if not subject.base().uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    found = text.Fallback.tiers

    def without_the_first(self: text.Fallback, asked: list[text.Term]) -> dict[int, int]:
        got = found(self, asked)
        return {n: t for n, t in got.items() if n != min(got)}
    monkeypatch.setattr(text.Fallback, "tiers", without_the_first)
    assert run(subject) == {FALLBACK}


def test_a_server_that_declares_nothing_has_examined_nothing() -> None:
    empty = NullKnowledge(declared=Support())
    with pytest.raises(AssertionError, match="nothing here says what this server supports"):
        conformance.KnowledgeContract().test_the_check_examined_something(empty)


def test_a_host_with_no_fts5_passes_the_contract_and_skips_the_comparison(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scry_core.knowledge.database._FTS",
                        "CREATE VIRTUAL TABLE entry_text USING nosuchmodule (name)")
    assert NullKnowledge().base().uses_fts5 is False
    assert run(NullKnowledge()) == set()
