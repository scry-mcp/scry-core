"""Runs a demo: one server started over stdio, the calls a prompt asks a model to make, each
answer checked, and a transcript a README can carry without drifting from the server.

A server repository declares a `Demo` in `demos/<name>/demo.py` and hands it to `main`
(`--binary`, `--transcript`, `--update-readme`, plus `--cwd`, `--rompath`, `--shared` and
`--display` where the demo `offers` them). Options reach the step declared `options=True`, or
only those a frozenset names; an option left out is absent, so the server's own default
decides.

stdout is `OK <step>: <summary>` or `FAIL <step>: <why>` per step run, then
`DEMO <name>: <n> steps, <k> OK` and the paths of the whole transcript and the NORMALISED one,
which is what a README carries and `readme_drift` compares.

Exit codes: 0 every step OK; 1 a step failed (later ones are not run); 2 a usage error; 3
INVALID, nothing was demonstrated (zero steps, options nothing takes, a `precheck` reason, a
server that did not start, a check raising `Invalid`, README markers not exactly once, a capture
the run did not write, a loop it wrote or could not convert). `execute` is the run without its
command line. The run ends with the cleanup call unless its last step made it, so no emulator
outlives it.

`--update-readme` rewrites the README block, the capture and the `Demo.front` flow only after a
run whose every step was OK.

A demo that declares a `Loop` has its video recorded by the runner: right after the step the
loop names, one `record` call writes `loop.avi` into the run's directory and its reply joins the
transcript as a call of its own. `--update-readme` converts it to `loop.mp4` beside the capture,
and `stale` asks only that the file is committed, never that its bytes are the run's: a
recording is not byte-stable. The conversion is refused past the loop's budget, naming the file
and its bytes.

A demo whose steps carry a `highlight` puts only those steps in the README block, each with its
sentence on how the call does it, and commits the whole normalised run beside the README as
`FULL_NAME`, which the block links; `stale` compares both.

Normalisation hides what differs between two honest runs and nothing else: `$HOME` as `~`, the
repository root as `.`, the values of `VOLATILE` keys (and the demo's and step's own) in a reply
as `<volatile>`, a written picture's `bytes` and `sha256` (the pixels are the run's, the bytes
the host zlib's), and of `host_args` keys in a call's arguments as `<host>`. Hiding is by key, so
a reply echoing a host argument needs that key in `volatile` too. A value the demo shows is never
hidden: if it differs between runs the demo is wrong. A step's summary is never searched for
volatile values, so it quotes only what the demo shows.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

from scry_core import file_names, fresh, png, prose
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

BEGIN = "<!-- demo-transcript:begin -->"
END = "<!-- demo-transcript:end -->"
FULL_NAME = "TRANSCRIPT.md"
VOLATILE_MARK = "<volatile>"

#: Frames a demo records for its loop, and the seconds of them its `loop.mp4` carries.
LOOP_FRAMES = 240
LOOP_SECONDS = 3
#: The most a converted loop may weigh: every demo page loads its own.
LOOP_BUDGET_BYTES = 1_500_000
LOOP_AVI = "loop.avi"
LOOP_MP4 = "loop.mp4"

ABRIDGED_ITEMS = 6
ABRIDGED_CHARS = 240
HOST_MARK = "<host>"

#: The tool every Scry server ends a session with.
CLEANUP_TOOL = "close"

#: Every Scry tool bounds its own waits at 600 s, so past this a server will not answer.
CALL_TIMEOUT_S = 900

#: The options a demo can offer beyond `--binary`, as its server's `start` spells them.
OFFERABLE = frozenset({"cwd", "rompath", "shared", "display"})

#: Reply keys whose values differ between two honest runs, each with the reason. A demo adds
#: its own through `Demo.volatile`, and a step those that vary in it alone through
#: `Step.volatile`.
VOLATILE: Mapping[str, str] = {
    "pid": "the operating system's process id, new on every launch",
    "stub_port": "a free port picked at launch",
    "scratch_dir": "a temporary directory created per session",
    "errorlog_path": "a file inside the per-session temporary directory",
    "stdout_path": "a file inside the per-session temporary directory",
    "boot_lua_path": "a file inside the per-session temporary directory",
    "query_s": "wall-clock time a query took",
    "after_s": "wall-clock time since a launch",
    "since_s": "wall-clock time since a stop",
    "wall_at": "a wall-clock timestamp",
    "elapsed_s": "wall-clock time a call took",
}


class StepFailed(Exception):
    """A step's answer was not the one its check asked for: the message says why."""


def expect(holds: bool, why: str) -> None:
    """A step's check: `StepFailed` with `why` unless `holds`."""
    if not holds:
        raise StepFailed(why)


