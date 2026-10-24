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
model carries no output schema, and a reply reaches it as its structured content. So what a model
reads of a reply is the description's `Reply` paragraph, and each server's battery holds the names
that paragraph gives to the model (`reply_sentence_names`, `unmodelled`): a sentence that promised
a field no reply can carry would be believed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, Required, get_args, get_type_hints

from mcp.server.mcpserver import MCPServer
from pydantic import ConfigDict, TypeAdapter
from typing_extensions import TypedDict

from scry_core import reply_contract as contract
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


def model_gap(tools: Iterable[str], models: Mapping[str, type]) -> str:
    """How the tools and their reply models fail to pair, in one sentence, or empty."""
    names = set(tools)
    if missing := sorted(names - models.keys()):
        return f"tools with no reply model: {missing}"
    if stray := sorted(models.keys() - names):
        return f"reply models with no tool: {stray}"
    return ""


def declare(server: MCPServer, models: Mapping[str, type]) -> None:
    """Publish each registered tool's model as its `outputSchema` and keep it for `check`. A tool
    with no model, or a model with no tool, is the server's bug, a `ValueError`: one would answer
    a shape nobody declared, the other declare a shape nobody answers."""
    tools = {t.name: t for t in registered(server)}
    if gap := model_gap(tools, models):
        raise ValueError(gap)
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


#: Where a `Reply` paragraph begins: the word, what qualifies it on its line (`(on a stop)`,
#: `, at the top`), and the colon that ends that.
_REPLY = re.compile(r"\bReply\b[^:\n]*:")


def reply_sentence_names(doc: str) -> list[str]:
    """The fields a docstring's `Reply` paragraphs name at their top level: each backticked
    identifier outside any parenthesis, and outside the list a colon opens until its sentence
    ends (inside either is a field's own part, a row's, or a value), in order. A paragraph opens
    however a docstring writes it (`Reply:`, `Reply (on a stop):`, `Reply, at the top:`), and a
    docstring with several (one per mode) has each read. Empty when it has none."""
    names: list[str] = []
    for found in _REPLY.finditer(doc):
        # AN OPENING THAT NAMES A FIELD (`Reply, per channel in `measures`:`) names the one the
        # list after its colon belongs to: that field is top level, the list its parts.
        opened = _top_level(doc[found.start() + len("Reply"):found.end() - 1])
        text = doc[found.end():]
        end = text.find("\n\n")
        words = opened + _top_level(text if end < 0 else text[:end], listing=bool(opened))
        for word in words:
            if word not in names:
                names.append(word)
    return names


def _top_level(text: str, listing: bool = False) -> list[str]:
    """The backticked identifiers of `text` outside a parenthesis and outside a colon's list
    (`listing` when `text` begins inside one)."""
    names: list[str] = []
    depth, i = 0, 0
    while i < len(text):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(depth - 1, 0)
        elif depth == 0 and c == ":":
            listing = True
        elif depth == 0 and c in ".;" and text[i + 1:i + 2] in ("", " ", "\n"):
            listing = False
        elif c == "`":
            close = text.find("`", i + 1)
            if close < 0:
                break
            word = text[i + 1:close]
            if depth == 0 and not listing and word.isidentifier():
                names.append(word)
            i = close
        i += 1
    return names


def own_fields(model: type, envelope: type = ReplyEnvelope) -> list[str]:
    """The fields `model` adds to `envelope`, the one every reply carries unless named."""
    shared = set(_fields(envelope))
    return [f for f in _fields(model) if f not in shared]


def unmodelled(doc: str, model: type, not_fields: Iterable[str] = ()) -> list[str]:
    """The names a docstring's `Reply:` paragraph gives at its top level that `model` does not
    hold: a sentence promising a field the reply cannot carry. The paragraph also names what is
    no field, and those are left out: a refusal's code, a verdict, and `not_fields` (the server's
    tools, the tool's own arguments, and the values it quotes)."""
    held = set(_fields(model))
    other = set(contract.CODES) | set(get_args(contract.Verdict)) | set(not_fields)
    return [n for n in reply_sentence_names(doc) if n not in held and n not in other]


def sentence_faults(tools: Iterable[Any], models: Mapping[str, type],
                    words: Mapping[str, Iterable[str]]) -> dict[str, Any]:
    """What a server's battery holds its descriptions to, by tool: a field a `Reply` paragraph
    names that the tool's model lacks, a model with fields of its own whose description names
    none, and an allowed word (`words`, the tool's quoted values, commands and row fields) the
    description no longer quotes. `tools` as `list_tools()` answers them. Empty when all hold."""
    tools = list(tools)
    names = {t.name for t in tools}
    wrong: dict[str, Any] = {}
    for t in tools:
        doc, model = t.description or "", models[t.name]
        allowed = set(words.get(t.name, ()))
        said = reply_sentence_names(doc)
        if not said and own_fields(model):
            wrong[t.name] = "its description names no field of its reply"
        elif miss := unmodelled(doc, model,
                                names | set(t.input_schema.get("properties", {})) | allowed):
            wrong[t.name] = miss
        elif unused := sorted(allowed - set(said)):
            wrong[t.name] = f"allowed and no longer quoted: {unused}"
    return wrong


def stop_fields_lacking(tools: Iterable[Any], models: Mapping[str, type],
                        stop_fields: str) -> dict[str, list[str]]:
    """The stop's fields a server's descriptions quote through one text (`stop_fields`, "the
    stop: `a`, `b`..."), held to the model of every tool that quotes it: the names each lacks.
    INVALID-shaped (a `ValueError`) when the text names fewer than two fields or no tool quotes
    it, so an empty answer is never a check that examined nothing."""
    fields = reply_sentence_names("Reply: " + stop_fields.split(":", 1)[1])
    quoting = [t for t in tools if stop_fields in (t.description or "")]
    if len(fields) < 2 or not quoting:
        raise ValueError(f"the stop's text names {fields} and {len(quoting)} tool(s) quote it: "
                         "nothing would be examined")
    return {t.name: lacks for t in quoting
            if (lacks := sorted(set(fields) - set(own_fields(models[t.name]))))}
