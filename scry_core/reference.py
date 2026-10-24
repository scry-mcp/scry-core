"""A server's reference generated from its registry: per tool its call, every argument with its
type, default and bounds, the fields its reply adds, its description and an example a live run
made, on its family's page (`docs/reference/<family>.md`, the family's name in lower case with
dashes), and in `REFERENCE.md` the index of every family and tool and the envelope every reply
carries.

WHY GENERATED. An argument documented by hand falls behind the code the day the code moves, and
nobody sees it, because the page still reads well. So what the registry knows is read from it,
and each server's drift test holds the pages to it (`drift`), naming the tool whose block and
code disagree. The prose outside the markers is the hand-written why: a rewrite keeps every line
of it, each paragraph travelling with the block it follows.

WHY A PAGE PER FAMILY. A reader comes back for one tool, so the page they read holds its family
and no other; the families are the server's own roster (`scry_core.roster`).

WHY THE EXAMPLES COME FROM A TRANSCRIPT. An example typed by hand shows the reply its author
believed in. `examples_from` picks, per tool, a call a live run made and judged, and
`docs/reference/examples.json` holds the pick, rewritten only from a run.

    uv run python -m scry_core.reference <module>:<attribute> \
        [--examples JSONL ... [--mark PATH=TEXT ...]] [--write]

Run from the server's repository, where `<module>` imports. The attribute is the server's
`Registry`. `--examples` rewrites `examples.json` from those transcripts first (each `--mark`
spells a directory of the run's host, its scratch or its bench, as the text it names); then
`--write`
rewrites the pages, or, without it, the pages are compared. Exit codes: 0 the pages agree with
the registry (or were rewritten); 1 drift, one finding a line; 2 a usage error (a spec naming no
registry included); 3 INVALID, nothing was compared (a registry with no tool or a roster naming
one it lacks, a transcript or an `examples.json` that cannot be read, a transcript with no OK
cell of a tool of the server).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import types
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
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

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool

from scry_core import demo
from scry_core.reply_schema import model_gap, own_fields
from scry_core.roster import Roster
from scry_core.strict_arguments import registered
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

REFERENCE_PAGE = "REFERENCE.md"
PAGES_DIR = "docs/reference"
EXAMPLES_PATH = f"{PAGES_DIR}/examples.json"

#: The blocks `REFERENCE.md` holds, beside the tools' blocks the family pages hold.
INDEX_BLOCK, ENVELOPE_BLOCK = "index", "envelope"

#: Reply fields an example leaves out: the `session` block closes every reply alike, and
#: `REFERENCE.md` documents it once.
LEFT_OUT = frozenset({"session"})


def begin_marker(name: str) -> str:
    return f"<!-- scry-reference:begin {name} -->"


def end_marker(name: str) -> str:
    return f"<!-- scry-reference:end {name} -->"


_MARKER = re.compile(begin_marker("(?P<begin>\\S+)") + "|" + end_marker("(?P<end>\\S+)"))


@dataclass(frozen=True)
class Registry:
    """What a server's reference is generated from: its registered tools (`server`, after
    `strict_arguments`, whose schemas are the ones a client is shown), each one's reply model,
    its roster, its envelope (the fields any of its replies may carry, which `REFERENCE.md`
    lists once) and the repository it lives in."""

    server: MCPServer
    models: Mapping[str, type]
    roster: Roster
    envelope: type
    root: Path


def _page(family: str) -> str:
    return f"{PAGES_DIR}/{re.sub('[^a-z0-9]+', '-', family.lower()).strip('-')}.md"


# ======================================================================== rendering


_PLAIN = {str: "string", int: "integer", float: "number", bool: "boolean",
          type(None): "null", Any: "any"}


def _one_of(values: Iterable[Any]) -> str:
    return "one of " + ", ".join(f"`{json.dumps(v)}`" for v in values)


def _either(phrases: Iterable[str]) -> str:
    """Alternatives joined, each named once: `dict[str, str] | dict[str, int]` is one object."""
    return " or ".join(dict.fromkeys(phrases))


def _array_of(item: str | None) -> str:
    return f"array of {item}" if item else "array"


def _reply_type(hint: Any) -> str:
    """A reply field's Python type, as a phrase in JSON's names."""
    origin, args = get_origin(hint), get_args(hint)
    if origin in (Required, NotRequired, Annotated):
        return _reply_type(args[0])
    if origin is Literal:
        return _one_of(args)
    if origin in (Union, types.UnionType):
        return _either(_reply_type(a) for a in args)
    if origin in (list, tuple):
        return _array_of(None if not args or args[0] is Any else _reply_type(args[0]))
    if origin is dict or hint is dict or is_typeddict(hint):
        return "object"
    return _PLAIN.get(hint, getattr(hint, "__name__", str(hint)))


def _argument_type(spec: Mapping[str, Any]) -> str:
    """An argument's JSON schema as a phrase: its type, its words, its bounds."""
    if "anyOf" in spec:
        text = _either(_argument_type(s) for s in spec["anyOf"])
    elif "enum" in spec:
        text = _one_of(spec["enum"])
    elif "const" in spec:
        text = f"`{json.dumps(spec['const'])}`"
    elif spec.get("type") == "array":
        text = _array_of(_argument_type(spec["items"]) if spec.get("items") else None)
    else:
        text = spec.get("type", "any")
    bounds = [f"{word} {spec[key]}" for key, word in (
        ("minimum", ">="), ("exclusiveMinimum", ">"), ("maximum", "<="),
        ("exclusiveMaximum", "<")) if key in spec]
    if "pattern" in spec:
        bounds.append(f"matching `{spec['pattern']}`")
    return f"{text} ({', '.join(bounds)})" if bounds else text


