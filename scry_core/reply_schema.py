"""Each tool's published `outputSchema` and the battery's strict check of every reply.

Each field is published as its value or `unavailable(why)`, and the fields an `ok` reply always
carries are required of it; `check` is the same judge, strict. The schema never reaches a model's
context, so `reply_sentence_names`, `unmodelled` and `conditions_unsaid` hold the description's
`Reply` paragraph to the model."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal, NotRequired, Required, get_args, get_origin, get_type_hints

from mcp.server.mcpserver import MCPServer
from pydantic import ConfigDict, TypeAdapter
from typing_extensions import TypedDict

from scry_core import reply_contract as contract
from scry_core.prose import counted
from scry_core.strict_arguments import registered


class ReplyEnvelope(TypedDict, total=False):
    """What every reply carries around its own fields."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    summary: str
    status: Required[Literal["ok", "INVALID"]]
    code: str
    message: str
    omitted: list[str]
    how: str
    note: str
    cancelled: dict[str, Any]
    session: dict[str, Any]


class Unavailable(TypedDict):
    """`reply_contract.unavailable(why)`, which any field may be in place of its value."""

    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    available: Literal[False]
    why: str


class MissingFields(ValueError):
    """An `ok` reply that leaves out fields its model requires."""


def _hints(model: type) -> dict[str, tuple[Any, bool]]:
    """Each field's hint without `Required`/`NotRequired`, and whether the field is required.

    Read from the hints as well as `__required_keys__`, which postponed annotations leave blind."""
    required = set(getattr(model, "__required_keys__", ()))
    out: dict[str, tuple[Any, bool]] = {}
    for name, hint in get_type_hints(model, include_extras=True).items():
        while get_origin(hint) in (Required, NotRequired):
            if get_origin(hint) is Required:
                required.add(name)
            else:
                required.discard(name)
            hint = get_args(hint)[0]
        out[name] = (hint, name in required)
    return out


def _metadata(hint: Any) -> tuple[Any, ...]:
    return tuple(getattr(hint, "__metadata__", ()))


def _values_or_unavailable(model: type) -> dict[str, Any]:
    """Each non-envelope field's hint widened with `Unavailable`."""
    envelope = _hints(ReplyEnvelope)
    return {name: hint if name in envelope else hint | Unavailable
            for name, (hint, _) in _hints(model).items()}


def own_required(model: type) -> frozenset[str]:
    """The fields `model` adds to the envelope that an `ok` reply always carries."""
    envelope = _hints(ReplyEnvelope)
    return frozenset(n for n, (_, required) in _hints(model).items()
                     if required and n not in envelope)


def judged(model: type) -> TypeAdapter[Any]:
    """The judge of `model`: each non-envelope field also takes `Unavailable`."""
    fields = _values_or_unavailable(model)
    fields["status"] = Required[fields["status"]]
    judge: Any = TypedDict(f"{model.__name__}Judged", fields, total=False)  # type: ignore[misc]
    setattr(judge, "__pydantic_config__", ConfigDict(extra="forbid", strict=True))  # noqa: B010
    return TypeAdapter(judge)


_JUDGES: dict[str, TypeAdapter[Any]] = {}
_OMIT_EMPTY: dict[str, frozenset[str]] = {}
_REQUIRED: dict[str, frozenset[str]] = {}


def omitted_when_empty(model: type) -> frozenset[str]:
    """The fields marked `OmitEmpty`; a required one is a `ValueError`."""
    hints = _hints(model)
    marked = {n for n, (h, _) in hints.items()
              if any(m is contract.OmitEmpty for m in _metadata(h))}
    if both := sorted(n for n in marked if hints[n][1]):
        raise ValueError(f"{model.__name__} requires {both}, which it marks OmitEmpty")
    return frozenset(marked)


def conditions(model: type) -> dict[str, contract.When]:
    """The `When` of each conditional field; a required one is a `ValueError`."""
    hints = _hints(model)
    found = {n: m for n, (h, _) in hints.items() for m in _metadata(h)
             if isinstance(m, contract.When)}
    if both := sorted(n for n in found if hints[n][1]):
        raise ValueError(f"{model.__name__} requires {both}, which it conditions with When")
    return found


