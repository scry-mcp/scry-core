"""The hand-written half of a server's reference: `docs/reference/asks.json`, with for each tool
what it does for a person, the example's ask and how to read its reply, a sentence per argument
and per field worth acting on, what it refuses, why it works as it does and the tools beside it.

The registry gives everything a program can know (names, types, defaults, the contract); this
file gives each sentence a person reads. `faults` holds it to the registry and to the limits a
page keeps, so a sentence past its limit or about an argument the tool lost is drift.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_type_hints

from mcp.server.mcpserver.tools import Tool

from scry_core import example
from scry_core.strict_arguments import refused
from scry_core.verdict import Invalid

ASKS_PATH = "docs/reference/asks.json"

SENTENCE_WORDS = 30
WHAT_WORDS = 25
FAMILY_WORDS = 25
ON_WORDS, ON_SENTENCES = 40, 2
LEAD_WORDS = 20
#: A line of a list: an argument, a returned field, a refusal.
LINE_WORDS, LINE_SENTENCES = 30, 2
RETURNS_MAX = 6
WHY_SHOWN = 3
WHY_WORDS, WHY_SENTENCES = 80, 4
MODE_COLUMNS, MODE_ROWS = 3, 12
RELATED_MAX = 6

_TOOL_KEYS = frozenset({"what", "ask", "on", "call", "shows", "reads", "then", "modes",
                        "arguments", "returns", "refuses", "why", "why_more", "related"})
_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def words(text: str) -> int:
    """The words of `text` as a reader counts them: a code span is one, a link its label."""
    return len(_LINK.sub(r"\1", _CODE.sub("code", text)).split())


def sentences(text: str) -> list[str]:
    """The sentences of `text`; a full stop inside a code span ends none."""
    held: list[str] = []

    def keep(match: re.Match[str]) -> str:
        held.append(match[0])
        return f"\x00{len(held) - 1}\x00"

    parts = re.split(r"(?<=[.?!])\s+", _CODE.sub(keep, text.strip()))
    return [re.sub(r"\x00(\d+)\x00", lambda m: held[int(m[1])], p) for p in parts if p]


@dataclass(frozen=True)
class Then:
    """An example's second call: `lead` introduces it, and it is a call the same run made
    later, whose reply is what the first call was for."""

    lead: str
    tool: str
    call: Mapping[str, Any]
    shows: tuple[str, ...]


@dataclass(frozen=True)
class Modes:
    """The table of the values `argument` takes: `head` names its columns, each row opens with
    one value."""

    argument: str
    head: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Ask:
    """One tool's sentences, as `asks.json` holds them."""

    what: str
    ask: str
    on: str
    call: Mapping[str, Any]
    shows: tuple[str, ...]
    reads: str
    arguments: Mapping[str, str]
    returns: Mapping[str, str]
    refuses: tuple[str, ...]
    why: tuple[str, ...]
    why_more: tuple[str, ...]
    related: tuple[str, ...]
    then: Then | None = None
    modes: Modes | None = None


@dataclass(frozen=True)
class Asks:
    """`families` is each family's one line; `tools` each tool's `Ask`; `odd` what the file
    holds that is no such thing, one finding a line."""

    families: Mapping[str, str]
    tools: Mapping[str, Ask]
    odd: tuple[str, ...] = ()


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(v for v in value if isinstance(v, str)) if isinstance(value, list) else ()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _then(value: Any) -> Then | None:
    if not isinstance(value, dict):
        return None
    return Then(str(value.get("lead", "")), str(value.get("tool", "")),
                _mapping(value.get("call")), _strings(value.get("shows")))


def _modes(value: Any) -> Modes | None:
    if not isinstance(value, dict):
        return None
    rows = value.get("rows")
    return Modes(str(value.get("argument", "")), _strings(value.get("head")),
                 tuple(_strings(r) for r in rows) if isinstance(rows, list) else ())


def _ask(entry: Mapping[str, Any]) -> Ask:
    return Ask(
        what=str(entry.get("what", "")), ask=str(entry.get("ask", "")),
        on=str(entry.get("on", "")), call=_mapping(entry.get("call")),
        shows=_strings(entry.get("shows")), reads=str(entry.get("reads", "")),
        arguments={k: str(v) for k, v in _mapping(entry.get("arguments")).items()},
        returns={k: str(v) for k, v in _mapping(entry.get("returns")).items()},
        refuses=_strings(entry.get("refuses")), why=_strings(entry.get("why")),
        why_more=_strings(entry.get("why_more")), related=_strings(entry.get("related")),
        then=_then(entry.get("then")), modes=_modes(entry.get("modes")))


