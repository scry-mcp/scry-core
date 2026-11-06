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

from scry_core import given, picture
from scry_core import strict_arguments as strict

#: Takes the tool name, the arguments as given and the SDK's validation error; returns the whole
#: body.
Refusal = Callable[[str, dict[str, Any], ValidationError], dict[str, Any]]

#: Opens the shared part of every server's `instructions`: what `note` is, said once for all tools.
REPLY_NOTE = ("A reply carries `note` only when it has something to say that its fields do not; "
              "a reply with no `note` has nothing more to say.")

#: Closes every server's `instructions`: the servers are proven on real use before they settle.
IN_DEVELOPMENT = (
    "IN DEVELOPMENT. This server is half of Scry, MCP servers for MAME and DOSBox-X still taking "
    "shape, which aim at one surface: a tool both have means the same and answers the same, "
    "beyond what the emulators themselves make different. Judge the server, not the program you "
    "investigate. When one of its tools got in your way (a misleading name, an argument you had "
    "to guess, a reply missing what you needed, a refusal that did not say what to do next, a "
    "capability you lacked) or, with both servers connected, the two answered one name "
    "differently, tell the user once, at the end of the task, naming the server, the tool and "
    "the case. With nothing to report, say nothing."
)


class Envelope(MCPServer):
    """An `MCPServer` whose schema refusals keep the reply envelope, and whose `instructions`
    end with `REPLY_NOTE` and `IN_DEVELOPMENT`; an empty one is refused."""

    def __init__(self, name: str, *, instructions: str, refusal: Refusal) -> None:
        if not instructions.strip():
            raise ValueError(f"{name} declares no instructions of its own")
        super().__init__(name, instructions=f"{instructions}\n\n{REPLY_NOTE}\n\n{IN_DEVELOPMENT}")
        self._refusal = refusal

    async def call_tool(self, name: str, arguments: dict[str, Any],
                        context: Context[Any, Any] | None = None) -> Any:
        with given.remembered(arguments):
            try:
                result = await super().call_tool(name, arguments, context)
                return _strict(name, picture.attached(result))
            except ToolError as e:
                cause = strict.refused_by_schema(e)
                if cause is None:
                    raise
                # Off the event loop: the refusal takes the server's lock, held by the worker
                # thread running a sync tool body that reports progress through the loop; a loop
                # parked on the lock would deadlock both.
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
