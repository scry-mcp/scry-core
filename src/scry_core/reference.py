"""A server's reference generated from its registry: per tool its call, arguments, reply fields,
description and a live example, on its family's page (`docs/reference/<family>.md`), and in
`REFERENCE.md` the index and the envelope every reply carries.

Generated because a hand-written argument list falls behind the code unseen; each server's drift
test holds the pages to the registry. The prose outside the markers is hand-written and a rewrite
keeps it, each paragraph travelling with the block it follows. Examples come from a live run's
transcript (`examples_from`, held in `docs/reference/examples.json`), never typed by hand.

    uv run python -m scry_core.reference <module>:<attribute> \
        [--examples JSONL ... [--mark PATH=TEXT ...] [--skip REGEX]] [--write]

Run from the server's repository. `--examples` rewrites `examples.json` from the transcripts
first (`--mark` spells a host directory as the text it names, `--skip` leaves out the cells a
pattern matches); `--write` rewrites the pages,
else they are compared. Exit codes: 0 the pages agree with
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
from collections.abc import Iterable, Iterator, Mapping, Sequence
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

from scry_core import demo, file_names, reply_contract
from scry_core.reply_schema import model_gap, own_fields
from scry_core.roster import Roster
from scry_core.strict_arguments import refused, registered
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

REFERENCE_PAGE = "REFERENCE.md"
PAGES_DIR = "docs/reference"
EXAMPLES_PATH = f"{PAGES_DIR}/examples.json"

INDEX_BLOCK, ENVELOPE_BLOCK = "index", "envelope"

#: Reply fields an example leaves out; `REFERENCE.md` documents `session` once.
LEFT_OUT = frozenset({"session"})


def begin_marker(name: str) -> str:
    return f"<!-- scry-reference:begin {name} -->"


def end_marker(name: str) -> str:
    return f"<!-- scry-reference:end {name} -->"


_MARKER = re.compile(begin_marker("(?P<begin>\\S+)") + "|" + end_marker("(?P<end>\\S+)"))


@dataclass(frozen=True)
class Registry:
    """What a reference is generated from: the server (after `strict_arguments`, so its schemas
    are the ones a client sees), reply models, roster, envelope and repository root."""

    server: MCPServer
    models: Mapping[str, type]
    roster: Roster
    envelope: type
    root: Path


def _page(family: str) -> str:
    try:
        return f"{PAGES_DIR}/{file_names.name(file_names.word(family, 'family'), extension='md')}"
    except reply_contract.Invalid as e:
        raise Invalid(str(e)) from None


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
    """A description as markdown shows it: `<` outside code is text, and indentation is flush."""
    parts = _CODE.split(text)
    # A text piece after a span starts mid-line: only its later lines may be flushed.
    return "".join(p if i % 2 else (_CODE_BLOCK_INDENT if i else _FIRST_INDENT).sub("", p)
                   .replace("<", "&lt;") for i, p in enumerate(parts))


#: What markdown shows as typed: a fenced block, a double-backtick span, a single one; a span may
#: wrap a line, never a paragraph.
_CODE = re.compile(r"(```.*?```|``(?:[^\n]|\n(?!\n))+?``|`(?:[^`\n]|\n(?!\n))+`)", re.DOTALL)
#: Four spaces open a markdown code block; a list nests with fewer, and keeps them.
_CODE_BLOCK_INDENT = re.compile(r"(?<=\n) {4,}")
_FIRST_INDENT = re.compile(r"^ {4,}", re.MULTILINE)


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
    """One tool's generated block."""
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
    if odd := sorted(n for n, e in held.items()
                     if not (isinstance(e, dict) and isinstance(e.get("call"), dict)
                             and isinstance(e.get("reply"), dict))):
        raise Invalid(f"{EXAMPLES_PATH}: no call and reply objects for {', '.join(odd)}")
    return held


@dataclass(frozen=True)
class _Expected:
    """A page as the registry would have it; `family` is empty for `REFERENCE.md`."""

    title: str
    blocks: dict[str, str]
    family: str = ""


