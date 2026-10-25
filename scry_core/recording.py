"""A session recorded as it was done and exported as `perform`'s own document. `Recorder` is fed
by a server's call boundary, `document` holds the export rules, `export` writes it, `diverged` is
the check a replayed step holds to. The runner is `scry_core.replay`, apart: a server never needs
the client it uses.

The recording starts at a `start` that left a session up (a failed plan included), is cleared by
the next one and survives `close`. Every outermost call is recorded except a sequence (its steps
are recorded instead) and the `outside` tools. Past `record_max` the recording stops and the export
says it is cut there. The document names the entry file, the states it loads and the declarations
the start found stored (`needs`), so a replay that would start under other breakpoints says so
before it plays.

Export rules, each drop named:

- a refused call is dropped, unless the machine moved under it (which cuts);
- a `drop` tool is dropped, unless the call moved the machine: dropped, the replay falls behind;
- a tool declared with fields is a CHECK carrying `recorded`; dropped when its arguments name what
  a dropped call wrote (`dest`, the `WRITTEN` fields), since it would hold by construction;
- any other tool is a STEP, carrying `stop_fields` as `recorded` if it left a new stop;
- a RELEASE, a `wall` call that moved the machine, or a reply with a `WALL_VERDICTS` verdict CUTS:
  the clock or a breakpoint stops the cpu inside a frame no replayed advance reaches, so every
  later stop would inherit the shift;
- a kept call writing a file the session named (`dest`) CUTS: a replay finds the file and is
  refused;
- the first call the rules cannot place (no reply, refused after the machine moved, machine
  unreadable or not where the call before left it) CUTS; what came before stands.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from scry_core import fresh, judges, prose
from scry_core.reply_contract import Invalid, unavailable

#: Storage ceiling per kept call, so a session that reads a million times is bounded too.
STORED_PER_KEPT = 10
DROPPED_SHOWN = 40
DOCUMENT_VERSION = 3
EXPORT_TOOL = "perform_export"
#: No Scry tool declares an argument by this name.
RECORDED = "recorded"
WALL_VERDICTS = frozenset({"TIMEOUT"})
RELEASED = ("it released the machine, and the stop that ends a run lands at a place inside its "
            "frame that no replayed advance reaches")
RUN_STOPPED_INSIDE = ("its run was stopped by the wall clock or by the machine itself, at a place "
                      "inside its frame that no replayed advance reaches")
WRITTEN = ("path", "manifest", "dir")

#: `wall`: a run the wall clock ends. A tuple of field names: a check of those fields.
Word = Literal["step", "wall", "drop"]
ExportAs = Word | tuple[str, ...]
Replay = ExportAs | Mapping[str, ExportAs]
WORDS: tuple[str, ...] = get_args(Word)


@dataclass(frozen=True)
class States:
    """The tool that saves and loads a state, its `method` values and the state-name argument."""

    tool: str
    save: str
    load: str
    argument: str


@dataclass(frozen=True)
class Machine:
    """The machine around a call. `seq` is the stop's sequence number; `seq` with `stop` (in
    `stop_fields`) says whether a call moved the machine; `known` is False when unreadable."""

    running: bool
    seq: int | None
    stop: Mapping[str, Any] = field(default_factory=dict)
    known: bool = True


UNREAD = Machine(running=True, seq=None, known=False)


@dataclass(frozen=True)
class Call:
    """One recorded call: `status` is the reply's, or `ended` when there was no reply."""

    op: str
    args: Mapping[str, Any]
    status: str
    recorded: Mapping[str, Any]
    before: Machine
    after: Machine
    walled: bool = False
    wrote: tuple[str, ...] = ()
    #: What `record_max` counts.
    keepable: bool = True


@dataclass
class Recording:
    """What a session did since its `start`."""

    start: Mapping[str, Any]
    calls: list[Call] = field(default_factory=list)
    kept: int = 0
    full: bool = False
    #: Stopped at the storage ceiling, not at `record_max`.
    stored_out: bool = False
    declarations: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Declared:
    """How a tool's calls are exported, and whether it only reads."""

    export_as: ExportAs
    read_only: bool


class Declaration(Protocol):
    """A server's stored declaration, as the Recorder reads it."""

    @property
    def kind(self) -> str: ...

    @property
    def ref(self) -> str: ...