def _in_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown_text(text: str) -> str:
    """A description as markdown shows it: a `<` outside a code span is text, not a tag, and a
    line the docstring indents is flush, since four spaces after a blank line would be read as a
    code block."""
    text = "\n".join(line.lstrip() for line in text.splitlines())
    parts = _CODE_SPAN.split(text)
    return "".join(p if i % 2 else p.replace("<", "&lt;") for i, p in enumerate(parts))


#: A code span, single or double backticks: what markdown shows as typed.
_CODE_SPAN = re.compile(r"(``.+?``|`[^`]+`)")


def _signature(tool: Tool) -> str:
    props = tool.parameters.get("properties", {})
    return f"{tool.name}(" + ", ".join(
        name if "default" not in spec else f"{name}={json.dumps(spec['default'])}"
        for name, spec in props.items()) + ")"


def _argument_table(tool: Tool) -> list[str]:
    props: dict[str, Any] = tool.parameters.get("properties", {})
    if not props:
        return ["Takes no argument."]
    required = set(tool.parameters.get("required", ()))
    lines = ["| argument | type | default |", "|---|---|---|"]
    for name, spec in props.items():
        default = "required" if name in required else f"`{json.dumps(spec.get('default'))}`"
        lines.append(f"| `{name}` | {_in_cell(_argument_type(spec))} | {_in_cell(default)} |")
    notes = [f"- `{n}`: {_markdown_text(' '.join(s['description'].split()))}"
             for n, s in props.items() if "description" in s]
    return lines + ([""] + notes if notes else [])


def _field_table(hints: Mapping[str, Any], names: Iterable[str], head: str) -> list[str]:
    return [f"| {head} | type |", "|---|---|",
            *(f"| `{n}` | {_in_cell(_reply_type(hints[n]))} |" for n in names)]


def _reply_fields(model: type, envelope: type) -> list[str]:
    own = own_fields(model, envelope)
    if not own:
        return ["The reply carries the envelope's fields only."]
    return _field_table(get_type_hints(model, include_extras=True), own, "reply field")


def _example(example: Mapping[str, Any] | None) -> list[str]:
    if example is None:
        return ["No example yet: a live run's transcript gives it."]
    return ["Example, from a live run:", "", demo.fenced(example["call"]), "",
            demo.fenced(example["reply"])]


def tool_block(tool: Tool, model: type, envelope: type,
               example: Mapping[str, Any] | None) -> str:
    """One tool's generated block: heading, title, call, description, arguments, reply fields,
    example."""
    lines = [f"## `{tool.name}`", ""]
    if tool.title:
        lines += [f"*{tool.title}*", ""]
    lines += ["```text", _signature(tool), "```", "",
              _markdown_text((tool.description or "").strip()), "",
              *_argument_table(tool), "",
              *_reply_fields(model, envelope), "", *_example(example)]
    return "\n".join(lines)


