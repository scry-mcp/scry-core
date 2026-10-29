"""`scry_core.envelope`, driven through the SDK's own `call_tool`."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import ValidationError

from scry_core.envelope import IN_DEVELOPMENT, REPLY_NOTE, Envelope


class _Server:

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str, bool]] = []
        self.loop_thread: int | None = None
        self.mcp = Envelope("t", instructions="i", refusal=self.refusal)

        @self.mcp.tool()
        def count(n: int) -> dict[str, Any]:
            if n < 0:
                raise RuntimeError("a defect in the body")
            value: Any = math.nan if n == 13 else n
            return {"summary": f"count {n}", "status": "ok", "n": value, "session": {}}

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


def test_every_server_tells_the_model_it_is_in_development_after_its_own_instructions() -> None:
    got = _Server().mcp.instructions or ""
    assert got == "i\n\n" + REPLY_NOTE + "\n\n" + IN_DEVELOPMENT
    assert "`note`" in REPLY_NOTE


def test_a_server_with_no_instructions_of_its_own_is_refused() -> None:
    with pytest.raises(ValueError, match="instructions"):
        Envelope("t", instructions=" \n", refusal=_Server().refusal)


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


def test_a_reply_that_is_not_valid_json_is_refused_at_the_boundary() -> None:
    """`allow_nan=False`: a NaN reply fails here instead of reaching a client as invalid JSON."""
    with pytest.raises(ValueError, match="count's reply holds NaN, which is not JSON compliant"):
        _Server().call(n=13)
    assert _Server().call(n=12).structured_content["n"] == 12