class Recorder:
    """One server's recording, fed by its `scry_core.boundary.Boundary`. Every argument is the
    server's own vocabulary; nothing here names a tool. `kinds` maps a declaration kind to its
    list tool and the reply field its rows are under; `sequences` are the tools whose steps are
    recorded in their place; `plan` is the `start_tool` argument whose steps are recorded after
    it and `plan_with` the arguments that only bound the plan (a replayed start runs no plan, and
    the server refuses its bound alone); `outside` are the tools no replay could take."""

    def __init__(self, server: str, entry: str, record_max: int, machine: Callable[[], Machine],
                 live: Callable[[], bool], *,
                 declarations: Callable[[], Iterable[Declaration]],
                 kinds: Mapping[str, tuple[str, str]],
                 stop_fields: tuple[str, ...], outside: frozenset[str], sequences: frozenset[str],
                 start_tool: str, states: States, plan: str | None = None,
                 plan_with: tuple[str, ...] = ()) -> None:
        self.server = server
        self.entry = entry
        self.record_max = record_max
        self._machine = machine
        self._live = live
        self._declarations = declarations
        self.kinds = dict(kinds)
        self.lists = {key: tool for tool, key in kinds.values()}
        self._found_live = False
        self.stop_fields = stop_fields
        self.outside = outside | {EXPORT_TOOL}
        self.sequences = sequences
        self.start_tool = start_tool
        self.plan = plan
        self.plan_with = plan_with
        self.states = states
        self.declared: dict[str, Declared | dict[str, Declared]] = {}
        self.recording: Recording | None = None
        self._starting: Recording | None = None
        # What a replayed `start` re-arms, before the plan's own steps declare anything.
        self._found_declared: dict[str, list[str]] | None = None

    def declare(self, tool: str, export_as: Replay | None, read_only: bool) -> None:
        """A tool registered: how its calls are exported, `drop` for a reader and `step` by
        default, or a mapping per `method`. A typo is refused at import, not silently a step."""
        if isinstance(export_as, Mapping):
            self.declared[tool] = {m: _declared(tool, e, read_only) for m, e in export_as.items()}
        else:
            self.declared[tool] = _declared(tool, export_as, read_only)

    def kind(self, tool: str, args: Mapping[str, Any]) -> Declared:
        """A call's declaration; an unregistered tool or unnamed `method` is a step."""
        declared = self.declared.get(tool, Declared("step", False))
        if isinstance(declared, dict):
            return declared.get(str(args.get("method")), Declared("step", False))
        return declared

    def begin(self, tool: str, parent: str | None, given: Mapping[str, Any]) -> Machine | None:
        """The machine before a call this recording takes, or None for one it does not."""
        if tool in self.outside:
            return None
        if parent is None and tool == self.start_tool:
            planned = self.plan is not None and bool(given.get(self.plan))
            dropped = {self.plan, *self.plan_with} if planned else {self.plan}
            self._starting = Recording({k: v for k, v in given.items() if k not in dropped})
            self._found_live = self._was_live()
            self._found_declared = None
            return None
        if parent is None:
            if tool in self.sequences or self.recording is None:
                return None
            return self._read()
        if parent in self.sequences and self.recording is not None:
            return self._read()
        if parent == self.start_tool and self.plan is not None and self._starting is not None:
            if self._found_declared is None:
                self._found_declared = self._stored()
            return self._read()
        return None

    def end(self, tool: str, parent: str | None, given: Mapping[str, Any],
            reply: Mapping[str, Any], began: Machine | None) -> None:
        """A call answered: a successful outermost `start` makes its recording the session's."""
        if parent is None and tool == self.start_tool:
            # A start refused over a live session touched nothing, so the earlier recording stays.
            session = reply.get("session")
            up = reply.get("status") == "ok" or (not self._found_live and isinstance(session, dict)
                                                 and session.get("alive") is True)
            if up and self._starting is not None:
                self.recording = self._starting
                self.recording.declarations = (self._found_declared
                                               if self._found_declared is not None
                                               else self._stored())
            self._starting = None
            return
        if began is not None:
            declared = self.kind(tool, given)
            fields = declared.export_as
            fields = fields if isinstance(fields, tuple) else self.stop_fields
            after = self._read()
            status = str(reply.get("status"))
            moved = _moved_between(began, after)
            dropped = not moved and (status != "ok" or declared.export_as in ("drop", "wall"))
            self._add(parent, Call(tool, dict(given), status,
                                   {f: reply[f] for f in fields if f in reply}, began, after,
                                   walled=reply.get("verdict") in WALL_VERDICTS,
                                   wrote=tuple(str(x) for x in (given.get("dest"),
                                                                *map(reply.get, WRITTEN))
                                               if isinstance(x, str) and x),
                                   keepable=not dropped))

    def ended(self, tool: str, parent: str | None, given: Mapping[str, Any],
              began: Machine | None) -> None:
        """A call that ended with no reply: a `start` drops the recording, any other is `ended`."""
        if parent is None and tool == self.start_tool:
            self.recording = self._starting = None
        elif began is not None:
            self._add(parent, Call(tool, dict(given), "ended", {}, began, self._read()))

    def _add(self, parent: str | None, call: Call) -> None:
        into = self._starting if parent == self.start_tool else self.recording
        if into is None:
            # Not an `assert`: `python -O` removes it.
            raise RuntimeError(f"{call.op} was taken with no recording to add it to")
        if into.full:
            return
        if into.kept + call.keepable > self.record_max:
            into.full = True
            return
        if len(into.calls) >= STORED_PER_KEPT * self.record_max:
            into.full = into.stored_out = True
            return
        into.calls.append(call)
        into.kept += call.keepable

    def _stored(self) -> dict[str, list[str]]:
        """The stored declarations by list's reply key, sorted; empty when the server cannot say."""
        try:
            held: dict[str, list[str]] = {key: [] for key in self.lists}
            for d in self._declarations():
                if d.kind in self.kinds:
                    held[self.kinds[d.kind][1]].append(d.ref)
            return {key: sorted(refs) for key, refs in held.items()}
        except Exception:  # noqa: BLE001 -- as `_read`
            return {}

    def _was_live(self) -> bool:
        """Whether a session was up as a start began; unreadable counts as up."""
        try:
            return self._live()
        except Exception:  # noqa: BLE001 -- as `_read`
            return True

    def _read(self) -> Machine:
        """The machine as the server reads it, or `UNREAD`: a recorder never fails a call."""
        try:
            return self._machine()
        except Exception:  # noqa: BLE001 -- the call stands; its export is cut here, saying why
            return UNREAD




