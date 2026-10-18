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

- a call the server refused is dropped, unless the machine moved under it;
- a tool declared `drop` (a read the export does not check, or a write only to the host: a file,
  a window, the emulator's pace) is dropped, unless the call moved the machine (a reader that
  steps the guest to read it), which is kept as a step: dropped, the replay would fall behind;
- a tool declared with fields is kept as a CHECK: the step carries `recorded`, those fields of its
  reply, and the replay's `perform` compares them;
- any other tool is kept as a STEP; one that left the machine at a new stop carries the stop's
  fields (`stop_fields`) as its `recorded`;
- a RUN THE WALL CLOCK SHAPED becomes frames: from a release (a call that left the machine running)
  to the first stop a call found it at (the one its reply says it found on its own, when it arrived
  unread) (or, when no call did, the stop the machine is at when the export reads it), or within one
  call of a tool declared `wall`, or of any tool whose reply's verdict says its wall-clock bound
  ended it (`WALL_VERDICTS`), the export writes `run_for(frames=<the difference between the two
  stops' frames>)` holding to the stop reached, whatever stopped it, because only a count of frames
  replays the same way; with the recorder's `reach`, that holds to the frame alone and the advance
  `reach` names then goes on to the stop's place and holds to the whole stop, because frames end at
  a frame's edge and a stop lands anywhere inside its frame; a run that would not stop at the same
  place shows as `diverged`;
- the first call the rules cannot place (its frames unknown, made while the machine ran, ended
  without a reply, or with the machine unreadable around it) CUTS the document there: what came
  before stands, and the reply names the call and why.
"""

from __future__ import annotations

import dataclasses
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
#: A reply's `verdict` when the call's wall-clock bound ended it, whatever the tool: such a run is
#: a run the wall clock shaped, written as the frames it took.
WALL_VERDICTS = frozenset({"TIMEOUT"})

#: What a tool's calls become in an export: kept as a `step`; a `wall` step, a run the wall clock
#: ends; `drop`ped; or, a tuple of field names, kept as a check of those fields.
Word = Literal["step", "wall", "drop"]
ExportAs = Word | tuple[str, ...]
WORDS: tuple[str, ...] = get_args(Word)


@dataclass(frozen=True)
class Machine:
    """The machine around a call, as the server reads it. `running`: whether it runs. `frame`
    and `seq`: the frame and the sequence number of the stop it is at, None when not known.
    `stop`: that stop in the fields a replayed advance answers with (`stop_fields`), so a
    `run_for` that replaces a run holds to them. `known`: False when the server could not be
    read at all."""

    running: bool
    frame: int | None
    seq: int | None
    stop: Mapping[str, Any] = field(default_factory=dict)
    known: bool = True


#: What a recording keeps for a machine the server could not read.
UNREAD = Machine(running=True, frame=None, seq=None, known=False)


@dataclass(frozen=True)
class Call:
    """One recorded call: `status` is the reply's, or `ended` for a call with no reply (cancelled,
    or failed in its body); `walled` when its reply says the wall clock's bound ended it; `wrote`
    the files it names as written (its `dest`, its reply's `path`); `found` the stop it found the
    machine at on its own (its reply's `stopped_on_its_own`): one that arrived while nobody read
    it, which ended a run before the call began."""

    op: str
    args: Mapping[str, Any]
    status: str
    recorded: Mapping[str, Any]
    before: Machine
    after: Machine
    walled: bool = False
    wrote: tuple[str, ...] = ()
    found: Mapping[str, Any] | None = None


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
    machine (`Machine`); `stop_fields` names the fields of a reply that say where a stop is;
    `sequences` the tools whose steps are recorded in their place; `start_tool` the tool that
    begins a recording and `plan` its argument whose steps are recorded after it; `outside` the
    tools that are no step a replay could take (`close`, the exporter's own); `reach` the advance
    that goes on from a frame's edge to a stop's place, as its op, the argument naming the place
    and the stop field holding it (`("run_to", "ref", "pc")`): without it, a run's frames hold to
    the whole stop."""

    def __init__(self, server: str, machine: Callable[[], Machine], *,
                 stop_fields: tuple[str, ...], outside: frozenset[str] = frozenset({"close"}),
                 sequences: frozenset[str] = frozenset({"perform", "drive"}),
                 start_tool: str = "start", plan: str | None = None,
                 reach: tuple[str, str, str] | None = None) -> None:
        self.server = server
        self._machine = machine
        self.stop_fields = stop_fields
        self.outside = outside | {EXPORT_TOOL}
        self.sequences = sequences
        self.start_tool = start_tool
        self.plan = plan
        self.reach = reach
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
            # recording before it belongs to a machine that is gone.
            session = reply.get("session")
            up = reply.get("status") == "ok" or (isinstance(session, dict)
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
                                                                reply.get("path"))
                                               if isinstance(x, str) and x),
                                   found=_found(reply.get("stopped_on_its_own"))))

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

    def read(self) -> Machine:
        """The machine now, as `_read` reads it: what an export ends a pending run at."""
        return self._read()

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