@dataclass(frozen=True)
class Reply(Mapping[str, Any]):
    """One tool's answer as a mapping, plus the media type of each non-text part."""

    data: dict[str, Any]
    attachments: tuple[str, ...] = ()

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


@dataclass
class Run:
    """What a step's arguments and checks read: options, output directory, replies by step name."""

    dir: Path
    options: dict[str, Any] = field(default_factory=dict)
    replies: dict[str, Reply] = field(default_factory=dict)


Args = Mapping[str, Any] | Callable[[Run], Mapping[str, Any]]


@dataclass(frozen=True)
class Step:
    """One call: `tool` with `args` (or a function of the run giving them). `check` returns the
    summary printed beside OK and raises `StepFailed` to say why not; a reply whose `status` is
    not `ok` fails before `check`. `options` marks the step the command line's options merge
    into (the server's `start`): `True` for all, or the set it takes. `volatile` hides reply keys
    in this step alone. `failure` words the FAIL of a non-`ok` reply. A check raising `Invalid`
    ends the run INVALID."""

    name: str
    tool: str
    args: Args
    check: Callable[[Reply, Run], str]
    options: bool | frozenset[str] = False
    volatile: Mapping[str, str] = field(default_factory=dict)
    failure: Callable[[Reply, Run], str] | None = None
    #: An exception in the call itself (timeout, server gone) is INVALID rather than FAIL.
    broken_is_invalid: bool = False
    #: A call the front door shows (`Demo.front`), reply abridged to the fields named. A named
    #: field the reply lacks fails the step, so the front door never shows a stale shape.
    shown: tuple[str, ...] = ()
    #: How the call does what it shows: the step goes in the README block with this sentence.
    highlight: str = ""


@dataclass(frozen=True)
class Loop:
    """A demo's video: the `frames` recorded after the step named `after` completes, converted to
    the demo's `loop.mp4` when the README is rewritten."""

    after: str
    frames: int = LOOP_FRAMES


@dataclass(frozen=True)
class Demo:
    """A demo as declared. `offers` names the `OFFERABLE` options it accepts,
    `reads` those it reads from `run.options` itself. `capture` is the image one step writes in
    `run.dir`. `precheck` answers why the demo cannot run, or empty. `host_args` maps argument
    keys that are the host's own to their reasons. `verdict` words the last line. `loop` is the
    recording the runner makes on its own, right after the step it follows."""

    name: str
    root: Path
    server: Sequence[str]
    steps: Sequence[Step]
    readme: Path | None = None
    capture: Callable[[Run], Path] | None = None
    offers: frozenset[str] = frozenset()
    precheck: Callable[[Run], str] | None = None
    volatile: Mapping[str, str] = field(default_factory=dict)
    host_args: Mapping[str, str] = field(default_factory=dict)
    reads: frozenset[str] = frozenset()
    verdict: Callable[[int, int], str] | None = None
    front: Path | None = None
    loop: Loop | None = None


def flow_begin(name: str) -> str:
    return f"<!-- demo-flow:begin {name} -->"


def flow_end(name: str) -> str:
    return f"<!-- demo-flow:end {name} -->"


def block_span(text: str, begin: str = BEGIN, end: str = END) -> tuple[int, int]:
    """Where the block between `begin` and `end` sits in `text`; bad markers raise `Invalid`."""
    if text.count(begin) != 1 or text.count(end) != 1:
        raise Invalid(f"the README must hold {begin} and {end} exactly once each "
                      f"(found {text.count(begin)} and {text.count(end)})")
    start, stop = text.index(begin) + len(begin), text.index(end)
    if stop < start:
        raise Invalid(f"{end} comes before {begin}")
    return start, stop


def block_of(text: str, begin: str = BEGIN, end: str = END) -> str:
    """The generated block of `text`, without its framing newlines."""
    start, stop = block_span(text, begin, end)
    return text[start:stop].strip("\n")


def with_block(text: str, block: str, begin: str = BEGIN, end: str = END) -> str:
    """`text` with a generated block replaced by `block`."""
    start, stop = block_span(text, begin, end)
    return f"{text[:start]}\n{block.strip(chr(10))}\n{text[stop:]}"


def first_difference(want: str, got: str, sides: tuple[str, str] = ("the README", "the run")
                     ) -> str:
    """The first line where `got` departs from `want`, or empty; `sides` names each."""
    a, b = want.splitlines(), got.splitlines()
    for i, (x, y) in enumerate(zip(a, b, strict=False), start=1):
        if x != y:
            return f"line {i}: {sides[0]} has {x!r}, {sides[1]} has {y!r}"
    if len(a) != len(b):
        return f"line {min(len(a), len(b)) + 1}: {sides[0]} has {len(a)}, {sides[1]} {len(b)}"
    return ""


