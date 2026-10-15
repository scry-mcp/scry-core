"""A demo: one server started by its command over stdio, the calls a prompt asks a model to make,
each answer checked, and a transcript a README can carry without drifting from the server.

A server repository keeps each demo as `demos/<name>/demo.py`, which declares a `Demo` (its
steps and checks) and hands it to `main`:

    uv run python demos/<name>/demo.py [--binary PATH] [--transcript PATH] [--update-readme]

plus `--rompath DIR` and `--shared` where the demo `offers` them, because its server's `start`
takes them under those names. The options given reach the one step declared `options=True`,
and only the options given: one left out is absent, so the server's own default decides.

stdout is one line per step that ran, `OK <step>: <summary>` or `FAIL <step>: <why>`, then
`DEMO <name>: <n> steps, <k> OK` and the paths of the two transcripts: the whole one, every call
and its whole reply as markdown (`--transcript`, default `tmp/demos/<name>/transcript.md` under
the repository; the run's other files go beside it), and the NORMALISED one, which is what a
README carries and what `readme_drift` compares.

Exit codes: 0 every step OK; 1 a step failed (the steps after it are not run); 2 a usage error,
an unknown option included; 3 INVALID, nothing was demonstrated: zero steps, options given and
no step to take them, a `precheck` reason (such as a ROM that is not there), a server that did
not start, a README whose markers are not there exactly once, a capture the run did not write,
or anything else that stopped the run before its verdict. Whatever happens, the run ends with
the cleanup call unless its last step already made it, so no emulator outlives it.

THE README BLOCK IS GENERATED, never typed. `--update-readme` rewrites what sits between
`<!-- demo-transcript:begin -->` and `<!-- demo-transcript:end -->` with the normalised
transcript and copies the capture this run wrote to `screen.png` beside the README, only after
a run whose every step was OK: a README showing a failed run would be a README that lies.

NORMALISATION hides what differs between two honest runs and nothing else: `$HOME` becomes `~`
and the repository root `.`, wherever either begins a path; in a REPLY the value of every key
in `VOLATILE` becomes `<volatile>`; and in the ARGUMENTS of a call the value of every key a
demo declares in `host_args` (a window's placement, say) becomes `<host>`. Hiding is by key, so a
reply that echoes a host argument needs that key in `volatile` too, and a summary must not quote
one. A value the demo SHOWS (a score, a register, an address
it found) is never on that list: if it differs between two runs the demo is wrong, and hiding
it would make the freshness check pass by not looking. A step's summary is the demo's own text
and is never searched for volatile values, so a summary quotes only what the demo shows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 3

BEGIN = "<!-- demo-transcript:begin -->"
END = "<!-- demo-transcript:end -->"
VOLATILE_MARK = "<volatile>"
HOST_MARK = "<host>"

#: The tool every Scry server ends a session with.
CLEANUP_TOOL = "close"

#: The bound on one call's answer. Every Scry tool bounds its own waits at 600 s, so a call
#: still unanswered well past that is a server that will not answer, not a slow one.
CALL_TIMEOUT_S = 900

#: The options a demo can offer beyond `--binary`, as its server's `start` spells them.
OFFERABLE = frozenset({"rompath", "shared"})

#: Reply keys whose values differ between two honest runs, each with the reason. A demo adds
#: its own through `Demo.volatile`.
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


class Invalid(Exception):
    """Nothing was demonstrated: no verdict about the server."""


@dataclass(frozen=True)
class Reply(Mapping[str, Any]):
    """One tool's answer: its structured document, else the JSON of its first text part, read
    as a mapping, and the media type of each part that is not text."""

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
    """What a step's arguments and checks read: the options given, the directory this run
    writes into, and every reply so far by step name (the current step's included)."""

    dir: Path
    options: dict[str, Any] = field(default_factory=dict)
    replies: dict[str, Reply] = field(default_factory=dict)


Args = Mapping[str, Any] | Callable[[Run], Mapping[str, Any]]


@dataclass(frozen=True)
class Step:
    """One call: `tool` with `args`, or a function of the run giving them. `check` returns the
    summary printed beside OK; it raises `StepFailed` to say why not, and any other exception in
    the step is that step's FAIL too, named by its type. A reply whose `status` is not `ok`
    fails before `check` is asked. `options=True` marks the step the command line's options are
    merged into, which is the server's `start`."""

    name: str
    tool: str
    args: Args
    check: Callable[[Reply, Run], str]
    options: bool = False


@dataclass(frozen=True)
class Demo:
    """A demo as its `demo.py` declares it. `server` is the command that starts the server and
    `root` the repository it runs in. `offers` names the options of `OFFERABLE` this server's
    `start` takes. `capture` is the image `--update-readme` copies, a file in `run.dir` that one
    step writes. `precheck` answers why the demo cannot run at all, or an empty string. `volatile`
    adds reply keys to `VOLATILE`, each with its reason; `host_args` names the argument keys whose
    values are the host's own rather than the demo's, each with its reason."""

    name: str
    root: Path
    server: Sequence[str]
    readme: Path
    steps: Sequence[Step]
    capture: Callable[[Run], Path]
    offers: frozenset[str] = frozenset()
    precheck: Callable[[Run], str] | None = None
    volatile: Mapping[str, str] = field(default_factory=dict)
    host_args: Mapping[str, str] = field(default_factory=dict)


# ======================================================================== the README block


def block_span(text: str) -> tuple[int, int]:
    """Where the generated block sits in `text`: just after BEGIN, and at END. Markers absent,
    repeated or out of order raise `Invalid`."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise Invalid(f"the README must hold {BEGIN} and {END} exactly once each "
                      f"(found {text.count(BEGIN)} and {text.count(END)})")
    start, end = text.index(BEGIN) + len(BEGIN), text.index(END)
    if end < start:
        raise Invalid(f"{END} comes before {BEGIN}")
    return start, end


def block_of(text: str) -> str:
    """The generated block of a README's `text`, without the newlines that frame it."""
    start, end = block_span(text)
    return text[start:end].strip("\n")


def with_block(text: str, block: str) -> str:
    """`text` with its generated block replaced by `block`."""
    start, end = block_span(text)
    return f"{text[:start]}\n{block.strip(chr(10))}\n{text[end:]}"


def first_difference(want: str, got: str) -> str:
    """The first line where `got` departs from `want`, by number, or empty when they agree."""
    a, b = want.splitlines(), got.splitlines()
    for i, (x, y) in enumerate(zip(a, b, strict=False), start=1):
        if x != y:
            return f"line {i}: the README has {x!r}, the run has {y!r}"
    if len(a) != len(b):
        return f"line {min(len(a), len(b)) + 1}: the README has {len(a)}, the run {len(b)}"
    return ""


def readme_drift(readme: Path, normalised: Path) -> str:
    """How a run's normalised transcript departs from the block its README carries, or empty:
    the comparison a server's freshness test makes."""
    return first_difference(block_of(readme.read_text(encoding="utf-8")),
                            normalised.read_text(encoding="utf-8").strip("\n"))


# ===================================================================== normalisation


@dataclass(frozen=True)
class Normaliser:
    """The host's paths, a reply's volatile values and the arguments that are the host's own,
    spelled for any host."""

    root: Path
    home: Path
    volatile: Mapping[str, str]
    host: Mapping[str, str] = field(default_factory=dict)

    def text(self, text: str) -> str:
        """`text` with the root as `.` and the home as `~` wherever one BEGINS a path: followed
        by a separator or the end, never inside a longer name (`/Users/mx` is not under
        `/Users/m`). The root goes first, since it usually lies inside the home and the longer
        prefix has to win. A prefix of `/` is left alone: it would rewrite every separator."""
        for prefix, mark in ((self.root, "."), (self.home, "~")):
            if str(prefix) != os.sep:
                text = re.sub(re.escape(str(prefix)) + r"(?=/|$|[^\w.-])", mark, text)
        return text

    def reply(self, value: Any) -> Any:
        """A reply with its paths spelled by `text` and every volatile key's value hidden."""
        return self._value(value, self.volatile, VOLATILE_MARK)

    def arguments(self, value: Any) -> Any:
        """The demo's arguments with their paths spelled by `text` and the host's own hidden;
        every other value is the demo's choice and is shown."""
        return self._value(value, self.host, HOST_MARK)

    def _value(self, value: Any, hidden: Mapping[str, str], mark: str) -> Any:
        if isinstance(value, dict):
            return {self.text(k): mark if k in hidden else self._value(v, hidden, mark)
                    for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._value(v, hidden, mark) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value


# ======================================================================== the transcript


def _fenced(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```"


def _entry(n: int, tool: str, args: Mapping[str, Any], reply: Reply | None, line: str) -> str:
    """One step of a transcript: its verdict line, then the call and the whole answer folded
    under it."""
    parts = [f"**{n}. `{tool}`**: {line}", "", "<details><summary>call and reply</summary>",
             "", _fenced(dict(args))]
    if reply is not None:
        parts += ["", _fenced(reply.data)]
        if reply.attachments:
            parts += ["", "Also attached: " + ", ".join(reply.attachments) + "."]
    parts += ["", "</details>"]
    return "\n".join(parts)


@dataclass
class Transcripts:
    """The two transcripts of one run, kept in step: every entry goes to both, the normalised
    one through the run's `Normaliser`."""

    norm: Normaliser
    whole: list[str] = field(default_factory=list)
    normalised: list[str] = field(default_factory=list)

    def add(self, n: int, tool: str, args: Mapping[str, Any], reply: Reply | None,
            line: str) -> None:
        self.whole.append(_entry(n, tool, args, reply, line))
        shown = None if reply is None else Reply(self.norm.reply(reply.data), reply.attachments)
        self.normalised.append(_entry(n, tool, self.norm.arguments(dict(args)), shown,
                                      self.norm.text(line)))


# ========================================================================= running


def _reply(result: CallToolResult) -> Reply:
    """A `CallToolResult` as a `Reply`: its structured document, else its first text part read
    as JSON; a part that is not text is named by its media type, since the text only repeats
    the document. A result the library flags as an error carries no `ok` status."""
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
    """`text` as a JSON document, or the text itself under `text` when it is not one."""
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _why(e: BaseException) -> str:
    """An exception as one line: a group as its first leaf, a `StepFailed` as its message, any
    other as its type and message, since an empty message would leave a FAIL with no reason."""
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
    """What a run did: its stdout lines, its transcripts, and its exit code."""

    lines: list[str]
    transcripts: Transcripts
    code: int = EXIT_OK


async def _drive(demo: Demo, run: Run, stderr_path: Path, norm: Normaliser) -> Outcome:
    out = Outcome([], Transcripts(norm))
    # The WHOLE environment, not the library's short default list: the server's own ladder
    # (`MAME_BINARY`, its state directories) reads variables the caller set.
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
                    out.transcripts.add(n, step.tool, args, reply, line)
                    closed = ok and step.tool == CLEANUP_TOOL
                    if not ok:
                        out.code = EXIT_FAILED
                        break
                    passed += 1
                if not closed:
                    await _cleanup(client, out)
        except Exception as e:  # anything the session itself raised, outside a step
            out.code = EXIT_FAILED if started else EXIT_INVALID
            out.lines.append(
                f"FAIL {demo.name}: the session with the server ended in an error ({_why(e)}); "
                f"its stderr is in {stderr_path}" if started else
                f"INVALID: the server did not start ({_why(e)}); its stderr is in {stderr_path}")
            if not started:
                return out
    out.lines.append(f"DEMO {demo.name}: {len(demo.steps)} steps, {passed} OK")
    return out


async def _step(client: Client, step: Step, run: Run
                ) -> tuple[bool, str, Mapping[str, Any], Reply | None]:
    """Run one step: its verdict, its line, the arguments it sent and the reply it got."""
    args: Mapping[str, Any] = {}
    reply: Reply | None = None
    try:
        built = dict(step.args(run) if callable(step.args) else step.args)
        if step.options:
            built.update(run.options)
        # Through JSON once, so what is sent is exactly what the transcript shows (a `Path`
        # becomes its text) and a value JSON cannot carry fails here, as this step.
        args = json.loads(json.dumps(built, default=str))
        reply = _reply(await client.call_tool(step.tool, dict(args)))
        run.replies[step.name] = reply
        if reply.get("status") != "ok":
            raise StepFailed(_refused(reply, step.tool))
        summary = step.check(reply, run)
        if not isinstance(summary, str):
            raise StepFailed(f"the check returned {summary!r}, not a summary")
        return True, f"OK {step.name}: {_one_line(summary)}", args, reply
    except Exception as e:  # every failure inside a step is that step's FAIL
        return False, f"FAIL {step.name}: {_why(e)}", args, reply


async def _cleanup(client: Client, out: Outcome) -> None:
    """The cleanup call, when the run did not end with it: its answer goes to the whole
    transcript only and never changes the verdict."""
    try:
        reply = _reply(await client.call_tool(CLEANUP_TOOL, {}))
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}`:\n\n" + _fenced(reply.data))
    except Exception as e:  # the verdict is already formed; this only reports
        out.transcripts.whole.append(f"Cleanup `{CLEANUP_TOOL}` failed: {_why(e)}")


def _parser(demo: Demo) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=f"demos/{demo.name}/demo.py", allow_abbrev=False,
                                description=f"Run the {demo.name} demo against its server.",
                                epilog="Exit codes: 0 every step OK, 1 a step failed, 2 a usage "
                                       "error, 3 nothing was demonstrated.")
    p.add_argument("--binary", help="the emulator to start; left out, the server's own ladder")
    if "rompath" in demo.offers:
        p.add_argument("--rompath", help="the directory holding the set's zip")
    if "shared" in demo.offers:
        p.add_argument("--shared", action="store_true", default=None,
                       help="somebody watches: a big window at real speed")
    p.add_argument("--transcript", type=Path,
                   help="where the whole transcript goes; the run's other files go beside it")
    p.add_argument("--update-readme", action="store_true",
                   help="rewrite the README's transcript block and screen.png from this run")
    return p


def main(demo: Demo, argv: Sequence[str] | None = None) -> int:
    """Run `demo` as its command line asks, print the verdict lines, answer the exit code."""
    unknown = demo.offers - OFFERABLE
    if unknown:
        raise ValueError(f"the demo {demo.name} offers {sorted(unknown)}, not among "
                         f"{sorted(OFFERABLE)}")
    ns = _parser(demo).parse_args(argv)
    transcript: Path = (ns.transcript or demo.root / "tmp" / "demos" / demo.name
                        / "transcript.md").resolve()
    given = {"binary": ns.binary, "rompath": getattr(ns, "rompath", None),
             "shared": getattr(ns, "shared", None)}
    run = Run(dir=transcript.parent, options={k: v for k, v in given.items() if v is not None})
    try:
        code = _main(demo, run, transcript, ns.update_readme)
    except Invalid as e:
        print(f"INVALID: {e}")
        code = EXIT_INVALID
    except Exception as e:  # anything else before a verdict: INVALID, never a traceback
        print(f"INVALID: {_why(e)}")
        code = EXIT_INVALID
    sys.stdout.flush()
    return code


def _main(demo: Demo, run: Run, transcript: Path, update_readme: bool) -> int:
    if not demo.steps:
        raise Invalid(f"the demo {demo.name} declares zero steps, so it demonstrates nothing")
    if run.options and not any(s.options for s in demo.steps):
        raise Invalid(f"options {sorted(run.options)} were given and no step of the demo "
                      f"{demo.name} takes them")
    if update_readme:
        block_span(demo.readme.read_text(encoding="utf-8"))
    why = demo.precheck(run) if demo.precheck else ""
    if why:
        raise Invalid(why)
    run.dir.mkdir(parents=True, exist_ok=True)
    capture = demo.capture(run)
    capture.unlink(missing_ok=True)  # only a picture THIS run wrote may reach the README
    norm = Normaliser(demo.root.resolve(), Path.home().resolve(),
                      {**VOLATILE, **demo.volatile}, demo.host_args)
    out = asyncio.run(_drive(demo, run, run.dir / "server.stderr", norm))
    normalised = transcript.with_name(transcript.stem + ".normalised.md")
    if out.transcripts.whole:
        transcript.write_text("\n\n".join(out.transcripts.whole) + "\n", encoding="utf-8")
        normalised.write_text("\n\n".join(out.transcripts.normalised) + "\n", encoding="utf-8")
    for line in out.lines:
        print(line)
    if out.transcripts.whole:
        print(f"transcript: {transcript}")
        print(f"normalised: {normalised}")
    if out.code == EXIT_OK and update_readme:
        _update_readme(demo, capture, normalised)
    return out.code


def _update_readme(demo: Demo, capture: Path, normalised: Path) -> None:
    if not capture.is_file():
        raise Invalid(f"the capture {capture} was not written by this run, so the README was "
                      "left as it was")
    text = with_block(demo.readme.read_text(encoding="utf-8"),
                      normalised.read_text(encoding="utf-8"))
    shutil.copyfile(capture, demo.readme.with_name("screen.png"))
    demo.readme.write_text(text, encoding="utf-8")
    print(f"README: {demo.readme} block and screen.png rewritten")
