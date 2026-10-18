"""A SESSION RECORDED AS IT WAS DONE, and exported as `perform`'s own document: what a Scry server's
call boundary feeds (`Recorder`), the rules of the export (`document`), the tool body that writes
it (`export`), and the check a replayed step holds to (`diverged`). The runner that plays a
document back is `scry_core.replay`, apart, because a server never needs the client it uses.

THE RECORDING is always on from a `start` that left a session up (the document's start; a plan it
ran that failed included) and cleared by the next one; `close` keeps it, so a session can be
exported after it closed. Every outermost call is recorded with its arguments as given, its status,
what its reply says that a replay must hold to, and the machine around it (`Machine`), except a
sequence (`perform`, `drive`), whose steps are recorded instead, and the tools that are no step of a
sequence (`outside`: `close`, the exporter); a `start` that runs a plan has its plan's steps
recorded after it. `RECORD_MAX` calls at most; past it the recording stops and the export says it is
cut there.

THE EXPORT keeps what moved the machine and what was checked, drops the rest and names each drop:

- a call the server refused is dropped, unless the machine moved under it (which cuts);
- a tool declared `drop` (a read the export does not check, or a write only to the host: a file,
  a window, the emulator's pace) is dropped, unless the call moved the machine (a reader that
  steps the guest to read it), which is kept as a step: dropped, the replay would fall behind;
- a tool declared with fields is kept as a CHECK: the step carries `recorded`, those fields of its
  reply, and the replay's `perform` compares them; one whose arguments name what a dropped call
  wrote (`dest`, or its reply's `WRITTEN` fields: the file, the directory, a file inside it) is
  dropped, because the replay does not write it and the check would hold by construction;
- any other tool is kept as a STEP; one that left the machine at a new stop carries the stop's
  fields (`stop_fields`) as its `recorded`;
- a RELEASE (a call that left the machine running), and a call declared `wall` that came back with
  the machine moved (a `resume(seconds=)` that stopped, a `stop`) or whose reply says its wall-clock
  bound ended it (`WALL_VERDICTS`), CUT the document there: whatever ends such a run, the clock or a
  breakpoint, stops the cpu at a place inside its frame, and no replayed advance reaches it, a count
  of frames ending at the frame's edge; every stop after it would inherit the shift, so what came
  before is the bench;
- the first call the rules cannot place (ended without a reply, refused after the machine moved,
  or with the machine unreadable around it) CUTS the document there: what came
  before stands, and the reply names the call and why.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

from scry_core import fresh
from scry_core.reply_contract import Invalid

#: The most calls one recording holds: as many as one `perform(until_frame=)` takes in steps.
RECORD_MAX = 5000
#: The most dropped calls an export's reply lists, the newest; `dropped_total` counts them all.
DROPPED_SHOWN = 40
#: The document's own version, which a runner of another shape refuses.
DOCUMENT_VERSION = 1
#: The tool that exports, which is never recorded.
EXPORT_TOOL = "perform_export"
#: The key a step's recorded fields sit under: no Scry tool declares an argument by that name.
RECORDED = "recorded"
#: A reply's `verdict` when the call's wall-clock bound ended it, whatever the tool: such a run
#: stopped wherever the clock found the cpu, and ends the document.
WALL_VERDICTS = frozenset({"TIMEOUT"})
#: Why a release ends the document: the run stops where the clock or the machine (a breakpoint)
#: stops the cpu, inside a frame and inside whatever loop it is in, and no replayed advance
#: reaches that place (a count of frames ends at a frame's edge); every stop after it would
#: inherit the shift.
RELEASED = ("it released the machine, and the stop that ends a run lands at a place inside its "
            "frame that no replayed advance reaches")
RUN_STOPPED_INSIDE = ("its run was stopped by the wall clock or by the machine itself, at a place "
                      "inside its frame that no replayed advance reaches")
#: The reply fields that name a file or a directory a call wrote, beside its `dest` argument.
WRITTEN = ("path", "manifest", "dir")

#: What a tool's calls become in an export: kept as a `step`; a `wall` step, a run the wall clock
#: ends; `drop`ped; or, a tuple of field names, kept as a check of those fields.
Word = Literal["step", "wall", "drop"]
ExportAs = Word | tuple[str, ...]
WORDS: tuple[str, ...] = get_args(Word)


@dataclass(frozen=True)
class Machine:
    """The machine around a call, as the server reads it. `running`: whether it runs. `seq`: the
    sequence number of the stop it is at, None when not known. `stop`: that stop in the fields a
    replayed advance answers with (`stop_fields`); with `seq`, what says a call moved the machine.
    `known`: False when the server could not be read at all."""

    running: bool
    seq: int | None
    stop: Mapping[str, Any] = field(default_factory=dict)
    known: bool = True


#: What a recording keeps for a machine the server could not read.
UNREAD = Machine(running=True, seq=None, known=False)


@dataclass(frozen=True)
class Call:
    """One recorded call: `status` is the reply's, or `ended` for a call with no reply (cancelled,
    or failed in its body); `walled` when its reply says the wall clock's bound ended it; `wrote`
    the files it names as written (its `dest`, its reply's `path`)."""

    op: str
    args: Mapping[str, Any]
    status: str
    recorded: Mapping[str, Any]
    before: Machine
    after: Machine
    walled: bool = False
    wrote: tuple[str, ...] = ()


@dataclass
class Recording:
    """What a session did since its `start`; `full` once it reached `RECORD_MAX`."""

    start: Mapping[str, Any]
    calls: list[Call] = field(default_factory=list)
    full: bool = False


@dataclass(frozen=True)
class Declared:
    """How a tool's calls are exported, and whether it reads only (what a drop is said to be)."""

    export_as: ExportAs
    read_only: bool


class Recorder:
    """One server's recording, fed by its `scry_core.boundary.Boundary`. `machine` reads the
    machine (`Machine`); `live` says whether a session is up, as the start refuses over one;
    `stop_fields` names the fields of a reply that say where a stop is;
    `sequences` the tools whose steps are recorded in their place; `start_tool` the tool that
    begins a recording and `plan` its argument whose steps are recorded after it; `outside` the
    tools that are no step a replay could take (`close`, the exporter's own)."""

    def __init__(self, server: str, machine: Callable[[], Machine], live: Callable[[], bool], *,
                 stop_fields: tuple[str, ...], outside: frozenset[str] = frozenset({"close"}),
                 sequences: frozenset[str] = frozenset({"perform", "drive"}),
                 start_tool: str = "start", plan: str | None = None) -> None:
        self.server = server
        self._machine = machine
        self._live = live
        self._found_live = False
        self.stop_fields = stop_fields
        self.outside = outside | {EXPORT_TOOL}
        self.sequences = sequences
        self.start_tool = start_tool
        self.plan = plan
        self.declared: dict[str, Declared] = {}
        self.recording: Recording | None = None
        self._starting: Recording | None = None

    def declare(self, tool: str, export_as: ExportAs | None, read_only: bool) -> None:
        """A tool registered: how its calls are exported, by default `drop` for a reader and
        `step` for the rest. Anything else is refused at import, as a typo would be a step."""
        if export_as is not None and not (
                export_as in WORDS or (isinstance(export_as, tuple) and export_as
                                       and all(isinstance(f, str) for f in export_as))):
            raise TypeError(f"{tool}: replay={export_as!r} is one of {list(WORDS)} or a tuple of "
                            "the reply fields a check holds to")
        self.declared[tool] = Declared(
            export_as if export_as is not None else "drop" if read_only else "step", read_only)

    def kind(self, tool: str) -> Declared:
        """A tool's declaration; one registered nowhere here is a step that reads."""
        return self.declared.get(tool, Declared("step", False))

    def begin(self, tool: str, parent: str | None, given: Mapping[str, Any]) -> Machine | None:
        """The machine before a call this recording takes, or None for one it does not: a
        tool `outside`, a sequence (its steps are taken instead), a call nested in anything
        but a sequence or a plan, and any call while nothing records."""
        if tool in self.outside:
            return None
        if parent is None and tool == self.start_tool:
            self._starting = Recording({k: v for k, v in given.items() if k != self.plan})
            self._found_live = self._was_live()
            return None
        if parent is None:
            if tool in self.sequences or self.recording is None:
                return None
            return self._read()
        if parent in self.sequences and self.recording is not None:
            return self._read()
        if parent == self.start_tool and self.plan is not None and self._starting is not None:
            return self._read()
        return None

    def end(self, tool: str, parent: str | None, given: Mapping[str, Any],
            reply: Mapping[str, Any], began: Machine | None) -> None:
        """A call answered: a successful outermost `start` makes its recording the session's;
        a call `begin` took is added to its recording."""
        if parent is None and tool == self.start_tool:
            # A START THAT LEFT A SESSION UP is that session's, a plan that failed included: the
            # recording before it belongs to a machine that is gone. One refused while a session
            # was live touched nothing, and the session up is the one recorded.
            session = reply.get("session")
            up = reply.get("status") == "ok" or (not self._found_live and isinstance(session, dict)
                                                 and session.get("alive") is True)
            if up and self._starting is not None:
                self.recording = self._starting
            self._starting = None
            return
        if began is not None:
            fields = self.kind(tool).export_as
            fields = fields if isinstance(fields, tuple) else self.stop_fields
            self._add(parent, Call(tool, dict(given), str(reply.get("status")),
                                   {f: reply[f] for f in fields if f in reply}, began,
                                   self._read(), walled=reply.get("verdict") in WALL_VERDICTS,
                                   wrote=tuple(str(x) for x in (given.get("dest"),
                                                                *map(reply.get, WRITTEN))
                                               if isinstance(x, str) and x)))

    def ended(self, tool: str, parent: str | None, given: Mapping[str, Any],
              began: Machine | None) -> None:
        """A call that ended with no reply, cancelled or failed: a `start` takes the recording
        with it (the machine it started is not the one recorded); any other call taken is added
        as `ended`, which cuts the export there."""
        if parent is None and tool == self.start_tool:
            self.recording = self._starting = None
        elif began is not None:
            self._add(parent, Call(tool, dict(given), "ended", {}, began, self._read()))

    def _add(self, parent: str | None, call: Call) -> None:
        into = self._starting if parent == self.start_tool else self.recording
        assert into is not None          # `begin` takes no call while there is nothing to add to
        if len(into.calls) >= RECORD_MAX:
            into.full = True
            return
        into.calls.append(call)

    def _was_live(self) -> bool:
        """Whether a session was up as a start began; unreadable counts as up, so a start that
        cannot be told apart keeps the recording rather than handing it to a refusal."""
        try:
            return self._live()
        except Exception:  # noqa: BLE001 -- as `_read`: a recorder never fails a call
            return True

    def _read(self) -> Machine:
        """The machine as the server reads it, or `UNREAD`: a recorder never fails a call."""
        try:
            return self._machine()
        except Exception:  # noqa: BLE001 -- the call stands; its export is cut here, saying why
            return UNREAD


# ============================================================================ the export


@dataclass
class Account:
    """What an export kept, dropped and cut, beside the steps it wrote."""

    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: int = 0
    dropped: list[dict[str, Any]] = field(default_factory=list)
    cut: dict[str, Any] | None = None
    saved: set[str] = field(default_factory=set)
    loaded: list[str] = field(default_factory=list)

    def drop(self, n: int, op: str, why: str) -> None:
        self.dropped.append({"call": n, "op": op, "why": why})

    def cut_at(self, n: int | None, op: str | None, why: str) -> None:
        self.cut = {"call": n, "op": op, "why": why}


def document(recorder: Recorder) -> tuple[dict[str, Any], Account]:
    """The recorder's recording as `perform`'s document, by the rules the module docstring sets
    out, and the account of what was kept, dropped and cut. `recorder.recording` is not None."""
    recording = recorder.recording
    assert recording is not None
    out = Account()
    unwritten: set[str] = set()          # files that dropped calls wrote, which no replay writes
    for n, call in enumerate(recording.calls, start=1):
        declared = recorder.kind(call.op)
        if not (call.before.known and call.after.known):
            out.cut_at(n, call.op, "the server could not read the machine around it")
            break
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
        if isinstance(declared.export_as, tuple):
            if _reads_any(call.args, unwritten):
                out.drop(n, call.op, "it holds to files a dropped call wrote, which a replay "
                         "does not write: kept, it would hold by construction")
                continue
            out.steps.append(_step(call, call.recorded))
            out.checks += bool(call.recorded)
            continue
        out.steps.append(_step(call, call.recorded if _moved(call) else {}))
        _states(out, call)
    if out.cut is None and recording.full:
        out.cut_at(RECORD_MAX + 1, None, f"the recording holds at most {RECORD_MAX} calls")
    doc = {"version": DOCUMENT_VERSION, "server": recorder.server, "start": dict(recording.start),
           "steps": out.steps, "needs": {"states": out.loaded}}
    return doc, out


def _reads_any(args: Mapping[str, Any], files: set[str]) -> bool:
    """Whether an argument names one of `files`, a directory holding one, or a file inside one
    (a series' `dest` is a directory, and its manifest a file in it)."""
    named = [Path(v) for v in args.values() if isinstance(v, str) and v]
    return any(Path(f) == n or n in Path(f).parents or Path(f) in n.parents
               for f in files for n in named)


def _moved(call: Call) -> bool:
    """Whether the call left the machine at another stop than the one it found."""
    return (call.after.seq, dict(call.after.stop)) != (call.before.seq, dict(call.before.stop))


def _step(call: Call, recorded: Mapping[str, Any]) -> dict[str, Any]:
    step: dict[str, Any] = {"op": call.op, **call.args}
    if recorded:
        step[RECORDED] = dict(recorded)
    return step


def _states(out: Account, call: Call) -> None:
    name = call.args.get("name")
    if call.op == "state_save" and isinstance(name, str):
        out.saved.add(name)
    elif (call.op == "state_load" and isinstance(name, str) and name not in out.saved
          and name not in out.loaded):
        out.loaded.append(name)


def _dropped_why(declared: Declared) -> str:
    return ("a read the export does not check" if declared.read_only else
            "it is declared a write to the host only (a file, a window, the pace)")


def export(recorder: Recorder, path: str, overwrite: bool = False) -> dict[str, Any]:
    """`perform_export`'s body: the recording written to `path` (absolute or `~`-led, `.json`,
    refused if it is there unless `overwrite`), and the account: `path`, `steps`, `checks`,
    `dropped` (the newest `DROPPED_SHOWN`) with `dropped_total`, `cut`, and `replay`, the
    runner's command line. `no_recording` when no `start` succeeded since the server began, or
    when the recording holds no step a replay could take (cut at its first, or every call
    dropped)."""
    if not (path.startswith("~") or Path(path).is_absolute()):
        raise Invalid("bad_argument", f"path={path!r} is absolute or starts with `~`")
    try:
        target = Path(path).expanduser()
    except RuntimeError as e:                      # `~nobody/...`: no such home
        raise Invalid("bad_argument", f"path={path!r}: {e}") from None
    if target.suffix != ".json":
        raise Invalid("bad_argument", f"path={path!r} ends in `.json`: the document is JSON")
    if not target.parent.is_dir():
        raise Invalid("bad_argument", f"{target.parent} is not a directory")
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
                      + (f"it is cut at call {out.cut['call']} ({out.cut['why']})" if out.cut
                         else f"{len(out.dropped)} calls, every one dropped"))
    data = (json.dumps(doc, indent=2) + "\n").encode()
    if overwrite and os.path.lexists(target):
        # A NEW FILE BESIDE IT, then moved over it: a write that fails leaves the old one whole.
        beside = target.with_name(f".{target.name}.new")
        beside.unlink(missing_ok=True)
        fresh.create(beside, data, "the replay document")
        os.replace(beside, target)
    else:
        fresh.create(target, data, "the replay document", named_by_caller=True)
    return {"path": str(target), "steps": len(out.steps), "checks": out.checks,
            "dropped": out.dropped[-DROPPED_SHOWN:], "dropped_total": len(out.dropped),
            "cut": out.cut,
            "replay": f"uv run python -m scry_core.replay {shlex.quote(str(target))}"}