def document(recorder: Recorder, now: Machine | None = None) -> tuple[dict[str, Any], Account]:
    """The recorder's recording as `perform`'s document, by the rules the module docstring sets
    out, and the account of what was kept, dropped and cut. `now` is the machine as the export
    reads it, which ends a run no recorded call saw end. `recorder.recording` is not None."""
    recording = recorder.recording
    assert recording is not None
    out = Account()
    released: tuple[int, Call] | None = None
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
        if released is not None and call.found is not None:
            # A STOP THAT ARRIVED UNREAD ended the run before this call began, and its reply says
            # where: the run ends there, and the call is judged from that stop.
            reached = _found_machine(call.found, recorder)
            if not _run_for(out, released, reached, None, recorder.reach):
                break
            released = None
            call = dataclasses.replace(call, before=reached)
        if released is not None and not call.before.running:
            # The machine had stopped before this call began: the run ends at that stop.
            if not _run_for(out, released, call.before, None, recorder.reach):
                break
            released = None
        if released is not None and not call.after.running:
            # This call found the machine stopped: a poll, a stop or a read that noticed is the
            # run's end; a call that went on to do its own work is kept after the run.
            noticed = declared.export_as in ("drop", "wall") or call.status != "ok"
            if not noticed and _moved_by_itself(call, recorder):
                out.cut_at(n, call.op, "it began on a machine whose run had just stopped, and "
                           "where that stop was is not recorded apart from its own")
                break
            if not _run_for(out, released, call.after, (n, call) if noticed else None,
                            recorder.reach):
                break
            released = None
            if noticed:
                continue
            call = Call(call.op, call.args, call.status, call.recorded, call.after, call.after)
        if call.status != "ok":
            if _moved(call):
                out.cut_at(n, call.op, f"the server refused it ({call.status}) after the "
                           "machine had moved under it")
                break
            out.drop(n, call.op, f"the server refused it ({call.status})")
            continue
        if released is not None:
            if declared.export_as == "drop":
                out.drop(n, call.op, _dropped_why(declared))
                continue
            out.cut_at(n, call.op, "it was made while the machine ran, at no frame a replay can "
                       "place it at")
            break
        if declared.export_as in ("drop", "wall") and not _moved(call):
            out.drop(n, call.op, _dropped_why(declared) if declared.export_as == "drop"
                     else "it ran nothing: the machine was where it left it")
            unwritten.update(call.wrote)
            continue
        if isinstance(declared.export_as, tuple):
            if _reads_any(call.args, unwritten):
                out.drop(n, call.op, "it holds to files a dropped call wrote, which a replay "
                         "does not write: kept, it would hold by construction")
                continue
            out.steps.append(_step(call, call.recorded))
            out.checks += bool(call.recorded)
            continue
        if call.after.running:
            released = (n, call)
            continue
        if (declared.export_as == "wall" or call.walled) and _moved(call):
            if not _run_for(out, (n, call), call.after, (n, call), recorder.reach):
                break
            continue
        out.steps.append(_step(call, call.recorded if _moved(call) else {}))
        _states(out, call)
    else:
        if released is not None and (now is None or now.running or not now.known):
            out.cut_at(released[0], released[1].op, "it left the machine running and no call "
                       "found it stopped again, so the frames of its run are unknown")
        elif released is not None and now is not None:
            _run_for(out, released, now, None, recorder.reach)
    if out.cut is None and recording.full:
        out.cut_at(RECORD_MAX + 1, None, f"the recording holds at most {RECORD_MAX} calls")
    doc = {"version": DOCUMENT_VERSION, "server": recorder.server, "start": dict(recording.start),
           "steps": out.steps, "needs": {"states": out.loaded}}
    return doc, out