def _generated(reg: Registry, examples: Mapping[str, Any]) -> dict[str, _Expected]:
    """Every page the registry generates, by repository-relative path."""
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
        # a page titled `# Lua` would take the anchor `#lua` its own tool needs.
        pages[_page(family)] = _Expected(f"# The {family} tools", {
            n: tool_block(tools[n], reg.models[n], reg.envelope, examples.get(n))
            for n in names}, family)
    return pages


# ======================================================================== a page's text


@dataclass(frozen=True)
class _Segment:
    """One block of a page and the hand-written prose after it."""

    name: str
    block: str
    after: str


def _parsed(text: str) -> tuple[str, list[_Segment]]:
    """A page as the prose before its first block and its segments; `Invalid` on unpaired
    markers."""
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
    """`text` with the blocks of `want` in its order. A dropped block's prose joins the block
    before it, so no hand-written line is lost."""
    head, segments = _parsed(text)
    if want.family and head.startswith("# "):
        head = want.title + head[len(head.split("\n", 1)[0]):]
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
    """Each way the pages and `examples.json` depart from the registry; `Invalid` when nothing
    could be compared."""
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
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        if want.family and first.startswith("# ") and first != want.title:
            found.append(f"{rel}: titled {first!r}, not {want.title!r}")
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
        else:
            if why := refused(tools[name], example["call"]):
                found.append(f"{EXAMPLES_PATH}: `{name}`'s example call is one the tool refuses "
                             f"({why})")
            known = set(get_type_hints(reg.models[name], include_extras=True))
            for field_name in sorted(set(example["reply"]) - known):
                found.append(f"{EXAMPLES_PATH}: `{name}`'s example replies `{field_name}`, "
                             "which its model does not name")
    return found


def write(reg: Registry) -> list[str]:
    """Rewrite every page from the registry and answer the paths that changed. All are rebuilt
    before the first is written, so an `Invalid` page leaves every one as it was."""
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


#: Reply keys that belong to the run that produced an example, not to the tool.
RUN_KEYS = {k: "" for k in ("created_at", "origin", "pid", "stub_port", "input_port",
                            "wall_at", "saved_at", "version")}
_CLOCK = re.compile(r"(?<!\d)(?:\d{4}-\d\d-\d\d(?:[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?"
                    r"(?:Z|[+-]\d\d:?\d\d)?)?|\d{8}T\d{6}(?:\.\d+)?Z?)(?!\d)")
#: A scratch directory a run makes: `<emulator>-...-` then the 12 hex characters of a uuid or the 8
#: of `tempfile.mkdtemp`, as a whole path component.
_RUN_DIR = re.compile(
    r"(?:(?<=[/\\])|^)((?:dosbox-x|mame)-[\w-]*?-)(?:[0-9a-f]{12}|[0-9a-z_]{8})(?!\w)")


