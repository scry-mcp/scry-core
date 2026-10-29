"""The schema is part of a tool's contract: what it does not declare is refused, never rescued.

The SDK's lax model coerces `"16"`, drops unknown names and parses JSON strings; here all
three are refused.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from pydantic import ConfigDict, ValidationError

STRICT_VERSION = 2


class _StrictMetadata(FuncMetadata):
    """The SDK's argument handling, JSON rescue off."""

    def pre_parse_json(self, data: dict[str, Any]) -> dict[str, Any]:
        return dict(data)


def registered(server: MCPServer) -> list[Tool]:
    """The tools registered on `server` so far."""
    return server._tool_manager.list_tools()


def refused(tool: Tool, args: dict[str, Any]) -> str | None:
    """Why `tool`'s strict schema refuses `args`, or None when it takes them."""
    try:
        tool.fn_metadata.arg_model.model_validate(args)
    except ValidationError as e:
        return "; ".join(f"{'.'.join(map(str, err['loc'])) or 'arguments'}: {err['msg']}"
                         for err in e.errors())
    return None


def strict_arguments(server: MCPServer) -> None:
    """Make every tool registered on `server` so far refuse what its lax model rescues."""
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
    """The schema's judgement behind `error`, or None for any other failure.

    A body's own `ValidationError` arrives as `UnexpectedToolError`: a defect, not a refusal."""
    cause = error.__cause__
    if isinstance(error, UnexpectedToolError) or not isinstance(cause, ValidationError):
        return None
    return cause


def schema_refusal(cause: ValidationError) -> str:
    """The schema's refusal in the servers' words."""
    parts = []
    for err in cause.errors():
        name = ".".join(str(x) for x in err["loc"]) or "an argument"
        msg = err["msg"]
        parts.append(f"{name} {msg[0].lower() + msg[1:]}; got {err.get('input')!r}")
    return "refused by the schema before the tool ran: " + "; ".join(parts)


def method_refusal(method: str, given: Iterable[str], takes: Iterable[str]) -> str | None:
    """Why `method` refuses `given` arguments it does not take, or None."""
    stray = sorted(set(given) - set(takes))
    if not stray:
        return None
    return (f"method `{method}` does not take {', '.join(f'`{a}`' for a in stray)}; it takes "
            + ", ".join(f"`{a}`" for a in takes))
