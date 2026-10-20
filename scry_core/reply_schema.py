"""THE REPLY'S PUBLISHED SHAPE: each tool's `outputSchema` names its fields, from a typed model
beside the tool (a `TypedDict` extending `ReplyEnvelope`), and the battery holds every reply to it.

THE SCHEMA A CLIENT READS NAMES THE FIELDS AND REFUSES NOTHING; THE BATTERY JUDGES THE TYPES. Any
datum may come back as `unavailable(why)`, and a field may take an arm no test has produced, so a
published type would one day refuse a real reply in a client that validates, and that client
would fail a call the server answered. So the published schema carries each field's name and no
constraint on its value, and `status` as required. The battery is strict (`check`, called by the
shape guard on every reply it builds): a field the model does not name, or a value of another
type, fails the run, which is where a new word or a new arm is discussed. The SDK still validates
against the tool's own return annotation, so no field is ever dropped from a reply; what `declare`
adds at run time is the published schema, and a refusal to start a server with a tool and no
model.

THE SCHEMA NEVER REACHES A MODEL'S CONTEXT in the client this fleet runs: the tool list it hands a
model carries no output schema, and a reply reaches it as its structured content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Required, get_type_hints

from mcp.server.mcpserver import MCPServer
from pydantic import ConfigDict, TypeAdapter
from typing_extensions import TypedDict

from scry_core.strict_arguments import registered


class ReplyEnvelope(TypedDict, total=False):
    """What every reply of both servers carries around its own fields."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    summary: str
    status: Required[Literal["ok", "INVALID"]]
    code: str
    message: str
    omitted: list[str]
    how: str
    cancelled: dict[str, Any]
    session: dict[str, Any]


class Unavailable(TypedDict):
    """`reply_contract.unavailable(why)`: any field may come back as it, in place of its value."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    available: Literal[False]
    why: str


def judged(model: type) -> TypeAdapter[Any]:
    """The battery's judge of `model`: its fields as declared, each but the envelope's also taking
    `Unavailable`, which the contract allows for any datum."""
    envelope = get_type_hints(ReplyEnvelope, include_extras=True)
    fields = {name: hint if name in envelope else hint | Unavailable
              for name, hint in get_type_hints(model, include_extras=True).items()}
    judge: Any = TypedDict(f"{model.__name__}Judged", fields, total=False)  # type: ignore[misc]
    setattr(judge, "__pydantic_config__", ConfigDict(extra="forbid", strict=True))  # noqa: B010
    return TypeAdapter(judge)


#: Each declared tool's model, as the battery judges a reply against it.
_JUDGES: dict[str, TypeAdapter[Any]] = {}


def published(model: type) -> dict[str, Any]:
    """`model`'s schema as a client reads it: every field named, none constrained, `status`
    required, room left for a field it does not name."""
    return {"type": "object", "properties": {name: {} for name in _fields(model)},
            "required": ["status"]}


def _fields(model: type) -> list[str]:
    """Every field `model` declares, its envelope's included, in declaration order."""
    return list(TypeAdapter(model).json_schema()["properties"])


def declare(server: MCPServer, models: Mapping[str, type]) -> None:
    """Publish each registered tool's model as its `outputSchema` and keep it for `check`. A tool
    with no model, or a model with no tool, is the server's bug, a `ValueError`: one would answer
    a shape nobody declared, the other declare a shape nobody answers."""
    tools = {t.name: t for t in registered(server)}
    if missing := sorted(tools.keys() - models.keys()):
        raise ValueError(f"tools with no reply model: {missing}")
    if stray := sorted(models.keys() - tools.keys()):
        raise ValueError(f"reply models with no tool: {stray}")
    for name, tool in tools.items():
        tool.fn_metadata = tool.fn_metadata.model_copy(
            update={"output_schema": published(models[name])})
        _JUDGES[name] = judged(models[name])


def check(name: str, reply: dict[str, Any]) -> None:
    """`reply` as the wire carries it (a tuple is a list there) against the model `name`
    declared, strictly: a field it does not name or a value of another type raises. A name
    nothing declared (a test's own probe) is not judged."""
    judge = _JUDGES.get(name)
    if judge is not None:
        judge.validate_python(_as_on_the_wire(reply))


def _as_on_the_wire(value: Any) -> Any:
    """`value` with every tuple a list, as JSON carries it; walked here rather than through
    `json`, whose functions a test may have replaced."""
    if isinstance(value, dict):
        return {k: _as_on_the_wire(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_as_on_the_wire(v) for v in value]
    return value
