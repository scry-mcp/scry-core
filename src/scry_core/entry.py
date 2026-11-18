"""One tool's entry on its family's page, in the one order every entry has: what it does, its
signature, an example to try, its modes, arguments, what comes back, what it refuses, why it
works this way, the tools beside it, and the contract the client receives, folded.

Each part sits under its own third-level heading, so a page built from this one can list them.
The registry gives the signature, the types and the contract; the server's `asks.json` gives
every sentence (`scry_core.asks`).
"""

from __future__ import annotations

import json
import re
import types
from collections.abc import Callable, Iterable, Mapping
from typing import (
    Annotated,
    Any,
    Literal,
    NotRequired,
    Required,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from mcp.server.mcpserver.tools import Tool

from scry_core import demo
from scry_core import example as shape
from scry_core.asks import Ask, Modes
from scry_core.reply_schema import own_fields

TRY, ARGUMENTS, RETURNS = "### Try it", "### Arguments", "### What comes back"
REFUSES, WHY, RELATED = "### What it refuses", "### Why it works this way", "### Related tools"
#: The fold `reply_differences` reads each tool's fields from, and one field's line in it.
FIELDS_FOLD = re.compile(r"<details><summary>All \d+ reply fields</summary>")
FIELD_LINE = re.compile(r"- `([^`]+)` \(")
NO_OWN_FIELDS = "The reply carries only the fields every reply has."
CONTRACT = "The contract your client receives"
#: What a transcript writes for a value that differs between two honest runs.
HIDDEN_MARKS = (demo.VOLATILE_MARK, demo.HOST_MARK)
_COUNTS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve")

_PLAIN = {str: "string", int: "integer", float: "number", bool: "boolean",
          type(None): "null", Any: "any"}


def _one_of(values: Iterable[Any]) -> str:
    return "one of " + ", ".join(f"`{json.dumps(v)}`" for v in values)


def _either(phrases: Iterable[str]) -> str:
    """Alternatives joined, each named once: `dict[str, str] | dict[str, int]` is one object."""
    return " or ".join(dict.fromkeys(phrases))


def _array_of(item: str | None) -> str:
    return f"array of {item}" if item else "array"


def reply_type(hint: Any) -> str:
    """A reply field's Python type, as a phrase in JSON's names."""
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Required, NotRequired, Annotated):
        return reply_type(args[0])
    if origin is Literal:
        return _one_of(args)
    if origin in (Union, types.UnionType):
        return _either(reply_type(a) for a in args)
    if origin in (list, tuple):
        return _array_of(None if not args or args[0] is Any else reply_type(args[0]))
    if origin is dict or hint is dict or is_typeddict(hint):
        return "object"
    return _PLAIN.get(hint, getattr(hint, "__name__", str(hint)))


def argument_type(spec: Mapping[str, Any]) -> str:
    """An argument's JSON schema as a phrase: its type, its words, its bounds."""
    if "anyOf" in spec:
        text = _either(argument_type(s) for s in spec["anyOf"])
    elif "enum" in spec:
        text = _one_of(spec["enum"])
    elif "const" in spec:
        text = f"`{json.dumps(spec['const'])}`"
    elif spec.get("type") == "array":
        text = _array_of(argument_type(spec["items"]) if spec.get("items") else None)
    else:
        text = spec.get("type", "any")
    bounds = [f"{word} {spec[key]}" for key, word in (
        ("minimum", ">="), ("exclusiveMinimum", ">"), ("maximum", "<="),
        ("exclusiveMaximum", "<")) if key in spec]
    if "pattern" in spec:
        bounds.append(f"matching `{spec['pattern']}`")
    return f"{text} ({', '.join(bounds)})" if bounds else text


def field_line(name: str, hint: Any) -> str:
    """A reply field and its type, as a list names it."""
    return f"- `{name}` ({reply_type(hint)})"


def in_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def signature(tool: Tool) -> str:
    props = tool.parameters.get("properties", {})
    return f"{tool.name}(" + ", ".join(
        name if "default" not in spec else f"{name}={json.dumps(spec['default'])}"
        for name, spec in props.items()) + ")"


def _pair(tool: str, call: Mapping[str, Any], reply: Mapping[str, Any], fields: Iterable[str]
          ) -> list[str]:
    """A call and the excerpt of its reply; `ValueError` when the excerpt shows a hidden value."""
    fields = list(fields)
    if hidden := [mark for mark in HIDDEN_MARKS if mark in shape.excerpt(reply, fields)]:
        raise ValueError(f"the excerpt of {fields} shows {', '.join(hidden)}, which stands for "
                         "a value the run hides: show fields that read the same every run")
    return shape.answered(tool, call, reply, fields)


