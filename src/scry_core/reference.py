"""A server's reference generated from its registry and its hand-written `asks.json`: per tool
one entry in the order `scry_core.entry` gives it, on its family's page
(`docs/reference/<family>.md`), and in `REFERENCE.md` the index and the fields every reply
carries.

Generated because a hand-written argument list falls behind the code unseen; each server's drift
test holds the pages to the registry. The prose outside the markers is hand-written and a rewrite
keeps it, each paragraph travelling with the block it follows. An example is a call a run made
and the reply it got (`examples_from`, held in `docs/reference/examples.json`), never typed by
hand: a demo's committed transcript gives it, or a live run's records.

    uv run python -m scry_core.reference <module>:<attribute> \
        [--examples TRANSCRIPT ... [--mark PATH=TEXT ...] [--skip REGEX]] [--write]

Run from the server's repository. `--examples` rewrites `examples.json` from the transcripts
first, a demo's normalised `.md` or a live run's `.jsonl`, taking for each tool the call its
ask is written for; a tool they do not call keeps the example it has while that is still its
ask's call (`--mark` spells a host directory as the text it names, `--skip` leaves out the cells
a pattern matches); `--write` rewrites the pages, and they are compared either way. Exit codes:
0 the pages agree with the registry; 1 they differ, one finding a line, or `asks.json` falls
short and no page was written; 2 a usage error (a spec naming no registry
included); 3 INVALID, nothing was compared (a registry with no tool or a roster naming one it
lacks, a transcript, an `examples.json` or an `asks.json` that cannot be read, a transcript with
no OK call of a tool of the server).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, get_type_hints

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.tools import Tool

from scry_core import asks as asked
from scry_core import demo, entry, file_names, reply_contract, transcript
from scry_core import example as shape
from scry_core.asks import Ask, Asks
from scry_core.reply_schema import model_gap, own_fields
from scry_core.roster import Roster
from scry_core.strict_arguments import registered
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


# ======================================================================== the pages


def _tools(reg: Registry) -> dict[str, Tool]:
    """The registry's tools by name; `Invalid` when it cannot be a reference's source."""
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
    return tools


def _index(reg: Registry, families: Mapping[str, str]) -> str:
    """Each family with the line saying what it holds, then its tools."""
    def said(family: str) -> str:
        line = families.get(family, "").strip().rstrip(".")
        return f"{line}. " if line else ""
    return "\n".join(f"- [{family}]({_page(family)}): {said(family)}" + ", ".join(
        f"[`{t}`]({_page(family)}#{t})" for t in tools) for family, tools in reg.roster.families)


def _envelope(reg: Registry) -> str:
    hints = get_type_hints(reg.envelope, include_extras=True)
    return "\n".join(entry.field_line(n, h) for n, h in hints.items())


def _call_and_reply(value: Any) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("call"), dict)
            and isinstance(value.get("reply"), dict))


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
    if odd := sorted(n for n, e in held.items() if not _call_and_reply(e) or (
            "then" in e and not (_call_and_reply(e["then"])
                                 and isinstance(e["then"].get("tool"), str)))):
        raise Invalid(f"{EXAMPLES_PATH}: no call and reply objects for {', '.join(odd)}")
    return held


@dataclass(frozen=True)
class _Expected:
    """A page as the registry would have it; `family` is empty for `REFERENCE.md`."""

    title: str
    blocks: dict[str, str]
    family: str = ""


@dataclass(frozen=True)
class _Pages:
    """Every page the registry generates, by repository-relative path, and what kept a block
    from being built, one finding a line: a block with a finding is in no page."""

    pages: dict[str, _Expected]
    unbuilt: list[str]


def _example_faults(name: str, ask: Ask, example: Mapping[str, Any]) -> list[str]:
    """How `example` is not the one `ask` is written for."""
    found = []
    if dict(example["call"]) != dict(ask.call):
        found.append(f"{EXAMPLES_PATH}: `{name}`'s example call is not the call its ask is "
                     "written for")
    then, second = ask.then, example.get("then")
    if (then is None) != (second is None):
        found.append(f"{EXAMPLES_PATH}: `{name}`'s example has "
                     f"{'a' if second is not None else 'no'} second call, and its ask has "
                     f"{'none' if then is None else 'one'}")
    elif then is not None and second is not None and (
            second["tool"] != then.tool or dict(second["call"]) != dict(then.call)):
        found.append(f"{EXAMPLES_PATH}: `{name}`'s second call is not the `{then.tool}` call "
                     "its ask is written for")
    return found


def _link(page_of: Mapping[str, str], here: str) -> Callable[[str], str]:
    """The address of a tool's entry as the page `here` links to it."""
    def link(tool: str) -> str:
        there = page_of[tool]
        return f"#{tool}" if there == here else f"{there.rsplit('/', 1)[1]}#{tool}"
    return link