def _found(value: object) -> Mapping[str, Any] | None:
    return dict(value) if isinstance(value, dict) and value else None


def _found_machine(found: Mapping[str, Any], recorder: Recorder) -> Machine:
    """The stop a call found, as the machine at it."""
    frame = found.get("frame")
    seq = found.get("stop_seq")
    return Machine(running=False, frame=frame if isinstance(frame, int) else None,
                   seq=seq if isinstance(seq, int) else None,
                   stop={f: found[f] for f in recorder.stop_fields if f in found})


def _reads_any(args: Mapping[str, Any], files: set[str]) -> bool:
    """Whether an argument names one of `files`, or a directory holding one."""
    named = [Path(v) for v in args.values() if isinstance(v, str) and v]
    return any(Path(f) == n or n in Path(f).parents for f in files for n in named)


def _moved(call: Call) -> bool:
    """Whether the call left the machine at another stop than the one it found."""
    return (call.after.seq, dict(call.after.stop)) != (call.before.seq, dict(call.before.stop))


def _moved_by_itself(call: Call, recorder: Recorder) -> bool:
    """Whether a call that found a stopped machine answered with a stop of its own making."""
    return any(f in call.recorded for f in recorder.stop_fields) and _moved(call)


def _step(call: Call, recorded: Mapping[str, Any]) -> dict[str, Any]:
    step: dict[str, Any] = {"op": call.op, **call.args}
    if recorded:
        step[RECORDED] = dict(recorded)
    return step


def _run_for(out: Account, released: tuple[int, Call], reached: Machine,
             replaced: tuple[int, Call] | None, reach: tuple[str, str, str] | None) -> bool:
    """The run from `released`'s stop to `reached`, as frames, the calls it replaces named;
    False (and the cut set) when the frames are unknown or do not go forward. With `reach`, the
    frames hold to the frame alone and the advance it names goes on to the stop's place: frames
    end at a frame's edge, and a stop that ended a run lands anywhere inside its frame."""
    began, ended = released[1].before.frame, reached.frame
    if began is None or ended is None:
        out.cut_at(released[0], released[1].op, "the run it began was ended by the wall clock "
                   "and the server reads no frame to replace it with")
        return False
    if ended <= began:
        out.cut_at(released[0], released[1].op, f"the run it began ended at frame {ended}, not "
                   f"after frame {began}, so no count of frames replays it")
        return False
    stop = dict(reached.stop)
    op, argument, field = reach if reach and reach[2] in stop else (None, "", "")
    edge = {f: v for f, v in stop.items() if f != field}
    out.steps.append({"op": "run_for", "frames": ended - began,
                      **({RECORDED: edge} if edge else {})})
    took = f"run_for(frames={ended - began})"
    if op is not None:
        out.steps.append({"op": op, argument: stop[field], RECORDED: stop})
        took += f" then {op}({argument}={stop[field]!r})"
    for at, call in dict([released, *([replaced] if replaced else [])]).items():
        out.drop(at, call.op, f"replaced by {took}, the frames its run took and its place")
    return True


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
    runner's command line. `no_recording` when no `start` succeeded since the server began."""
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
    doc, out = document(recorder, recorder.read())
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
