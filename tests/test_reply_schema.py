"""`scry_core.reply_schema`: a tool's reply model published as its `outputSchema`, room left for a
field it does not name, and every reply the battery builds held to it strictly."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from scry_core import reply_schema
from scry_core import reply_shapes_guard as shapes
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
    assert all(spec == {} for spec in props.values()), "a published type could refuse a real reply"


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


def test_the_stop_fields_are_held_to_every_tool_that_quotes_them() -> None:
    stop = "the stop: `rows`, `pc`"
    tools = [_Tool("a", f"Reply: {stop}."), _Tool("b", "Reply: `rows`.")]
    assert reply_schema.stop_fields_lacking(tools, {"a": _Model, "b": _Model}, stop) == {
        "a": ["pc"]}
    with pytest.raises(ValueError, match="nothing would be examined"):
        reply_schema.stop_fields_lacking(tools[1:], {"b": _Model}, stop)
