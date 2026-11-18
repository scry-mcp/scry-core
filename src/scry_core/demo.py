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
the run did not write, a moment its recordings do not hold, a loop that could not be made).
`execute` is the run without its command line. The run ends with the cleanup call unless its
last step made it, so no emulator outlives it.

`--update-readme` rewrites the README blocks, the capture, the loop and the `Demo.front` flow
only after a run whose every step was OK.

The steps that carry an `ask` are the demo's examples, each in the one shape `example` renders:
they are the README block, and the `Demo.front` flow without their whole replies. The whole
normalised run is committed beside the README as `FULL_NAME`. `--update-readme` asks for
`TRY_STEPS` of them.

A demo with a `Lead` opens its repository's README: its loop, large and centred and linked to
its page, a caption, and one step of the run as an exchange (what was asked, the call, the
answer, and with `Lead.learns` what the step's check read in it), between the README's
`lead_begin` and `lead_end` markers.

A demo's `Moment`s are what its `loop.webp` shows, cut from the run's own recordings by
`motion`: the file a `record` step wrote, or the video of a session that records itself
(`Demo.video`), cut by the `frame` the replies carry. The README's motion block holds the
picture and each moment's sentence. `stale` asks only that the loop is committed, never that its
bytes are the run's: a recording is not byte-stable.

Normalisation hides what differs between two honest runs and nothing else: `$HOME` as `~`, the
repository root as `.`, the values of `VOLATILE` keys (and the demo's and step's own) in a reply
as `<volatile>`, a written picture's `bytes` and `sha256` (the pixels are the run's, the bytes
the host zlib's), and of `host_args` keys in a call's arguments as `<host>`; a step's `optional`
keys, which a server sends only sometimes, are left out whether they came or not. Hiding is by
key, so a reply echoing a host argument needs that key in `volatile` too. A value the demo shows
is never hidden: if it differs between runs the demo is wrong. A step's summary is never searched
for volatile values, so it quotes only what the demo shows.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

from scry_core import example, file_names, fresh, motion, png, prose
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

BEGIN = "<!-- demo-transcript:begin -->"
END = "<!-- demo-transcript:end -->"
FULL_NAME = "TRANSCRIPT.md"
VOLATILE_MARK = "<volatile>"

MOTION_BEGIN = "<!-- demo-motion:begin -->"
MOTION_END = "<!-- demo-motion:end -->"
#: The heading level of a step to try on a demo's own page, and in a README's example calls.
TRY_LEVEL, FLOW_LEVEL = 3, 4
HOST_MARK = "<host>"

#: The steps a demo's README offers to try, fewest and most.
TRY_STEPS = (2, 4)
#: The most words of a moment's one sentence.
CAPTION_WORDS = 25
#: The fields an example's excerpt shows when its step names none.
EXCERPT = ("summary",)
#: The tool whose reply names the AVI it wrote, and the reply key every stop counts frames in.
RECORD_TOOL = "record"
FRAME_KEY = "frame"
#: The wall-clock seconds a recording may take: an emulator under its debugger can run well
#: below real speed, and a recording cut at its bound fails the step.
RECORD_SECONDS = 300

#: The tool every Scry server ends a session with.
CLEANUP_TOOL = "close"

#: Every Scry tool bounds its own waits at 600 s, so past this a server will not answer.
CALL_TIMEOUT_S = 900

#: The options a demo can offer beyond `--binary`, as its server's `start` spells them.
OFFERABLE = frozenset({"cwd", "rompath", "shared", "display"})

#: The reason a demo's `host_args` gives for hiding which display a run's window opened on.
DISPLAY = "the host's display layout"


def window_args(run: Run) -> dict[str, Any]:
    """What a demo's `start` asks of the window: watched, behind so it takes nobody's focus, on
    the display `--display` names and the host's main one otherwise."""
    return {"shared": True, "background": True, "display": run.options.get("display", 0)}

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

#: What a recording reports of the machine it ran: it begins where the demo left the machine, and
#: how many frames it got from there, the clock and cycles at both ends, the place it stopped with
#: the survey of that stop, and the file's size all follow that start.
RECORDING_TIMING: Mapping[str, str] = {
    key: "it follows where the recording began, which the host reached"
    for key in ("summary", "frame", "frame_before", "frame_after", "frame_begin", "frame_end",
                "avi_frames", "bytes", "cycles", "emulated_before_s", "emulated_after_s", "polls",
                "stop_seq", "pc", "cpu_mode", "regs", "instruction", "following", "watches",
                "watch_hit", "regpoint_hit", "e9", "cause", "note")}


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
    in this step alone, and `optional` drops from its transcript keys a server sends only
    sometimes, each with its reason. `failure` words the FAIL of a non-`ok` reply. A check raising
    `Invalid` ends the run INVALID."""

    name: str
    tool: str
    args: Args
    check: Callable[[Reply, Run], str]
    options: bool | frozenset[str] = False
    volatile: Mapping[str, str] = field(default_factory=dict)
    optional: Mapping[str, str] = field(default_factory=dict)
    failure: Callable[[Reply, Run], str] | None = None
    #: An exception in the call itself (timeout, server gone) is INVALID rather than FAIL.
    broken_is_invalid: bool = False
    #: What a person would type to get this call: the step is one of the demo's examples, with
    #: `title` heading it and `reads` saying how to read the reply.
    ask: str = ""
    title: str = ""
    reads: str = ""
    #: The reply's fields an example's excerpt shows, `EXCERPT` when none is named. A named
    #: field the reply lacks fails the step, so a page never shows a stale shape.
    shown: tuple[str, ...] = ()


@dataclass(frozen=True)
class Moment:
    """A stretch of the run the demo's loop shows: what the screen did from the end of step
    `after` to the end of step `until`, with `caption` as its one sentence. `until` is a
    `record` step right after `after`, or any later step of a session that records itself.
    `frames` of the stretch are shown from its frame `skip`; 0 shows it to its end."""

    after: str
    until: str
    caption: str
    skip: int = 0
    frames: int = 0


@dataclass(frozen=True)
class Lead:
    """How a demo opens the README `front`: its loop linked to its own page, `caption` under
    it, then step `step` as an exchange: `ask`, the call, and the `answer` fields of its reply
    on one line; with `learns`, the step's check reads the reply in plain words under it."""

    front: Path
    step: str
    ask: str
    caption: str
    answer: tuple[str, ...] = ("summary",)
    learns: bool = False


#: Characters of a long string a lead's call keeps at each end: a phone wraps the call only
#: between its arguments, so a value is as wide as the table's cell can hold.
LEAD_STRING_ENDS = 4


def narrow(value: Any) -> Any:
    """`value` with every string longer than a phone's cell holds cut to `LEAD_STRING_ENDS`
    characters at each end, however short the whole call is."""
    if isinstance(value, str) and len(value) > 2 * LEAD_STRING_ENDS + len(example.ELIDED):
        return value[:LEAD_STRING_ENDS] + example.ELIDED + value[-LEAD_STRING_ENDS:]
    if isinstance(value, dict):
        return {k: narrow(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [narrow(v) for v in value]
    return value


@dataclass(frozen=True)
class Demo:
    """A demo as declared. `offers` names the `OFFERABLE` options it accepts,
    `reads` those it reads from `run.options` itself. `capture` is the image one step writes in
    `run.dir`. `precheck` answers why the demo cannot run, or empty. `host_args` maps argument
    keys that are the host's own to their reasons. `verdict` words the last line. `moments` are
    what the loop shows, `alt` says what moves in it, and `video` is the folder a session that
    records itself writes its video in."""

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
    moments: Sequence[Moment] = ()
    alt: str = ""
    video: Callable[[Run], Path] | None = None
    lead: Lead | None = None


def flow_begin(name: str) -> str:
    return f"<!-- demo-flow:begin {name} -->"


def flow_end(name: str) -> str:
    return f"<!-- demo-flow:end {name} -->"


def lead_begin(name: str) -> str:
    return f"<!-- demo-lead:begin {name} -->"


def lead_end(name: str) -> str:
    return f"<!-- demo-lead:end {name} -->"


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

    def reply(self, value: Any, also: Mapping[str, str] | None = None,
              dropped: Collection[str] = ()) -> Any:
        """A reply with paths spelled, volatile keys' values hidden, `also` included, and the
        `dropped` keys left out."""
        return self._value(value, {**self.volatile, **(also or {})}, VOLATILE_MARK,
                           frozenset(dropped))

    def arguments(self, value: Any) -> Any:
        """The demo's arguments with paths spelled and host-owned keys hidden."""
        return self._value(value, self.host, HOST_MARK)

    def _value(self, value: Any, hidden: Mapping[str, str], mark: str,
               dropped: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, dict) and mark == VOLATILE_MARK and _picture(value):
            hidden = {**hidden, **PICTURE_VOLATILE}
        if isinstance(value, dict):
            return {self.text(k): mark if k in hidden else self._value(v, hidden, mark, dropped)
                    for k, v in value.items() if k not in dropped}
        if isinstance(value, list | tuple):
            return [self._value(v, hidden, mark, dropped) for v in value]
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


def _entry(n: int, tool: str, args: Mapping[str, Any], reply: Reply | None, line: str) -> str:
    """One transcript step: verdict line, then call and reply folded."""
    parts = [f"**{n}. `{tool}`**: {line}", "",
             "<details><summary>call and reply</summary>", "", example.fenced(dict(args))]
    if reply is not None:
        parts += ["", example.fenced(reply.data)]
        if reply.attachments:
            parts += ["", "Also attached: " + ", ".join(reply.attachments) + "."]
    parts += ["", "</details>"]
    return "\n".join(parts)


@dataclass
class Transcripts:
    """The run's transcripts; every entry goes to each, normalised through `Normaliser`."""

    norm: Normaliser
    flow_norm: Normaliser | None = None
    lead: Lead | None = None
    whole: list[str] = field(default_factory=list)
    normalised: list[str] = field(default_factory=list)
    flow: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    #: The lead step's call, its answer and what its check read in it, as a README spells them.
    exchange: tuple[str, str, str] | None = None

    def answered(self, step: Step, reply: Reply) -> str:
        """The lead's answer off `reply` as a README spells it, which is the text the step is
        judged by; `ValueError` when the reply cannot give it on one line."""
        if self.lead is None:
            raise ValueError(f"step {step.name} is no lead's")
        spell = self.flow_norm or self.norm
        return example.answer(spell.reply(reply.data, step.volatile, step.optional),
                              self.lead.answer)

    def add(self, n: int, step: Step, args: Mapping[str, Any], reply: Reply | None,
            line: str, ok: bool) -> None:
        """One step's entry in every transcript; a step that passed with an `ask` is an example
        too, and the lead's step is the README's exchange."""
        tool, optional = step.tool, step.optional
        tried = ok and bool(step.ask)
        spell = self.flow_norm or self.norm
        if ok and reply is not None and self.lead is not None and step.name == self.lead.step:
            learned = spell.text(line).removeprefix(f"OK {step.name}: ")
            self.exchange = (example.call_text(tool, narrow(spell.arguments(dict(args))),
                                               lines=1),
                             self.answered(step, reply), learned if self.lead.learns else "")
        self.whole.append(_entry(n, tool, args, reply, line))
        normal = None if reply is None else Reply(
            self.norm.reply(reply.data, step.volatile, optional), reply.attachments)
        normal_args = self.norm.arguments(dict(args))
        self.normalised.append(_entry(n, tool, normal_args, normal, self.norm.text(line)))
        if not tried or reply is None or normal is None:
            return
        number = len(self.examples) + 1
        fields = step.shown or EXCERPT
        self.examples.append(example.render(example.Example(
            step.ask, tool, normal_args, normal.data, fields, step.reads, step.title), number,
            level=TRY_LEVEL))
        self.flow.append(example.render(example.Example(
            step.ask, tool, spell.arguments(dict(args)),
            spell.reply(reply.data, step.volatile, optional), fields, step.reads, step.title),
            number, whole=False, level=FLOW_LEVEL))


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
        marks={**norm.marks, str(root): placeholder(root)}), demo.lead))
    led = demo.lead.step if demo.lead is not None else None
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
                    ok, line, args, reply = await _step(
                        client, step, run, out.transcripts.answered if step.name == led else None)
                    out.lines.append(norm.text(line))
                    out.transcripts.add(n, step, args, reply, line, ok)
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


