"""A source index whose row holds a digest of the list line instead of the line: how it is read
and how an entry's cited line is compared with it."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from null_server import KNOWLEDGE, an_entry, write_dictionary

from scry_core import knowledge
from scry_core.knowledge import check, sources

REF = "rbil61:INTERRUP.G D-214C"
LINE = "INT 21 - DOS 2+ - EXIT - TERMINATE WITH RETURN CODE"


def index_of(row: dict[str, str]) -> sources.SourceIndex:
    return sources.parse_index(json.dumps({
        "format": sources.INDEX_FORMAT, "pins": {}, "lists": {}, "rows": {REF: row}}))


def base_citing(tmp_path: Path, cites: str) -> knowledge.Base:
    entry = an_entry("0x4C", "exit")
    entry["sources"] = [{"role": "documentation", "ref": REF, "cites": cites}]
    write_dictionary(tmp_path, "calls", "port", "ibm-pc", [entry])
    return knowledge.Base.load(tmp_path)


def test_a_digest_is_the_sha256_of_the_lines_utf8_bytes() -> None:
    assert sources.digest(LINE) == hashlib.sha256(LINE.encode("utf-8")).hexdigest()
    assert sources.digest("café") == hashlib.sha256(b"caf\xc3\xa9").hexdigest()


def test_a_row_holds_a_line_or_a_digest_and_says_which_lines_it_holds() -> None:
    held = index_of({"digest": sources.digest(LINE), "key": "0x21/0x4C"}).rows[REF]
    assert (held.line, held.digest, held.key) == ("", sources.digest(LINE), "0x21/0x4C")
    assert held.holds(LINE) and not held.holds(LINE + " ")
    whole = index_of({"line": LINE}).rows[REF]
    assert whole.holds(LINE) and not whole.holds("INT 21") and whole.digest == ""


@pytest.mark.parametrize(("row", "says"), [
    ({}, "no `line` text and no `digest`"),
    ({"line": LINE, "digest": sources.digest(LINE)}, "both a `line` and a `digest`"),
    ({"digest": "abc"}, "`digest` is 64 hex digits"),
    ({"digest": sources.digest(LINE).upper()}, "`digest` is 64 hex digits"),
    ({"digest": 5}, "`digest` is 64 hex digits")])
def test_a_row_that_holds_neither_or_both_or_a_bad_digest_is_refused(
        row: dict[str, object], says: str) -> None:
    with pytest.raises(ValueError, match=says):
        index_of(row)  # type: ignore[arg-type]


def test_an_entry_citing_a_line_of_a_digest_row_is_held_to_the_digest(tmp_path: Path) -> None:
    row = {"digest": sources.digest(LINE), "key": "0x4C"}
    assert check.against_sources(base_citing(tmp_path, LINE), index_of(row)) == []
    other = tmp_path / "other"
    other.mkdir()
    [fault] = check.against_sources(base_citing(other, LINE + "."), index_of(row))
    assert fault == (f"calls 0x4C cites {LINE + '.'!r}, and {REF} holds a line of digest "
                     f"{sources.digest(LINE)[:12]}, which is not that line's")


def test_a_check_against_a_digest_row_compares_the_whole_line_it_cites(tmp_path: Path) -> None:
    base = base_citing(tmp_path, LINE)
    [entry] = base.entries()
    row = {"digest": sources.digest(LINE), "key": "0x4C"}
    whole = knowledge.Check("b", "a", ((REF, LINE),), "d")
    part = knowledge.Check("b", "a", ((REF, "TERMINATE WITH"),), "d")
    assert check._checked_lines(_with(entry, whole), index_of(row)) == []
    [fault] = check._checked_lines(_with(entry, part), index_of(row))
    assert "neither the line it cites" in fault
    assert check._checked_lines(_with(entry, part), index_of({"line": LINE})) == []


def _with(entry: knowledge.Entry, checked: knowledge.Check) -> knowledge.Entry:
    return dataclasses.replace(entry, checked=checked)


def test_a_committed_index_may_hold_both_shapes_of_row() -> None:
    index = sources.read_index(KNOWLEDGE / "null-sources.json")
    assert all(row.line and not row.digest for row in index.rows.values())