def readme_drift(readme: Path, normalised: Path) -> str:
    """How a run's normalised transcript departs from the README block, or empty."""
    return first_difference(block_of(readme.read_text(encoding="utf-8")),
                            normalised.read_text(encoding="utf-8").strip("\n"))


def flow_drift(front: Path, name: str, flow: Path) -> str:
    """How a run's flow departs from demo `name`'s front-door block, or empty."""
    return first_difference(block_of(front.read_text(encoding="utf-8"), flow_begin(name),
                                     flow_end(name)),
                            flow.read_text(encoding="utf-8").strip("\n"))


def _marked(mark: str) -> Callable[[re.Match[str]], str]:
    """A substitution writing `mark`, then the path's `rest` with forward slashes."""
    return lambda m: mark + m["rest"].replace("\\", "/")


@dataclass(frozen=True)
class Normaliser:
    """Spells the host's paths, volatile reply values and host arguments for any host."""

    root: Path
    home: Path
    volatile: Mapping[str, str]
    host: Mapping[str, str] = field(default_factory=dict)
    #: Further prefixes with their marks, longest first: one may lie inside the root or home.
    marks: Mapping[str, str] = field(default_factory=dict)

    def text(self, text: str) -> str:
        """`text` with the root as `.` and the home as `~` where one begins a path, never inside a
        longer name (`/Users/mx` is not under `/Users/m`). A prefix of `/` is left alone."""
        marks = sorted(self.marks.items(), key=lambda pm: -len(pm[0]))
        for prefix, mark in (*marks, (str(self.root), "."), (str(self.home), "~")):
            prefix = prefix.rstrip("/\\")
            if prefix:
                # The rest of the path keeps its words and loses Windows' separators.
                text = re.sub(r"(?<![\w.-])" + re.escape(prefix)
                              + r"(?P<rest>[\\/][^\s\"'`,;:=&|)\]}]*|(?![\w.-]))",
                              _marked(mark), text)
        return text

    def reply(self, value: Any, also: Mapping[str, str] | None = None) -> Any:
        """A reply with paths spelled and volatile keys' values hidden, `also` included."""
        return self._value(value, {**self.volatile, **(also or {})}, VOLATILE_MARK)

    def arguments(self, value: Any) -> Any:
        """The demo's arguments with paths spelled and host-owned keys hidden."""
        return self._value(value, self.host, HOST_MARK)

    def _value(self, value: Any, hidden: Mapping[str, str], mark: str) -> Any:
        if isinstance(value, dict) and mark == VOLATILE_MARK and _picture(value):
            hidden = {**hidden, **PICTURE_VOLATILE}
        if isinstance(value, dict):
            return {self.text(k): mark if k in hidden else self._value(v, hidden, mark)
                    for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._value(v, hidden, mark) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value


#: A written picture's size and digest: the pixels are the run's, the bytes the host zlib's.
PICTURE_VOLATILE = {key: "the host's zlib compresses the same pixels into different bytes"
                    for key in ("bytes", "sha256")}


def _picture(value: Mapping[str, Any]) -> bool:
    """Whether `value` is a written picture as a reply names it: a PNG path with its digest."""
    path = value.get("path")
    return isinstance(path, str) and path.lower().endswith(".png") and "sha256" in value


def placeholder(root: Path) -> str:
    """The repository as a reader copies it: absolute, as tool paths are."""
    return f"/path/to/{root.name}"


def abridged(value: Any) -> Any:
    """`value` cut to its shape: a long list's first items then `... N more`, a long string's
    head."""
    if isinstance(value, dict):
        return {k: abridged(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        kept = [abridged(v) for v in value[:ABRIDGED_ITEMS]]
        return kept + ([f"... {len(value) - ABRIDGED_ITEMS} more"]
                       if len(value) > ABRIDGED_ITEMS else [])
    if isinstance(value, str) and len(value) > ABRIDGED_CHARS:
        return f"{value[:ABRIDGED_CHARS]} ... ({len(value)} characters)"
    return value


def _shown(tool: str, args: Mapping[str, Any], reply: Reply | None,
           fields: tuple[str, ...]) -> str:
    """One step as the front door shows it: the call, and the reply abridged."""
    call = f"{tool}(" + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}"
                                  for k, v in args.items()) + ")"
    data = None if reply is None else {k: reply.data[k] for k in fields}
    answer = "(no reply)" if data is None else _compact(abridged(data))
    return f"```\n{call}\n-> {answer}\n```"


#: Longest line a small object inside a reply is folded onto.
ONE_LINE_MAX = 100


def _flat(value: dict[str, Any]) -> bool:
    """Whether every value is a scalar or a list of scalars."""
    def scalar(v: Any) -> bool:
        return isinstance(v, (str, int, float, bool)) or v is None
    return all(scalar(v) or (isinstance(v, list) and all(scalar(x) for x in v))
               for v in value.values())


def _compact(value: Any, depth: int = 0) -> str:
    """`value` as indented JSON with a list of scalars on one line: a rect or a point is one
    thought, and a column of numbers is most of a big reply's bytes."""
    pad = "  " * (depth + 1)
    if depth and isinstance(value, dict) and value and _flat(value):
        line = json.dumps(value, ensure_ascii=False)
        if len(line) <= ONE_LINE_MAX:
            return line
    if isinstance(value, dict) and value:
        rows = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {_compact(v, depth + 1)}"
                for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + "\n" + "  " * depth + "}"
    if isinstance(value, list) and value and not all(
            isinstance(v, (str, int, float, bool)) or v is None for v in value):
        rows = [pad + _compact(v, depth + 1) for v in value]
        return "[\n" + ",\n".join(rows) + "\n" + "  " * depth + "]"
    return json.dumps(value, ensure_ascii=False)


def fenced(value: Any) -> str:
    """`value` as a JSON code block."""
    return "```json\n" + _compact(value) + "\n```"


def _entry(n: int, tool: str, args: Mapping[str, Any], reply: Reply | None, line: str,
           highlight: str = "") -> str:
    """One transcript step: verdict line, its highlight, then call and reply folded."""
    parts = [f"**{n}. `{tool}`**: {line}", ""]
    if highlight:
        parts += [highlight, ""]
    parts += ["<details><summary>call and reply</summary>", "", fenced(dict(args))]
    if reply is not None:
        parts += ["", fenced(reply.data)]
        if reply.attachments:
            parts += ["", "Also attached: " + ", ".join(reply.attachments) + "."]
    parts += ["", "</details>"]
    return "\n".join(parts)


@dataclass
class Transcripts:
    """The run's transcripts; every entry goes to each, normalised through `Normaliser`."""

    norm: Normaliser
    flow_norm: Normaliser | None = None
    whole: list[str] = field(default_factory=list)
    normalised: list[str] = field(default_factory=list)
    flow: list[str] = field(default_factory=list)
    story: list[str] = field(default_factory=list)

    def add(self, n: int, tool: str, args: Mapping[str, Any], reply: Reply | None,
            line: str, volatile: Mapping[str, str] | None = None,
            shown: tuple[str, ...] = (), highlight: str = "") -> None:
        self.whole.append(_entry(n, tool, args, reply, line))
        normal = None if reply is None else Reply(self.norm.reply(reply.data, volatile),
                                                  reply.attachments)
        normal_args = self.norm.arguments(dict(args))
        self.normalised.append(_entry(n, tool, normal_args, normal, self.norm.text(line)))
        if highlight:
            self.story.append(_entry(n, tool, normal_args, normal, self.norm.text(line),
                                     highlight))
        if shown:
            spell = self.flow_norm or self.norm
            flow_reply = None if reply is None else Reply(spell.reply(reply.data, volatile),
                                                          reply.attachments)
            self.flow.append(_shown(tool, spell.arguments(dict(args)), flow_reply,
                                    shown))


def _reply(result: CallToolResult) -> Reply:
    """A `CallToolResult` as a `Reply`; one flagged as an error carries no `ok` status."""
    structured = result.structured_content
    data: dict[str, Any] | None = structured if isinstance(structured, dict) else None
    attachments: list[str] = []
    for part in result.content:
        if part.type != "text":
            attachments.append(getattr(part, "mime_type", None) or part.type)
        elif data is None:
            data = _document(part.text)
    data = data if data is not None else {}
    if result.is_error and "status" not in data:
        data = {"status": "error", **data}
    return Reply(data, tuple(attachments))


def _document(text: str) -> dict[str, Any]:
    """`text` as a JSON document, else itself under `text`."""
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _why(e: BaseException) -> str:
    """An exception as one line; the type is named so an empty message still gives a reason."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    text = " ".join(str(e).split())
    return text if isinstance(e, StepFailed) and text else (
        f"{type(e).__name__}: {text}" if text else type(e).__name__)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _refused(reply: Reply, tool: str) -> str:
    """Why a reply that is not `ok` failed its step, in the reply's own words."""
    said = reply.get("summary") or reply.get("message") or reply.get("text") or "no reason given"
    return f"{tool} answered {reply.get('status')!r}: {said}"


@dataclass
class Outcome:
    """A run's stdout lines, transcripts and exit code."""

    lines: list[str]
    transcripts: Transcripts
    code: int = EXIT_PASS


async def _drive(demo: Demo, run: Run, stderr_path: Path, norm: Normaliser) -> Outcome:
    root = norm.root
    out = Outcome([], Transcripts(norm, Normaliser(
        root, norm.home, norm.volatile, norm.host,
        marks={**norm.marks, str(root): placeholder(root)})))
    params = StdioServerParameters(command=demo.server[0], args=list(demo.server[1:]),
                                   cwd=str(demo.root), env=dict(os.environ))
    passed, started = 0, False
    with stderr_path.open("w", encoding="utf-8") as errlog:
        try:
            async with Client(stdio_client(params, errlog=errlog),
                              read_timeout_seconds=CALL_TIMEOUT_S) as client:
                started = True
                closed = False
                for n, step in enumerate(demo.steps, start=1):
                    ok, line, args, reply = await _step(client, step, run)
                    out.lines.append(norm.text(line))
                    out.transcripts.add(n, step.tool, args, reply, line, step.volatile,
                                        step.shown if ok else (), step.highlight)
                    closed = ok and step.tool == CLEANUP_TOOL
                    if not ok:
                        out.code = EXIT_INVALID if line.startswith("INVALID") else EXIT_FAIL
                        break
                    passed += 1
                if not closed:
                    await _cleanup(client, out)
        except Exception as e:  # outside a step
            out.code = EXIT_FAIL if started else EXIT_INVALID
            out.lines.append(
                f"FAIL {demo.name}: the session with the server ended in an error ({_why(e)}); "
                f"its stderr is in {stderr_path}" if started else
                f"INVALID: the server did not start ({_why(e)}); its stderr is in {stderr_path}")
            if not started:
                return out
    if out.code != EXIT_INVALID:              # an INVALID line is the run's last word
        out.lines.append(demo.verdict(len(demo.steps), passed) if demo.verdict else
                         f"DEMO {demo.name}: {prose.counted(len(demo.steps), 'step')}, {passed} OK")
    return out


async def _step(client: Client, step: Step, run: Run
                ) -> tuple[bool, str, Mapping[str, Any], Reply | None]:
    """Run one step: ok, its line, the arguments sent and the reply."""
    args: Mapping[str, Any] = {}
    reply: Reply | None = None
    try:
        built = dict(step.args(run) if callable(step.args) else step.args)
        if step.options:
            built.update({k: v for k, v in run.options.items()
                          if step.options is True or k in step.options})
        args = json.loads(json.dumps(built, default=str))
        reply = _reply(await client.call_tool(step.tool, dict(args)))
        run.replies[step.name] = reply
        if reply.get("status") != "ok":
            raise StepFailed(step.failure(reply, run) if step.failure else
                             _refused(reply, step.tool))
        summary = step.check(reply, run)
        if not isinstance(summary, str):
            raise StepFailed(f"the check returned {summary!r}, not a summary")
        if lacking := [k for k in step.shown if k not in reply]:
            raise StepFailed(f"the front door shows {lacking}, which the reply does not carry")
        return True, f"OK {step.name}: {_one_line(summary)}", args, reply
    except Invalid as e:
        return False, f"INVALID {step.name}: {_one_line(str(e))}", args, reply
    except StepFailed as e:
        return False, f"FAIL {step.name}: {_why(e)}", args, reply
    except Exception as e:
        kind = "INVALID" if step.broken_is_invalid and reply is None else "FAIL"
        return False, f"{kind} {step.name}: {_why(e)}", args, reply


async def _cleanup(client: Client, out: Outcome) -> None:
    """The cleanup call: its answer goes to the whole transcript only, never the verdict."""
    try:
        reply = _reply(await client.call_tool(CLEANUP_TOOL, {}))
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}`:\n\n" + fenced(reply.data))
    except Exception as e:  # the verdict is already formed; this only reports
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}` failed: {_why(e)}")


