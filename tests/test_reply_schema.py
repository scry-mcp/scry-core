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
