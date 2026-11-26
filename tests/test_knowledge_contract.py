"""`conformance.KnowledgeContract`: a server with a small base of rows passes it, and a copy of
that base broken one rule at a time fails the case that rule belongs to, and only it."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, NullKnowledge, a_row, write_rows

from scry_core import conformance
from scry_core.knowledge import Support, sealed, shared, text
from scry_core.knowledge import base as rows_base

CASES = sorted(n for n in dir(conformance.KnowledgeContract) if n.startswith("test_"))
ROWS_PARSE = "test_every_dictionary_of_rows_parses_and_ids_are_unique"
FROZEN = "test_a_sealed_row_is_never_reworded"
ROWS_SERVED = "test_the_base_serves_the_sealed_entries_and_holds_the_rest_back"
ROWS_RETURNED = "test_no_query_shape_returns_an_entry_of_rows_held_back"
ROWS_EXAMINED = "test_the_rows_check_examined_something"
ROWS_FALLBACK = "test_the_rows_fallback_answers_as_fts5_does"
ROWS_SCOPES = "test_the_rows_half_holds_the_code_to_a_declared_scope"
ROWS_REOPENED = "test_a_reopened_part_of_rows_is_never_sealed_again_as_it_was"
ROWS_ALIAS = "test_no_alias_of_rows_is_another_entry_s_name"
ROWS_PINNED = "test_each_emulator_is_pinned_in_the_rows_base_where_scry_core_pins_it"


class TestNullKnowledge(conformance.KnowledgeContract):
    @pytest.fixture
    def subject(self) -> NullKnowledge:
        return NullKnowledge()


def run(subject: NullKnowledge) -> set[str]:
    """The cases of the rows contract that fail on `subject`."""
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


class ServesEveryRow(NullKnowledge):
    """Loads its dictionaries of rows with no lock, so every entry answers."""

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return rows_base.Base((self.rows,), None, fts5)


class RowsPinAnother(NullKnowledge):
    """Pins an emulator elsewhere than scry-core does, in its base of rows."""

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return rows_base.Base.load(*self.rows_sources(), lock=self.rows_lock(), fts5=fts5,
                                   pins={**shared.PINS, "dosbox-x": "0" * 40})


class ResealedAsItWas(NullKnowledge):
    """Seals again, at the seal it had, a part the lock says was reopened."""

    def rows_lock(self) -> sealed.Lock:
        dictionary, entry = _first_row(self)
        seal = sealed.seal_of(dictionary, entry, sealed.OFFICIAL)
        part = sealed.Part(seal, "a reader", "a writer", {})
        again = sealed.Reopened(entry.id, sealed.OFFICIAL, (), "a reader", "why", part)
        return sealed.Lock({entry.id: {sealed.OFFICIAL: part}}, (again,))


class ReopenedAndNeverRewritten(NullKnowledge):
    """Reopened a part, left it unsealed, and never rewrote a row."""

    def rows_lock(self) -> sealed.Lock:
        dictionary, entry = _first_row(self)
        seal = sealed.seal_of(dictionary, entry, sealed.OFFICIAL)
        part = sealed.Part(seal, "a reader", "a writer", {})
        again = sealed.Reopened(entry.id, sealed.OFFICIAL, (), "a reader", "why", part)
        return sealed.Lock({}, (again,))


def _first_row(subject: NullKnowledge) -> tuple[Any, Any]:
    """The first entry of the subject's dictionary of rows, with its dictionary."""
    _, dictionary, faults = next(iter(rows_base.dictionaries(subject.rows)))
    assert dictionary is not None and not faults, faults
    return dictionary, dictionary.entries[0]


