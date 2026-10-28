"""The MCP boundary: a schema refusal gets the reply envelope, and a media tool's picture is
attached."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio.to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from scry_core import picture
from scry_core import strict_arguments as strict

#: Takes the tool name, the arguments as given and the SDK's validation error; returns the whole
#: body.
Refusal = Callable[[str, dict[str, Any], ValidationError], dict[str, Any]]

#: Closes every server's `instructions`: the servers are proven on real use before they settle.
IN_DEVELOPMENT = (
    "IN DEVELOPMENT. Scry is still taking shape, and its MAME and DOSBox-X servers are meant to "
    "be one surface: a tool both have takes the same arguments and answers the same fields. Be "
    "critical of it. When a tool gets in your way (a name that misleads, an argument you had to "
    "guess, a reply missing what you needed, a refusal that does not say what to do next, a "
    "feature you lacked) or answers differently from its twin on the other emulator, tell the "
    "user in your reply, naming the tool and the case."
)


class Envelope(MCPServer):
    """An `MCPServer` whose schema refusals keep the reply envelope."""

    def __init__(self, name: str, *, instructions: str, refusal: Refusal) -> None:
        super().__init__(name, instructions=f"{instructions}\n\n{IN_DEVELOPMENT}")
        self._refusal = refusal

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context[Any, Any] | None = None) -> Any:
        try:
            result = await super().call_tool(name, arguments, context)
            return _strict(name, picture.attached(result))
        except ToolError as e:
            cause = strict.refused_by_schema(e)
            if cause is None:
                raise
            # Off the event loop: the refusal takes the server's lock, held by the worker thread
            # running a sync tool body that reports progress through the loop; a loop parked on
            # the lock would deadlock both.
            body = await anyio.to_thread.run_sync(self._refusal, name, arguments, cause)
        text = TextContent(type="text", text=json.dumps(body, indent=2, allow_nan=False))
        return CallToolResult(content=[text], structured_content=body)


def _strict(name: str, result: Any) -> Any:
    """`result`, after checking its text is JSON: the SDK writes NaN/Infinity as bare constants."""
    def not_json(constant: str) -> Any:
        raise ValueError(f"{name}'s reply holds {constant}, which is not JSON compliant: a value "
                         "the tool computed is no number JSON can carry")
    if isinstance(result, CallToolResult) and isinstance(result.structured_content, dict):
        for part in result.content:
            if isinstance(part, TextContent):
                json.loads(part.text, parse_constant=not_json)
    return result