def load(root: Path) -> Asks:
    """The asks of the repository at `root`; none when the file is not there. `Invalid` when it
    cannot be read as an object of `families` and `tools`."""
    path = root / ASKS_PATH
    if not path.is_file():
        return Asks({}, {})
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Invalid(f"{ASKS_PATH} cannot be read: {e}") from e
    if not isinstance(held, dict) or not isinstance(held.get("tools"), dict) \
            or not isinstance(held.get("families", {}), dict):
        raise Invalid(f"{ASKS_PATH} is not an object holding `families` and `tools`, each an "
                      "object by name")
    odd = [f"{ASKS_PATH}: `{k}` is no part of it: it holds `families` and `tools`"
           for k in sorted(set(held) - {"families", "tools"})]
    tools = {}
    for name, entry in held["tools"].items():
        if not isinstance(entry, dict):
            odd.append(f"{ASKS_PATH}: `{name}` holds a {type(entry).__name__}, not an object")
            continue
        odd += [f"{ASKS_PATH}: `{name}` has `{k}`, which no entry takes"
                for k in sorted(set(entry) - _TOOL_KEYS)]
        tools[name] = _ask(entry)
    families = {k: str(v) for k, v in held.get("families", {}).items()}
    return Asks(families, tools, tuple(odd))


def _within(where: str, text: str, limit: int, most: int = 1) -> list[str]:
    """What `text` breaks: empty, over `limit` words or `most` sentences, a sentence too long."""
    if not text.strip():
        return [f"{where} is empty"]
    found = []
    said = sentences(text)
    if words(text) > limit or len(said) > most:
        found.append(f"{where} is {words(text)} words in {len(said)} sentences, and it takes "
                     f"at most {limit} in {most}")
    found += [f"{where} has a sentence of {words(s)} words, and a sentence takes at most "
              f"{SENTENCE_WORDS}" for s in said if words(s) > SENTENCE_WORDS]
    return found


def _example_faults(name: str, ask: Ask, tools: Mapping[str, Tool]) -> list[str]:
    found = []
    try:
        example.checked(f"`{name}`", ask.ask, ask.reads)
    except ValueError as e:
        found.append(str(e))
    found += _within(f"`{name}`: `on`", ask.on, ON_WORDS, ON_SENTENCES)
    if why := refused(tools[name], dict(ask.call)):
        found.append(f"`{name}`: `call` is one the tool refuses ({why})")
    if not ask.shows:
        found.append(f"`{name}`: `shows` names no field of the reply to show")
    if (then := ask.then) is not None:
        found += _within(f"`{name}`: `then.lead`", then.lead, LEAD_WORDS)
        if then.tool not in tools:
            found.append(f"`{name}`: `then.tool` is `{then.tool}`, which is no tool")
        elif why := refused(tools[then.tool], dict(then.call)):
            found.append(f"`{name}`: `then.call` is one `{then.tool}` refuses ({why})")
        if not then.shows:
            found.append(f"`{name}`: `then.shows` names no field of the reply to show")
    return found


def _modes_faults(name: str, modes: Modes, properties: Mapping[str, Any]) -> list[str]:
    where = f"`{name}`: `modes`"
    values = _enum(properties.get(modes.argument, {}))
    if not values:
        return [f"{where} is on `{modes.argument}`, which is no argument with named values"]
    found = []
    if not 2 <= len(modes.head) <= MODE_COLUMNS:
        found.append(f"{where} has {len(modes.head)} columns, and a table takes 2 to "
                     f"{MODE_COLUMNS}")
    if len(modes.rows) > MODE_ROWS:
        found.append(f"{where} has {len(modes.rows)} rows, and a table takes at most {MODE_ROWS}")
    if ragged := [r[0] if r else "" for r in modes.rows if len(r) != len(modes.head)]:
        found.append(f"{where}: the rows of {ragged} do not have its {len(modes.head)} columns")
    listed = [r[0].strip("`") for r in modes.rows if r]
    if sorted(listed) != sorted(values):
        found.append(f"{where} lists {listed}, and `{modes.argument}` takes {values}")
    for row in modes.rows:
        for cell in row[1:]:
            found += _within(f"{where}, the row of {row[0]}", cell, LINE_WORDS, LINE_SENTENCES)
    return found


def _enum(spec: Mapping[str, Any]) -> list[str]:
    """The named values an argument's schema takes, a null alternative left out."""
    if "enum" in spec:
        return [str(v) for v in spec["enum"]]
    return [v for alternative in spec.get("anyOf", ()) for v in _enum(alternative)]