def diverged(recorded: Mapping[str, Any], reply: Mapping[str, Any]
             ) -> tuple[str, Any, Any] | None:
    """The first recorded field the reply does not hold to: (field, recorded, got), or None.
    Both sides are compared as JSON carries them, since the recorded side came through it."""
    for name, value in recorded.items():
        got = json.loads(json.dumps(reply.get(name), default=str))
        if got != value:
            return name, value, got
    return None


def step_arguments(step: Mapping[str, Any]) -> dict[str, Any]:
    """A step's arguments for its tool: everything but its `op` and its `recorded`."""
    return {k: v for k, v in step.items() if k not in ("op", RECORDED)}


def refuse_recorded(step: Mapping[str, Any]) -> str | None:
    """Why a step's `recorded` is not one (a sequence's preflight refuses the step with it), or
    None when it is a mapping or absent."""
    if isinstance(step.get(RECORDED, {}), dict):
        return None
    return (f"carries `{RECORDED}` as {step[RECORDED]!r}: it is the fields a replay holds the "
            "step's reply to, a mapping of field to value")


def divergence(i: int, op: str, reply: Mapping[str, Any],
               apart: tuple[str, Any, Any]) -> tuple[str, dict[str, Any]]:
    """The message and the fields of the INVALID `diverged` a sequence answers when step `i`
    (`op`) did not hold to its `recorded`: what the runner reads (`failed_at`, `field`,
    `recorded`, `got`) and the step's own reply under `failed`, as a failed step carries it."""
    field, recorded, got = apart
    return (f"step {i} ({op!r}) diverged: `{field}` was recorded {recorded!r} and came back "
            f"{got!r}", {"failed_at": i, "failed": {"op": op, "reply": dict(reply)},
                         "field": field, "recorded": recorded, "got": got})
