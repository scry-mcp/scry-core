"""`scry_core.knowledge_tool`: the judge, the body over a base and a live source, the summary line,
the description against the client's cap, and the registration."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from null_server import NullKnowledge

from scry_core import client_cap, knowledge_tool, reply_schema
from scry_core.knowledge import Base
from scry_core.reply_contract import Invalid

PINS = {"dosbox-x": "0e900e855"}


@pytest.fixture(scope="module")
def base() -> Base:
    got = Base.load(NullKnowledge().root, pins=PINS)
    assert got.faults() == []
    return got


def ask(base: Base, live: knowledge_tool.Live | None = None, **arguments: Any) -> dict[str, Any]:
    return knowledge_tool.find(base, live, **arguments)


def refused(base: Base, code: str, **arguments: Any) -> Invalid:
    with pytest.raises(Invalid) as caught:
        ask(base, **arguments)
    assert caught.value.code == code, str(caught.value)
    return caught.value


@pytest.mark.parametrize("arguments", [
    {}, {"limit": 10}, {"scope": "ibm-pc"}, {"id": 4}, {"kind": "port", "key": "zzz"},
    {"kind": "nothing"}, {"key": ""}, {"text": "***"}, {"kind": "port", "limit": 0},
    {"kind": "port", "limit": 51}, {"kind": "port", "limit": True}, {"kind": "port", "limit": "3"},
    {"kind": "irq", "key": "0x5"}])
def test_the_judge_refuses_what_no_machine_and_no_base_could_answer(
        arguments: dict[str, Any]) -> None:
    with pytest.raises(Invalid) as caught:
        knowledge_tool.judge(**arguments)
    assert caught.value.code == "bad_argument"


@pytest.mark.parametrize("arguments", [
    {"id": "ibm-pc:port:0x3C8"}, {"kind": "port"}, {"key": "0x3C8"}, {"text": "timer*"},
    {"device": "sb"}, {"kind": "port", "key": "0x3c0..0x3cf", "limit": 50},
    {"key": "0x21/0x4C"}, {"key": "name with spaces"},
    {"kind": "call", "key": "0x21/0x00..0x21/0x4C"}])
def test_the_judge_lets_a_question_through(arguments: dict[str, Any]) -> None:
    knowledge_tool.judge(**arguments)


def test_one_match_answers_the_whole_entry_with_where_to_open_its_sources(base: Base) -> None:
    got = ask(base, kind="port", key="0x3c4")
    assert got["entries_total"] == 1 and got["truncated"] is False and got["examined"] == 2
    assert got["query"] == {"kind": "port", "key": "0x3C4"} and "how" not in got
    [entry] = got["entries"]
    assert entry["id"] == "ibm-pc:port:0x3C4" and entry["device"] == "vga-seq"
    assert entry["behaviour"].startswith("A write selects") and entry["aliases"] == ["SEQ index"]
    [source] = entry["sources"]
    assert source["role"] == "emulator" and source["url"] == (
        "https://github.com/joncampbell123/dosbox-x/blob/0e900e855/src/hardware/vga_seq.cpp")
    assert "checked" not in entry and "differs" not in entry


def test_an_entry_says_whether_it_was_checked_and_what_ties_it_to_its_hardware(
        base: Base) -> None:
    [call] = ask(base, id="ibm-pc:call:0x21/0x4C")["entries"]
    assert call["checked"] is True
    [device] = ask(base, kind="device", key="vga-seq")["entries"]
    assert device["used_by"] == ["ibm-pc:port:0x3C4", "ibm-pc:port:0x3C5"]
    assert device["ports"] == [{"base": "0x3C4", "length": 2}]
    [register] = ask(base, id="vga-seq:register:0x04")["entries"]
    assert register["reached"] == {"index": ["ibm-pc:port:0x3C4"],
                                   "data": ["ibm-pc:port:0x3C5"]}


def test_several_matches_are_rows_and_the_whole_entry_is_asked_by_id(base: Base) -> None:
    got = ask(base, kind="port", limit=1)
    assert got["entries_total"] == 2 and got["truncated"] is True and got["how"] == (
        knowledge_tool.HOW)
    assert got["entries"] == [{"id": "ibm-pc:port:0x3C4", "kind": "port", "key": "0x3C4",
                               "name": "sequencer index", "scope": "ibm-pc",
                               "device": "vga-seq"}]
    assert ask(base, kind="port")["truncated"] is False
    assert ask(base, device="vga-seq")["entries_total"] == 3


def test_words_find_entries_and_a_number_with_no_kind_finds_every_kind(base: Base) -> None:
    assert [e["id"] for e in ask(base, text="sequencer*")["entries"]] == [
        "ibm-pc:device:vga-seq", "ibm-pc:port:0x3C4", "ibm-pc:port:0x3C5"]
    assert ask(base, key="0x3C5")["entries"][0]["id"] == "ibm-pc:port:0x3C5"
    assert ask(base, key="0x21/0x4D")["entries"][0]["name"] == "get return code"


def test_a_number_the_base_does_not_hold_is_an_answer_and_stays_a_number(base: Base) -> None:
    got = ask(base, kind="port", key="0x3C6")
    assert got["entries_total"] == 0
    assert got["entries"] == [] and got["examined"] == 2
    assert [e["key"] for e in got["nearest"]] == ["0x3C5"] and "how" not in got
    assert got["note"] == "the base holds 2 ports and none at 0x3C6: it stays a number"
    assert ask(base, text="zebra")["note"] == "the base holds 6 entries and none says zebra"


def test_an_id_the_base_does_not_hold_names_the_nearest(base: Base) -> None:
    caught = refused(base, "unknown_ref", id="ibm-pc:port:0x3C7")
    assert "ibm-pc:port:0x3C4" in caught.fields["nearest"] and len(caught.fields["nearest"]) == 5
    assert "the nearest are" in str(caught)


def test_a_device_the_base_does_not_hold_names_those_it_has(base: Base) -> None:
    caught = refused(base, "unknown_ref", device="sbx")
    assert "vga-seq" in str(caught) and caught.fields["nearest"]


def test_a_kind_the_server_holds_nothing_of_names_the_kinds_it_has(base: Base) -> None:
    caught = refused(base, "no_channel", kind="irq")
    assert caught.fields["kinds"] == ["call", "port", "device", "register"]
    assert "it has call, port, device, register" in str(caught)


def test_a_scope_the_server_does_not_hold_names_those_it_has(base: Base) -> None:
    assert "ibm-pc, vga-seq" in str(refused(base, "bad_argument", kind="port", scope="m68000"))


def test_a_base_that_loaded_nothing_says_why(tmp_path: Any) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert "not JSON" in str(refused(Base.load(tmp_path), "no_channel", kind="port"))


class Machine:
    """A machine that says what its inputs are, as a server with a live kind does."""

    kinds: tuple[str, ...] = ("input",)

    def __init__(self, alive: bool) -> None:
        self.alive = alive
        self.asked: list[tuple[str, str, str]] = []

    def scopes(self) -> tuple[str, ...]:
        return ("ibm-pc",) if self.alive else ()

    def rows(self, kind: str, key: str, device: str) -> Sequence[dict[str, Any]] | None:
        self.asked.append((kind, key, device))
        return [{"kind": "input", "key": ":IN1/Coin 1", "name": "Coin 1"}] if self.alive else None


def test_a_kind_read_from_the_machine_needs_a_session_and_its_rows_are_marked_live(
        base: Base) -> None:
    with pytest.raises(Invalid) as caught:
        ask(base, Machine(False), kind="input", key=":IN1")
    assert caught.value.code == "no_session"
    machine = Machine(True)
    got = ask(base, machine, kind="input", key=":IN1")
    assert got["entries_total"] == 1 and machine.asked == [("input", ":IN1", "")]
    assert got["entries"] == [{"kind": "input", "key": ":IN1/Coin 1", "name": "Coin 1",
                               "live": True}]
    assert ask(base, machine, kind="port")["scope"] == ["ibm-pc", "vga-seq"]


def test_a_tag_of_the_running_machine_asks_the_machine_and_not_the_base(base: Base) -> None:
    machine = Machine(True)
    got = ask(base, machine, device=":ymsnd")
    assert machine.asked == [("", "", ":ymsnd")] and got["entries"][0]["live"] is True
    with pytest.raises(Invalid) as caught:
        ask(base, Machine(False), device=":ymsnd")
    assert caught.value.code == "no_session"


def test_the_summary_says_what_was_asked_and_what_answered(base: Base) -> None:
    def line(**arguments: Any) -> str:
        return knowledge_tool.summary(arguments, ask(base, **arguments))
    assert line(kind="port", key="0x3c4") == "kind port key 0x3C4: sequencer index"
    assert line(id="ibm-pc:port:0x3C5") == "id ibm-pc:port:0x3C5: sequencer data"
    assert line(kind="port") == "kind port: 2 entries"
    assert line(kind="port", limit=1) == "kind port: 2 entries, the first 1 listed"
    assert line(kind="port", key="0x3C6").startswith(
        "kind port key 0x3C6: no entry; the base holds")


def test_a_reply_of_the_body_is_one_the_model_accepts(base: Base) -> None:
    judge = reply_schema.judged(knowledge_tool.KnowledgeFindReply)
    asked: list[dict[str, Any]] = [{"kind": "port"}, {"id": "ibm-pc:call:0x21/0x4C"},
                                   {"text": "zebra"}, {"kind": "port", "key": "0x3C6"},
                                   {"device": "vga-seq"}]
    for arguments in asked:
        judge.validate_python({"status": "ok", **ask(base, **arguments)})


def test_the_description_says_what_the_model_returns_and_fits_the_clients_cap() -> None:
    doc = inspect.cleandoc(knowledge_tool.knowledge_find.__doc__ or "")
    model = knowledge_tool.KnowledgeFindReply
    assert reply_schema.unmodelled(doc, model) == []
    assert reply_schema.conditions_unsaid(doc, model) == []
    assert client_cap.utf16_units(doc + "\n\n" + knowledge_tool.REFERENCE) < (
        client_cap.CLIENT_TEXT_CAP // 2)
    assert doc.splitlines()[0].startswith("What a number is called")


def test_the_description_names_every_kind_and_every_refusal_the_body_can_make() -> None:
    doc = knowledge_tool.knowledge_find.__doc__ or ""
    for word in ("vector", "call", "error", "port", "irq", "memory", "input", "device",
                 "register", "command", "bad_argument", "unknown_ref", "no_channel",
                 "no_session"):
        assert f"`{word}`" in doc, word


def test_registering_binds_the_body_to_the_server_s_base_and_closes_its_reply(
        base: Base) -> None:
    seen: dict[str, Any] = {}

    def wrap(title: str, **options: Any) -> Callable[[Callable[..., Any]], Any]:
        seen.update(title=title, **options)
        return lambda fn: fn

    tool = knowledge_tool.register(wrap, lambda fields: {"answered": True, **fields}, base)
    assert seen["title"] == knowledge_tool.TITLE and seen["read_only"] is True
    assert seen["summary"] is knowledge_tool.summary
    assert tool.__doc__.rstrip().endswith(knowledge_tool.REFERENCE)
    got = tool(kind="port", key="0x3C5")
    assert got["answered"] is True and got["entries"][0]["id"] == "ibm-pc:port:0x3C5"
    assert list(inspect.signature(tool).parameters) == [
        "id", "kind", "key", "text", "device", "scope", "limit"]
    assert "enum" in repr(inspect.signature(tool).parameters["kind"].annotation)


def test_a_server_with_nothing_live_answers_a_machine_question_with_no_session(
        base: Base) -> None:
    with pytest.raises(Invalid) as caught:
        knowledge_tool.find(base, None, device=":ymsnd")
    assert caught.value.code == "no_session"


def test_the_signature_the_client_sees_is_not_a_body() -> None:
    with pytest.raises(NotImplementedError):
        knowledge_tool.knowledge_find()


def test_a_live_machine_narrows_the_answer_to_its_scopes_and_the_devices_inside_them(
        base: Base) -> None:
    assert ask(base, Machine(True), device="vga-seq")["entries_total"] == 3
    assert ask(base, Machine(True), kind="register")["entries_total"] == 1


@pytest.mark.parametrize("arguments", [{"kind": "call", "key": "0x21/0x4D..0x21/0x4C"},
                                       {"key": "0x21/0x4D..0x21/0x4C"}])
def test_a_range_of_calls_that_runs_downward_is_refused_by_the_judge_and_by_the_body(
        base: Base, arguments: dict[str, Any]) -> None:
    assert "runs upward" in str(refused(base, "bad_argument", **arguments))
    if "kind" in arguments:
        with pytest.raises(Invalid, match="runs upward"):
            knowledge_tool.judge(**arguments)