def _steady(value: Any) -> Any:
    """`value` with a clock reading or a run directory's random name replaced by a mark."""
    if isinstance(value, dict):
        return {k: _steady(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_steady(v) for v in value]
    if isinstance(value, str):
        return _RUN_DIR.sub(r"\1<run>", _CLOCK.sub("<time>", value))
    return value


def _leaves(value: Any) -> Iterator[str]:
    """Every key and scalar of `value` as a person reads it, with no JSON escape in it."""
    if isinstance(value, Mapping):
        for k, v in value.items():
            yield str(k)
            yield from _leaves(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _leaves(v)
    else:
        yield value if isinstance(value, str) else json.dumps(value)


def examples_from(records: Iterable[Mapping[str, Any]], tools: set[str],
                  norm: demo.Normaliser, skip: re.Pattern[str] | None = None) -> dict[str, Any]:
    """One example per tool of `tools` from a live run's records. Only an OK cell whose reply
    carries a `status` is a candidate, and not one whose call, reply or name `skip` matches; the
    first `ok` reply wins, else the first refusal. Paths are spelled host-independently, `LEFT_OUT`
    dropped, the run's own values (`RUN_KEYS`, clock readings) hidden, long values abridged."""
    ok: dict[str, Mapping[str, Any]] = {}
    refused: dict[str, Mapping[str, Any]] = {}
    for rec in records:
        name, reply = rec.get("tool"), rec.get("reply")
        if (name in tools and rec.get("verdict") == "OK" and isinstance(reply, dict)
                and "status" in reply
                and not (skip and any(skip.search(leaf) for leaf in _leaves(
                    [rec.get("args"), reply, rec.get("section"), rec.get("label")])))):
            (ok if reply["status"] == "ok" else refused).setdefault(str(name), rec)
    return {name: {"from": f"{rec.get('section', '')}: {rec.get('label', '')}",
                   "call": _steady(norm.reply(dict(rec.get("args") or {}), RUN_KEYS)),
                   "reply": demo.abridged(_steady(norm.reply(
                       {k: v for k, v in rec["reply"].items() if k not in LEFT_OUT},
                       RUN_KEYS)))}
            for name, rec in sorted({**refused, **ok}.items())}


def _records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Every record of the JSON Lines files `paths`."""
    try:
        return [json.loads(line) for p in paths
                for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as e:
        raise Invalid(f"a transcript cannot be read: {e}") from e


# ======================================================================== the command


class _BadSpec(ValueError):
    """A spec naming no Registry: usage, unlike a module that raises while it is built."""


def _loaded(spec: str) -> Registry:
    """The `Registry` `spec` names, else a `_BadSpec`."""
    module, _, attribute = spec.partition(":")
    if not attribute or not module or module.startswith("."):
        raise _BadSpec(f"{spec!r} is not <module>:<attribute>")
    try:
        loaded = importlib.import_module(module)
    except ModuleNotFoundError as e:
        # only the named module missing is the caller's; a dependency it imports is the module's
        if e.name is None or not (module == e.name or module.startswith(f"{e.name}.")):
            raise
        raise _BadSpec(f"{spec} names nothing: {e}") from e
    try:
        found = getattr(loaded, attribute)
    except AttributeError as e:
        raise _BadSpec(f"{spec} names nothing: {e}") from e
    if not isinstance(found, Registry):
        raise _BadSpec(f"{spec} is a {type(found).__name__}, not a Registry")
    return found


def _mark(value: str) -> tuple[str, str]:
    path, sep, text = value.rpartition("=")
    if not sep or not path or not text:
        raise argparse.ArgumentTypeError(f"{value!r} is not PATH=TEXT")
    return path, text


def _pattern(value: str) -> re.Pattern[str]:
    try:
        return re.compile(value)
    except re.error as e:
        raise argparse.ArgumentTypeError(f"{value!r} is not a regular expression: {e}") from e


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
    p.add_argument("--skip", type=_pattern, metavar="REGEX",
                   help="leave out the cells whose call, reply, section or label matches REGEX, "
                        "so the tool's next OK cell is its example (a board a stranger cannot "
                        "have); a tool left with none shows a refusal, else no example")
    p.add_argument("--write", action="store_true", help="rewrite the pages")
    ns = p.parse_args(argv)
    if ns.mark and not ns.examples:
        p.error("--mark spells the examples' paths, so it needs --examples")
    if ns.skip and not ns.examples:
        p.error("--skip picks among the examples' cells, so it needs --examples")
    try:
        reg = _loaded(ns.registry)
    except _BadSpec as e:
        p.error(str(e))
    except Exception as e:  # a module that cannot be built compared nothing: INVALID, not drift
        print(f"INVALID: {ns.registry} could not be loaded: {type(e).__name__}: {e}")
        return EXIT_INVALID
    try:
        if ns.examples:
            tools = {t.name for t in registered(reg.server)}
            root = reg.root.resolve()
            marks = {spelled: text for path, text in ns.mark
                     for spelled in (path, os.path.realpath(path))}
            norm = demo.Normaliser(root, Path.home().resolve(), {},
                                   marks={**marks, str(root): demo.placeholder(root)})
            picked = examples_from(_records(ns.examples), tools, norm, ns.skip)
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
    except Exception as e:  # anything else before a verdict: INVALID, never read as drift
        print(f"INVALID: {type(e).__name__}: {e}")
        return EXIT_INVALID
    for line in found:
        print(line)
    return EXIT_FAIL if found else EXIT_PASS


if __name__ == "__main__":  # pragma: no cover -- run in a child by the tests
    # `-m` makes a second copy of the module whose `Registry` is not the server's class.
    from scry_core.reference import main as imported_main

    raise SystemExit(imported_main())