#: Every option a demo can be given: `--binary` always, the rest where it offers them.
KNOWN_OPTIONS = OFFERABLE | {"binary"}


def _declared(demo: Demo) -> None:
    """Refuse unknown option names and malformed declarations."""
    for step in demo.steps:
        if not isinstance(step.volatile, Mapping):
            raise ValueError(f"step {step.name}: `volatile` is {step.volatile!r}, not a mapping "
                             "of keys to their reasons")
        if not (isinstance(step.shown, tuple) and all(isinstance(k, str) for k in step.shown)):
            raise ValueError(f"step {step.name}: `shown` is {step.shown!r}, not a tuple of the "
                             "reply's field names")
        if not isinstance(step.highlight, str):
            raise ValueError(f"step {step.name}: `highlight` is {step.highlight!r}, not a "
                             "sentence")
        if not isinstance(step.options, bool | frozenset):
            raise ValueError(f"step {step.name}: `options` is {step.options!r}, not True, False "
                             "or a frozenset of option names")
    if demo.loop is not None and demo.loop.after not in {step.name for step in demo.steps}:
        raise ValueError(f"the demo {demo.name}'s Loop follows {demo.loop.after!r}, which is no "
                         "step of it")
    if demo.front is not None and not any(step.shown for step in demo.steps):
        raise ValueError(f"the demo {demo.name} names a front door and shows no step")
    if demo.front is None and any(step.shown for step in demo.steps):
        raise ValueError(f"the demo {demo.name} shows steps and names no front door")
    named = {("offers", n) for n in demo.offers - OFFERABLE} | {
        ("reads", n) for n in demo.reads - KNOWN_OPTIONS} | {
        (f"step {s.name}", n) for s in demo.steps if isinstance(s.options, frozenset)
        for n in s.options - KNOWN_OPTIONS}
    if named:
        raise ValueError(f"the demo {demo.name} names options the runner does not know: "
                         f"{sorted(named)}; it knows {sorted(KNOWN_OPTIONS)}")