def _generated(reg: Registry, examples: Mapping[str, Any], said: Asks) -> _Pages:
    """The pages as the registry, the asks and the examples give them."""
    tools = _tools(reg)
    page_of = {n: _page(family) for family, names in reg.roster.families for n in names}
    pages = {REFERENCE_PAGE: _Expected("# Reference", {
        INDEX_BLOCK: _index(reg, said.families), ENVELOPE_BLOCK: _envelope(reg)})}
    unbuilt: list[str] = []
    for family, names in reg.roster.families:
        here = _page(family)
        blocks = {}
        for n in names:
            ask, example = said.tools.get(n), examples.get(n)
            if ask is None:
                continue  # `asks.faults` names it
            if example is not None and (faults := _example_faults(n, ask, example)):
                unbuilt += faults
                continue
            try:
                block = entry.tool_block(tools[n], reg.models[n], reg.envelope, ask, example,
                                         _link(page_of, here))
            except (ValueError, KeyError) as e:
                unbuilt.append(f"`{n}`'s entry: {e}")
                continue
            blocks[n] = block
        # a page titled `# Lua` would take the anchor `#lua` its own tool needs.
        pages[here] = _Expected(f"# The {family} tools", blocks, family)
    return _Pages(pages, unbuilt)


def _asks_faults(reg: Registry, said: Asks) -> list[str]:
    tools = _tools(reg)
    return asked.faults(said, tools, reg.models,
                        {n: own_fields(reg.models[n], reg.envelope) for n in tools},
                        [family for family, _ in reg.roster.families])


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


def _named(reg: Registry, want: _Expected) -> list[str]:
    """The blocks a page holds, in order: a family's tools, or `REFERENCE.md`'s own."""
    if not want.family:
        return list(want.blocks)
    return [n for family, names in reg.roster.families if family == want.family for n in names]


