"""`scry_core.reply_schema`: a tool's reply model published as its `outputSchema`, room left for a
field it does not name, and every reply the battery builds held to it strictly."""

from __future__ import annotations

from typing import Annotated, Any, Required

import pytest
from jsonschema import Draft202012Validator
from mcp.server.mcpserver import MCPServer

from scry_core import reply_schema
from scry_core import reply_shapes_guard as shapes
from scry_core.reply_contract import OmitEmpty, When
from scry_core.strict_arguments import registered


class StatusReply(reply_schema.ReplyEnvelope, total=False):
    alive: bool
    pc: str | dict[str, Any]
    title: str
    crop: list[Any]


def _server() -> MCPServer:
    server = MCPServer("t")

    @server.tool()
    def status() -> dict[str, Any]:
        return {"status": "ok", "alive": True}
    return server


def test_a_declared_model_is_published_naming_every_field_and_refusing_none() -> None:
    server = _server()
    reply_schema.declare(server, {"status": StatusReply})
    schema = registered(server)[0].output_schema
    assert schema is not None and "additionalProperties" not in schema, schema
    assert schema["required"] == ["status"], schema
    props = schema["properties"]
    assert {"summary", "status", "session", "alive", "pc", "title"} <= set(props), props


def test_a_published_field_is_its_value_or_unavailable() -> None:
    server = _server()
    reply_schema.declare(server, {"status": StatusReply})
    schema = registered(server)[0].output_schema
    assert schema is not None
    validator = Draft202012Validator(schema)
    for good in ({"status": "ok", "alive": True, "pc": "0814:0106"},
                 {"status": "ok", "alive": {"available": False, "why": "gone"}}):
        assert not list(validator.iter_errors(good)), good
    for bad in ({"status": "ok", "alive": 1}, {"status": "ok", "alive": {"available": False}},
                {"status": "maybe"}, {"alive": True}):
        assert list(validator.iter_errors(bad)), bad


class NeededReply(reply_schema.ReplyEnvelope, total=False):
    pc: Required[str]
    polls: Annotated[int, When("by frames")]
    note: str


def _needed() -> Draft202012Validator:
    server = _server()
    reply_schema.declare(server, {"status": NeededReply})
    schema = registered(server)[0].output_schema
    assert schema is not None
    return Draft202012Validator(schema)


def test_a_required_field_is_required_of_an_ok_reply_and_never_of_a_refusal() -> None:
    validator = _needed()
    assert not list(validator.iter_errors({"status": "ok", "pc": "0x10"}))
    assert not list(validator.iter_errors(
        {"status": "INVALID", "code": "no_session", "message": "none"}))
    assert list(validator.iter_errors({"status": "ok"}))
    assert not list(validator.iter_errors({"status": "ok", "omitted": ["pc"]}))
    assert list(validator.iter_errors({"status": "ok", "omitted": ["note"]}))


def test_the_judge_refuses_an_ok_reply_missing_a_required_field() -> None:
    reply_schema.declare(_server(), {"status": NeededReply})
    reply_schema.check("status", {"status": "ok", "pc": "0x10"})
    reply_schema.check("status", {"status": "ok", "omitted": ["pc"], "how": "narrow"})
    reply_schema.check("status", {"status": "INVALID", "code": "no_session", "message": "none"})
    with pytest.raises(reply_schema.MissingFields, match="pc"):
        reply_schema.check("status", {"status": "ok", "polls": 3})
    with pytest.raises(reply_schema.MissingFields, match="pc"):
        reply_schema.check("status", {"status": "ok", "omitted": ["note"]})


@pytest.fixture(autouse=True)
def no_judge_left_behind() -> Any:
    """A model a case declares leaves with it: the judges are keyed by tool name alone."""
    kept = dict(reply_schema._JUDGES)
    yield
    reply_schema._JUDGES.clear()
    reply_schema._JUDGES.update(kept)


def test_a_reply_is_held_to_its_model_strictly() -> None:
    reply_schema.declare(_server(), {"status": StatusReply})
    reply_schema.check("status", {"status": "ok", "alive": True, "pc": "0814:0106"})
    reply_schema.check("status", {"status": "ok", "crop": (0, 0, 8, 8)})  # a list on the wire
    reply_schema.check("status", {"status": "ok", "alive": {"available": False, "why": "gone"}})
    reply_schema.check("nobody", {"anything": 1})                 # an undeclared name: unjudged
    for bad in ({"status": "ok", "alive": 1}, {"status": "ok", "nope": True},
                {"alive": True}, {"status": "maybe"},
                {"status": "ok", "alive": {"available": True, "why": "it is not unavailable"}}):
        with pytest.raises(ValueError):
            reply_schema.check("status", bad)


def test_a_tool_with_no_model_or_a_model_with_no_tool_is_the_server_s_bug() -> None:
    with pytest.raises(ValueError, match=r"no reply model: \['status'\]"):
        reply_schema.declare(_server(), {})
    with pytest.raises(ValueError, match=r"with no tool: \['stray'\]"):
        reply_schema.declare(_server(), {"status": StatusReply, "stray": StatusReply})


def test_the_shape_guard_fails_a_reply_its_model_does_not_declare() -> None:
    reply_schema.declare(_server(), {"status": StatusReply})
    summary = shapes._wrap_summary(lambda name, args, reply: f"{name}: {reply['status']}")
    assert summary("status", {}, {"status": "ok", "alive": True}) == "status: ok"
    with pytest.raises(AssertionError, match="not the shape its model declares"):
        summary("status", {}, {"status": "ok", "alive": True, "extra": 1})