def loop_avi(run_dir: Path) -> Path:
    """Where a run records its loop."""
    return run_dir / LOOP_AVI


def loop_mp4(readme: Path) -> Path:
    """The demo's tracked loop, beside its README."""
    return readme.with_name(LOOP_MP4)


def _loop_step(loop: Loop) -> Step:
    """The recording the runner makes on its own, as one call among the demo's steps."""
    def check(reply: Reply, run: Run) -> str:
        path = reply.get("path")
        if not isinstance(path, str):
            raise StepFailed("the reply names no `path`, so what it wrote is unknown")
        if reply.get("began") is not True or reply.get("ended") is not True:
            raise StepFailed(f"the recording at {path} did not both begin and end: the run read "
                             "no file the reply can answer for")
        frames = reply.get("avi_frames")
        if not isinstance(frames, int):
            raise StepFailed(f"the reply names no `avi_frames`, so what {path} holds is unknown")
        if not Path(path).is_file():
            raise StepFailed(f"{path} was not written by this call")
        return f"{frames} frames in {path}"

    return Step("loop", "record",
                lambda run: {"frames": loop.frames, "dest": loop_avi(run.dir)}, check)


def _with_loop(demo: Demo) -> Demo:
    """`demo` with its `Loop`'s recording made a step of its own, right after the one it follows."""
    if demo.loop is None:
        return demo
    steps: list[Step] = []
    for step in demo.steps:
        steps.append(step)
        if step.name == demo.loop.after:
            steps.append(_loop_step(demo.loop))
    return replace(demo, steps=steps)