def omit_empty(name: str, reply: dict[str, Any]) -> dict[str, Any]:
    """`reply` without the fields `name`'s model marks `OmitEmpty` whose value is empty."""
    marked = _OMIT_EMPTY.get(name)
    if not marked:
        return reply
    return {k: v for k, v in reply.items() if k not in marked or not contract.is_empty(v)}


def published(model: type) -> dict[str, Any]:
    """`model`'s schema as a client reads it: each field its value or `Unavailable`, and the
    required fields required of an `ok` reply (or named in its `omitted`)."""
    shape: Any = TypedDict(  # type: ignore[misc]
        f"{model.__name__}Published", _values_or_unavailable(model), total=False)
    schema: dict[str, Any] = TypeAdapter(shape).json_schema()
    schema["required"] = ["status"]
    if need := sorted(own_required(model)):
        schema["if"] = {"properties": {"status": {"const": "ok"}}, "required": ["status"]}
        schema["then"] = {"allOf": [
            {"anyOf": [{"required": [n]},
                       {"required": ["omitted"],
                        "properties": {"omitted": {"contains": {"const": n}}}}]}
            for n in need]}
    return schema


def _fields(model: type) -> list[str]:
    """Every field `model` declares, the envelope's included."""
    return list(TypeAdapter(model).json_schema()["properties"])


def model_gap(tools: Iterable[str], models: Mapping[str, type]) -> str:
    """How the tools and their reply models fail to pair, or empty."""
    names = set(tools)
    if missing := sorted(names - models.keys()):
        return f"tools with no reply model: {missing}"
    if stray := sorted(models.keys() - names):
        return f"reply models with no tool: {stray}"
    return ""


def declare(server: MCPServer, models: Mapping[str, type]) -> None:
    """Publish each tool's model as its `outputSchema`; a tool and model unpaired is a
    `ValueError`."""
    tools = {t.name: t for t in registered(server)}
    if gap := model_gap(tools, models):
        raise ValueError(gap)
    for name, tool in tools.items():
        _OMIT_EMPTY[name] = omitted_when_empty(models[name])
        conditions(models[name])
        _REQUIRED[name] = own_required(models[name])
        tool.fn_metadata = tool.fn_metadata.model_copy(
            update={"output_schema": published(models[name])})
        _JUDGES[name] = judged(models[name])


def check(name: str, reply: dict[str, Any]) -> None:
    """`reply` as the wire carries it against `name`'s model; an undeclared name is not judged.
    An `ok` reply missing a required field its `omitted` does not name is `MissingFields`."""
    judge = _JUDGES.get(name)
    if judge is None:
        return
    wire = _as_on_the_wire(reply)
    judge.validate_python(wire)
    if wire.get("status") != "ok":
        return
    gone = sorted(_REQUIRED.get(name, frozenset()) - wire.keys() - set(wire.get("omitted", ())))
    if gone:
        raise MissingFields(f"{name}'s ok reply omits {gone}, which its model requires")