def example_lines(tool: str, ask: Ask, example: Mapping[str, Any]) -> list[str]:
    """The example in its one shape: where it can be tried, the ask, the call, an excerpt of the
    reply, how to read it and the reply whole, folded; a second call when the first one's point
    is what a later call answers. `ValueError` when the excerpt names what a reply does not
    carry."""
    lines = [ask.on, "", *shape.asked(ask.ask), "",
             *_pair(tool, example["call"], example["reply"], ask.shows)]
    then, second = ask.then, example.get("then")
    if then is not None and second is not None:
        lines += ["", then.lead, "", *_pair(then.tool, second["call"], second["reply"],
                                            then.shows)]
        whole = shape.folded("The two replies, whole",
                             "The first call's:", shape.fenced(dict(example["reply"])),
                             "The second call's:", shape.fenced(dict(second["reply"])))
    else:
        whole = shape.folded("The whole reply", shape.fenced(dict(example["reply"])))
    return [*lines, "", ask.reads, "", *whole]


def _modes(modes: Modes) -> list[str]:
    count = _COUNTS[len(modes.rows)] if len(modes.rows) < len(_COUNTS) else str(len(modes.rows))
    return [f"### The {count} {modes.argument}s", "",
            "| " + " | ".join(modes.head) + " |", "|" + "---|" * len(modes.head),
            *("| " + " | ".join(in_cell(c) for c in row) + " |" for row in modes.rows)]


def _taken(spec: Mapping[str, Any], required: bool) -> str:
    """An argument's type and whether a call must give it: `required`, `optional` for one that
    is left out by default, else its default."""
    if required:
        return f"{argument_type(spec)}, required"
    if spec.get("default") is None:
        given = [s for s in spec.get("anyOf", ()) if s.get("type") != "null"]
        return f"{argument_type({**spec, 'anyOf': given} if given else spec)}, optional"
    return f"{argument_type(spec)}, default `{json.dumps(spec['default'])}`"


def _arguments(tool: Tool, ask: Ask) -> list[str]:
    props: dict[str, Any] = tool.parameters.get("properties", {})
    if not props:
        return ["Takes no argument."]
    required = set(tool.parameters.get("required", ()))
    return [f"- `{name}` ({_taken(spec, name in required)}): {ask.arguments.get(name, '')}"
            for name, spec in props.items()]


def _returns(model: type, envelope: type, ask: Ask) -> list[str]:
    own = own_fields(model, envelope)
    lines = [f"- `{name}`: {text}" for name, text in ask.returns.items()]
    if not own:
        return [*lines, *([""] if lines else []), NO_OWN_FIELDS]
    hints = get_type_hints(model, include_extras=True)
    return [*lines, "", *shape.folded(
        f"All {len(own)} reply fields", "\n".join(field_line(n, hints[n]) for n in own))]


def _contract(tool: Tool) -> list[str]:
    """The tool's description and its arguments' own, as the client receives them: text, in a
    fence longer than any the description opens."""
    props: dict[str, Any] = tool.parameters.get("properties", {})
    notes = [f"{n}: {' '.join(s['description'].split())}"
             for n, s in props.items() if "description" in s]
    text = "\n\n".join([(tool.description or "").strip(), *notes])
    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
    return shape.folded(CONTRACT, f"{fence}text\n{text}\n{fence}")


def tool_block(tool: Tool, model: type, envelope: type, ask: Ask,
               example: Mapping[str, Any] | None, link: Callable[[str], str]) -> str:
    """One tool's generated block; `link` gives the address of another tool's entry."""
    lines = [f"## `{tool.name}`", "", ask.what, "", "```text", signature(tool), "```", "", TRY, ""]
    lines += (example_lines(tool.name, ask, example) if example is not None
              else [ask.on, "", *shape.asked(ask.ask), "",
                    "No reply to show yet: a run gives it."])
    if ask.modes is not None:
        lines += ["", *_modes(ask.modes)]
    lines += ["", ARGUMENTS, "", *_arguments(tool, ask), "", RETURNS, "",
              *_returns(model, envelope, ask)]
    if ask.refuses:
        lines += ["", REFUSES, "", *(f"- {line}" for line in ask.refuses)]
    if ask.why:
        lines += ["", WHY, "", *"\n\n".join(ask.why).split("\n")]
        if ask.why_more:
            lines += ["", "<details><summary>More on why</summary>", "",
                      *"\n\n".join(ask.why_more).split("\n"), "", "</details>"]
    if ask.related:
        lines += ["", RELATED, "", *(f"- [`{name}`]({link(name)})" for name in ask.related)]
    return "\n".join([*lines, "", *_contract(tool)])