async def _step(client: Client, step: Step, run: Run,
                answered: Callable[[Step, Reply], str] | None = None
                ) -> tuple[bool, str, Mapping[str, Any], Reply | None]:
    """Run one step: ok, its line, the arguments sent and the reply. `answered` gives what a
    README's exchange shows of it, and refuses a reply that cannot say it on one line."""
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
        try:
            if step.ask:
                example.excerpt(reply.data, step.shown or EXCERPT)
            if answered is not None:
                answered(step, reply)
        except ValueError as e:
            raise StepFailed(str(e)) from e
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
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}`:\n\n"
                                     + example.fenced(reply.data))
    except Exception as e:  # the verdict is already formed; this only reports
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}` failed: {_why(e)}")


#: Every option a demo can be given: `--binary` always, the rest where it offers them.
KNOWN_OPTIONS = OFFERABLE | {"binary"}


def declared(demo: Demo) -> None:
    """Refuse, as `ValueError`, what a demo declares wrongly, before any call: unknown option
    names, a step that is no step, an example or a moment past its limits."""
    for step in demo.steps:
        for declared in ("volatile", "optional"):
            if not isinstance(getattr(step, declared), Mapping):
                raise ValueError(f"step {step.name}: `{declared}` is "
                                 f"{getattr(step, declared)!r}, not a mapping of keys to their "
                                 "reasons")
        if not (isinstance(step.shown, tuple) and all(isinstance(k, str) for k in step.shown)):
            raise ValueError(f"step {step.name}: `shown` is {step.shown!r}, not a tuple of the "
                             "reply's field names")
        if step.ask or step.reads or step.title:
            example.checked(f"step {step.name}", step.ask, step.reads)
            if not step.title.strip():
                raise ValueError(f"step {step.name}: an example carries a `title`, the few "
                                 "words that head it")
            hidden = {*VOLATILE, *demo.volatile, *step.volatile}
            if shown_hidden := sorted(set(step.shown or EXCERPT) & hidden):
                raise ValueError(f"step {step.name}: its example shows {shown_hidden}, which "
                                 "the transcript hides as the host's: show fields that read "
                                 "the same on every run")
        if not isinstance(step.options, bool | frozenset):
            raise ValueError(f"step {step.name}: `options` is {step.options!r}, not True, False "
                             "or a frozenset of option names")
        if shown_dropped := sorted(set(step.optional) & set(step.shown)):
            raise ValueError(f"step {step.name}: `optional` drops {shown_dropped}, and `shown` "
                             "shows it: a key a page shows comes every run")
    names = [step.name for step in demo.steps]
    if twice := sorted({name for name in names if names.count(name) > 1}):
        raise ValueError(f"the demo {demo.name} names {twice} more than once: a step's reply is "
                         "kept under its name, and a moment is found by it")
    _moments_declared(demo)
    _lead_declared(demo)
    if demo.front is not None and not any(step.ask for step in demo.steps):
        raise ValueError(f"the demo {demo.name} names a front door and no step carries an "
                         "`ask` to show there")
    named = {("offers", n) for n in demo.offers - OFFERABLE} | {
        ("reads", n) for n in demo.reads - KNOWN_OPTIONS} | {
        (f"step {s.name}", n) for s in demo.steps if isinstance(s.options, frozenset)
        for n in s.options - KNOWN_OPTIONS}
    if named:
        raise ValueError(f"the demo {demo.name} names options the runner does not know: "
                         f"{sorted(named)}; it knows {sorted(KNOWN_OPTIONS)}")