def drift(reg: Registry) -> list[str]:
    """Each way the pages, `asks.json` and `examples.json` depart from the registry; `Invalid`
    when nothing could be compared."""
    examples = _examples(reg)
    said = asked.load(reg.root)
    found = _asks_faults(reg, said)
    built = _generated(reg, examples, said)
    found += built.unbuilt
    tools = _tools(reg)
    for rel, want in built.pages.items():
        path = reg.root / rel
        named = _named(reg, want)
        if not path.is_file():
            found.append(f"{rel}: missing, and it holds {', '.join(named)}")
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
        for name in named:
            if name not in held:
                found.append(f"{rel}: no block for `{name}`")
            elif name in want.blocks and (diff := demo.first_difference(
                    held[name], want.blocks[name], ("the page", "the registry"))):
                found.append(f"`{name}` in {rel}: {diff}")
        for s in segments:
            if s.name not in named:
                found.append(f"{rel}: `{s.name}` is no tool of the {want.family} family"
                             if want.family else f"{rel}: `{s.name}` is no block of it")
        order = [s.name for s in segments if s.name in named]
        if order != [n for n in named if n in held]:
            found.append(f"{rel}: blocks out of the roster's order: {', '.join(order)}")
    docs = reg.root / PAGES_DIR
    for extra in sorted(docs.glob("*.md")) if docs.is_dir() else []:
        if (rel := extra.relative_to(reg.root).as_posix()) not in built.pages:
            found.append(f"{rel}: names no family")
    found += [f"`{n}` has no example in {EXAMPLES_PATH}"
              for n in sorted(set(tools) - set(examples))]
    for name, example in sorted(examples.items()):
        if name not in tools:
            found.append(f"{EXAMPLES_PATH}: `{name}` is no tool")
            continue
        second = [(example["then"]["tool"], example["then"])] if "then" in example else []
        for tool, shown in ((name, example), *second):
            if tool not in tools:
                found.append(f"{EXAMPLES_PATH}: `{name}`'s second call is to `{tool}`, which "
                             "is no tool")
                continue
            if why := asked.call_refused(tools[tool], shown["call"]):
                found.append(f"{EXAMPLES_PATH}: `{name}`'s example call is one the tool refuses "
                             f"({why})")
            known = set(get_type_hints(reg.models[tool], include_extras=True))
            for field_name in sorted(set(shown["reply"]) - known):
                found.append(f"{EXAMPLES_PATH}: `{name}`'s example replies `{field_name}`, "
                             "which its model does not name")
    return found


class Unready(Exception):
    """The pages cannot be written yet: `findings` says what each entry lacks."""

    def __init__(self, findings: list[str]) -> None:
        super().__init__(f"{len(findings)} findings")
        self.findings = findings


def write(reg: Registry) -> list[str]:
    """Rewrite every page from the registry and answer the paths that changed. All are rebuilt
    before the first is written, so an `Invalid` page leaves every one as it was; so does an
    entry that cannot be built, which is `Unready` with each reason."""
    said = asked.load(reg.root)
    built = _generated(reg, _examples(reg), said)
    if short := _asks_faults(reg, said) + built.unbuilt:
        raise Unready(short)
    changed = {}
    for rel, want in built.pages.items():
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
                    r"(?:Z|[+-]\d\d:?\d\d)?)?|\d{8}[Tt]\d{6,12}(?:\.\d+)?[Zz]?)(?!\d)")
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


def _spelled(rec: Mapping[str, Any], norm: demo.Normaliser) -> tuple[dict[str, Any], Any]:
    """A record's call and reply as a page spells them: a demo's transcript already hides what
    its run decides, a live run's records are spelled here."""
    args = dict(rec.get("args") or {})
    reply = {k: v for k, v in rec["reply"].items() if k not in LEFT_OUT}
    if rec.get("normalised"):
        return args, shape.abridged(reply)
    return (_steady(norm.reply(args, RUN_KEYS)),
            shape.abridged(_steady(norm.reply(reply, RUN_KEYS))))


def _candidate(rec: Mapping[str, Any], tools: set[str], skip: re.Pattern[str] | None) -> bool:
    """Whether a record may be an example: an OK cell of a tool, with a reply that carries a
    `status`, which `skip` matches nowhere."""
    reply = rec.get("reply")
    return (rec.get("tool") in tools and rec.get("verdict") == "OK" and isinstance(reply, dict)
            and "status" in reply
            and not (skip and any(skip.search(leaf) for leaf in _leaves(
                [rec.get("args"), reply, rec.get("section"), rec.get("label")]))))


def _later_call(records: Sequence[Mapping[str, Any]], at: int, then: asked.Then,
                norm: demo.Normaliser, skip: re.Pattern[str] | None
                ) -> dict[str, Any] | None:
    """The call `then` names, as the run of record `at` made it later on, or None: the first
    that was answered `ok`, else the first refused."""
    run = records[at].get("section")
    refused = None
    for rec in records[at + 1:]:
        if rec.get("section") == run and _candidate(rec, {then.tool}, skip):
            call, reply = _spelled(rec, norm)
            if call != dict(then.call):
                continue
            if reply["status"] == "ok":
                return {"tool": then.tool, "call": call, "reply": reply}
            refused = refused or {"tool": then.tool, "call": call, "reply": reply}
    return refused


