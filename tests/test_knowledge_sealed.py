"""The seal of an entry written as rows: one seal for its official part and one per emulator, read
by a session that did not write it; the freeze on a reworded sealed row; `reopen --row`, and the
re-check of an overturned row refused to the reader who judged it."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE

from scry_core.knowledge import rows, sealed

NAME = "pic8259-commands.json"
SEALED = "pic8259:command:0xE0..0xE7"
OPEN = "pic8259:command:0x20..0x27"
PARTS = ("doc", "dosbox-x", "mame")


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the null server's dictionary of rows, and an empty lock beside it."""
    dictionary = tmp_path / NAME
    shutil.copy(KNOWLEDGE / "null-rows" / NAME, dictionary)
    return dictionary, tmp_path / "lock.json"


def edit(dictionary: Path, id_: str, change: Callable[[dict[str, Any]], None]) -> None:
    doc = json.loads(dictionary.read_text(encoding="utf-8"))
    change(next(e for e in doc["entries"] if f"pic8259:command:{e['key']}" == id_))
    dictionary.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def row(n: str, **fields: Any) -> Callable[[dict[str, Any]], None]:
    def change(entry: dict[str, Any]) -> None:
        next(r for r in entry["rows"] if r["n"] == n).update(fields)
    return change


def standing(dictionary: Path, lock: Path, id_: str = SEALED) -> str:
    got, faults = rows.read(dictionary)
    assert got is not None and not faults
    return sealed.read_lock(lock).standing(got, next(e for e in got.entries if e.id == id_))


def seal_all(dictionary: Path, lock: Path, by: str = "reader", ids: tuple[str, ...] = (SEALED,)
             ) -> None:
    for part in PARTS:
        assert sealed.seal(dictionary, ids, lock, part, by, "writer") == []


def test_an_entry_is_served_only_once_every_part_is_sealed(files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "reader", "writer") == []
    assert standing(dictionary, lock) == f"{sealed.UNSEALED} (dosbox-x)"
    assert sealed.seal(dictionary, [SEALED], lock, "dosbox-x", "reader", "writer") == []
    assert standing(dictionary, lock) == f"{sealed.UNSEALED} (mame)"
    assert sealed.seal(dictionary, [SEALED], lock, "mame", "other", "writer") == []
    assert standing(dictionary, lock) == sealed.SERVED


def test_a_part_read_by_its_writer_is_refused_and_nothing_is_written(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "w", "w") == [
        "'w' wrote the part: a reader who did not write it seals it"]
    assert not lock.exists()