def _moments_declared(demo: Demo) -> None:
    """Refuse moments the demo's own steps cannot give, before a call is made."""
    names = [step.name for step in demo.steps]
    tools = {step.name: step.tool for step in demo.steps}
    if len(demo.moments) > motion.CUTS_MAX:
        raise ValueError(f"the demo {demo.name} declares {len(demo.moments)} moments, and a "
                         f"loop shows at most {motion.CUTS_MAX}")
    if demo.moments and not demo.alt.strip():
        raise ValueError(f"the demo {demo.name} shows moments and its `alt` does not say what "
                         "moves")
    for moment in demo.moments:
        if unknown := [name for name in (moment.after, moment.until) if name not in names]:
            raise ValueError(f"a moment of the demo {demo.name} names {unknown}, which "
                             f"{'is' if len(unknown) == 1 else 'are'} no step of it")
        gap = names.index(moment.until) - names.index(moment.after)
        if tools[moment.until] == RECORD_TOOL and gap != 1:
            raise ValueError(f"the moment until {moment.until!r} is a recording, so it shows "
                             f"what followed the step before it, not {moment.after!r}")
        if tools[moment.until] != RECORD_TOOL and (gap < 1 or demo.video is None):
            raise ValueError(f"the moment from {moment.after!r} to {moment.until!r} needs "
                             f"{moment.until!r} after {moment.after!r} and the demo's `video`, "
                             "the folder its session records itself in")
        if moment.skip < 0 or moment.frames < 0:
            raise ValueError(f"the moment until {moment.until!r}: `skip` and `frames` count "
                             "frames, so neither is negative")
        if not moment.caption.strip() or example.words(moment.caption) > CAPTION_WORDS \
                or example.sentences(moment.caption) != 1:
            raise ValueError(f"the moment until {moment.until!r}: its caption is one sentence "
                             f"of at most {CAPTION_WORDS} words")


