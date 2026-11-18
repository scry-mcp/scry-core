"""An example as every public page shows it: what a person asks, the call, an excerpt of the
real reply, how to read it, and the whole reply folded.

A call is cut to fit its lines, so a page may not print the call a client makes: the ask is what
a person pastes, and the whole call is in the run's transcript.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ASK_WORDS = 25
READS_WORDS = 40
READS_SENTENCES = 2
#: The lines a call and a reply excerpt may take, and the columns of each.
CALL_LINES = 3
REPLY_LINES = 12
COLUMNS = 100

ABRIDGED_ITEMS = 6
ABRIDGED_CHARS = 240
#: The lengths an excerpt's strings are cut to, tried in turn until every line fits.
STRING_CUTS = (ABRIDGED_CHARS, 160, 120, 90, 60, 40, 24)
#: What stands for the part of a value a call's line has no room for.
ELIDED = "…"
#: Characters of a long string a call keeps at each end.
CALL_STRING_ENDS = 16
ONE_LINE_MAX = 100
#: The room a list's own key and indent take on its line, when a list is fitted to columns.
ONE_LINE_KEY = 24


def words(text: str) -> int:
    return len(text.split())


def sentences(text: str) -> int:
    return len([part for part in re.split(r"(?<=[.?!])\s+", text.strip()) if part])


def abridged(value: Any, chars: int = ABRIDGED_CHARS, items: int = ABRIDGED_ITEMS) -> Any:
    """`value` cut to its shape: a long list's first `items` then `... N more`, a long string's
    head."""
    if isinstance(value, dict):
        return {k: abridged(v, chars, items) for k, v in value.items()}
    if isinstance(value, list | tuple):
        kept = [abridged(v, chars, items) for v in value[:items]]
        return kept + ([f"... {len(value) - items} more"] if len(value) > items else [])
    if isinstance(value, str) and len(value) > chars:
        return f"{value[:chars]} ... ({len(value)} characters)"
    return value


def _flat(value: dict[str, Any]) -> bool:
    """Whether every value is a scalar or a list of scalars."""
    def scalar(v: Any) -> bool:
        return isinstance(v, (str, int, float, bool)) or v is None
    return all(scalar(v) or (isinstance(v, list) and all(scalar(x) for x in v))
               for v in value.values())


def compact(value: Any, depth: int = 0, columns: int = 0) -> str:
    """`value` as indented JSON with a list of scalars on one line: a rect or a point is one
    thought, and a column of numbers is most of a big reply's bytes. With `columns`, a list
    whose line would pass them is a column instead."""
    pad = "  " * (depth + 1)
    if depth and isinstance(value, dict) and value and _flat(value):
        line = json.dumps(value, ensure_ascii=False)
        if len(line) <= ONE_LINE_MAX:
            return line
    if isinstance(value, dict) and value:
        rows = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {compact(v, depth + 1, columns)}"
                for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + "\n" + "  " * depth + "}"
    line = json.dumps(value, ensure_ascii=False)
    if isinstance(value, list) and value and (
            not all(isinstance(v, (str, int, float, bool)) or v is None for v in value)
            or 0 < columns < len(line) + ONE_LINE_KEY):
        rows = [pad + compact(v, depth + 1, columns) for v in value]
        return "[\n" + ",\n".join(rows) + "\n" + "  " * depth + "]"
    return line


def fenced(value: Any) -> str:
    """`value` as a JSON code block."""
    return "```json\n" + compact(value) + "\n```"


def _short(value: Any) -> Any:
    """`value` as a call's line has room for it: a long string's two ends, a list's first item
    and how many follow, an object's keys with their values cut the same way."""
    if isinstance(value, str) and len(value) > 2 * CALL_STRING_ENDS + len(ELIDED):
        return value[:CALL_STRING_ENDS] + ELIDED + value[-CALL_STRING_ENDS:]
    if isinstance(value, dict):
        return {k: _short(v) for k, v in value.items()}
    if isinstance(value, list | tuple) and len(value) > 1 and not all(
            isinstance(v, (int, float, bool)) for v in value):
        return [_short(value[0]), f"{ELIDED} {len(value) - 1} more"]
    if isinstance(value, list | tuple):
        return [_short(v) for v in value]
    return value


def _counted(value: Any) -> str:
    """What stands for a value no line has room for: how many items or keys it holds."""
    if isinstance(value, list | tuple):
        return f"[{ELIDED} {len(value)} item{'s' * (len(value) != 1)}]"
    if isinstance(value, dict):
        return f"{{{ELIDED} {len(value)} key{'s' * (len(value) != 1)}}}"
    return ELIDED


def _wrapped(tool: str, parts: Sequence[str]) -> list[str]:
    """`tool(parts)` broken between arguments where a line fills."""
    lines, line = [], f"{tool}("
    for i, part in enumerate(parts):
        piece = part + (", " if i < len(parts) - 1 else ")")
        if len(line) + len(piece.rstrip()) > COLUMNS and line.strip():
            lines.append(line.rstrip())
            line = "    "
        line += piece
    return [*lines, line] if parts else [f"{tool}()"]


