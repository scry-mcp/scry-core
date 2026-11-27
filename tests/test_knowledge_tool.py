"""`scry_core.knowledge_tool`: the judge, the body over a base and a live source, the summary line,
the description against the client's cap, and the registration."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from null_server import KNOWLEDGE, a_row, write_rows

from scry_core import client_cap, knowledge_tool, reply_schema
from scry_core.knowledge import base as rows_base
from scry_core.knowledge import sealed
from scry_core.reply_contract import Invalid

PINS = {"dosbox-x": "0e900e855"}
EXIT_REF = "dosbox-x:src/dos/handler.cpp"


def a_port(key: str, name: str, **fields: Any) -> dict[str, Any]:
    rows = [a_row(1, "is", f"The {name} selects a sequencer register.",
                  quotes=[("dosbox-x:src/hardware/vga_seq.cpp", "10")]),
            {**a_row(2, "place", "The sequencer answers it.", of="dosbox-x"), "vs": "place"}]
    return {"key": key, "name": name, "regions": [], "closed": [], "rows": rows, **fields}


def a_call(key: str, name: str) -> dict[str, Any]:
    return {"key": key, "name": name, "regions": [], "closed": [],
            "rows": [a_row(1, "is", f"The call {name}.", quotes=[(EXIT_REF, "1")]),
                     a_row(2, "out AX", "The result.", quotes=[(EXIT_REF, "2")])]}


def the_devices(tmp_path: Path) -> Path:
    write_rows(tmp_path, "devices", "device", "ibm-pc", [
        {"key": "vga-seq", "name": "VGA sequencer", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The sequencer of the VGA."),
                  a_row(2, "reset", "It comes up at index 0.")]}])
    return tmp_path


def the_calls(tmp_path: Path) -> Path:
    write_rows(tmp_path, "calls", "call", "ibm-pc", [
        a_call("0x21/0x4C", "exit"), a_call("0x21/0x4D", "get return code")])
    return tmp_path


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> rows_base.Base:
    root = tmp_path_factory.mktemp("tool")
    write_rows(root, "ports", "port", "ibm-pc", [
        a_port("0x3C4", "sequencer index", aliases=["SEQ index"], device="vga-seq"),
        a_port("0x3C5", "sequencer data", device="vga-seq")])
    the_devices(root)
    the_calls(root)
    write_rows(root, "vga-seq", "register", "vga-seq", [
        {"key": "0x04", "name": "memory mode", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The memory mode register."), a_row(2, "read", "Readable.")]}])
    got = rows_base.Base((root,), None, pins=PINS)
    assert got.faults() == [], got.faults()
    return got


def ask(base: rows_base.Base, live: knowledge_tool.Live | None = None,
        **arguments: Any) -> dict[str, Any]:
    return knowledge_tool.find(base, live, **arguments)


def refused(base: rows_base.Base, code: str, **arguments: Any) -> Invalid:
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


def test_one_match_answers_the_whole_entry_with_where_to_open_its_sources(
        base: rows_base.Base) -> None:
    got = ask(base, kind="port", key="0x3c4")
    assert got["entries_total"] == 1 and got["truncated"] is False and got["examined"] == 2
    assert got["query"] == {"kind": "port", "key": "0x3C4"} and "how" not in got
    [entry] = got["entries"]
    assert entry["id"] == "ibm-pc:port:0x3C4" and entry["aliases"] == ["SEQ index"]
    [row] = [r for r in entry["rows"] if r["of"] == "doc"]
    assert row["text"].startswith("The sequencer index")
    assert row["cites"] == [{"file": "src/hardware/vga_seq.cpp", "lines": "10"}]
    assert entry["sources"] == [{"where": "src/hardware/vga_seq.cpp",
                                 "url": "https://github.com/joncampbell123/dosbox-x/blob/"
                                        "0e900e855/src/hardware/vga_seq.cpp"}]
    assert "checked" not in entry


def test_an_entry_answers_with_the_call_it_names_and_where_its_lines_are(
        base: rows_base.Base) -> None:
    [call] = ask(base, id="ibm-pc:call:0x21/0x4C")["entries"]
    assert call["name"] == "exit"
    assert [r["on"] for r in call["rows"]] == ["is", "out AX"]
    assert call["sources"] == [{"where": "src/dos/handler.cpp",
                                "url": "https://github.com/joncampbell123/dosbox-x/blob/"
                                       "0e900e855/src/dos/handler.cpp"}]
    [device] = ask(base, kind="device", key="vga-seq")["entries"]
    assert device["name"] == "VGA sequencer" and device["kind"] == "device"
    [register] = ask(base, id="vga-seq:register:0x04")["entries"]
    assert register["scope"] == "vga-seq" and register["name"] == "memory mode"


def test_several_matches_are_rows_and_the_whole_entry_is_asked_by_id(
        base: rows_base.Base) -> None:
    got = ask(base, kind="port", limit=1)
    assert got["entries_total"] == 2 and got["truncated"] is True and got["how"] == (
        knowledge_tool.HOW)
    assert got["entries"] == [{"id": "ibm-pc:port:0x3C4", "kind": "port", "key": "0x3C4",
                               "name": "sequencer index", "scope": "ibm-pc"}]
    assert ask(base, kind="port")["truncated"] is False
    assert ask(base, device="vga-seq")["entries_total"] == 2


def test_words_find_entries_and_a_number_with_no_kind_finds_every_kind(
        base: rows_base.Base) -> None:
    assert [e["id"] for e in ask(base, text="sequencer*")["entries"]] == [
        "ibm-pc:device:vga-seq", "ibm-pc:port:0x3C4", "ibm-pc:port:0x3C5"]
    assert ask(base, key="0x3C5")["entries"][0]["id"] == "ibm-pc:port:0x3C5"
    assert ask(base, key="0x21/0x4D")["entries"][0]["name"] == "get return code"


def test_a_number_the_base_does_not_hold_is_an_answer_and_stays_a_number(
        base: rows_base.Base) -> None:
    got = ask(base, kind="port", key="0x3C6")
    assert got["entries_total"] == 0
    assert got["entries"] == [] and got["examined"] == 2
    assert [e["key"] for e in got["nearest"]] == ["0x3C5"] and "how" not in got
    assert got["note"] == "the base holds 2 ports and none at 0x3C6: it stays a number"
    assert ask(base, text="zebra")["note"] == "the base holds 6 entries and none says zebra"


def test_an_id_the_base_does_not_hold_names_the_nearest(base: rows_base.Base) -> None:
    caught = refused(base, "unknown_ref", id="ibm-pc:port:0x3C7")
    assert "ibm-pc:port:0x3C4" in caught.fields["nearest"] and len(caught.fields["nearest"]) == 5
    assert "the nearest are" in str(caught)


def test_a_device_the_base_does_not_hold_names_those_it_has(base: rows_base.Base) -> None:
    caught = refused(base, "unknown_ref", device="sbx")
    assert "vga-seq" in str(caught) and caught.fields["nearest"]


def test_a_kind_the_server_holds_nothing_of_names_the_kinds_it_has(base: rows_base.Base) -> None:
    caught = refused(base, "no_channel", kind="irq")
    assert caught.fields["kinds"] == ["call", "port", "device", "register"]
    assert "it has call, port, device, register" in str(caught)


def test_a_scope_the_server_does_not_hold_names_those_it_has(base: rows_base.Base) -> None:
    assert "ibm-pc, vga-seq" in str(refused(base, "bad_argument", kind="port", scope="m68000"))


def test_a_base_that_loaded_nothing_says_why(tmp_path: Any) -> None:
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert "JSON" in str(refused(rows_base.Base((tmp_path,), None), "no_channel", kind="port"))


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
        base: rows_base.Base) -> None:
    with pytest.raises(Invalid) as caught:
        ask(base, Machine(False), kind="input", key=":IN1")
    assert caught.value.code == "no_session"
    machine = Machine(True)
    got = ask(base, machine, kind="input", key=":IN1")
    assert got["entries_total"] == 1 and machine.asked == [("input", ":IN1", "")]
    assert got["entries"] == [{"kind": "input", "key": ":IN1/Coin 1", "name": "Coin 1",
                               "live": True}]
    assert ask(base, machine, kind="port")["scope"] == ["ibm-pc", "vga-seq"]


def test_a_tag_of_the_running_machine_asks_the_machine_and_not_the_base(
        base: rows_base.Base) -> None:
    machine = Machine(True)
    got = ask(base, machine, device=":ymsnd")
    assert machine.asked == [("", "", ":ymsnd")] and got["entries"][0]["live"] is True
    with pytest.raises(Invalid) as caught:
        ask(base, Machine(False), device=":ymsnd")
    assert caught.value.code == "no_session"


class Tagged:
    """A machine that names its devices by tag, as MAME does; one of them has a chip in the base."""

    kinds: tuple[str, ...] = ("device",)

    def __init__(self, alive: bool = True, scopes: tuple[str, ...] = ("ibm-pc",)) -> None:
        self.alive = alive
        self.held = scopes
        self.asked: list[tuple[str, str, str]] = []

    def scopes(self) -> tuple[str, ...]:
        return self.held if self.alive else ()

    def rows(self, kind: str, key: str, device: str) -> Sequence[dict[str, Any]] | None:
        self.asked.append((kind, key, device))
        if not self.alive:
            return None
        if device != ":seq":
            return []
        return [{"kind": "device", "key": ":seq", "name": "sequencer", "type": "vga",
                 "chip": "ibm-pc:device:vga-seq"}]


@pytest.mark.parametrize("tag", [":seq", "seq"])
def test_a_device_is_asked_by_its_tag_with_or_without_the_colon_and_its_chip_comes_with_it(
        base: rows_base.Base, tag: str) -> None:
    machine = Tagged()
    got = ask(base, machine, kind="device", key=tag)
    assert machine.asked == [("device", "", ":seq")]
    assert got["query"] == {"kind": "device", "key": ":seq"} and got["entries_total"] == 1
    [row] = got["entries"]
    assert row["live"] is True and row["name"] == "sequencer"
    assert row["chip_entry"]["id"] == "ibm-pc:device:vga-seq"
    assert row["chip_entry"]["name"] and row["chip_entry"]["sources"]


def test_a_device_key_of_the_base_never_asks_the_machine(base: rows_base.Base) -> None:
    machine = Tagged()
    got = ask(base, machine, kind="device", key="vga-seq")
    assert machine.asked == [] and got["entries"][0]["id"] == "ibm-pc:device:vga-seq"


def test_a_tag_with_no_machine_says_it_needs_one_and_names_the_keys_that_do_not(
        base: rows_base.Base) -> None:
    with pytest.raises(Invalid) as caught:
        ask(base, Tagged(False), kind="device", key=":seq")
    assert caught.value.code == "no_session"
    assert "needs a running machine" in str(caught.value) and "vga-seq" in str(caught.value)
    with pytest.raises(Invalid) as caught:
        ask(base, Tagged(False), device=":seq")
    assert "vga-seq" in str(caught.value)


def test_a_shared_chip_is_asked_by_its_key_with_a_machine_running(tmp_path: Path) -> None:
    write_rows(tmp_path, "chips", "device", "chip", [
        {"key": "ym3812", "name": "OPL2", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The OPL2."), a_row(2, "reset", "Silent.")]}])
    write_rows(tmp_path, "cpu", "vector", "m6809", [
        {"key": "0xFFF8", "name": "IRQ", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The IRQ vector.")]}])
    held = rows_base.Base((tmp_path,), None)
    machine = Tagged(scopes=("m6809",))
    got = ask(held, machine, kind="device", key="ym3812")
    assert machine.asked == [] and [e["id"] for e in got["entries"]] == ["chip:device:ym3812"]
    assert ask(held, machine, text="OPL2")["entries_total"] == 1


def test_a_tag_the_machine_does_not_have_says_so_and_not_what_the_base_holds(
        base: rows_base.Base) -> None:
    got = ask(base, Tagged(), kind="device", key=":nosuch")
    assert got["entries_total"] == 0
    assert got["note"] == "the running machine has no device at :nosuch: it stays a number"
    assert "base holds" not in knowledge_tool.summary({}, got)


def test_a_server_with_no_devices_of_its_own_reads_a_tag_shaped_key_as_a_key(
        base: rows_base.Base) -> None:
    got = ask(base, None, kind="device", key="seq")
    assert got["entries_total"] == 0 and "none at seq" in got["note"]


@pytest.fixture
def cpus(tmp_path: Path) -> rows_base.Base:
    """Three cpus and a chip: the scopes a model gets wrong by a letter."""
    for scope, key in (("m6809", "0xFFF8"), ("m68000", "0x08"), ("v30", "0x00")):
        write_rows(tmp_path, f"{scope}-vectors", "vector", scope, [
            {"key": key, "name": f"{scope} vector", "regions": [], "closed": [],
             "rows": [a_row(1, "is", "A vector.")]}])
    write_rows(tmp_path, "ym2203-regs", "register", "ym2203", [
        {"key": "0x00", "name": "tone", "regions": [], "closed": [],
         "rows": [a_row(1, "is", "The tone register."), a_row(2, "write", "Writable.")]}])
    got = rows_base.Base((tmp_path,), None)
    assert got.faults() == []
    return got


@pytest.mark.parametrize(("typed", "read"), [("6809", "m6809"), ("M6809", "m6809"),
                                             ("m-6809", "m6809"), ("68000", "m68000"),
                                             ("YM2203", "ym2203"), ("2203", "ym2203"),
                                             ("m6809", "m6809")])
def test_a_scope_that_is_a_near_miss_is_answered_as_the_scope_it_plainly_means_and_says_so(
        cpus: rows_base.Base, typed: str, read: str) -> None:
    got = ask(cpus, kind=("vector" if read.startswith(("m", "v")) else "register"), scope=typed)
    assert got["scope"] == [read] and got["entries_total"] == 1
    if typed != read:
        assert got["note"] == f"scope {typed!r} was read as {read}"
    else:
        assert "note" not in got


def test_a_near_miss_that_could_be_two_scopes_or_none_is_refused_naming_those_that_exist(
        cpus: rows_base.Base, tmp_path: Path) -> None:
    for typed in ("68", "z80", "6", "80", "-", "8000"):
        caught = refused(cpus, "bad_argument", kind="vector", scope=typed)
        assert "m68000, m6809, v30, ym2203" in str(caught), typed
    for scope in ("mc6809", "m6809", "z80", "mz80", "pit"):
        write_rows(tmp_path, f"{scope}-vectors", "vector", scope, [
            {"key": "0xFFF8", "name": "irq", "regions": [], "closed": [],
             "rows": [a_row(1, "is", "A vector.")]}])
    held = rows_base.Base((tmp_path,), None)
    named = str(refused(held, "bad_argument", kind="vector", scope="6809"))
    assert ", ".join(held.scopes()) in named
    assert ask(held, kind="vector", scope="z80")["scope"] == ["z80"]
    assert "pit" in str(refused(held, "bad_argument", kind="vector", scope="-"))


def test_a_near_miss_that_found_nothing_keeps_its_note_beside_the_answer(
        cpus: rows_base.Base) -> None:
    got = ask(cpus, kind="vector", key="0x77", scope="6809")
    assert got["entries_total"] == 0 and got["note"].startswith("scope '6809' was read as m6809;")
    assert "stays a number" in got["note"]


def test_a_near_miss_that_is_no_scope_and_no_key_says_which(base: rows_base.Base) -> None:
    with pytest.raises(Invalid, match="is not one this server holds"):
        ask(base, kind="vector", scope="8086")


def test_every_example_of_the_description_is_a_question_the_judge_lets_through(
        base: rows_base.Base) -> None:
    doc = inspect.cleandoc(knowledge_tool.knowledge_find.__doc__ or "")
    assert doc in client_cap.delivered(doc)
    filled = {"<scope>": "ibm-pc", "<device>": "vga-seq"}
    examples = [{k: filled.get(v, v) for k, v in one.items()} for one in _examples(doc)]
    assert len(examples) >= 7
    for one in examples:
        knowledge_tool.judge(**one)
    shapes = {tuple(sorted(one)) for one in examples}
    assert len(shapes) >= 5, shapes
    assert any(one.get("key") == "0x10/0x12/BL=0x36" for one in examples)
    assert any(one.get("key", "").startswith(":") and one.get("kind") == "device"
               for one in examples)


def test_the_summary_says_what_was_asked_and_what_answered(base: rows_base.Base) -> None:
    def line(**arguments: Any) -> str:
        return knowledge_tool.summary(arguments, ask(base, **arguments))
    assert line(kind="port", key="0x3c4") == "kind port key 0x3C4: sequencer index"
    assert line(id="ibm-pc:port:0x3C5") == "id ibm-pc:port:0x3C5: sequencer data"
    assert line(kind="port") == "kind port: 2 entries"
    assert line(kind="port", limit=1) == "kind port: 2 entries, the first 1 listed"
    assert line(kind="port", key="0x3C6").startswith(
        "kind port key 0x3C6: no entry; the base holds")


def test_a_reply_of_the_body_is_one_the_model_accepts(base: rows_base.Base) -> None:
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


def test_the_scopes_a_description_lists_are_those_the_server_holds(cpus: rows_base.Base,
                                                                  base: rows_base.Base) -> None:
    for held, listed in ((cpus, "m68000, m6809, v30, ym2203"), (base, "ibm-pc, vga-seq")):
        tool = knowledge_tool.register(lambda title, **o: lambda fn: fn, lambda f: f, held)
        assert f"Scopes: {listed}." in tool.__doc__
    assert "Scopes:" not in (knowledge_tool.knowledge_find.__doc__ or "")


def test_the_registered_description_stays_under_half_the_cap_with_a_long_list_of_scopes() -> None:
    doc = inspect.cleandoc(knowledge_tool.knowledge_find.__doc__ or "")
    scopes = [f"chipset{n:02d}" for n in range(45)]
    line = knowledge_tool.scopes_line(scopes)
    assert client_cap.utf16_units(f"{doc}\n\n{line}\n\n{knowledge_tool.REFERENCE}") < (
        client_cap.CLIENT_TEXT_CAP // 2)


def _examples(doc: str) -> list[dict[str, str]]:
    paragraph = next(p for p in doc.split("\n\n") if p.startswith("Examples"))
    return [dict(word.partition("=")[::2] for word in span.split())
            for span in re.findall(r"`([^`]*=[^`]*)`", paragraph)]


def test_registering_binds_the_body_to_the_server_s_base_and_closes_its_reply(
        base: rows_base.Base) -> None:
    seen: dict[str, Any] = {}

    def wrap(title: str, **options: Any) -> Callable[[Callable[..., Any]], Any]:
        seen.update(title=title, **options)
        return lambda fn: fn

    tool = knowledge_tool.register(wrap, lambda fields: {"answered": True, **fields}, base)
    assert seen["title"] == knowledge_tool.TITLE and seen["read_only"] is True
    assert seen["summary"] is knowledge_tool.summary
    assert tool.__doc__.rstrip().endswith(knowledge_tool.REFERENCE)
    assert knowledge_tool.REFERENCE == "Reference: REFERENCE.md, Knowledge base."
    got = tool(kind="port", key="0x3C5")
    assert got["answered"] is True and got["entries"][0]["id"] == "ibm-pc:port:0x3C5"
    assert list(inspect.signature(tool).parameters) == [
        "id", "kind", "key", "text", "device", "scope", "limit"]
    assert "enum" in repr(inspect.signature(tool).parameters["kind"].annotation)


def test_a_server_with_nothing_live_answers_a_machine_question_with_no_session(
        base: rows_base.Base) -> None:
    with pytest.raises(Invalid) as caught:
        knowledge_tool.find(base, None, device=":ymsnd")
    assert caught.value.code == "no_session"


def test_the_signature_the_client_sees_is_not_a_body() -> None:
    with pytest.raises(NotImplementedError):
        knowledge_tool.knowledge_find()


def test_a_live_machine_narrows_the_answer_to_its_scopes_and_the_devices_inside_them(
        base: rows_base.Base) -> None:
    assert ask(base, Machine(True), device="vga-seq")["entries_total"] == 2
    assert ask(base, Machine(True), kind="register")["entries_total"] == 1


@pytest.mark.parametrize("arguments", [{"kind": "call", "key": "0x21/0x4D..0x21/0x4C"},
                                       {"key": "0x21/0x4D..0x21/0x4C"}])
def test_a_range_of_calls_that_runs_downward_is_refused_by_the_judge_and_by_the_body(
        base: rows_base.Base, arguments: dict[str, Any]) -> None:
    assert "runs upward" in str(refused(base, "bad_argument", **arguments))
    if "kind" in arguments:
        with pytest.raises(Invalid, match="runs upward"):
            knowledge_tool.judge(**arguments)


@pytest.fixture
def served(tmp_path: Path) -> rows_base.Base:
    root = tmp_path / "rows"
    root.mkdir()
    (root / "pic8259-commands.json").write_bytes(
        (KNOWLEDGE / "null-rows" / "pic8259-commands.json").read_bytes())
    return rows_base.Base((root,), sealed.read_lock(KNOWLEDGE / "null-rows-lock.json"))


SEALED_ID = "pic8259:command:0xE0..0xE7"
HELD_ID = "pic8259:command:0x20..0x27"


class TestOnlySealedEntriesAreServed:
    def test_a_reply_carries_the_two_counts(self, served: rows_base.Base) -> None:
        got = ask(served, kind="command", key="0xE0..0xE7")
        assert (got["served"], got["held_back"]) == (1, 1)
        assert ask(served, id=SEALED_ID)["held_back"] == 1

    def test_a_key_whose_entry_is_held_back_says_it_exists_and_is_not_confirmed(
            self, served: rows_base.Base) -> None:
        got = ask(served, kind="command", key="0x20..0x27")
        assert got["entries"] == [] and got["entries_total"] == 0
        assert "not confirmed" in got["note"] and got["unconfirmed"] == [HELD_ID]
        assert "not confirmed" in knowledge_tool.summary({}, got)

    def test_an_id_that_is_held_back_says_so_and_does_not_name_it(
            self, served: rows_base.Base) -> None:
        got = ask(served, id=HELD_ID)
        assert got["entries"] == [] and "not confirmed" in got["note"]
        assert "non-specific" not in str(got)

    def test_a_range_serves_the_sealed_and_says_how_many_it_holds_back(
            self, served: rows_base.Base) -> None:
        got = ask(served, kind="command", key="0x20..0x27")
        assert got["entries"] == []
        assert got["note"] == ("an entry exists and is not confirmed, so it is not served: "
                               "it stays a number")

    def test_a_text_question_never_returns_a_sealed_back_entry(
            self, served: rows_base.Base) -> None:
        got = ask(served, text="non-specific*")
        assert [e["key"] for e in got["entries"]] == []

    def test_words_that_match_nothing_are_not_blamed_on_the_entries_held_back(
            self, served: rows_base.Base) -> None:
        asked: list[dict[str, Any]] = [{"kind": "command", "text": "zebra"},
                                       {"kind": "command", "key": "0x20..0x27", "text": "zebra"}]
        for arguments in asked:
            got = ask(served, **arguments)
            assert "unconfirmed" not in got and "not confirmed" not in got["note"]
            assert "not confirmed" not in knowledge_tool.summary(arguments, got)

    def test_the_counts_are_the_status_block(self, served: rows_base.Base) -> None:
        assert knowledge_tool.counts(served) == {"served": 1, "held_back": 1}

    def test_a_question_nothing_matches_is_still_nothing_known(
            self, served: rows_base.Base) -> None:
        got = ask(served, kind="command", key="0x999")
        assert "stays a number" in got["note"] and "not confirmed" not in got["note"]

    def test_a_base_that_serves_nothing_but_holds_entries_back_says_so(
            self, tmp_path: Path) -> None:
        root = tmp_path / "rows"
        root.mkdir()
        (root / "pic8259-commands.json").write_bytes(
            (KNOWLEDGE / "null-rows" / "pic8259-commands.json").read_bytes())
        nothing = rows_base.Base((root,), sealed.Lock({}))
        got = ask(nothing, kind="command", key="0x20..0x27")
        assert "not confirmed" in got["note"] and got["served"] == 0


def test_a_row_is_asked_by_its_id(served: rows_base.Base) -> None:
    got = ask(served, id=f"{SEALED_ID}#1")
    assert got["entries_total"] == 1
    [row] = got["entries"][0]["rows"]
    assert row["n"] == "1" and row["cites"][0]["url"]


def test_a_question_that_matches_served_and_held_back_entries_counts_both(
        served: rows_base.Base) -> None:
    got = ask(served, kind="command", key="0x20..0xE7")
    assert got["entries_total"] == 1 and got["held_back"] == 1
    assert got["unconfirmed"] == [HELD_ID] and "not confirmed" in got["note"]


def test_two_held_back_entries_are_counted_together(tmp_path: Path) -> None:
    root = tmp_path / "rows"
    root.mkdir()
    doc = json.loads((KNOWLEDGE / "null-rows" / "pic8259-commands.json").read_text(
        encoding="utf-8"))
    doc["entries"].append({
        "key": "0x30..0x37", "name": "a third command", "regions": [], "closed": [],
        "rows": [a_row(1, "is", "A third command."), a_row(2, "write", "Writable.")]})
    (root / "pic8259-commands.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    base_ = rows_base.Base((root,), sealed.read_lock(KNOWLEDGE / "null-rows-lock.json"))
    got = ask(base_, kind="command", key="0x20..0xE7")
    assert (got["served"], got["held_back"]) == (1, 2)
    assert got["note"] == ("2 more entries exist and are not confirmed, so not served")