def _lead_declared(demo: Demo) -> None:
    """Refuse a lead the demo's own declarations cannot give, before a call is made."""
    lead = demo.lead
    if lead is None:
        return
    if demo.readme is None or not demo.moments:
        raise ValueError(f"the demo {demo.name} opens a README with its loop, and it declares "
                         "no moment or no page of its own")
    if lead.front.resolve() == demo.readme.resolve():
        raise ValueError(f"the demo {demo.name}: its lead opens the demo's own page, which the "
                         "run rewrites from its own blocks")
    if lead.front.parent.resolve() not in demo.readme.resolve().parents:
        raise ValueError(f"the demo {demo.name}: its lead opens {lead.front}, and the demo's "
                         "own page is not under that folder, so no link reaches it")
    steps = {step.name: step for step in demo.steps}
    if lead.step not in steps:
        raise ValueError(f"the demo {demo.name}: its lead names the step {lead.step!r}, which "
                         "is no step of it")
    if not (isinstance(lead.answer, tuple) and lead.answer
            and all(isinstance(k, str) for k in lead.answer)):
        raise ValueError(f"the demo {demo.name}: its lead's `answer` is {lead.answer!r}, not a "
                         "tuple of the reply's field names")
    step = steps[lead.step]
    hidden = {*VOLATILE, *demo.volatile, *step.volatile, *step.optional}
    if answer_hidden := sorted(set(lead.answer) & hidden):
        raise ValueError(f"the demo {demo.name}: its lead answers with {answer_hidden}, which "
                         "the transcript hides as the host's or drops: answer with fields that "
                         "read the same on every run")
    if not lead.ask.strip() or example.words(lead.ask) > example.ASK_WORDS:
        raise ValueError(f"the demo {demo.name}: its lead's `ask` is {example.words(lead.ask)} "
                         f"words, and an ask is 1 to {example.ASK_WORDS}")
    if not lead.caption.strip() or example.words(lead.caption) > CAPTION_WORDS \
            or example.sentences(lead.caption) != 1:
        raise ValueError(f"the demo {demo.name}: its lead's caption is one sentence of at most "
                         f"{CAPTION_WORDS} words")