def _as_on_the_wire(value: Any) -> Any:
    """`value` with every tuple a list; not via `json`, which a test may replace."""
    if isinstance(value, dict):
        return {k: _as_on_the_wire(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_as_on_the_wire(v) for v in value]
    return value


_REPLY = re.compile(r"\bReply\b[^:\n]*:")


def _paragraphs(doc: str) -> list[tuple[str, str]]:
    """Each `Reply` paragraph as what opens it before the colon and what follows."""
    out: list[tuple[str, str]] = []
    for found in _REPLY.finditer(doc):
        text = doc[found.end():]
        end = text.find("\n\n")
        out.append((doc[found.start() + len("Reply"):found.end() - 1],
                    text if end < 0 else text[:end]))
    return out


def reply_sentence_names(doc: str) -> list[str]:
    """The fields a docstring's `Reply` paragraphs name at top level: backticked identifiers
    outside parentheses and outside the list a colon opens."""
    names: list[str] = []
    for head, body in _paragraphs(doc):
        # `Reply, per channel in `measures`:` names the field the list after the colon belongs to
        opened = _top_level(head)
        for word in opened + _top_level(body, listing=bool(opened)):
            if word not in names:
                names.append(word)
    return names


def _top_level(text: str, listing: bool = False) -> list[str]:
    """The backticked identifiers of `text` outside parentheses and a colon's list."""
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
    """The fields `model` adds to `envelope`."""
    shared = set(_fields(envelope))
    return [f for f in _fields(model) if f not in shared]


def unmodelled(doc: str, model: type, not_fields: Iterable[str] = ()) -> list[str]:
    """The `Reply:` names that `model` does not hold, minus codes, verdicts and `not_fields`."""
    held = set(_fields(model))
    other = set(contract.CODES) | set(get_args(contract.Verdict)) | set(not_fields)
    return [n for n in reply_sentence_names(doc) if n not in held and n not in other]


def _said(words: str, text: str, own: str) -> bool:
    """Whether `words` stand in `text` as whole words, outside the backticked name `own`."""
    outside = text.replace(f"`{own}`", " ")
    return re.search(rf"(?<!\w){re.escape(' '.join(words.lower().split()))}(?!\w)",
                     outside) is not None


def conditions_unsaid(doc: str, model: type, not_fields: Iterable[str] = ()) -> list[str]:
    """The promised fields the model leaves optional without a condition (`When`; `OmitEmpty`
    is one by its nature), and those whose `When` words the blocks holding a `Reply` do not say
    as whole words, the field's own name not counting."""
    envelope = set(_hints(ReplyEnvelope))
    held, required = set(_fields(model)), own_required(model)
    skip = envelope | set(contract.CODES) | set(get_args(contract.Verdict)) | set(not_fields)
    marked, when = omitted_when_empty(model), conditions(model)
    said = " ".join(" ".join(block.split()) for block in doc.split("\n\n")
                    if _REPLY.search(block)).lower()
    faults: list[str] = []
    for n in reply_sentence_names(doc):
        if n in skip or n not in held or n in required or n in marked:
            continue
        if n not in when:
            faults.append(f"{n}: optional, so its condition is `When(...)` in the model")
        elif not all(_said(w, said, n.lower()) for w in when[n].words):
            faults.append(f"{n}: `{when[n]!r}` is not said in the Reply paragraph")
    return faults


def sentence_faults(tools: Iterable[Any], models: Mapping[str, type],
                    words: Mapping[str, Iterable[str]]) -> dict[str, Any]:
    """By tool, a description's fault: an unmodelled `Reply` field, none named, a stale allowed
    word, or an optional field with no stated condition."""
    tools = list(tools)
    names = {t.name for t in tools}
    wrong: dict[str, Any] = {}
    for t in tools:
        doc, model = t.description or "", models[t.name]
        allowed = set(words.get(t.name, ()))
        skip = names | set(t.input_schema.get("properties", {})) | allowed
        said = reply_sentence_names(doc)
        if not said and own_fields(model):
            wrong[t.name] = "its description names no field of its reply"
        elif miss := unmodelled(doc, model, skip):
            wrong[t.name] = miss
        elif unused := sorted(allowed - set(said)):
            wrong[t.name] = f"allowed and no longer quoted: {unused}"
        elif bare := conditions_unsaid(doc, model, set(t.input_schema.get("properties", {}))
                                       | allowed):
            wrong[t.name] = bare
    return wrong


def stop_fields_lacking(tools: Iterable[Any], models: Mapping[str, type],
                        stop_fields: str) -> dict[str, list[str]]:
    """The `stop_fields` names each quoting tool's model lacks; a `ValueError` if none is
    checked."""
    fields = reply_sentence_names("Reply: " + stop_fields.split(":", 1)[1])
    quoting = [t for t in tools if stop_fields in (t.description or "")]
    if len(fields) < 2 or not quoting:
        raise ValueError(f"the stop's text names {fields} and "
                         f"{counted(len(quoting), 'tool')} quote it: nothing would be examined")
    return {t.name: lacks for t in quoting
            if (lacks := sorted(set(fields) - set(own_fields(models[t.name]))))}