def _index(reg: Registry) -> str:
    return "\n".join(f"- [{family}]({_page(family)}): " + ", ".join(
        f"[`{t}`]({_page(family)}#{t})" for t in tools) for family, tools in reg.roster.families)


def _envelope(reg: Registry) -> str:
    hints = get_type_hints(reg.envelope, include_extras=True)
    return "\n".join(_field_table(hints, hints, "field"))


def _examples(reg: Registry) -> dict[str, Any]:
    path = reg.root / EXAMPLES_PATH
    if not path.is_file():
        return {}
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Invalid(f"{EXAMPLES_PATH} cannot be read: {e}") from e
    if not isinstance(held, dict):
        raise Invalid(f"{EXAMPLES_PATH} holds a {type(held).__name__}, not an object by tool")
    return held


@dataclass(frozen=True)
class _Expected:
    """A page as the registry would have it: its heading when it has to be created, its blocks
    by name in the roster's order, and the family it holds (empty for `REFERENCE.md`)."""

    title: str
    blocks: dict[str, str]
    family: str = ""


def _generated(reg: Registry, examples: Mapping[str, Any]) -> dict[str, _Expected]:
    """Every page the registry generates, by path relative to the repository; `Invalid` for a
    registry with no tool or a roster naming one the server lacks."""
    tools = {t.name: t for t in registered(reg.server)}
    if not tools:
        raise Invalid("the registry holds no tool, so there is nothing to compare")
    if unlisted := reg.roster.unlisted(tools):
        raise Invalid("the roster is not the registry: " + "; ".join(unlisted))
    if gap := model_gap(tools, reg.models):
        raise Invalid(gap)
    if len({_page(f) for f, _ in reg.roster.families}) != len(reg.roster.families):
        raise Invalid("two families share a page: "
                      + ", ".join(f"{f} -> {_page(f)}" for f, _ in reg.roster.families))
    pages = {REFERENCE_PAGE: _Expected("# Reference", {INDEX_BLOCK: _index(reg),
                                                      ENVELOPE_BLOCK: _envelope(reg)})}
    for family, names in reg.roster.families:
        # "The ... tools", never the bare family name: a page titled `# Lua` would take the
        # anchor `#lua` its own tool `lua` needs.
        pages[_page(family)] = _Expected(f"# The {family} tools", {
            n: tool_block(tools[n], reg.models[n], reg.envelope, examples.get(n))
            for n in names}, family)
    return pages


# ======================================================================== a page's text


@dataclass(frozen=True)
class _Segment:
    """One block of a page and the hand-written prose that follows it, up to the next block."""

    name: str
    block: str
    after: str


def _parsed(text: str) -> tuple[str, list[_Segment]]:
    """A page as the prose before its first block and its segments in the page's order; an
    `Invalid` naming the block whose markers do not pair."""
    head, segments = text, list[_Segment]()
    at, open_name, body_at = 0, "", 0
    for m in _MARKER.finditer(text):
        if m["begin"]:
            if open_name:
                raise Invalid(f"`{open_name}` is not closed before `{m['begin']}` begins")
            if segments:
                segments[-1] = replace(segments[-1], after=text[at:m.start()])
            else:
                head = text[:m.start()]
            open_name, body_at = m["begin"], m.end()
        elif m["end"] != open_name:
            raise Invalid(f"an end marker for `{m['end']}` closes no open block")
        else:
            segments.append(_Segment(open_name, text[body_at:m.start()].strip("\n"), ""))
            open_name, at = "", m.end()
    if open_name:
        raise Invalid(f"`{open_name}` is never closed")
    if segments:
        segments[-1] = replace(segments[-1], after=text[at:])
    return head, segments