def recorded(frames: int, said: Callable[[Reply, Run], str] | None = None
             ) -> Callable[[Reply, Run], str]:
    """The check of a `record` step a moment shows: the AVI began, ended at its last frame and
    is on disk. `said` words the summary."""
    def check(reply: Reply, run: Run) -> str:
        path = reply.get("path")
        if not isinstance(path, str):
            raise StepFailed("the reply names no `path`, so what it wrote is unknown")
        if reply.get("began") is not True or reply.get("ended") is not True:
            raise StepFailed(f"the recording at {path} did not both begin and end: the run read "
                             "no file the reply can answer for")
        if not isinstance(reply.get("avi_frames"), int):
            raise StepFailed(f"the reply names no `avi_frames`, so what {path} holds is unknown")
        if reply.get("verdict") != "ELAPSED":
            raise StepFailed(f"the recording at {path} ended {reply.get('verdict')!r}: a bound or "
                             "a stop cut it, so the file is not the stretch the demo asked for")
        if not Path(path).is_file():
            raise StepFailed(f"{path} was not written by this call")
        return said(reply, run) if said else f"recorded {frames} frames in {path}"
    return check


def recording(name: str, frames: int, said: Callable[[Reply, Run], str] | None = None) -> Step:
    """A step that records `frames` frames into the run's directory, for a `Moment` to show: the
    machine runs them, so the step stands where the demo would otherwise let it run."""
    def args(run: Run) -> dict[str, Any]:
        dest = run.dir / file_names.name(file_names.word(name, "the step's name"),
                                         extension="avi")
        dest.unlink(missing_ok=True)  # `record` writes only a file that is not there yet
        return {"frames": frames, "dest": dest, "seconds": RECORD_SECONDS}

    return Step(name, RECORD_TOOL, args, recorded(frames, said), volatile=RECORDING_TIMING)


def _last(value: Any, key: str) -> int | None:
    """The last whole number under `key` anywhere in `value`, in the order it was written."""
    found = None
    if isinstance(value, Mapping):
        for k, v in value.items():
            inner = v if k == key and isinstance(v, int) and not isinstance(v, bool) \
                else _last(v, key)
            found = inner if inner is not None else found
    elif isinstance(value, list | tuple):
        for v in value:
            inner = _last(v, key)
            found = inner if inner is not None else found
    return found


def _span(demo: Demo, run: Run, moment: Moment) -> tuple[Path, int, int]:
    """Where the stretch from `moment.after` to `moment.until` sits in the session's own video:
    the file, its first frame and how many. The video's last frame is the last one any reply
    counted, so a frame number is a place counted back from the end. A step whose reply counts
    no frame did not move the machine: it stands at the last frame counted before it. A video
    longer than the last frame counted says a later step moved the machine uncounted, and is
    refused: every place would be read that many frames late."""
    if demo.video is None:
        raise Invalid(f"the demo {demo.name} names no `video` for its moments")
    folder = demo.video(run)
    files = sorted(folder.glob("*.avi"))
    if not files:
        raise Invalid(f"the session wrote no video in {folder}, so there is no moment to cut")
    counted: dict[str, int] = {}
    for name, reply in run.replies.items():
        frame = _last(reply.data, FRAME_KEY)
        if frame is not None or counted:
            counted[name] = frame if frame is not None else list(counted.values())[-1]
    if lacking := [name for name in (moment.after, moment.until) if name not in counted]:
        raise Invalid(f"no reply up to step {lacking[0]!r} counts a `{FRAME_KEY}`, so the moment "
                      "it bounds cannot be found in the video")
    latest = list(counted.values())[-1]
    held = [motion.facts(file)[0] for file in files]
    if sum(held) > latest:
        raise Invalid(f"the session's video holds {sum(held)} frames and the last reply to count "
                      f"one counts frame {latest}: a step after it moved the machine without "
                      "counting, so end the run's last advance with a step whose reply counts "
                      f"its `{FRAME_KEY}`")
    first = sum(held) - (latest - counted[moment.after])
    frames = counted[moment.until] - counted[moment.after]
    before = 0
    for file, n in zip(files, held, strict=True):
        if before <= first and first + frames <= before + n:
            return file, first - before, frames
        before += n
    each = ", ".join(f"{file.name}: {n}" for file, n in zip(files, held, strict=True))
    raise Invalid(f"the moment from {moment.after!r} to {moment.until!r} is frames {first} to "
                  f"{first + frames - 1} of the session's video, which no one file of {folder} "
                  f"holds whole ({each})")