def examples_from(records: Iterable[Mapping[str, Any]], tools: set[str],
                  norm: demo.Normaliser, skip: re.Pattern[str] | None = None,
                  wanted: Mapping[str, Ask] | None = None) -> dict[str, Any]:
    """One example per tool of `tools` from a run's records. Only an OK cell whose reply carries
    a `status` is a candidate, and not one whose call, reply or name `skip` matches. A tool
    `wanted` names takes only a cell whose call is the one its ask is written for, with the
    second call its ask names as the same run made it later. Every tool takes its first `ok`
    reply, else its first refusal. Paths are spelled host-independently, `LEFT_OUT` dropped,
    the run's own values (`RUN_KEYS`, clock readings) hidden, long values abridged."""
    records = list(records)
    wanted = wanted or {}
    ok: dict[str, dict[str, Any]] = {}
    refusal: dict[str, dict[str, Any]] = {}
    for at, rec in enumerate(records):
        name = str(rec.get("tool"))
        if name in ok or not _candidate(rec, tools, skip):
            continue
        call, reply = _spelled(rec, norm)
        found = {"from": f"{rec.get('section', '')}: {rec.get('label', '')}", "call": call,
                 "reply": reply}
        ask = wanted.get(name)
        if ask is not None:
            if call != dict(ask.call):
                continue
            if ask.then is not None:
                second = _later_call(records, at, ask.then, norm, skip)
                if second is None:
                    continue
                found["then"] = second
        (ok if reply["status"] == "ok" else refusal).setdefault(name, found)
    return dict(sorted({**refusal, **ok}.items()))


def _still_asked(held: Mapping[str, Any], names: set[str], said: Mapping[str, Ask]
                 ) -> dict[str, Any]:
    """The examples of `held` for the tools `names` that no transcript given called: each is
    kept while it is still the call its ask is written for."""
    return {name: example for name, example in held.items()
            if name in names and (name not in said or not _example_faults(
                name, said[name], example))}


def _records(paths: Sequence[Path], root: Path) -> list[dict[str, Any]]:
    """Every record of `paths`: a live run's JSON Lines, or a demo's normalised transcript
    (`.md`), named by its path under `root`."""
    found: list[dict[str, Any]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
            if p.suffix == ".md":
                inside = p.resolve().is_relative_to(root)
                found += transcript.records(
                    text, p.resolve().relative_to(root).as_posix() if inside else p.name)
            else:
                found += [json.loads(line) for line in text.splitlines() if line.strip()]
        except (OSError, ValueError) as e:
            raise Invalid(f"a transcript cannot be read: {e}") from e
    return found


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
    p.add_argument("--examples", nargs="+", type=Path, metavar="TRANSCRIPT",
                   help=f"rewrite {EXAMPLES_PATH} from these first: a demo's normalised "
                        "transcript (.md) or a live run's records (.jsonl)")
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
            said = asked.load(reg.root).tools
            picked = examples_from(_records(ns.examples, root), tools, norm, ns.skip, said)
            if not picked:
                raise Invalid("the transcripts hold no OK call of a tool of this server")
            kept = _still_asked(_examples(reg), set(tools) - set(picked), said)
            (reg.root / PAGES_DIR).mkdir(parents=True, exist_ok=True)
            (reg.root / EXAMPLES_PATH).write_text(json.dumps(
                dict(sorted({**kept, **picked}.items())), indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8")
            print(f"examples: {len(picked) + len(kept)} of {len(tools)} tools, {len(kept)} kept "
                  f"as it was, in {EXAMPLES_PATH}")
        if ns.write:
            for rel in write(reg):
                print(f"written: {rel}")
        found = drift(reg)
    except Unready as e:
        found = [*e.findings, "no page was written: the entries above cannot be built"]
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