def call_text(tool: str, args: Mapping[str, Any], lines: int = CALL_LINES) -> str:
    """`tool(argument=value)` within `lines` lines of `COLUMNS` columns: whole when it fits,
    else its long values cut, else its last arguments counted and left out, else its argument
    names with what each holds counted, else the tool alone."""
    def parts(values: Mapping[str, Any]) -> list[str]:
        return [f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in values.items()]

    def fits(written: Sequence[str]) -> bool:
        return len(written) <= lines and all(len(line) <= COLUMNS for line in written)

    whole = _wrapped(tool, parts(args))
    if fits(whole):
        return "\n".join(whole)
    cut = {k: _short(v) for k, v in args.items()}
    for kept in range(len(cut), 0, -1):
        shown = parts(dict(list(cut.items())[:kept]))
        if kept < len(cut):
            shown.append(f"{ELIDED} {len(cut) - kept} more")
        written = _wrapped(tool, shown)
        if fits(written):
            return "\n".join(written)
    named = _wrapped(tool, [f"{k}={_counted(v)}" for k, v in args.items()])
    return "\n".join(named) if fits(named) else f"{tool}({ELIDED})"


def excerpt(reply: Mapping[str, Any], fields: Sequence[str]) -> str:
    """The `fields` of `reply` as JSON: a long string cut so its line stays within `COLUMNS`, a
    list kept as far as `REPLY_LINES` hold it. `ValueError` when a field is missing or the
    excerpt passes those lines with every list cut to `ABRIDGED_ITEMS`."""
    if lacking := [k for k in fields if k not in reply]:
        raise ValueError(f"the excerpt shows {lacking}, which the reply does not carry")
    picked = {k: reply[k] for k in fields}
    text = ""
    for items in range(REPLY_LINES, ABRIDGED_ITEMS - 1, -1):
        for chars in STRING_CUTS:
            text = compact(abridged(picked, chars, items), columns=COLUMNS)
            if all(len(line) <= COLUMNS for line in text.splitlines()):
                break
        else:
            raise ValueError(f"the excerpt of {list(fields)} has a line past {COLUMNS} columns "
                             "that no cut of its strings shortens: name other fields")
        if len(text.splitlines()) <= REPLY_LINES:
            return text
    raise ValueError(f"the excerpt of {list(fields)} is {len(text.splitlines())} lines, "
                     f"and a reply shows at most {REPLY_LINES}: name fewer fields")


@dataclass(frozen=True)
class Example:
    """One example: the `ask` a person types, the call, the reply it got, the `fields` of it the
    excerpt shows and the sentences that read them. `title` heads it on a page of several."""

    ask: str
    tool: str
    args: Mapping[str, Any]
    reply: Mapping[str, Any]
    fields: Sequence[str]
    reads: str
    title: str = ""


def checked(where: str, ask: str, reads: str) -> None:
    """`ValueError` naming `where` when an ask or its reading passes the limits a page holds."""
    if not ask.strip() or words(ask) > ASK_WORDS:
        raise ValueError(f"{where}: `ask` is {words(ask)} words, and an ask is 1 to {ASK_WORDS}")
    if not reads.strip() or words(reads) > READS_WORDS or sentences(reads) > READS_SENTENCES:
        raise ValueError(f"{where}: `reads` is {words(reads)} words in {sentences(reads)} "
                         f"sentences, and a reply is read in at most {READS_SENTENCES} sentences "
                         f"and {READS_WORDS} words")


def answer(reply: Mapping[str, Any], fields: Sequence[str]) -> str:
    """The `fields` of `reply` on one line, for an exchange a README opens with: one string
    said bare, anything else as JSON. `ValueError` when a field is missing or the line passes
    `COLUMNS`."""
    if lacking := [k for k in fields if k not in reply]:
        raise ValueError(f"the exchange answers with {lacking}, which the reply does not carry")
    only = reply[fields[0]] if len(fields) == 1 else None
    line = only if isinstance(only, str) else json.dumps({k: reply[k] for k in fields},
                                                         ensure_ascii=False)
    if len(line) > COLUMNS or "\n" in line:
        raise ValueError(f"the exchange's answer is {len(line)} characters on its one line, and "
                         f"a line holds {COLUMNS}: name other fields")
    return line


def render(example: Example, number: int = 0, whole: bool = True, level: int = 0) -> str:
    """The example in its one shape; `whole` adds the reply entire, folded. Its title is a
    heading of `level`, so a page's outline lists its examples, or bold when `level` is 0."""
    titled = f"{number}. {example.title}" if number else example.title
    head = f"{'#' * level} {titled}" if level else f"**{titled}**"
    parts = [head, ""] if example.title else []
    parts += ["Ask:", "", "> " + example.ask, "",
              "Call:", "", "```text", call_text(example.tool, example.args), "```", "",
              f"Reply, {len(example.fields)} of {len(example.reply)} fields:", "",
              "```json", excerpt(example.reply, example.fields), "```", "",
              example.reads]
    if whole:
        parts += ["", "<details><summary>The whole reply</summary>", "",
                  fenced(dict(example.reply)), "", "</details>"]
    return "\n".join(parts)