def cuts(demo: Demo, run: Run) -> list[motion.Cut]:
    """The demo's moments as cuts of the recordings this run wrote."""
    tools = {step.name: step.tool for step in demo.steps}
    found = []
    for moment in demo.moments:
        if tools[moment.until] == RECORD_TOOL:
            reply = run.replies[moment.until]
            source, first, held = Path(str(reply["path"])), 0, int(reply["avi_frames"])
        else:
            source, first, held = _span(demo, run, moment)
        if moment.skip >= held:
            raise Invalid(f"the moment until {moment.until!r} skips {moment.skip} frames of a "
                          f"stretch of {held}")
        frames = moment.frames or held - moment.skip
        if moment.skip + frames > held:
            raise Invalid(f"the moment until {moment.until!r} shows frames {moment.skip} to "
                          f"{moment.skip + frames - 1} of a stretch of {held}: it would run on "
                          "into what the next step did")
        found.append(motion.Cut(source, first + moment.skip, frames))
    return found


def _moving(alt: str, folder: str = "") -> str:
    """The loop in `folder`, with the still for a reader who asks for no motion."""
    return ('<picture><source media="(prefers-reduced-motion: reduce)" '
            f'srcset="{folder}screen.png"><img src="{folder}{motion.LOOP_NAME}" '
            f'alt="{html.escape(alt, quote=True)}"></picture>')