@dataclass
class Account:
    """What an export kept, dropped and cut, beside the steps it wrote."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    cut: dict[str, Any] = field(default_factory=lambda: unavailable(
        "the recording kept every call a replay takes"))
    saved: set[str] = field(default_factory=set)
    loaded: list[str] = field(default_factory=list)

    def drop(self, n: int, op: str, why: str) -> None:
        self.dropped.append({"call": n, "op": op, "why": why})

    def cut_at(self, n: int, op: str | dict[str, Any], why: str) -> None:
        self.cut = {"call": n, "op": op, "why": why}


def document(recorder: Recorder) -> tuple[dict[str, Any], Account]:
    """The recording as `perform`'s document by the module's rules, and the account."""
    recording = recorder.recording
    if recording is None:
        raise RuntimeError("document() of a recorder with no recording: `export` refuses first")
    out = Account()
    unwritten: set[str] = set()          # files dropped calls wrote
    previous: Machine | None = None
    for n, call in enumerate(recording.calls, start=1):
        declared = recorder.kind(call.op, call.args)
        if not (call.before.known and call.after.known):
            out.cut_at(n, call.op, "the server could not read the machine around it")
            break
        if previous is not None and not _same_machine(previous, call.before):
            out.cut_at(n, call.op, "the machine was not where the call before it left it: "
                       "something no recorded call did moved it")
            break
        previous = call.after
        if call.status == "ended":
            out.cut_at(n, call.op, "it ended with no reply (cancelled, or failed in its body), "
                       "so where it left the machine is not recorded")
            break
        if call.after.running:             # refused or not: a release is a release
            out.cut_at(n, call.op, RELEASED)
            break
        if call.status != "ok":
            if _moved(call):
                out.cut_at(n, call.op, f"the server refused it ({call.status}) after the "
                           "machine had moved under it")
                break
            out.drop(n, call.op, f"the server refused it ({call.status})")
            continue
        if declared.export_as in ("drop", "wall") and not _moved(call):
            out.drop(n, call.op, _dropped_why(declared) if declared.export_as == "drop"
                     else "it ran nothing: the machine was where it left it")
            unwritten.update(call.wrote)
            continue
        if (declared.export_as == "wall" or call.walled) and _moved(call):
            out.cut_at(n, call.op, RUN_STOPPED_INSIDE)
            break
        if isinstance(call.args.get("dest"), str) and call.args["dest"]:
            out.cut_at(n, call.op, f"it writes {call.args['dest']}, a file the session named, "
                       "which a replay finds there already and is refused")
            break
        if isinstance(declared.export_as, tuple):
            if _reads_any(call.args, unwritten):
                out.drop(n, call.op, "it holds to files a dropped call wrote, which a replay "
                         "does not write: kept, it would hold by construction")
                continue
            out.steps.append(_step(call, call.recorded))
            out.checks += bool(call.recorded)
            continue
        out.steps.append(_step(call, call.recorded if _moved(call) else {}))
        _states(out, call, recorder.states)
    if "call" not in out.cut and recording.full:
        out.cut_at(len(recording.calls) + 1, unavailable("the recording's bound cut it, no call"),
                   f"the recording holds at most {STORED_PER_KEPT * recorder.record_max} calls "
                   "in all, the ones an export drops included" if recording.stored_out else
                   f"the recording holds at most {recorder.record_max} calls a replay keeps")
    doc = {"version": DOCUMENT_VERSION, "server": recorder.server, "entry": recorder.entry,
           "start": dict(recording.start), "steps": out.steps,
           "needs": {"states": out.loaded,
                     "declarations": {key: {"tool": recorder.lists[key], "refs": refs}
                                      for key, refs in recording.declarations.items()}}}
    return doc, out


def _reads_any(args: Mapping[str, Any], files: set[str]) -> bool:
    """Whether an argument names one of `files`, a directory holding one, or a file inside one."""
    named = [Path(v) for v in args.values() if isinstance(v, str) and v]
    return any(Path(f) == n or n in Path(f).parents or Path(f) in n.parents
               for f in files for n in named)


def _moved(call: Call) -> bool:
    """Whether the call left the machine at another stop than the one it found."""
    return _moved_between(call.before, call.after)


def _moved_between(before: Machine, after: Machine) -> bool:
    return (after.seq, dict(after.stop)) != (before.seq, dict(before.stop))


def _same_machine(a: Machine, b: Machine) -> bool:
    """Whether two readings describe one machine: running alike, at one stop."""
    return a.running == b.running and not _moved_between(a, b)


def _step(call: Call, recorded: Mapping[str, Any]) -> dict[str, Any]:
    step: dict[str, Any] = {"op": call.op, **call.args}
    if recorded:
        step[RECORDED] = dict(recorded)
    return step


def _states(out: Account, call: Call, states: States) -> None:
    name = call.args.get(states.argument)
    if call.op != states.tool or not isinstance(name, str):
        return
    if call.args.get("method") == states.save:
        out.saved.add(name)
    elif call.args.get("method") == states.load and name not in out.saved \
            and name not in out.loaded:
        out.loaded.append(name)


def _declared(tool: str, export_as: ExportAs | None, read_only: bool) -> Declared:
    if export_as is not None and not (
            export_as in WORDS or (isinstance(export_as, tuple) and export_as
                                   and all(isinstance(f, str) for f in export_as))):
        raise TypeError(f"{tool}: replay={export_as!r} is one of {list(WORDS)} or a tuple of "
                        "the reply fields a check holds to")
    return Declared(export_as if export_as is not None else "drop" if read_only else "step",
                    read_only)


def _dropped_why(declared: Declared) -> str:
    return ("a read the export does not check" if declared.read_only else
            "it changes nothing in the emulated machine")


def export(recorder: Recorder, dest: str, overwrite: bool = False) -> dict[str, Any]:
    """`perform_export`'s body: the recording written to `dest`, and the account (`dropped` holds
    the newest `DROPPED_SHOWN`). Raises `no_recording` when no `start` succeeded or no step is
    left to replay."""
    target = judges.writable_file("dest", dest)
    if target.suffix != ".json":
        raise Invalid("bad_argument", f"dest={dest!r} must end in `.json`: the document is JSON")
    if target.is_dir():
        raise Invalid("bad_argument", f"{target} is a directory")
    if os.path.lexists(target) and not overwrite:
        raise Invalid("bad_argument", f"{target} is there already; pass overwrite=true to "
                      "replace it")
    if recorder.recording is None:
        raise Invalid("no_recording", "nothing is recorded: a recording begins at a `start` "
                      "that succeeds")
    doc, out = document(recorder)
    if not out.steps:
        raise Invalid("no_recording", "the recording holds no step a replay could take: "
                      + (f"it is cut at call {out.cut['call']} ({out.cut['why']})"
                         if "call" in out.cut
                         else f"{len(out.dropped)} calls, every one dropped"))
    data = (json.dumps(doc, indent=2) + "\n").encode()
    if overwrite and os.path.lexists(target):
        fresh.replace(target, data, "the replay document")
    else:
        fresh.create(target, data, "the replay document", named_by_caller=True)
    return {"path": str(target), "steps": len(out.steps), "checks": out.checks,
            "dropped": out.dropped[-DROPPED_SHOWN:], "dropped_total": len(out.dropped),
            "cut": out.cut,
            "replay": f"uv run python -m scry_core.replay {shlex.quote(str(target))}"}


def diverged(recorded: Mapping[str, Any], reply: Mapping[str, Any]
             ) -> tuple[str, Any, Any] | None:
    """The first recorded field the reply does not hold to: (field, recorded, got), or None.
    Both sides are compared as JSON carries them."""
    for name, value in recorded.items():
        got = json.loads(json.dumps(reply.get(name), default=str))
        if got != value:
            return name, value, got
    return None


def step_arguments(step: Mapping[str, Any]) -> dict[str, Any]:
    """A step's arguments for its tool: everything but its `op` and its `recorded`."""
    return {k: v for k, v in step.items() if k not in ("op", RECORDED)}