def _taken(demo: Demo) -> set[str]:
    """The options a step merges or the demo reads."""
    taken = set(demo.reads)
    for step in demo.steps:
        taken |= KNOWN_OPTIONS if step.options is True else set(step.options or ())
    return taken


def _parser(demo: Demo) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"demos/{demo.name}/demo.py", allow_abbrev=False,
                                description=f"Run the {demo.name} demo against its server.",
                                epilog="Exit codes: 0 every step OK, 1 a step failed, 2 a usage "
                                       "error, 3 nothing was demonstrated.")
    p.add_argument("--binary", help="the emulator to start; left out, the server's own ladder")
    if "cwd" in demo.offers:
        p.add_argument("--cwd", help="the directory the emulator runs from, absolute or ~-led: "
                                     "your own copy of the program")
    if "rompath" in demo.offers:
        p.add_argument("--rompath", help="the directory holding the set's zip")
    if "shared" in demo.offers:
        p.add_argument("--shared", action="store_true", default=None,
                       help="somebody watches: a big window at real speed")
    if "display" in demo.offers:
        p.add_argument("--display", type=int,
                       help="the display the emulator's window opens on, 0 the main one")
    p.add_argument("--transcript", type=Path,
                   help="where the whole transcript goes; the run's other files go beside it")
    p.add_argument("--update-readme", action="store_true",
                   help="rewrite the README's transcript block, screen.png and the loop from "
                        "this run")
    return p


def main(demo: Demo, argv: Sequence[str] | None = None) -> int:
    """Run `demo` as its command line asks; answer the exit code."""
    _declared(demo)
    ns = _parser(demo).parse_args(argv)
    transcript: Path = (ns.transcript or demo.root / "tmp" / "demos" / demo.name
                        / "transcript.md").resolve()
    given = {"binary": ns.binary, "cwd": getattr(ns, "cwd", None),
             "rompath": getattr(ns, "rompath", None),
             "shared": getattr(ns, "shared", None),
             "display": getattr(ns, "display", None)}
    if empty := [k for k in ("binary", "cwd", "rompath") if given[k] == ""]:
        print(f"INVALID: --{empty[0]} names a path, and an empty one names nothing")
        return EXIT_INVALID
    run = Run(dir=transcript.parent, options={k: v for k, v in given.items() if v is not None})
    try:
        code = execute(demo, run, transcript, ns.update_readme)
    except Invalid as e:
        print(f"INVALID: {e}")
        code = EXIT_INVALID
    except Exception as e:  # INVALID, never a traceback
        print(f"INVALID: {_why(e)}")
        code = EXIT_INVALID
    sys.stdout.flush()
    return code