def rows_copy(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> NullKnowledge:
    """The null subject over a copy of its dictionary of rows, changed by `change`."""
    folder = tmp_path / "rows"
    folder.mkdir()
    name = "pic8259-commands.json"
    doc = json.loads((KNOWLEDGE / "null-rows" / name).read_text(encoding="utf-8"))
    change(doc)
    (folder / name).write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return NullKnowledge(rows=folder)


def test_the_fixture_base_passes_every_case_and_the_runner_can_tell_a_failure() -> None:
    assert len(CASES) == 12 and run(NullKnowledge()) == set()
    assert run(NullKnowledge(declared=Support())) == {ROWS_EXAMINED, ROWS_SCOPES}


def test_a_base_of_rows_served_with_no_lock_fails_the_cases_that_hold_it() -> None:
    assert run(ServesEveryRow()) == {ROWS_SERVED, ROWS_RETURNED}


@pytest.mark.parametrize("subject", [ResealedAsItWas(), ReopenedAndNeverRewritten()])
def test_a_reopened_part_left_at_the_seal_it_had_fails_the_reopening_case(
        subject: NullKnowledge) -> None:
    assert run(subject) == {ROWS_REOPENED}


def test_a_sealed_row_reworded_is_held_back_and_fails_the_freeze_case(tmp_path: Path) -> None:
    def reword(doc: dict[str, Any]) -> None:
        entry(doc, "0xE0..0xE7")["rows"][0]["text"] += " Reworded."
    subject = rows_copy(tmp_path, reword)
    assert run(subject) == {FROZEN}
    assert subject.rows_base().by_id("pic8259:command:0xE0..0xE7") is None


def test_a_dictionary_of_rows_with_a_fault_fails_the_parse_case(tmp_path: Path) -> None:
    def fault(doc: dict[str, Any]) -> None:
        entry(doc, "0x20..0x27")["rows"][0]["of"] = "nobody"
    assert ROWS_PARSE in run(rows_copy(tmp_path, fault))


def test_a_dictionary_of_rows_that_does_not_parse_fails_the_parse_case_alone(
        tmp_path: Path) -> None:
    subject = rows_copy(tmp_path, lambda doc: None)
    (tmp_path / "rows" / "broken.json").write_text("{", encoding="utf-8")
    failed = run(subject)
    assert ROWS_PARSE in failed and FROZEN not in failed


def test_an_alias_that_is_another_entry_s_name_fails_the_alias_case(tmp_path: Path) -> None:
    def collide(doc: dict[str, Any]) -> None:
        entry(doc, "0x20..0x27")["aliases"] = ["rotate on specific EOI"]
    assert run(rows_copy(tmp_path, collide)) == {ROWS_ALIAS}


def test_a_server_that_pins_an_emulator_elsewhere_than_scry_core_fails_the_pin_case() -> None:
    assert run(RowsPinAnother()) == {ROWS_PINNED}


def test_text_searched_through_both_paths_that_differ_fails_the_fallback_case(
        monkeypatch: pytest.MonkeyPatch) -> None:
    subject = NullKnowledge()
    if not subject.rows_base().uses_fts5:
        pytest.skip("this host's SQLite has no FTS5")
    found = text.Fallback.tiers

    def without_the_first(self: text.Fallback, asked: list[text.Term]) -> dict[int, int]:
        got = found(self, asked)
        return {n: t for n, t in got.items() if n != min(got)}
    monkeypatch.setattr(text.Fallback, "tiers", without_the_first)
    assert run(subject) == {ROWS_FALLBACK}


def test_a_server_that_declares_nothing_has_examined_nothing() -> None:
    empty = NullKnowledge(declared=Support())
    with pytest.raises(AssertionError, match="nothing here says what this server supports"):
        conformance.KnowledgeContract().test_the_rows_check_examined_something(empty)


def test_a_host_with_no_fts5_passes_the_contract_and_skips_the_comparison(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rows_base.Base, "_fts",
                        lambda self: "CREATE VIRTUAL TABLE entry_text USING nosuchmodule (name)")
    assert NullKnowledge().rows_base().uses_fts5 is False
    assert run(NullKnowledge()) == set()


class ReopenedForAnEntryGone(NullKnowledge):
    """A lock records a reopening for an entry no dictionary holds."""

    def rows_lock(self) -> sealed.Lock:
        again = sealed.Reopened("gone:command:0x01", sealed.OFFICIAL, (), "a reader", "why",
                                sealed.Part("a seal", "a reader", "a writer", {}))
        return sealed.Lock({}, (again,))


def test_a_reopened_record_for_an_entry_no_dictionary_holds_is_left_to_the_lock() -> None:
    assert run(ReopenedForAnEntryGone()) == set()


def test_a_row_with_no_word_is_skipped_when_the_searches_are_chosen(tmp_path: Path) -> None:
    folder = tmp_path / "rows"
    write_rows(folder, "errors", "error", "ibm-pc", [
        {"key": "1", "name": "x", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "...")]}])
    subject = NullKnowledge(rows=folder)
    assert {"x", "x*"} <= set(conformance._rows_asked(subject))


def test_the_query_shapes_cover_a_call_a_memory_area_and_a_device(tmp_path: Path) -> None:
    folder = tmp_path / "rows"
    write_rows(folder, "calls", "call", "ibm-pc", [
        {"key": "0x10/0x12", "name": "parent", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The parent."), a_row(2, "out AX", "The result.")]},
        {"key": "0x10/0x12/BL=0x36", "name": "variant", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The variant."), a_row(2, "out AX", "The result.")]}])
    write_rows(folder, "memory", "memory", "ibm-pc", [
        {"key": "0x449", "name": "video mode", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The mode."),
                  {**a_row(2, "place", "Reached here.", of="dosbox-x"), "vs": "place"}]}])
    write_rows(folder, "devices", "device", "ibm-pc", [
        {"key": "vga-seq", "name": "VGA sequencer", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The sequencer."), a_row(2, "reset", "It resets.")]}])
    served = rows_base.Base((folder,), None)
    shapes = {how for e in served.entries() for how, _ in conformance._asked(served, e)}
    assert {"its address", "its device entry", "the variants of its call"} <= shapes