def test_the_reply_sentence_names_its_top_level_fields() -> None:
    doc = ("Read it.\n\n    Reply: `rows` (`addr`, `bytes`), `truncated`, and `path` when\n"
           "    `dest` was given (`none` otherwise); `trace`: `cpu`, `set_path`. `note`.\n\n"
           "    Reference: x.")
    assert reply_schema.reply_sentence_names(doc) == ["rows", "truncated", "path", "dest",
                                                      "trace", "note"]
    assert reply_schema.reply_sentence_names("No reply sentence.") == []


class _Model(reply_schema.ReplyEnvelope, total=False):
    rows: list[int]


def test_a_sentence_field_the_model_lacks_is_named_and_the_rest_are_not() -> None:
    doc = "Reply: `rows`, `extra`, `TARGET`, `bad_argument`, `quoted`, and `unclosed"
    assert reply_schema.unmodelled(doc, _Model, ["quoted"]) == ["extra"]


def test_a_reply_paragraph_is_found_however_it_opens() -> None:
    for opening in ("Reply:", "Reply (on a stop):", "Reply, at the top:"):
        assert reply_schema.reply_sentence_names(f"Do it.\n\n{opening} `rows`.") == ["rows"]
    assert reply_schema.own_fields(_Model) == ["rows"]
    per_row = "Reply, per channel in `measures` (`channel`): `peak`, `rms`. `path` too."
    assert reply_schema.reply_sentence_names(per_row) == ["measures", "path"]


class _Tool:
    def __init__(self, name: str, description: str, args: tuple[str, ...] = ()) -> None:
        self.name, self.description = name, description
        self.input_schema: dict[str, Any] = {"properties": {a: {} for a in args}}


def test_the_sentence_faults_name_a_missing_field_a_silent_model_and_a_stale_word() -> None:
    tools = [_Tool("one", "Reply: `rows`, `extra`."), _Tool("two", "No paragraph."),
             _Tool("three", "Reply: `rows` and `quit`.")]
    models = {"one": _Model, "two": _Model, "three": _Model}
    got = reply_schema.sentence_faults(tools, models, {"three": ("quit", "gone")})
    assert got == {"one": ["extra"], "two": "its description names no field of its reply",
                   "three": "allowed and no longer quoted: ['gone']"}


def test_an_optional_promised_field_must_state_its_condition_in_the_sentence() -> None:
    models = {"a": NeededReply, "b": NeededReply, "c": NeededReply}
    tools = [_Tool("a", "Reply: `pc`, `polls` (by frames), `note`."),
             _Tool("b", "Reply: `pc` and `polls`."),
             _Tool("c", "Reply: `pc`; `summary`, `status`.")]
    got = reply_schema.sentence_faults(tools, models, {})
    assert got == {
        "a": ["note: optional, so its condition is `When(...)` in the model"],
        "b": ["polls: `When('by frames')` is not said in the Reply paragraph"]}


def test_the_stop_fields_are_held_to_every_tool_that_quotes_them() -> None:
    stop = "the stop: `rows`, `pc`"
    tools = [_Tool("a", f"Reply: {stop}."), _Tool("b", "Reply: `rows`.")]
    assert reply_schema.stop_fields_lacking(tools, {"a": _Model, "b": _Model}, stop) == {
        "a": ["pc"]}
    with pytest.raises(ValueError, match="nothing would be examined"):
        reply_schema.stop_fields_lacking(tools[1:], {"b": _Model}, stop)


class CountedReply(reply_schema.ReplyEnvelope, total=False):
    hits: int
    retries: Annotated[int, OmitEmpty]
    notes: Annotated[list[str], OmitEmpty]
    warned: Annotated[bool | dict[str, Any], OmitEmpty]


def test_a_marked_field_left_empty_is_dropped_and_an_answer_at_zero_is_kept() -> None:
    reply_schema.declare(_server(), {"status": CountedReply})
    empty = {"status": "ok", "hits": 0, "retries": 0, "notes": [], "warned": False}
    assert reply_schema.omit_empty("status", empty) == {"status": "ok", "hits": 0}
    full = {"status": "ok", "hits": 0, "retries": 2, "notes": ["n"], "warned": True}
    assert reply_schema.omit_empty("status", full) == full
    assert reply_schema.omit_empty("nobody", {"status": "ok", "retries": 0}) == {
        "status": "ok", "retries": 0}
    reply_schema.check("status", {"status": "ok", "retries": 1})


def test_a_marked_field_is_never_required() -> None:
    server = _server()
    reply_schema.declare(server, {"status": CountedReply})
    schema = registered(server)[0].output_schema
    assert schema is not None and not {"retries", "notes", "warned"} & set(schema["required"])

    class Marked(reply_schema.ReplyEnvelope, total=False):
        always: Required[Annotated[int, OmitEmpty]]

    with pytest.raises(ValueError, match="always"):
        reply_schema.declare(_server(), {"status": Marked})


def test_a_condition_is_read_from_the_model_and_is_never_required() -> None:
    assert reply_schema.conditions(NeededReply) == {"polls": "by frames"}
    assert reply_schema.own_required(NeededReply) == frozenset({"pc"})
    with pytest.raises(TypeError, match="condition"):
        When("  ")

    class Both(reply_schema.ReplyEnvelope, total=False):
        always: Required[Annotated[int, When("sometimes")]]

    with pytest.raises(ValueError, match="always"):
        reply_schema.declare(_server(), {"status": Both})


def test_the_shape_guard_names_a_missing_required_field() -> None:
    reply_schema.declare(_server(), {"status": NeededReply})
    summary = shapes._wrap_summary(lambda name, args, reply: f"{name}: {reply['status']}")
    with pytest.raises(AssertionError, match="omits.*pc"):
        summary("status", {}, {"status": "ok"})