def execute(demo: Demo, run: Run, transcript: Path, update_readme: bool = False) -> int:
    """Run `demo`, write its transcripts at `transcript`, answer the exit code; `Invalid` stops
    it before a verdict."""
    if not demo.steps:
        raise Invalid(f"the demo {demo.name} declares zero steps, so it demonstrates nothing")
    demo = _with_loop(demo)
    untaken = set(run.options) - _taken(demo)
    if untaken:
        raise Invalid(f"options {sorted(untaken)} were given and nothing in the demo "
                      f"{demo.name} takes them")
    if update_readme:
        if demo.readme is None or demo.capture is None:
            raise _no_readme(demo)
        block_span(demo.readme.read_text(encoding="utf-8"))
        if demo.front is not None:
            block_span(demo.front.read_text(encoding="utf-8"), flow_begin(demo.name),
                       flow_end(demo.name))
    why = demo.precheck(run) if demo.precheck else ""
    if why:
        raise Invalid(why)
    run.dir.mkdir(parents=True, exist_ok=True)
    capture = demo.capture(run) if demo.capture is not None else None
    if capture is not None:
        capture.unlink(missing_ok=True)  # only this run's picture may reach the README
    if demo.loop is not None:
        loop_avi(run.dir).unlink(missing_ok=True)  # nor an earlier run's recording
    norm = Normaliser(demo.root.resolve(), Path.home().resolve(),
                      {**VOLATILE, **demo.volatile}, demo.host_args)
    normalised, flow, story = _beside(transcript)
    flow.unlink(missing_ok=True)  # only this run's flow may reach the front door
    story.unlink(missing_ok=True)
    out = asyncio.run(_drive(demo, run, run.dir / "server.stderr", norm))
    if out.transcripts.whole:
        transcript.write_text("\n\n".join(out.transcripts.whole) + "\n", encoding="utf-8")
        normalised.write_text("\n\n".join(out.transcripts.normalised) + "\n", encoding="utf-8")
    if out.transcripts.flow:
        flow.write_text("\n\n".join(out.transcripts.flow) + "\n", encoding="utf-8")
    if out.transcripts.story:
        story.write_text(_story(out.transcripts.story, len(demo.steps)), encoding="utf-8")
    for line in out.lines:
        print(line)
    if out.transcripts.whole:
        print(f"transcript: {transcript}")
        print(f"normalised: {normalised}")
    if out.code == EXIT_PASS and update_readme and capture is not None and demo.readme:
        _update_readmes(demo, run, demo.readme, capture, normalised, flow, story)
    return out.code


def load(demo_file: Path) -> Demo:
    """The `DEMO` a demo file declares, imported without running its command line."""
    spec = importlib.util.spec_from_file_location(f"demo_{demo_file.parent.name}", demo_file)
    if spec is None or spec.loader is None:
        raise TypeError(f"{demo_file} cannot be imported")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = getattr(module, "DEMO", None)
    if not isinstance(found, Demo):
        raise TypeError(f"{demo_file}'s DEMO is {found!r}, not a Demo")
    return found


def _beside(transcript: Path) -> tuple[Path, Path, Path]:
    """The normalised transcript, the front door's flow and the README's highlights, written
    beside `transcript`."""
    stem = file_names.word(transcript.stem, "transcript")
    def beside(part: str) -> Path:
        return transcript.with_name(file_names.name(stem, part, extension="md"))
    return beside("normalised"), beside("flow"), beside("story")


def _story(entries: list[str], calls: int) -> str:
    """The README block of a highlighted demo: what it holds, the highlights, the link."""
    return (f"The run is {prose.counted(calls, 'call')}; these are the ones that show how it is "
            f"done, and every call with its reply is in [{FULL_NAME}]({FULL_NAME}).\n\n"
            + "\n\n".join(entries) + "\n")


def highlighted(demo: Demo) -> bool:
    return any(step.highlight for step in demo.steps)


