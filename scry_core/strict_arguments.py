"""The schema is part of a tool's contract: what it does not declare is refused, never rescued.

It is apart from `reply_contract.py` because a server may answer in an envelope of its own and
carry no refusal table: what every server shares is the schema's judgement and the sentence
that reports it.

WHY. The SDK offers no switch for it: its argument model is built LAX, so a convertible type is
coerced (`"16"` becomes 16), an unknown name is dropped (a retired `width=4`, a misspelt
`limt=5`, runs as if never sent) and a JSON string is parsed into the list it spells.
`strict_arguments` swaps each tool's model for a strict subclass that forbids extras, with the
rescue off, so all three reach the server's own envelope as a refusal, and the schema a client
is shown is rebuilt from the same model. `ctx` is injected by the SDK and never part of the
model. The hooks this rides on are pinned by `tests/test_strict_arguments.py`, which fails when
the SDK moves them.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import ConfigDict, ValidationError

#: The version of what this module does: a consumer can assert the behaviour it was written for.
STRICT_VERSION = 2


class _StrictMetadata(FuncMetadata):
    """The SDK's argument handling with its JSON rescue turned off: a string reaches the model
    as the string it is, so a list sent as `'[...]'` is the wrong type it looks like."""

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data)


def registered(server: MCPServer) -> list[Tool]:
    """The tools registered on `server` so far: the one place this package and the servers reach
    the SDK's registry, which it keeps private."""
    return server._tool_manager.list_tools()


def strict_arguments(server: MCPServer) -> None:
    """Make every tool registered on `server` so far refuse what its lax model would rescue."""
    strict = ConfigDict(strict=True, extra="forbid", arbitrary_types_allowed=True)
    for t in registered(server):
        meta = t.fn_metadata
        model: type[ArgModelBase] = type(
            meta.arg_model.__name__, (meta.arg_model,),
            {"model_config": strict, "__module__": meta.arg_model.__module__})
        t.fn_metadata = _StrictMetadata(arg_model=model, output_schema=meta.output_schema,
                                        output_model=meta.output_model,
                                        wrap_output=meta.wrap_output)
        t.parameters = model.model_json_schema(by_alias=True)


def refused_by_schema(error: ToolError) -> ValidationError | None:
    """The schema's judgement behind `error`, or None when `error` is any other failure.

    The SDK raises a plain `ToolError` from the arguments' `ValidationError`, and an
    `UnexpectedToolError` around anything that escapes a tool body, a body's own
    `ValidationError` included. The cause alone cannot tell the two apart; the wrapper can, and
    a defect answered as a refusal would read as the caller's mistake."""
    cause = error.__cause__
    if isinstance(error, UnexpectedToolError) or not isinstance(cause, ValidationError):
        return None
    return cause


def schema_refusal(cause: ValidationError) -> str:
    """The schema's refusal in the servers' words: which argument, what was expected, what
    came. The judgement stays the schema's; only the sentence is ours."""
    parts = []
    for err in cause.errors():
        name = ".".join(str(x) for x in err["loc"]) or "an argument"
        msg = err["msg"]
        parts.append(f"{name} {msg[0].lower() + msg[1:]}; got {err.get('input')!r}")
    return "refused by the schema before the tool ran: " + "; ".join(parts)
