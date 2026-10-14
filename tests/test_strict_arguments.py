"""The schema as part of a tool's contract, on a server of the test's own: what the lax model
would rescue is refused, with the schema's judgement in the servers' words, and a failure that is
not the schema's is never dressed as one."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from scry_core import strict_arguments as sa


class _Row(BaseModel):
    n: int


def _server(strict: bool) -> MCPServer:
    server = MCPServer("t")

    @server.tool()
    def count(n: int, names: list[str] | None = None) -> int:
        return n + len(names or [])

    @server.tool()
    def broken() -> int:
        return _Row.model_validate({"n": "x"}).n

    if strict:
        sa.strict_arguments(server)
    return server


def _call(server: MCPServer, args: dict[str, Any], tool: str = "count") -> Any:
    return asyncio.run(server.call_tool(tool, args))


@pytest.mark.parametrize(("args", "said"), [
    ({"n": "16"}, "n input should be a valid integer; got '16'"),
    ({"n": 1, "limt": 5}, "limt extra inputs are not permitted; got 5"),
    ({"n": 1, "names": '["a"]'}, "names input should be a valid list; got '[\"a\"]'"),
])
def test_what_the_lax_model_would_rescue_is_refused_by_the_schema(
        args: dict[str, Any], said: str) -> None:
    assert not _call(_server(strict=False), args).is_error, "the control: the SDK rescues it"
    with pytest.raises(ToolError) as exc:
        _call(_server(strict=True), args)
    cause = sa.refused_by_schema(exc.value)
    assert cause is not None
    assert sa.schema_refusal(cause) == f"refused by the schema before the tool ran: {said}"


def test_a_valid_call_still_runs_and_the_schema_shown_forbids_extras() -> None:
    server = _server(strict=True)
    assert _call(server, {"n": 2, "names": ["a"]}).structured_content == {"result": 3}
    (count,) = [t for t in server._tool_manager.list_tools() if t.name == "count"]
    assert count.parameters["additionalProperties"] is False


def test_a_failure_inside_the_body_is_not_the_schemas() -> None:
    """A tool body's own `ValidationError` escapes wrapped as unexpected: it is a defect, and
    answering it as a refusal would read as the caller's mistake."""
    with pytest.raises(ToolError) as exc:
        _call(_server(strict=True), {}, tool="broken")
    assert sa.refused_by_schema(exc.value) is None
    assert sa.refused_by_schema(ToolError("plain")) is None