def _why_faults(name: str, ask: Ask) -> list[str]:
    """What the why breaks: the paragraphs an entry shows, then the folded blocks, which may
    also be a list, a table or code."""
    where = f"`{name}`: why"
    found = []
    if len(ask.why) > WHY_SHOWN:
        found.append(f"`{name}`: `why` has {len(ask.why)} paragraphs, and an entry shows at "
                     f"most {WHY_SHOWN}: the rest goes in `why_more`")
    for i, text in enumerate((*ask.why, *ask.why_more), 1):
        block = text.strip()
        if not block.startswith(("- ", "|", "```")):
            found += _within(f"{where}, paragraph {i}", text, WHY_WORDS, WHY_SENTENCES)
        elif i <= len(ask.why):
            found.append(f"{where}, block {i} is a list, a table or code, which an entry shows "
                         "only folded: it goes in `why_more`")
        elif block.startswith("```"):
            if block.count("```") != 2 or not block.endswith("```"):
                found.append(f"{where}, block {i} opens a code block it never closes")
        elif block.startswith("|"):
            columns = max(row.replace("\\|", "").strip().strip("|").count("|") + 1
                          for row in block.splitlines())
            if columns > MODE_COLUMNS:
                found.append(f"{where}, block {i} is a table of {columns} columns, and a table "
                             f"takes at most {MODE_COLUMNS}")
        else:
            for k, item in enumerate(re.split(r"\n(?=- )", block), 1):
                found += _within(f"{where}, item {k} of block {i}", item[2:], LINE_WORDS,
                                 LINE_SENTENCES)
    return found


def _tool_faults(name: str, ask: Ask, tools: Mapping[str, Tool], model: type,
                 own: Sequence[str]) -> list[str]:
    found = _within(f"`{name}`: `what`", ask.what, WHAT_WORDS)
    found += _example_faults(name, ask, tools)
    properties: Mapping[str, Any] = tools[name].parameters.get("properties", {})
    if sorted(ask.arguments) != sorted(properties):
        found.append(f"`{name}`: `arguments` has a sentence for {sorted(ask.arguments)}, and "
                     f"the tool takes {sorted(properties)}")
    for argument, text in ask.arguments.items():
        found += _within(f"`{name}`: the argument `{argument}`", text, LINE_WORDS,
                         LINE_SENTENCES)
    fields = set(get_type_hints(model, include_extras=True))
    if stray := sorted(set(ask.returns) - fields):
        found.append(f"`{name}`: `returns` names {stray}, which its reply model does not")
    if not (bool(own) <= bool(ask.returns)) or len(ask.returns) > RETURNS_MAX:
        found.append(f"`{name}`: `returns` has {len(ask.returns)} fields, and it takes 1 to "
                     f"{RETURNS_MAX} of a reply that has fields of its own")
    for field, text in ask.returns.items():
        found += _within(f"`{name}`: the field `{field}`", text, LINE_WORDS, LINE_SENTENCES)
    for i, text in enumerate(ask.refuses, 1):
        found += _within(f"`{name}`: refusal {i}", text, LINE_WORDS, LINE_SENTENCES)
    found += _why_faults(name, ask)
    if ask.modes is not None:
        found += _modes_faults(name, ask.modes, properties)
    related = list(ask.related)
    if stray := [r for r in related if r not in tools or r == name]:
        found.append(f"`{name}`: `related` names {stray}, each of which is not another tool")
    if len(set(related)) != len(related) or len(related) > RELATED_MAX:
        found.append(f"`{name}`: `related` names {len(related)} tools, and it takes at most "
                     f"{RELATED_MAX}, each once")
    return found


def faults(asks: Asks, tools: Mapping[str, Tool], models: Mapping[str, type],
           own: Mapping[str, Sequence[str]], families: Iterable[str]) -> list[str]:
    """Each way `asks` departs from the registry and from a page's limits, one finding a line;
    `own` is each tool's reply fields beyond the ones every reply carries."""
    found = list(asks.odd)
    families = list(families)
    found += [f"{ASKS_PATH}: the family {f} has no line saying what it holds"
              for f in families if f not in asks.families]
    found += [f"{ASKS_PATH}: `{f}` is no family of the roster"
              for f in sorted(set(asks.families) - set(families))]
    for family, line in asks.families.items():
        found += _within(f"the family {family}'s line", line, FAMILY_WORDS)
    found += [f"`{n}` has no entry in {ASKS_PATH}" for n in sorted(set(tools) - set(asks.tools))]
    for name, ask in sorted(asks.tools.items()):
        if name not in tools:
            found.append(f"{ASKS_PATH}: `{name}` is no tool")
        else:
            found += _tool_faults(name, ask, tools, models[name], own[name])
    return found
