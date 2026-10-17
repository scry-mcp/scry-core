"""THE MCP BOUNDARY every Scry server answers through, where two things happen once for every
tool: the schema's refusal is given the reply envelope, and a tool's picture is attached.

THE SCHEMA'S REFUSAL. The SDK validates every call against the tool's schema before the tool
runs, and its refusal is its own error text, outside the reply shape every tool promises. Nothing
is validated twice: the refusal is caught here, once, and handed to the server's `refusal`, which
builds the envelope (`summary`, `status`, `code`, `message`, `session`) so a caller reads one
shape. Any other error keeps the SDK's path: a defect in a tool body is never dressed as a
refusal.

THE PICTURE. A media tool's body names its PNG in `image`; the picture itself is attached here,
beside the JSON (`scry_core.picture.attached`), so a tool body and a test deal in a plain dict.
"""

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

#: The server's reply to a call its schema refused: the tool's name, the arguments as given, the
#: SDK's validation error, and back the whole reply body, envelope included.
Refusal = Callable[[str, dict[str, Any], ValidationError], dict[str, Any]]


class Envelope(MCPServer):
    """An `MCPServer` whose every reply keeps the envelope, the schema's refusal included."""

    def __init__(self, name: str, *, instructions: str, refusal: Refusal) -> None:
        super().__init__(name, instructions=instructions)
        self._refusal = refusal

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context[Any, Any] | None = None) -> Any:
        try:
            return picture.attached(await super().call_tool(name, arguments, context))
        except ToolError as e:
            cause = strict.refused_by_schema(e)
            if cause is None:
                raise
            # OFF THE EVENT LOOP, AND THAT IS NOT A PREFERENCE. The refusal takes the server's
            # lock, and the tool bodies are synchronous, so the SDK runs each on a worker thread
            # and that thread is what holds the lock; a bounded wait reports progress from there
            # through the event loop (`anyio.from_thread.run`). A loop parked acquiring the lock
            # never runs that callback, so the worker never finishes and never lets go, and the
            # loop never gets the lock: both sides would wait for ever.
            body = await anyio.to_thread.run_sync(self._refusal, name, arguments, cause)
        text = TextContent(type="text", text=json.dumps(body, indent=2))
        return CallToolResult(content=[text], structured_content=body)