def refuse_recorded(step: Mapping[str, Any]) -> str | None:
    """Why a step's `recorded` is not a mapping, or None."""
    if isinstance(step.get(RECORDED, {}), dict):
        return None
    return (f"carries `{RECORDED}` as {step[RECORDED]!r}: it is the fields a replay holds the "
            "step's reply to, a mapping of field to value")


def divergence(i: int, op: str, reply: Mapping[str, Any],
               apart: tuple[str, Any, Any]) -> tuple[str, dict[str, Any]]:
    """The message and fields of the INVALID `diverged` for step `i` (0-based; the message counts
    from 1): what the runner reads (`failed_at`, `field`, `recorded`, `got`) and the step's reply
    under `failed`."""
    field, recorded, got = apart
    return (f"step {i + 1} ({op!r}) diverged: `{field}` was recorded {recorded!r} and came back "
            f"{got!r}", {"failed_at": i, "failed": {"op": op, "reply": dict(reply)},
                         "field": field, "recorded": recorded, "got": got})


class Unrecorded:
    """The recorder of a server that records nothing: every hook a no-op."""

    recording: Recording | None = None

    def declare(self, tool: str, export_as: Replay | None, read_only: bool) -> None:
        """Nothing is exported, so nothing is declared."""

    def begin(self, tool: str, parent: str | None, given: Mapping[str, Any]) -> Machine | None:
        return None

    def end(self, tool: str, parent: str | None, given: Mapping[str, Any],
            reply: Mapping[str, Any], began: Machine | None) -> None:
        """No recording to add to."""

    def ended(self, tool: str, parent: str | None, given: Mapping[str, Any],
              began: Machine | None) -> None:
        """No recording to add to."""


