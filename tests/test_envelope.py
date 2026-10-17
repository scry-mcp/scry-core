"""`scry_core.envelope`: the schema's refusal given the server's envelope, off the event loop, and
every other error left on the SDK's path; driven through the SDK's own `call_tool`."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import ValidationError

from scry_core.envelope import Envelope


class _Server:
    """A server of one tool, `count(n: int)`, whose refusal records how it was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str, bool]] = []
        self.loop_thread: int | None = None
        self.mcp = Envelope("t", instructions="i", refusal=self.refusal)

        @self.mcp.tool()
        def count(n: int) -> dict[str, Any]:
            if n < 0:
                raise RuntimeError("a defect in the body")
            return {"summary": f"count {n}", "status": "ok", "n": n, "session": {}}

    def refusal(self, name: str, arguments: dict[str, Any],
                cause: ValidationError) -> dict[str, Any]:
        on_a_worker = threading.get_ident() != self.loop_thread
        self.calls.append((name, arguments, type(cause).__name__, on_a_worker))
        return {"summary": f"{name}: INVALID", "status": "INVALID", "code": "bad_argument",
                "message": str(cause.errors()[0]["loc"]), "session": {}}

    def call(self, **arguments: Any) -> Any:
        async def on_the_loop() -> Any:
            self.loop_thread = threading.get_ident()
            return await self.mcp.call_tool("count", arguments)
        return asyncio.run(on_the_loop())


def test_a_call_the_schema_refuses_is_the_servers_envelope_built_off_the_loop() -> None:
    s = _Server()
    got = s.call(n="many")
    assert isinstance(got, CallToolResult)
    assert got.structured_content is not None and got.structured_content["code"] == "bad_argument"
    assert json.loads(got.content[0].text) == got.structured_content  # type: ignore[union-attr]
    assert s.calls == [("count", {"n": "many"}, "ValidationError", True)]


def test_a_call_the_schema_takes_answers_from_the_tool_and_the_refusal_is_not_asked() -> None:
    s = _Server()
    got = s.call(n=3)
    assert s.calls == []
    assert "count 3" in json.dumps(got, default=str)


def test_a_defect_in_a_body_keeps_the_sdks_path_and_is_never_a_refusal() -> None:
    s = _Server()
    with pytest.raises(ToolError, match="Error executing tool count"):
        s.call(n=-1)
    assert s.calls == []
