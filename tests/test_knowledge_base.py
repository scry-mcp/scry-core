"""The base of rows a server serves: only sealed entries, each answered with its rows in the order
a reply shows them, the verdicts of each emulator, citations that say where and copy no text, the
rows' words in the search, and no Python object kept per entry."""

from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, NullKnowledge

from scry_core import knowledge_tool, reply_schema
from scry_core.knowledge import base as rows_base
from scry_core.knowledge import sealed
from scry_core.knowledge.base import ROWS_SHOWN, Base
from scry_core.reply_contract import Invalid

SEALED = "pic8259:command:0xE0..0xE7"
OPEN = "pic8259:command:0x20..0x27"
#: What the base may keep in Python objects per entry (`test_knowledge.KEPT_PER_ENTRY`).
KEPT_PER_ENTRY = 64


@pytest.fixture
def served() -> Base:
    return NullKnowledge().rows_base()


@pytest.fixture(scope="module")
def pilot() -> Base:
    """scry-core's own dictionaries of rows, every entry loaded."""
    return Base(("scry_core",), None)


def test_only_the_entry_sealed_in_every_part_is_served(served: Base) -> None:
    assert served.ids() == [SEALED] and served.held_back == 1
    assert served.unconfirmed(id=OPEN) == [OPEN] and served.by_id(OPEN) is None
    assert served.faults() == []


def test_with_no_seal_nothing_is_served_and_everything_is_held_back() -> None:
    nothing = Base.load(KNOWLEDGE / "null-rows", lock=sealed.Lock({}))
    assert len(nothing) == 0 and nothing.held_back == 2


def test_a_whole_entry_says_what_the_document_says_first_then_each_emulator_s_notes(
        pilot: Base) -> None:
    for e in pilot.entries():
        shown = pilot.whole(e)["rows"]
        parties = [r["of"] for r in shown]
        assert parties == sorted(parties, key=("doc", "dosbox-x", "mame").index), e.id
        for r in shown:
            assert ("vs" in r) == (r["of"] != "doc") and ("verdicts" not in r or r["of"] == "doc")


def test_each_doc_row_carries_each_emulator_s_verdict_in_the_reply_s_words(pilot: Base) -> None:
    whole = pilot.whole(_by(pilot, SEALED))
    said = {w for r in whole["rows"] for w in r.get("verdicts", {}).values()}
    assert said and said <= set(rows_base.VERDICT_WORDS.values())
    assert "as documented" in {w for e in pilot.entries() for r in pilot.whole(e)["rows"]
                               for w in r.get("verdicts", {}).values()}


def test_a_citation_says_where_and_copies_no_text(pilot: Base) -> None:
    whole = pilot.whole(_by(pilot, SEALED))
    cites = [c for r in whole["rows"] for c in r["cites"]]
    assert {"document": "Intel 8259A programmable interrupt controller",
            "lines": cites[0]["lines"]} == cites[0]
    assert all(set(c) <= {"document", "file", "lines"} for c in cites)
    assert {s["where"] for s in whole["sources"]} >= {
        "Intel 8259A programmable interrupt controller", "src/hardware/pic.cpp"}
    assert all(s["url"].startswith("https://") for s in whole["sources"])


def test_a_row_asked_by_its_id_gives_the_url_of_each_line(pilot: Base) -> None:
    whole = pilot.whole(_by(pilot, SEALED))
    note = next(r for r in whole["rows"] if r["of"] == "dosbox-x")
    got = pilot.row(f"{SEALED}#{note['n']}")
    assert got is not None and [r["n"] for r in got["rows"]] == [note["n"]]
    (cite, *_) = got["rows"][0]["cites"]
    pin = pilot.pins["dosbox-x"]
    assert cite["url"] == (f"https://github.com/joncampbell123/dosbox-x/blob/{pin}/"
                           f"{cite['file']}#L{cite['lines'].replace('-', '-L')}")
    assert pilot.row(f"{SEALED}#nosuch") is None and pilot.row(SEALED) is None


def test_a_long_entry_is_cut_and_the_notes_go_before_the_doc_rows(pilot: Base) -> None:
    e = max(pilot.entries(), key=lambda e: pilot.whole(e).get("rows_total", 0))
    whole = pilot.whole(e)
    total = whole["rows_total"]
    assert total > ROWS_SHOWN and len(whole["rows"]) == ROWS_SHOWN
    docs = sum(r["of"] == "doc" for r in pilot._rows(e))
    assert sum(r["of"] == "doc" for r in whole["rows"]) == min(docs, ROWS_SHOWN)