#: `perform_export`'s description halves both servers share (`docs.filled`).
EXPORTS = ("Write what this session did since its `start` to `dest` as `perform`'s own document, "
           "so an investigation becomes a bench: `uv run python -m scry_core.replay <dest>`, from "
           "this server's repository, plays it with no model and exits 0 when every step held. "
           "Answers in any state, a closed session's included.")
EXPORT_REPLY = ("`dest` absolute or `~`-led, ending `.json`; refused if it is there unless "
                "`overwrite`. Reply: `path` (the file written), `steps`, `checks`, `dropped` "
                f"(the last {DROPPED_SHOWN}, each `call`, `op`, `why`) and `dropped_total`, "
                "`cut` (`call`, `op`, `why`, or unavailable) and `replay`, the runner's command "
                "line. `no_recording` before a `start` succeeded, after one was cancelled, or when "
                "no recorded call is a step a replay could take.")
DOC_VALUES = {"EXPORTS": EXPORTS, "EXPORT_REPLY": EXPORT_REPLY}


def export_summary(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """`perform_export`'s one line."""
    cut = f", cut at call {reply['cut']['call']}" if "call" in reply.get("cut", {}) else ""
    return (f"perform_export: {prose.counted(reply['steps'], 'step')}, "
            f"{prose.counted(reply['checks'], 'check')}, "
            f"{reply['dropped_total']} dropped{cut} to {reply['path']}")
