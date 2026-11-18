"""`scry_core.asks`: the hand-written half of a reference, held to the registry and to the
limits a page keeps."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_reference import ASKS, _asks, _held, _registry

from scry_core import asks, reference
from scry_core.verdict import Invalid

Change = Callable[[dict[str, Any]], None]


def _peek(key: str, value: Any) -> Change:
    def change(held: dict[str, Any]) -> None:
        held["tools"]["peek"][key] = value
    return change


def _drop(held: dict[str, Any]) -> None:
    del held["tools"]["poke"]


def _stray_tool(held: dict[str, Any]) -> None:
    held["tools"]["gone"] = held["tools"]["poke"]


def _no_family(held: dict[str, Any]) -> None:
    del held["families"]["Read"]


def _stray_family(held: dict[str, Any]) -> None:
    held["families"]["Gone"] = "Nothing."


def _top_level(held: dict[str, Any]) -> None:
    held["notes"] = {}


LONG = " ".join(["word"] * 31) + "."


@pytest.mark.parametrize(("change", "finding"), [
    (_drop, f"`poke` has no entry in {ASKS}"),
    (_stray_tool, f"{ASKS}: `gone` is no tool"),
    (_no_family, f"{ASKS}: the family Read has no line saying what it holds"),
    (_stray_family, f"{ASKS}: `Gone` is no family of the roster"),
    (_top_level, f"{ASKS}: `notes` is no part of it: it holds `families` and `tools`"),
    (_peek("title", "x"), f"{ASKS}: `peek` has `title`, which no entry takes"),
    (_peek("what", ""), "`peek`: `what` is empty"),
    (_peek("what", " ".join(["word"] * 26) + "."),
     "`peek`: `what` is 26 words in 1 sentences, and it takes at most 25 in 1"),
    (_peek("what", "One thing. Another thing."),
     "`peek`: `what` is 4 words in 2 sentences, and it takes at most 25 in 1"),
    (_peek("ask", " ".join(["word"] * 26)), "`peek`: `ask` is 26 words, and an ask is 1 to 25"),
    (_peek("reads", "One. Two. Three."),
     "`peek`: `reads` is 3 words in 3 sentences, and a reply is read in at most 2 sentences "
     "and 40 words"),
    (_peek("on", ""), "`peek`: `on` is empty"),
    (_peek("call", {"addr": "0x10", "width": 4}),
     "`peek`: `call` is one the tool refuses (width: Extra inputs are not permitted)"),
    (_peek("call", {"addr": "0x10", "width": "<host>"}),
     "`peek`: `call` is one the tool refuses (width: Extra inputs are not permitted)"),
    (_peek("call", {"addr": "<host>", "width": 4}),
     "`peek`: `call` is one the tool refuses (width: Extra inputs are not permitted)"),
    (_peek("shows", []), "`peek`: `shows` names no field of the reply to show"),
    (_peek("then", {"lead": "Then:", "tool": "gone", "call": {}, "shows": ["status"]}),
     "`peek`: `then.tool` is `gone`, which is no tool"),
    (_peek("then", {"lead": "Then:", "tool": "poke", "call": {"addr": "0x10"},
                    "shows": ["status"]}),
     "`peek`: `then.call` is one `poke` refuses (value: Field required)"),
    (_peek("then", {"lead": "", "tool": "poke", "call": {"addr": "0x10", "value": 1},
                    "shows": []}), "`peek`: `then.shows` names no field of the reply to show"),
    (_peek("arguments", {"addr": "Where."}),
     "`peek`: `arguments` has a sentence for ['addr'], and the tool takes "
     "['addr', 'length', 'mode']"),
    (_peek("arguments", {"addr": LONG, "length": "How many.", "mode": "Which."}),
     "`peek`: the argument `addr` has a sentence of 31 words, and a sentence takes at most 30"),
    (_peek("returns", {"gone": "Nothing."}),
     "`peek`: `returns` names ['gone'], which its reply model does not"),
    (_peek("returns", {}),
     "`peek`: `returns` has 0 fields, and it takes 1 to 6 of a reply that has fields of its "
     "own"),
    (_peek("refuses", ["One. Two. Three."]),
     "`peek`: refusal 1 is 3 words in 3 sentences, and it takes at most 30 in 2"),
    (_peek("why", ["a.", "b.", "c.", "d."]),
     "`peek`: `why` has 4 paragraphs, and an entry shows at most 3: the rest goes in "
     "`why_more`"),
    (_peek("why", []),
     "`peek`: `why_more` has 1 block and `why` none: the fold opens under the paragraphs an "
     "entry shows"),
    (_peek("on", None), f"{ASKS}: `peek`: `on` is not a string"),
    (_peek("what", 5), f"{ASKS}: `peek`: `what` is not a string"),
    (_peek("why", "A paragraph."), f"{ASKS}: `peek`: `why` is not a list of strings"),
    (_peek("related", ["poke", 3]), f"{ASKS}: `peek`: `related` is not a list of strings"),
    (_peek("call", "peek(addr=1)"), f"{ASKS}: `peek`: `call` is not an object"),
    (_peek("arguments", {"addr": None, "length": "How many.", "mode": "Which."}),
     f"{ASKS}: `peek`: `arguments` is not an object of strings"),
    (_peek("then", "poke"), f"{ASKS}: `peek`: `then` is not an object"),
    (_peek("then", {"lead": "Then:", "tool": "poke", "call": {"addr": "0x10", "value": 1},
                    "shows": "status"}),
     f"{ASKS}: `peek`: `then.shows` is not a list of strings"),
    (_peek("modes", {"argument": "mode", "head": ["mode", "what"], "rows": [["`byte`", 1]]}),
     f"{ASKS}: `peek`: `modes.rows` is not a list of lists of strings"),
    (_peek("why_more", ["One. Two. Three. Four. Five."]),
     "`peek`: why, paragraph 2 is 5 words in 5 sentences, and it takes at most 80 in 4"),
    (_peek("modes", {"argument": "length", "head": ["a", "b"], "rows": []}),
     "`peek`: `modes` is on `length`, which is no argument with named values"),
    (_peek("modes", {"argument": "mode", "head": ["mode", "what"], "rows": [["`byte`", "One."]]}),
     "`peek`: `modes` lists ['byte'], and `mode` takes ['byte', 'word']"),
    (_peek("modes", {"argument": "mode", "head": ["a", "b", "c", "d"],
                     "rows": [["byte", "x"], ["word", "y"]]}),
     "`peek`: `modes` has 4 columns, and a table takes 2 to 3"),
    (_peek("related", ["peek"]),
     "`peek`: `related` names ['peek'], each of which is not another tool"),
    (_peek("related", ["poke", "poke"]),
     "`peek`: `related` names 2 tools, and it takes at most 6, each once"),
])
def test_each_way_the_asks_fall_short_is_a_finding_and_no_page_is_written(
        tmp_path: Path, change: Change, finding: str) -> None:
    reg = _registry(tmp_path)
    held = _held()
    change(held)
    _asks(tmp_path, held)
    assert finding in reference.drift(reg), reference.drift(reg)
    with pytest.raises(reference.Unready) as unready:
        reference.write(reg)
    assert finding in unready.value.findings
    assert not (tmp_path / "REFERENCE.md").exists(), "a page was written with a finding open"


@pytest.mark.parametrize(("more", "finding"), [
    (["- One thing.\n- Another, at `0x10. 2`."], ""),
    (["| value | means |\n|---|---|\n| `byte` | one |"], ""),
    (["```yaml\nformats:\n  - name: tiles\n```"], ""),
    (["- One. Two. Three."],
     "`peek`: why, item 1 of block 2 is 3 words in 3 sentences, and it takes at most 30 in 2"),
    (["| a | b | c | d |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |"],
     "`peek`: why, block 2 is a table of 4 columns, and a table takes at most 3"),
    (["```yaml\nformats:"], "`peek`: why, block 2 opens a code block it never closes"),
])
def test_the_folded_why_takes_a_list_a_table_or_code_each_within_its_limit(
        tmp_path: Path, more: list[str], finding: str) -> None:
    reg = _registry(tmp_path)
    held = _held()
    held["tools"]["peek"]["why_more"] = more
    _asks(tmp_path, held)
    said = [f for f in reference.drift(reg) if "why" in f]
    assert said == ([finding] if finding else []), said


@pytest.mark.parametrize("block", ["- One thing.", "| a | b |\n|---|---|\n| 1 | 2 |",
                                   "```\ncode\n```"])
def test_the_why_an_entry_shows_is_paragraphs_only(tmp_path: Path, block: str) -> None:
    reg = _registry(tmp_path)
    held = _held()
    held["tools"]["peek"]["why"] = [block]
    _asks(tmp_path, held)
    assert ("`peek`: why, block 1 is a list, a table or code, which an entry shows only "
            "folded: it goes in `why_more`") in reference.drift(reg), reference.drift(reg)


def test_the_fixture_s_own_asks_have_no_finding(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    _asks(tmp_path)
    assert [f for f in reference.drift(reg) if "asks.json" in f or f.startswith("`p")] == [
        "`peek` has no example in docs/reference/examples.json",
        "`poke` has no example in docs/reference/examples.json"]


@pytest.mark.parametrize("content", ["{broken", "[1]", '{"tools": []}',
                                     '{"tools": {}, "families": []}'])
def test_an_asks_file_that_is_not_its_two_objects_is_invalid(tmp_path: Path, content: str) -> None:
    (tmp_path / ASKS).parent.mkdir(parents=True)
    (tmp_path / ASKS).write_text(content, encoding="utf-8")
    with pytest.raises(Invalid, match="asks.json"):
        reference.drift(_registry(tmp_path))


def test_an_entry_that_is_not_an_object_is_a_finding(tmp_path: Path) -> None:
    held = _held()
    held["tools"]["peek"] = 3
    _asks(tmp_path, held)
    found = reference.drift(_registry(tmp_path))
    assert f"{ASKS}: `peek` holds a int, not an object" in found, found


@pytest.mark.parametrize(("text", "count"), [
    ("Read `run_for(frames=1)` once.", 3), ("See [the README](../../README.md) now.", 4),
    ("", 0), ("one  two\nthree", 3)])
def test_a_code_span_is_one_word_and_a_link_its_label(text: str, count: int) -> None:
    assert asks.words(text) == count


@pytest.mark.parametrize(("text", "said"), [
    ("It stops. Then it runs.", ["It stops.", "Then it runs."]),
    ("At `0x1. 2` it stops.", ["At `0x1. 2` it stops."]),
    ("Why? Because! So.", ["Why?", "Because!", "So."]), ("  ", [])])
def test_a_full_stop_inside_a_code_span_ends_no_sentence(text: str, said: list[str]) -> None:
    assert asks.sentences(text) == said


def test_an_asks_file_is_read_as_json_once(tmp_path: Path) -> None:
    _asks(tmp_path)
    held = asks.load(tmp_path)
    assert held.tools["peek"].modes == asks.Modes(
        "mode", ("mode", "what it reads"), (("`byte`", "One byte a cell."), ("`word`", "Two.")))
    assert held.tools["poke"].then is None and not held.odd
    assert json.loads((tmp_path / ASKS).read_text(encoding="utf-8"))["families"] == dict(
        held.families)
    assert asks.load(tmp_path / "nowhere") == asks.Asks({}, {})