def _rewritten(text: str, want: _Expected) -> str:
    """`text` with the blocks of `want` in its order. A block keeps the prose that followed it,
    a missing one goes in at its place in the roster, and a block of no tool of the page goes
    while its prose joins the block before it, so no hand-written line is lost."""
    head, segments = _parsed(text)
    after: dict[str, str] = {}
    previous = ""
    for s in segments:
        if s.name in want.blocks:
            after[s.name] = after.get(s.name, "") + s.after
            previous = s.name
        elif previous:
            after[previous] += s.after
        else:
            head += s.after
    if not segments:
        head = head.rstrip("\n") + "\n\n"
    out = head + "".join(f"{begin_marker(n)}\n{b}\n{end_marker(n)}{after.get(n, chr(10) * 2)}"
                         for n, b in want.blocks.items())
    return out.rstrip("\n") + "\n"


# ===================================================================== the comparison


def drift(reg: Registry) -> list[str]:
    """Each way the pages and `examples.json` depart from the registry, one finding per line, or
    empty; `Invalid` when nothing could be compared."""
    examples = _examples(reg)
    pages = _generated(reg, examples)
    found: list[str] = []
    for rel, want in pages.items():
        path = reg.root / rel
        if not path.is_file():
            found.append(f"{rel}: missing, and it holds {', '.join(want.blocks)}")
            continue
        try:
            _, segments = _parsed(path.read_text(encoding="utf-8"))
        except Invalid as e:
            found.append(f"{rel}: {e}")
            continue
        held = {s.name: s.block for s in segments}
        for name, block in want.blocks.items():
            if name not in held:
                found.append(f"{rel}: no block for `{name}`")
            elif diff := demo.first_difference(held[name], block, ("the page", "the registry")):
                found.append(f"`{name}` in {rel}: {diff}")
        for s in segments:
            if s.name not in want.blocks:
                found.append(f"{rel}: `{s.name}` is no tool of the {want.family} family"
                             if want.family else f"{rel}: `{s.name}` is no block of it")
        order = [s.name for s in segments if s.name in want.blocks]
        if order != [n for n in want.blocks if n in held]:
            found.append(f"{rel}: blocks out of the roster's order: {', '.join(order)}")
    docs = reg.root / PAGES_DIR
    for extra in sorted(docs.glob("*.md")) if docs.is_dir() else []:
        if (rel := extra.relative_to(reg.root).as_posix()) not in pages:
            found.append(f"{rel}: names no family")
    tools = {t.name: t for t in registered(reg.server)}
    found += [f"`{n}` has no example in {EXAMPLES_PATH}"
              for n in sorted(set(tools) - set(examples))]
    for name, example in sorted(examples.items()):
        if name not in tools:
            found.append(f"{EXAMPLES_PATH}: `{name}` is no tool")
        elif stale := sorted(set(example.get("call", {}))
                             - set(tools[name].parameters.get("properties", {}))):
            found.append(f"{EXAMPLES_PATH}: `{name}`'s example passes "
                         + ", ".join(f"`{a}`" for a in stale) + ", which it does not take")
    return found