def test_an_entry_no_official_document_answers_says_whose_source_it_is(tmp_path: Path) -> None:
    family = json.loads((KNOWLEDGE / "rows" / "family.json").read_text(encoding="utf-8"))
    (tmp_path / "family.json").write_text(json.dumps(family), encoding="utf-8")
    base = Base((tmp_path,), None)
    emulator = [e for e in base.entries() if e.source == "emulator"]
    assert emulator and base.faults() == []
    assert base.whole(emulator[0])["source"].endswith("'s source; no official document found")
    assert all("source" not in base.whole(e) for e in base.entries() if e.source == "official")


def test_the_rows_text_is_searched_beside_the_names(pilot: Base) -> None:
    word = "bottom"
    found = pilot.search(words=word)
    assert found.total and all(word not in e.name.lower() for e in found.entries)


def test_the_index_of_our_own_answers_the_rows_as_fts5_does(pilot: Base) -> None:
    if not pilot.uses_fts5:
        pytest.skip("this host's SQLite has no FTS5, so the fallback is the only path")
    ours = Base(("scry_core",), None, fts5=False)
    for words in ("bottom", "rotate", "specific eoi", "icw*", "mode", "zebra"):
        assert [e.id for e in ours.search(words=words, limit=50).entries] == [
            e.id for e in pilot.search(words=words, limit=50).entries], words


def _by(base: Base, id_: str) -> rows_base.Served:
    got = base.by_id(id_)
    assert got is not None
    return got


def ask(base: Base, **arguments: Any) -> dict[str, Any]:
    return knowledge_tool.find(base, None, **arguments)


def test_knowledge_find_answers_an_entry_with_its_rows_and_a_row_by_its_id(served: Base) -> None:
    whole = ask(served, id=SEALED)
    (entry,) = whole["entries"]
    assert entry["rows"][0]["of"] == "doc" and "description" not in entry
    one = ask(served, id=f"{SEALED}#1")
    assert [r["n"] for r in one["entries"][0]["rows"]] == ["1"]
    assert "url" in one["entries"][0]["rows"][0]["cites"][0]
    with pytest.raises(Invalid) as refused:
        ask(served, id=f"{SEALED}#99")
    assert refused.value.code == "unknown_ref"


def test_knowledge_find_says_an_entry_held_back_exists_and_is_not_served(served: Base) -> None:
    got = ask(served, kind="command", key="0x20")
    assert got["entries"] == [] and got["unconfirmed"] == [OPEN]
    assert (got["served"], got["held_back"]) == (1, 1)


def test_a_reply_over_rows_is_one_the_model_accepts(served: Base) -> None:
    judge = reply_schema.judged(knowledge_tool.KnowledgeFindReply)
    for arguments in ({"id": SEALED}, {"id": f"{SEALED}#1"}, {"text": "rotate"},
                      {"kind": "command"}, {"kind": "command", "key": "0x20"}):
        judge.validate_python({"status": "ok", **ask(served, **arguments)})


def _synthetic(folder: Path, count: int) -> None:
    """`count` calls of 12 `doc` rows of 18 words with two quotes each."""
    words = " ".join(["word"] * 16)
    entries = [{"key": f"0x21/0x{n // 8:02X}/0x{n % 8:02X}", "name": f"call {n}", "rows": [
        {"n": str(r), "on": "is" if r == 1 else "out CF=0", "of": "doc",
         "text": f"Row {r} {words}.", "quotes": [
             {"ref": "rbil61:INTERRUP.F", "lines": str(r), "sha": "0" * 64},
             {"ref": "rbil61:INTERRUP.F", "lines": str(r + 1), "sha": "1" * 64}]}
        for r in range(1, 13)]} for n in range(count)]
    (folder / "calls.json").write_text(json.dumps({
        "format": "scry-knowledge/2", "dictionary": "calls", "title": "Synthetic calls",
        "kind": "call", "scope": "ibm-pc", "covers": "FIXTURE of a test", "source": "official",
        "entries": entries}), encoding="utf-8")


def test_a_base_of_rows_keeps_no_python_object_per_entry(tmp_path: Path) -> None:
    count = 2000
    _synthetic(tmp_path, count)
    if not Base((tmp_path,), None).uses_fts5:
        pytest.skip("this host's SQLite has no FTS5, so the index of our own is built in Python")
    gc.collect()
    tracemalloc.start()
    try:
        base = Base((tmp_path,), None)
        gc.collect()
        kept, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(base) == count and base.faults() == []
    assert kept / count < KEPT_PER_ENTRY, f"{kept / count:.0f} bytes kept an entry"