def _inline(text: str) -> str:
    """A hand-written sentence as HTML: its marks escaped, its `code` in code type."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text, quote=False))


def motion_block(demo: Demo, cut_ms: Sequence[int]) -> str:
    """The README's motion block: the loop, centred, with the still for a reader who asks for no
    motion, each moment's sentence under it, and how long each lasts for a page that lights them
    in time."""
    captions = [f"{n}. {moment.caption}" for n, moment in enumerate(demo.moments, start=1)]
    return "\n".join([f'<p align="center">{_moving(demo.alt)}</p>', "", *captions, "",
                      f"<!-- moments-ms: {','.join(str(ms) for ms in cut_ms)} -->"])


def lead_block(demo: Demo, lead: Lead, readme: Path, call: str, answer: str,
               learned: str) -> str:
    """What opens the README `lead.front`: the demo's loop, centred and linked to its page,
    its caption, and the exchange as a table of three rows, a fourth with what was `learned`."""
    folder = readme.resolve().parent.relative_to(lead.front.resolve().parent).as_posix() + "/"
    rows = (("You ask", _inline(lead.ask)),
            ("Your client calls", f"<code>{html.escape(call, quote=False)}</code>"),
            ("SCRY answers", f"<code>{html.escape(answer, quote=False)}</code>"),
            *([("Your client learns", _inline(learned))] if learned else []))
    return "\n".join([
        f'<p align="center"><a href="{folder}">{_moving(demo.alt, folder)}</a></p>',
        f'<p align="center"><em>{_inline(lead.caption)}</em></p>', "",
        '<table align="center">',
        *(f'<tr><th align="left">{head}</th><td>{cell}</td></tr>' for head, cell in rows),
        "</table>"])


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
                   help="rewrite the README's blocks, TRANSCRIPT.md, screen.png and the loop "
                        "from this run")
    return p


def main(demo: Demo, argv: Sequence[str] | None = None) -> int:
    """Run `demo` as its command line asks; answer the exit code."""
    declared(demo)
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
    untaken = set(run.options) - _taken(demo)
    if untaken:
        raise Invalid(f"options {sorted(untaken)} were given and nothing in the demo "
                      f"{demo.name} takes them")
    if update_readme:
        if demo.readme is None or demo.capture is None:
            raise _no_readme(demo)
        tried = sum(1 for step in demo.steps if step.ask)
        if not TRY_STEPS[0] <= tried <= TRY_STEPS[1]:
            raise Invalid(f"the demo {demo.name} marks {prose.counted(tried, 'step')} with an "
                          f"`ask`, and a README offers {TRY_STEPS[0]} to {TRY_STEPS[1]} to try")
        block_span(demo.readme.read_text(encoding="utf-8"))
        if demo.moments:
            block_span(demo.readme.read_text(encoding="utf-8"), MOTION_BEGIN, MOTION_END)
            motion.programs()
        if demo.front is not None:
            block_span(demo.front.read_text(encoding="utf-8"), flow_begin(demo.name),
                       flow_end(demo.name))
        if demo.lead is not None:
            block_span(demo.lead.front.read_text(encoding="utf-8"), lead_begin(demo.name),
                       lead_end(demo.name))
    why = demo.precheck(run) if demo.precheck else ""
    if why:
        raise Invalid(why)
    run.dir.mkdir(parents=True, exist_ok=True)
    capture = demo.capture(run) if demo.capture is not None else None
    if capture is not None:
        capture.unlink(missing_ok=True)  # only this run's picture may reach the README
    norm = Normaliser(demo.root.resolve(), Path.home().resolve(),
                      {**VOLATILE, **demo.volatile}, demo.host_args)
    files = _beside(transcript)
    for stale_file in (files.flow, files.examples, files.motion, files.lead):
        stale_file.unlink(missing_ok=True)  # only this run's may reach a README
    out = asyncio.run(_drive(demo, run, run.dir / "server.stderr", norm))
    if out.transcripts.whole:
        transcript.write_text("\n\n".join(out.transcripts.whole) + "\n", encoding="utf-8")
        files.normalised.write_text(_whole(out.transcripts.normalised), encoding="utf-8")
    if out.transcripts.flow:
        files.flow.write_text("\n\n".join(out.transcripts.flow) + "\n", encoding="utf-8")
    if out.transcripts.examples:
        files.examples.write_text("\n\n".join(out.transcripts.examples) + "\n",
                                  encoding="utf-8")
    if out.transcripts.exchange and demo.lead is not None and demo.readme is not None:
        files.lead.write_text(lead_block(demo, demo.lead, demo.readme,
                                         *out.transcripts.exchange) + "\n", encoding="utf-8")
    for line in out.lines:
        print(line)
    if out.transcripts.whole:
        print(f"transcript: {transcript}")
        print(f"normalised: {files.normalised}")
    shown = cuts(demo, run) if out.code == EXIT_PASS and demo.moments else []
    if shown:
        files.motion.write_text(motion_block(demo, motion.lasting(shown)) + "\n",
                                encoding="utf-8")
    if out.code == EXIT_PASS and update_readme and capture is not None and demo.readme:
        _update_readmes(demo, run, demo.readme, capture, files, shown)
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


@dataclass(frozen=True)
class Beside:
    """What a run writes beside its transcript: the normalised run, the front door's flow, the
    README's examples, its motion block and the front door's lead."""

    normalised: Path
    flow: Path
    examples: Path
    motion: Path
    lead: Path


def _beside(transcript: Path) -> Beside:
    stem = file_names.word(transcript.stem, "transcript")
    def beside(part: str) -> Path:
        return transcript.with_name(file_names.name(stem, part, extension="md"))
    return Beside(beside("normalised"), beside("flow"), beside("examples"), beside("motion"),
                  beside("lead"))


def _whole(entries: list[str]) -> str:
    """The normalised run as `FULL_NAME` carries it: what its marks stand for, then every call."""
    return (f"Every call of the run with its reply, in order: "
            f"{prose.counted(len(entries), 'call')}. "
            f"`{VOLATILE_MARK}` stands for a value that changes from run to run, and "
            f"`{HOST_MARK}` for one this host decides.\n\n" + "\n\n".join(entries) + "\n")


def stale(demo: Demo, run_dir: Path) -> list[str]:
    """How the committed README blocks, whole run, flow and picture depart from the run in
    `run_dir`, one line each, or empty."""
    files = _beside(run_dir / "transcript.md")
    needed = ([files.examples, files.normalised] if demo.readme is not None else []) + (
        [files.flow] if demo.front is not None else []) + (
        [files.motion] if demo.readme is not None and demo.moments else []) + (
        [files.lead] if demo.lead is not None else [])
    if missing := [path.name for path in needed if not path.is_file()]:
        return [f"{demo.name}: the run in {run_dir} wrote no {', '.join(missing)}"]
    found = []
    if demo.readme is not None:
        if drift := readme_drift(demo.readme, files.examples):
            found.append(f"{demo.name}'s README: {drift}")
        whole = demo.readme.with_name(FULL_NAME)
        if not whole.is_file():
            found.append(f"{demo.name}'s {FULL_NAME} is not committed")
        elif drift := first_difference(
                whole.read_text(encoding="utf-8").strip("\n"),
                files.normalised.read_text(encoding="utf-8").strip("\n"), (FULL_NAME, "the run")):
            found.append(f"{demo.name}'s {FULL_NAME}: {drift}")
    if demo.front is not None and (drift := flow_drift(demo.front, demo.name, files.flow)):
        found.append(f"the front door's {demo.name} flow: {drift}")
    if demo.lead is not None and (drift := first_difference(
            block_of(demo.lead.front.read_text(encoding="utf-8"), lead_begin(demo.name),
                     lead_end(demo.name)),
            files.lead.read_text(encoding="utf-8").strip("\n"))):
        found.append(f"the README's {demo.name} lead: {drift}")
    if demo.readme is not None and demo.capture is not None:
        shot, committed = demo.capture(Run(dir=run_dir)), demo.readme.with_name("screen.png")
        if not (same_picture(shot, committed) or cut_from(shot, committed)):
            found.append(f"{demo.name}'s screen.png is not this run's capture")
    if demo.readme is not None and demo.moments:
        if drift := first_difference(
                block_of(demo.readme.read_text(encoding="utf-8"), MOTION_BEGIN, MOTION_END),
                files.motion.read_text(encoding="utf-8").strip("\n")):
            found.append(f"{demo.name}'s motion block: {drift}")
        if not demo.readme.with_name(motion.LOOP_NAME).is_file():
            found.append(f"{demo.name}'s {motion.LOOP_NAME} is not committed")
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


def cut_from(capture: Path, still: Path) -> bool:
    """Whether `still` is a rectangle of the picture in `capture`, as a loop that cuts its
    frames cuts the still beside it."""
    if not (capture.is_file() and still.is_file()):
        return False
    try:
        return png.cut_from(png.decode(capture.read_bytes()), png.decode(still.read_bytes()))
    except png.NotAPicture:
        return False


def _no_readme(demo: Demo) -> Invalid:
    return Invalid(f"the demo {demo.name} has no README block to update")


def _update_readmes(demo: Demo, run: Run, readme: Path, capture: Path, files: Beside,
                    shown: Sequence[motion.Cut]) -> None:
    """Rewrite the README blocks, whole run, picture, loop and flow; every text and the loop are
    built before any file is written, so a failure leaves all as they were."""
    if not capture.is_file():
        raise Invalid(f"the capture {capture} was not written by this run, so the README was "
                      "left as it was")
    text = with_block(readme.read_text(encoding="utf-8"),
                      files.examples.read_text(encoding="utf-8"))
    if shown:
        text = with_block(text, files.motion.read_text(encoding="utf-8"), MOTION_BEGIN,
                          MOTION_END)
    fronts: dict[Path, tuple[str, list[str]]] = {}

    def opened(front: Path, what: str, block: Path, begin: str, end: str) -> None:
        """One more generated block of `front`, which a flow and a lead may share."""
        before, parts = fronts.get(front.resolve(), (front.read_text(encoding="utf-8"), []))
        fronts[front.resolve()] = (with_block(before, block.read_text(encoding="utf-8"), begin,
                                              end), [*parts, what])

    if demo.front is not None:
        opened(demo.front, "flow", files.flow, flow_begin(demo.name), flow_end(demo.name))
    if demo.lead is not None:
        if not files.lead.is_file():
            raise Invalid(f"the run wrote no exchange for the lead of {demo.name}, so the "
                          "READMEs were left as they were")
        opened(demo.lead.front, "lead", files.lead, lead_begin(demo.name), lead_end(demo.name))
    built = motion.build(shown, run.dir / "loop") if shown else None
    picture = capture.read_bytes()
    if built is not None:
        picture = motion.still(picture, built.kept)
    readme.with_name("screen.png").write_bytes(picture)
    shutil.copyfile(files.normalised, readme.with_name(FULL_NAME))
    readme.write_text(text, encoding="utf-8")
    print(f"README: {readme} blocks, {FULL_NAME} and screen.png rewritten")
    for front, (written, parts) in fronts.items():
        front.write_text(written, encoding="utf-8")
        print(f"README: {front} {' and '.join(parts)} {demo.name} rewritten")
    if built is not None:
        loop = readme.with_name(motion.LOOP_NAME)
        fresh.replace(loop, built.data, "the demo's loop")
        print(f"README: {loop} rewritten: {len(built.data)} bytes, "
              f"{'lossless' if built.lossless else 'lossy'}, "
              f"{sum(built.cut_ms) / 1000:g} s in {prose.counted(len(shown), 'moment')}")