def test_a_part_the_dictionary_has_no_code_of_and_an_id_it_lacks_are_refused(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    assert sealed.seal(dictionary, [SEALED], lock, "bochs", "r", "w")[0].startswith(
        "bochs is no part of")
    assert sealed.seal(dictionary, ["pic8259:command:0x99"], lock, "doc", "r", "w") == [
        "pic8259:command:0x99 is no entry of pic8259-commands"]


def test_a_dictionary_with_a_fault_is_not_sealed(files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    edit(dictionary, OPEN, row("1", of="nobody"))
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "r", "w")[-1] == (
        "`rows check` it before it is sealed")


@pytest.mark.parametrize("change, part", [
    (row("1", text="OCW2 says something else now."), "doc"),
    (row("1", quotes=[{"ref": "datasheet:8259A.raw.txt", "lines": "636-640",
                       "sha": "0" * 64}]), "doc"),
    (lambda e: e.update(name="another name"), "doc"),
    (lambda e: e["closed"].pop(), "mame"),
])
def test_a_sealed_entry_changed_is_held_back_and_frozen(
        files: tuple[Path, Path], change: Callable[[dict[str, Any]], None], part: str) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    got, _ = rows.read(dictionary)
    assert got is not None and sealed.frozen(got, sealed.read_lock(lock)) == []
    edit(dictionary, SEALED, change)
    assert standing(dictionary, lock).startswith(sealed.CHANGED)
    got, _ = rows.read(dictionary)
    assert got is not None
    frozen = sealed.frozen(got, sealed.read_lock(lock))
    assert len(frozen) == 1 and frozen[0].startswith(f"{SEALED} ({part}):")


def test_the_freeze_names_the_reworded_row_and_a_new_seal_over_it_is_refused(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    edit(dictionary, SEALED, row("1", text="OCW2 says something else now."))
    got, _ = rows.read(dictionary)
    assert got is not None
    assert "rows 1 changed since 'reader' sealed it" in sealed.frozen(got,
                                                                      sealed.read_lock(lock))[0]
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "fresh", "writer") == [
        f"{SEALED} (doc) changed since 'reader' sealed it: reopen the rows at fault first"]


def test_a_line_that_only_moves_breaks_no_seal(files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    got, _ = rows.read(dictionary)
    assert got is not None
    entry = next(e for e in got.entries if e.id == SEALED)
    quote = entry.rows[0].quotes[0]
    first, last = quote.first, quote.last
    edit(dictionary, SEALED, row("1", quotes=[{"ref": quote.ref, "lines": f"{first+1}-{last+1}",
                                               "sha": quote.sha}]))
    assert standing(dictionary, lock) == sealed.SERVED


def reopened(dictionary: Path, lock: Path) -> None:
    seal_all(dictionary, lock)
    assert sealed.reopen(dictionary, [SEALED], lock, "doc", ["1"], "auditor",
                         "says more than its lines") == []


def test_reopen_lifts_the_seal_of_the_part_and_records_the_rows_at_fault(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    reopened(dictionary, lock)
    assert standing(dictionary, lock) == f"{sealed.UNSEALED} (doc)"
    held = sealed.read_lock(lock)
    assert "doc" not in held.sealed[SEALED] and set(held.sealed[SEALED]) == {"dosbox-x", "mame"}
    (again,) = held.reopened
    assert (again.id, again.part, again.rows, again.by) == (SEALED, "doc", ("1",), "auditor")
    assert again.was.rows["1"].by == "reader"


OVERTURNED = (f"{SEALED} (doc): 'reader' judged what was reopened (row 1), so another reader "
              "seals the rewrite")


def test_the_reader_whose_judgement_was_overturned_may_not_judge_the_rewrite(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    reopened(dictionary, lock)
    edit(dictionary, SEALED, row("1", text="OCW2 with R, SL and EOI set rotates on an EOI."))
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "reader", "writer") == [OVERTURNED]
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "second", "writer") == []
    part = sealed.read_lock(lock).sealed[SEALED]["doc"]
    assert part.rows["1"].by == "second"
    assert {part.rows[n].by for n in part.rows if n != "1"} == {"reader"}
    assert standing(dictionary, lock) == sealed.SERVED


def test_a_row_at_fault_rewritten_under_another_label_is_not_judged_by_its_old_reader(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    reopened(dictionary, lock)
    edit(dictionary, SEALED, lambda e: e["rows"][0].update(n="1b", text="OCW2 rotates."))
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "reader", "writer") == [OVERTURNED]


def test_a_part_reopened_for_what_is_not_a_row_is_sealed_again_by_another_reader(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    edit(dictionary, SEALED, lambda e: e.update(name="another name"))
    assert sealed.reopen(dictionary, [SEALED], lock, "doc", [], "auditor", "name") == []
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "reader", "writer") == [
        f"{SEALED} (doc): 'reader' judged what was reopened (the part), so another reader "
        "seals the rewrite"]
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "second", "writer") == []
    assert standing(dictionary, lock) == sealed.SERVED


def test_a_doc_row_rewritten_holds_back_the_verdicts_given_on_it(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    assert sealed.reopen(dictionary, [SEALED], lock, "doc", ["2"], "auditor", "why") == []
    edit(dictionary, SEALED, row("2", text="A write with these bits set rotates the priority."))
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "second", "writer") == []
    assert standing(dictionary, lock) == f"{sealed.CHANGED} (dosbox-x)"
    got, _ = rows.read(dictionary)
    assert got is not None
    assert {f.split("): ")[0] + ")" for f in sealed.frozen(got, sealed.read_lock(lock))} == {
        f"{SEALED} (dosbox-x)", f"{SEALED} (mame)"}


def test_a_quote_with_no_digest_is_not_sealed(files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    edit(dictionary, SEALED, lambda e: e["rows"][0]["quotes"][0].pop("sha"))
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "r", "w") == [
        f"{SEALED} (doc): row 1 has a quote with no digest: `rows quote --stamp` it first"]


def test_a_reopened_row_sealed_again_unchanged_is_refused(files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    reopened(dictionary, lock)
    assert sealed.seal(dictionary, [SEALED], lock, "doc", "second", "writer") == [
        f"{SEALED} (doc): row 1 was reopened and is unchanged: rewrite it first"]


@pytest.mark.parametrize("ids, part, named, fault", [
    ([OPEN], "doc", ["1"], f"{OPEN} (doc) is not sealed: only a sealed part is reopened"),
    ([SEALED], "doc", ["99"], f"{SEALED} (doc): no sealed row 99"),
])
def test_reopen_refuses_what_is_not_sealed(files: tuple[Path, Path], ids: list[str], part: str,
                                           named: list[str], fault: str) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    assert sealed.reopen(dictionary, ids, lock, part, named, "a", "why") == [fault]


def test_reopen_with_no_row_names_none_and_keeps_every_row_s_judgement(
        files: tuple[Path, Path]) -> None:
    dictionary, lock = files
    seal_all(dictionary, lock)
    assert sealed.reopen(dictionary, [SEALED], lock, "doc", [], "a", "why") == []
    (again,) = sealed.read_lock(lock).reopened
    assert again.rows == () and set(again.was.rows) == {"1", "2"}


@pytest.mark.parametrize("text", [
    "{", "[]", json.dumps({"format": "scry-knowledge-lock/2", "checked": {}}),
    json.dumps({"format": sealed.LOCK_FORMAT, "sealed": {"x": {"doc": {"seal": "s"}}}}),
    json.dumps({"format": sealed.LOCK_FORMAT, "sealed": {}, "reopened": [{"id": "x"}]}),
    json.dumps({"format": sealed.LOCK_FORMAT, "sealed": {}, "reopened": None}),
])
def test_a_lock_of_another_shape_is_refused_by_name(text: str) -> None:
    with pytest.raises(ValueError, match=f"is not a `{sealed.LOCK_FORMAT}` document"):
        sealed.parse_lock(text)


def test_the_command_seals_and_reopens_and_says_a_refusal_with_exit_1(
        files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    dictionary, lock = files
    common = [str(dictionary), SEALED, "--lock", str(lock)]
    assert rows.main(["seal", *common, "--part", "doc", "--by", "r", "--writer", "w"]) == 0
    assert "sealed doc of 1" in capsys.readouterr().out
    assert rows.main(["seal", *common, "--part", "doc", "--by", "w", "--writer", "w"]) == 1
    assert "a reader who did not write it" in capsys.readouterr().out
    assert rows.main(["reopen", *common, "--part", "doc", "--row", "1", "--by", "a",
                      "--why", "w"]) == 0
    assert "reopened doc of 1" in capsys.readouterr().out