def stale(demo: Demo, run_dir: Path) -> list[str]:
    """How the committed README block, flow and picture depart from the run in `run_dir`, one
    line each, or empty."""
    normalised, flow, story = _beside(run_dir / "transcript.md")
    highlights = highlighted(demo)
    needed = ([story if highlights else normalised, *([normalised] if highlights else [])]
              if demo.readme is not None else []) + ([flow] if demo.front is not None else [])
    if missing := [path.name for path in needed if not path.is_file()]:
        return [f"{demo.name}: the run in {run_dir} wrote no {', '.join(missing)}"]
    found = []
    if demo.readme is not None and (drift := readme_drift(
            demo.readme, story if highlights else normalised)):
        found.append(f"{demo.name}'s README: {drift}")
    if demo.readme is not None:
        whole = demo.readme.with_name(FULL_NAME)
        if not highlights and whole.is_file():
            found.append(f"{demo.name}'s {FULL_NAME} is committed and the demo has no highlight")
        elif highlights and not whole.is_file():
            found.append(f"{demo.name}'s {FULL_NAME} is not committed")
        elif highlights and (drift := first_difference(
                whole.read_text(encoding="utf-8").strip("\n"),
                normalised.read_text(encoding="utf-8").strip("\n"), (FULL_NAME, "the run"))):
            found.append(f"{demo.name}'s {FULL_NAME}: {drift}")
    if demo.front is not None and (drift := flow_drift(demo.front, demo.name, flow)):
        found.append(f"the front door's {demo.name} flow: {drift}")
    if demo.readme is not None and demo.capture is not None:
        shot, committed = demo.capture(Run(dir=run_dir)), demo.readme.with_name("screen.png")
        if not same_picture(shot, committed):
            found.append(f"{demo.name}'s screen.png is not this run's capture")
    if demo.readme is not None and demo.loop is not None \
            and not loop_mp4(demo.readme).is_file():
        found.append(f"{demo.name}'s {LOOP_MP4} is not committed")
    return found


def same_picture(a: Path, b: Path) -> bool:
    """Whether two files hold the same picture: the same bytes, or the same pixels, because each
    host's zlib compresses one raster into different bytes."""
    if not (a.is_file() and b.is_file()):
        return False
    x, y = a.read_bytes(), b.read_bytes()
    if x == y:
        return True
    try:
        return png.decode(x) == png.decode(y)
    except png.NotAPicture:
        return False


def _convert_loop(avi: Path, mp4: Path) -> bytes:
    """The run's AVI converted for `mp4`, refused past the loop's budget. The conversion lands in
    the run's own directory, so a refusal or a failure leaves the committed `mp4` as it was."""
    if not avi.is_file():
        raise Invalid(f"this run wrote no {avi.name} at {avi}, so there is no loop to convert")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise Invalid("ffmpeg is not on PATH, and the loop is converted with it")
    converted = avi.with_name(LOOP_MP4)
    done = subprocess.run([ffmpeg, "-y", "-i", str(avi), "-t", str(LOOP_SECONDS), "-an",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "30",
                           "-preset", "slow", "-movflags", "+faststart", str(converted)],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        converted.unlink(missing_ok=True)
        said = done.stderr.strip().splitlines()
        raise Invalid(f"ffmpeg refused to convert {avi} (exit {done.returncode}): "
                      f"{said[-1] if said else 'no words'}")
    size = converted.stat().st_size
    data = converted.read_bytes()
    converted.unlink()
    if size > LOOP_BUDGET_BYTES:
        raise Invalid(f"the loop {mp4} is {size} bytes, past the {LOOP_BUDGET_BYTES}-byte "
                      "budget: record fewer frames, or let the demo show less")
    return data


def _no_readme(demo: Demo) -> Invalid:
    return Invalid(f"the demo {demo.name} has no README block to update")


def _update_readmes(demo: Demo, run: Run, readme: Path, capture: Path, normalised: Path,
                    flow: Path, story: Path) -> None:
    """Rewrite the README block, picture and flow; every text is built before any file is
    written, so a failure leaves all as they were."""
    if not capture.is_file():
        raise Invalid(f"the capture {capture} was not written by this run, so the README was "
                      "left as it was")
    text = with_block(readme.read_text(encoding="utf-8"),
                      (story if highlighted(demo) else normalised).read_text(encoding="utf-8"))
    front = None if demo.front is None else with_block(
        demo.front.read_text(encoding="utf-8"), flow.read_text(encoding="utf-8"),
        flow_begin(demo.name), flow_end(demo.name))
    loop = loop_mp4(readme) if demo.loop is not None else None
    converted = None if loop is None else _convert_loop(loop_avi(run.dir), loop)
    shutil.copyfile(capture, readme.with_name("screen.png"))
    if highlighted(demo):
        shutil.copyfile(normalised, readme.with_name(FULL_NAME))
    readme.write_text(text, encoding="utf-8")
    print(f"README: {readme} block and screen.png rewritten")
    if demo.front is not None and front is not None:
        demo.front.write_text(front, encoding="utf-8")
        print(f"README: {demo.front} flow {demo.name} rewritten")
    if loop is not None and converted is not None:
        fresh.replace(loop, converted, "the demo's loop")
        print(f"README: {loop} rewritten")
