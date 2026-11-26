"""A source index whose row holds a digest of the list line instead of the line: how it is read
and how it holds the line an entry cites."""

from __future__ import annotations

import hashlib
import json

import pytest
from null_server import KNOWLEDGE

from scry_core.knowledge import sources

REF = "rbil61:INTERRUP.G D-214C"
LINE = "INT 21 - DOS 2+ - EXIT - TERMINATE WITH RETURN CODE"


def index_of(row: dict[str, str]) -> sources.SourceIndex:
    return sources.parse_index(json.dumps({
        "format": sources.INDEX_FORMAT, "pins": {}, "lists": {}, "rows": {REF: row}}))


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


def test_a_committed_index_may_hold_both_shapes_of_row() -> None:
    index = sources.read_index(KNOWLEDGE / "null-sources.json")
    assert all(row.line and not row.digest for row in index.rows.values())