def write(reg: Registry) -> list[str]:
    """Rewrite every page from the registry, creating the pages that are not there under their
    heading, and answer the paths of the pages that changed. Every page is rebuilt before the
    first is written, so a page whose markers do not pair (`Invalid`) leaves all of them as
    they were."""
    changed = {}
    for rel, want in _generated(reg, _examples(reg)).items():
        path = reg.root / rel
        before = path.read_text(encoding="utf-8") if path.is_file() else f"{want.title}\n"
        try:
            text = _rewritten(before, want)
        except Invalid as e:
            raise Invalid(f"{rel}: {e}") from e
        if text != before:
            changed[rel] = text
    for rel, text in changed.items():
        (reg.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (reg.root / rel).write_text(text, encoding="utf-8")
    return list(changed)


# ======================================================================== the examples


def examples_from(records: Iterable[Mapping[str, Any]], tools: set[str],
                  norm: demo.Normaliser) -> dict[str, Any]:
    """One example per tool of `tools`, by name, from a live run's records (`tool`, `args`,
    `reply`, `section`, the cell's `label` or `cell`, its `verdict`). Only a record of an OK cell
    whose reply carries a `status` is a candidate (an exception the harness caught is none); the
    first with an `ok` reply wins, else the first refusal, since a refusal is a real reply too.
    Its paths are spelled for any host as a demo's are, the `LEFT_OUT` fields dropped and its long
    values abridged."""
    ok: dict[str, Mapping[str, Any]] = {}
    refused: dict[str, Mapping[str, Any]] = {}
    for rec in records:
        name, reply = rec.get("tool"), rec.get("reply")
        if (name in tools and rec.get("verdict") == "OK" and isinstance(reply, dict)
                and "status" in reply):
            (ok if reply["status"] == "ok" else refused).setdefault(str(name), rec)
    return {name: {"from": f"{rec.get('section', '')}: {rec.get('label', rec.get('cell', ''))}",
                   "call": demo.abridged(norm.reply(dict(rec.get("args") or {}))),
                   "reply": demo.abridged(norm.reply(
                       {k: v for k, v in rec["reply"].items() if k not in LEFT_OUT}))}
            for name, rec in sorted({**refused, **ok}.items())}


def _records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Every record of the JSON Lines files `paths`; `Invalid` for one that cannot be read."""
    try:
        return [json.loads(line) for p in paths
                for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as e:
        raise Invalid(f"a transcript cannot be read: {e}") from e


# ======================================================================== the command


def _loaded(spec: str) -> Registry:
    """The `Registry` `spec` names, or a `ValueError` saying what it names instead."""
    module, _, attribute = spec.partition(":")
    if not attribute:
        raise ValueError(f"{spec!r} is not <module>:<attribute>")
    try:
        found = getattr(importlib.import_module(module), attribute)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"{spec} names nothing: {e}") from e
    if not isinstance(found, Registry):
        raise ValueError(f"{spec} is a {type(found).__name__}, not a Registry")
    return found


def _mark(value: str) -> tuple[str, str]:
    path, sep, text = value.partition("=")
    if not sep or not path or not text:
        raise argparse.ArgumentTypeError(f"{value!r} is not PATH=TEXT")
    return path, text


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m scry_core.reference", allow_abbrev=False,
                                description="Generate or check a server's reference pages.",
                                epilog="Exit codes: 0 agree (or rewritten), 1 drift, 2 a usage "
                                       "error, 3 nothing was compared.")
    p.add_argument("registry", help="<module>:<attribute> naming the server's Registry")
    p.add_argument("--examples", nargs="+", type=Path, metavar="JSONL",
                   help=f"rewrite {EXAMPLES_PATH} from these live transcripts first")
    p.add_argument("--mark", action="append", default=[], metavar="PATH=TEXT", type=_mark,
                   help="spell a directory of the live run's host as TEXT in the examples (its "
                        "scratch as $TMPDIR, its bench, its builds); repeatable")
    p.add_argument("--write", action="store_true", help="rewrite the pages")
    ns = p.parse_args(argv)
    try:
        reg = _loaded(ns.registry)
    except ValueError as e:
        p.error(str(e))
    try:
        if ns.examples:
            tools = {t.name for t in registered(reg.server)}
            root = reg.root.resolve()
            marks = {spelled: text for path, text in ns.mark
                     for spelled in (path, os.path.realpath(path))}
            # The repository as an absolute placeholder, never `.`: every path a tool takes is
            # absolute, so an example a reader copies has to be one too.
            norm = demo.Normaliser(root, Path.home().resolve(), {},
                                   marks={**marks, str(root): f"/path/to/{root.name}"})
            picked = examples_from(_records(ns.examples), tools, norm)
            if not picked:
                raise Invalid("the transcripts hold no OK cell of a tool of this server")
            (reg.root / PAGES_DIR).mkdir(parents=True, exist_ok=True)
            (reg.root / EXAMPLES_PATH).write_text(
                json.dumps(picked, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"examples: {len(picked)} of {len(tools)} tools, in {EXAMPLES_PATH}")
        if ns.write:
            for rel in write(reg):
                print(f"written: {rel}")
            return EXIT_PASS
        found = drift(reg)
    except Invalid as e:
        print(f"INVALID: {e}")
        return EXIT_INVALID
    for line in found:
        print(line)
    return EXIT_FAIL if found else EXIT_PASS


if __name__ == "__main__":  # pragma: no cover -- run in a child by the tests
    # `-m` runs this file as `__main__`, a second copy of the module whose `Registry` is not the
    # class a server built its registry from, so the command runs the imported copy's `main`.
    from scry_core.reference import main as imported_main

    raise SystemExit(imported_main())
