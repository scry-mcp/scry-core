"""`scry_core.recording`: what a recording takes, what an export keeps, drops and cuts, and the
check a replayed step holds to; driven through a call boundary over a double machine."""

from __future__ import annotations

import asyncio
import json
import shlex
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scry_core import boundary, cancel, recording
from scry_core.envelope import Envelope
from scry_core.reply_contract import Invalid


def _held(refs: list[str]) -> dict[str, Any]:
    return {"breakpoint_list": {"key": "breakpoints", "refs": refs}}


#: The double's tool names, which a real server declares as its own.
VOCABULARY: dict[str, Any] = {"outside": frozenset({"close"}),
                              "sequences": frozenset({"perform", "drive"}),
                              "start_tool": "start", "states": ("state_save", "state_load", "name"),
                              "lists": {"breakpoint_list": "breakpoints"}}


class _Machine:
    """The machine the double's tools move: running or not, its frame and its stop's number."""

    def __init__(self) -> None:
        self.running = False
        self.frame: int | None = 100
        self.seq = 1
        self.unreadable = False
        self.bare = False          # a server whose stops carry no fields (dosbox-x's are counted)
        self.up = False            # a session is live, which a second start is refused over
        self.start_raises = False  # a start whose body fails, ending with no reply

    def read(self) -> recording.Machine:
        if self.unreadable:
            raise OSError("the console did not answer")
        stop = ({} if self.running or self.bare else
                {"pc": f"0x{self.seq:x}", "frame": self.frame})
        return recording.Machine(self.running, self.seq, stop)

    def stop_at(self, frame: int | None) -> None:
        self.running, self.frame, self.seq = False, frame, self.seq + 1


#: The double's own `perform` step limit, which it declares to its recorder.
RECORD_MAX = 5000


class _Server:
    """A boundary with a recorder and the tools a session uses, each moving `_Machine`."""

    def tool(self, title: str, **kw: Any) -> Callable[[Callable[..., Any]], Any]:
        """`Boundary.tool` with the double's line, the tool's name."""
        def register(fn: Callable[..., Any]) -> Any:
            def line(args: dict[str, Any], reply: dict[str, Any], name: str = fn.__name__) -> str:
                return name
            return self.b.tool(title, summary=line, **kw)(fn)
        return register

    def __init__(self, plan: str | None = None) -> None:
        self.m = _Machine()
        self.declared: list[str] = []
        self.recorder = recording.Recorder("double", "double.py", RECORD_MAX, self.m.read,
                                           lambda: self.m.up,
                                           declarations=lambda: {"breakpoint_list": self.declared},
                                           stop_fields=("pc", "frame"), plan=plan,
                                           **VOCABULARY)
        self.b = boundary.Boundary(
            Envelope("t", instructions="i", refusal=lambda *a: {}), threading.RLock(),
            invoke=lambda fn, bound: dict(fn(*bound.args, **bound.kwargs)),
            end=lambda n, o: ("stopped", None),
            refusal_line=lambda n, r: n, session_block=lambda: {}, take_cancelled=lambda: None,
            keep_cancelled=lambda r: None, doc=lambda n, t: t, recorder=self.recorder)
        b, m = self, self.m

        def stopped() -> dict[str, Any]:
            return {"status": "ok", "pc": f"0x{m.seq:x}", "frame": m.frame}

        @b.tool("start")
        def start(system: str, plan: list[dict[str, Any]] | None = None,
                  fails: bool = False, over_live: bool = False) -> dict[str, Any]:
            if over_live:                      # refused before anything is spawned
                return {"status": "INVALID", "code": "session_live", "message": "close first",
                        "session": {"alive": True}}
            if fails:
                return {"status": "INVALID", "code": "bad_argument", "message": "no",
                        "session": {"alive": False}}
            if m.start_raises:
                raise RuntimeError("the start failed in its body")
            m.running, m.frame, m.seq, m.up = False, 100, 1, True
            for step in plan or []:
                got = ops[step["op"]](**{k: v for k, v in step.items() if k != "op"})
                if got.get("status") != "ok":    # the plan failed; the session stays up
                    return {"status": "INVALID", "code": "step_failed", "message": "plan",
                            "session": {"alive": True}}
            return {"status": "ok"}

        @b.tool("run_for")
        def run_for(frames: int, seconds: float = 30.0) -> dict[str, Any]:
            if seconds < 1:                    # the bound ran out first, a third of the way
                m.stop_at(None if m.frame is None else m.frame + frames // 3)
                return {**stopped(), "verdict": "TIMEOUT"}
            m.stop_at(None if m.frame is None else m.frame + frames)
            return stopped()

        @b.tool("resume", replay="wall")
        def resume(seconds: float = 0, frames_then: int = 30) -> dict[str, Any]:
            if seconds:
                m.stop_at(None if m.frame is None else m.frame + frames_then)
                return stopped()
            m.running = True
            return {"status": "ok"}

        @b.tool("stop", replay="wall")
        def stop(frames_then: int = 50, already: bool = False) -> dict[str, Any]:
            if not already:
                m.stop_at(None if m.frame is None else m.frame + frames_then)
            return stopped()

        @b.tool("write")
        def write(ref: str, value: int) -> dict[str, Any]:
            if ref == "bad":
                return {"status": "INVALID", "code": "unknown_ref", "message": "no such ref"}
            return {"status": "ok"}

        @b.tool("declare")
        def declare(ref: str) -> dict[str, Any]:
            self.declared.append(ref)            # a breakpoint_at, say: the store grows
            return {"status": "ok"}

        @b.tool("record")
        def record(dest: str, frames: int) -> dict[str, Any]:
            m.stop_at((m.frame or 0) + frames)      # a run that writes a file the caller named
            return {"status": "ok", "path": dest, **stopped()}

        @b.tool("peek", read_only=True)
        def peek() -> dict[str, Any]:
            m.stop_at(m.frame)     # a reader that steps the guest to read it
            return {"status": "ok"}

        @b.tool("look")
        def look() -> dict[str, Any]:
            return stopped()       # where the machine stands, which this step did not move

        @b.tool("wait_out")
        def wait_out(frames: int) -> dict[str, Any]:
            m.stop_at(None if m.frame is None else m.frame + frames)
            return {"status": "INVALID", "code": "wait_expired", "message": "ran out"}

        @b.tool("crashes")
        def crashes(frames: int, cancelled: bool = False) -> dict[str, Any]:
            m.stop_at(None if m.frame is None else m.frame + frames)
            if cancelled:
                raise asyncio.CancelledError
            raise ZeroDivisionError

        @b.tool("close")
        def close() -> dict[str, Any]:
            return {"status": "ok"}

        @b.tool("read_memory", read_only=True, replay=("hex",))
        def read_memory(ref: str) -> dict[str, Any]:
            return {"status": "ok", "hex": "beef", "addr": ref}

        @b.tool("log", read_only=True)
        def log() -> dict[str, Any]:
            return {"status": "ok", "lines": []}

        @b.tool("poke_and_look")
        def poke_and_look(ref: str) -> dict[str, Any]:
            read_memory(ref=ref)               # a tool's own use of another, not the caller's
            return {"status": "ok"}

        @b.tool("snapshot", replay="drop")
        def snapshot(dest: str = "") -> dict[str, Any]:
            return {"status": "ok", "path": dest or "/tmp/x.png"}

        @b.tool("golden_check", read_only=True, replay=("matched",))
        def golden_check(dir: str = "", manifest: str = "") -> dict[str, Any]:
            return {"status": "ok", "matched": ["a.png"]}

        @b.tool("series_capture", replay="drop")
        def series_capture(dest: str = "") -> dict[str, Any]:
            return {"status": "ok", "manifest": f"{dest or '/tmp/s'}/manifest.json"}

        @b.tool("go_refused")
        def go_refused() -> dict[str, Any]:
            m.running = True       # let go, then refused what it was asked after
            return {"status": "INVALID", "code": "bad_argument", "message": "after the release"}

        @b.tool("state_save")
        def state_save(name: str) -> dict[str, Any]:
            return {"status": "ok"}

        @b.tool("state_load")
        def state_load(name: str) -> dict[str, Any]:
            m.stop_at(m.frame)
            return stopped()

        @b.tool("perform")
        def perform(steps: list[dict[str, Any]]) -> dict[str, Any]:
            for step in steps:
                ops[step["op"]](**{k: v for k, v in step.items() if k != "op"})
            return {"status": "ok"}

        @b.tool(recording.EXPORT_TOOL, replay="drop")
        def perform_export(path: str, overwrite: bool = False) -> dict[str, Any]:
            return {"status": "ok", **recording.export(self.recorder, path, overwrite)}

        ops = {"run_for": run_for, "write": write, "read_memory": read_memory, "resume": resume,
               "declare": declare}
        self.tools = {f.__name__: f for f in (start, run_for, resume, stop, write, peek,
                                              look, golden_check, series_capture, go_refused,
                                              wait_out, crashes, close, read_memory, log,
                                              poke_and_look, snapshot, state_save, state_load,
                                              perform, perform_export, record, declare)}

    def __getattr__(self, name: str) -> Any:
        return self.tools[name]

    def document(self) -> tuple[dict[str, Any], Any]:
        assert self.recorder.recording is not None
        return recording.document(self.recorder)


# ======================================================================== the recording


def test_nothing_is_recorded_before_a_start_and_a_start_begins_the_recording() -> None:
    s = _Server()
    s.write(ref="a", value=1)
    nothing_yet = s.recorder.recording
    assert nothing_yet is None
    s.start(system="board")
    s.write(ref="a", value=1)
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "board"}
    assert [(c.op, dict(c.args)) for c in rec.calls] == [("write", {"ref": "a", "value": 1})]


def test_a_sequences_steps_are_recorded_in_its_place_and_the_export_never() -> None:
    s = _Server()
    s.start(system="board")
    s.perform(steps=[{"op": "run_for", "frames": 2}, {"op": "write", "ref": "a", "value": 3}])
    rec = s.recorder.recording
    assert rec is not None and [c.op for c in rec.calls] == ["run_for", "write"]
    assert rec.calls[0].args == {"frames": 2}          # as given: no defaults filled


def test_a_call_a_tool_makes_of_another_is_not_the_callers_and_is_not_recorded() -> None:
    s = _Server()
    s.start(system="board")
    s.poke_and_look(ref="a")
    rec = s.recorder.recording
    assert rec is not None and [c.op for c in rec.calls] == ["poke_and_look"]


def test_a_failed_start_keeps_the_recording_and_a_new_start_clears_it() -> None:
    s = _Server()
    s.start(system="one")
    s.write(ref="a", value=1)
    s.start(system="two", fails=True)
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "one"} and len(rec.calls) == 1
    s.start(system="two")
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "two"} and rec.calls == []


def test_a_plans_steps_are_recorded_after_the_start_and_the_start_drops_the_plan() -> None:
    s = _Server(plan="plan")
    s.start(system="board", plan=[{"op": "run_for", "frames": 5}])
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "board"}
    assert [(c.op, dict(c.args)) for c in rec.calls] == [("run_for", {"frames": 5})]


def test_the_recording_stops_at_its_cap_and_the_export_says_where() -> None:
    """The cap counts the calls an export keeps: reads it drops cost nothing."""
    s = _Server()
    s.recorder.record_max = 3
    s.start(system="board")
    for v in range(5):
        s.log()
        s.write(ref="a", value=v)
    doc, out = s.document()
    assert len(doc["steps"]) == 3
    assert out.cut == {"call": 8, "op": None,
                       "why": "the recording holds at most 3 calls a replay keeps"}


def test_a_recording_of_reads_alone_is_bounded_too() -> None:
    s = _Server()
    s.recorder.record_max = 2
    s.start(system="board")
    for _ in range(recording.STORED_PER_KEPT * 2 + 5):
        s.log()
    assert s.recorder.recording is not None
    assert len(s.recorder.recording.calls) == recording.STORED_PER_KEPT * 2
    assert s.recorder.recording.full
    _, out = s.document()
    assert out.cut is not None and "the ones an export drops included" in out.cut["why"]


# ============================================================================ the export


def test_a_run_and_a_check_are_kept_and_each_step_holds_to_where_it_stopped() -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=10)
    s.write(ref="a", value=1)
    s.look()
    s.read_memory(ref="score")
    doc, out = s.document()
    assert doc["steps"] == [
        {"op": "run_for", "frames": 10, "recorded": {"pc": "0x2", "frame": 110}},
        {"op": "write", "ref": "a", "value": 1},
        {"op": "look"},                                # it moved nothing, so it holds to nothing
        {"op": "read_memory", "ref": "score", "recorded": {"hex": "beef"}}]
    assert out.checks == 1 and out.cut is None and out.dropped == []
    assert doc["version"] == 2 and doc["server"] == "double"
    assert doc["needs"] == {"states": [], "declarations": _held([])}


def test_refused_calls_unchecked_reads_and_host_writers_are_dropped_and_named() -> None:
    s = _Server()
    s.start(system="board")
    s.write(ref="bad", value=1)
    s.log()
    s.snapshot()
    _doc, out = s.document()
    assert [(d["call"], d["op"]) for d in out.dropped] == [(1, "write"), (2, "log"),
                                                           (3, "snapshot")]
    assert "refused it (INVALID)" in out.dropped[0]["why"]
    assert "a read the export does not check" in out.dropped[1]["why"]
    assert "changes nothing in the emulated machine" in out.dropped[2]["why"]


def test_a_release_no_call_saw_end_cuts_the_document_at_the_release() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "resume"


def test_a_state_loaded_and_not_saved_in_the_recording_is_what_the_document_needs() -> None:
    s = _Server()
    s.start(system="board")
    s.state_save(name="mine")
    s.state_load(name="mine")
    s.state_load(name="theirs")
    doc, _out = s.document()
    assert doc["needs"] == {"states": ["theirs"], "declarations": _held([])}


def test_the_export_writes_the_document_and_accounts_for_it(tmp_path: Path) -> None:
    s = _Server()
    s.start(system="board")
    for _ in range(45):
        s.log()
    s.run_for(frames=3)
    path = tmp_path / "session.json"
    got = s.perform_export(path=str(path))
    assert got["path"] == str(path) and got["steps"] == 1 and got["checks"] == 0
    assert got["dropped_total"] == 45 and len(got["dropped"]) == recording.DROPPED_SHOWN
    assert got["dropped"][-1]["call"] == 45 and got["cut"] is None
    assert shlex.split(got["replay"]) == ["uv", "run", "python", "-m", "scry_core.replay",
                                          str(path)]
    assert json.loads(path.read_text())["steps"][0]["frames"] == 3
    assert s.recorder.recording is not None
    assert all(c.op != recording.EXPORT_TOOL for c in s.recorder.recording.calls)


@pytest.mark.parametrize("path, absolute, says", [
    ("relative.json", False, "must be an absolute path or start with `~`"),
    ("session.txt", True, "ends in `.json`"),
    ("no/such/dir/session.json", True, "is not a directory"),
])
def test_an_export_to_a_path_it_cannot_take_is_refused(tmp_path: Path, path: str, absolute: bool,
                                                         says: str) -> None:
    s = _Server()
    s.start(system="board")
    with pytest.raises(Invalid, match=says):
        recording.export(s.recorder, str(tmp_path / path) if absolute else path)


def test_an_export_over_a_file_needs_overwrite_and_one_with_nothing_recorded_is_refused(
        tmp_path: Path) -> None:
    s = _Server()
    with pytest.raises(Invalid) as e:
        recording.export(s.recorder, str(tmp_path / "x.json"))
    assert e.value.code == "no_recording"
    s.start(system="board")
    s.run_for(frames=1)
    taken = tmp_path / "taken.json"
    taken.write_text("{}")
    with pytest.raises(Invalid, match="is there already"):
        recording.export(s.recorder, str(taken))
    assert recording.export(s.recorder, str(taken), overwrite=True)["steps"] == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["taken.json"], "nothing left beside it"


def test_an_export_led_by_a_tilde_lands_under_the_home(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))        # the home on Windows
    s = _Server()
    s.start(system="board")
    s.run_for(frames=1)
    assert recording.export(s.recorder, "~/s.json")["path"] == str(tmp_path / "s.json")


def test_a_step_holds_to_every_recorded_field_and_names_the_first_it_does_not() -> None:
    assert recording.diverged({"pc": "0x10", "frame": 5}, {"pc": "0x10", "frame": 5}) is None
    assert recording.diverged({"pc": "0x10", "frame": 5}, {"pc": "0x10", "frame": 6}) == \
        ("frame", 5, 6)
    assert recording.diverged({"hex": "ab"}, {}) == ("hex", "ab", None)


def test_a_refusal_that_moved_the_machine_cuts_the_document_and_one_that_did_not_is_dropped(
        ) -> None:
    s = _Server()
    s.start(system="board")
    s.write(ref="bad", value=1)
    s.wait_out(frames=30)
    doc, out = s.document()
    assert doc["steps"] == [] and [d["op"] for d in out.dropped] == ["write"]
    assert out.cut is not None and out.cut["op"] == "wait_out"


@pytest.mark.parametrize("cancelled", [False, True])
def test_a_call_that_ended_with_no_reply_cuts_the_document(cancelled: bool) -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=1)
    with pytest.raises((asyncio.CancelledError, ZeroDivisionError)):
        s.crashes(frames=5, cancelled=cancelled)
    doc, out = s.document()
    assert [st["op"] for st in doc["steps"]] == ["run_for"]
    assert out.cut is not None and out.cut["op"] == "crashes" and "no reply" in out.cut["why"]
    assert s.b.nested == 0


def test_a_start_cancelled_as_it_returns_keeps_the_recording_its_reply_describes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The reply was in hand: the session it says is up is the one recorded."""
    s = _Server()
    s.start(system="one")
    calls = [0]
    real = cancel.check

    def cancelled_as_it_returns() -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise asyncio.CancelledError
        real()
    monkeypatch.setattr(cancel, "check", cancelled_as_it_returns)
    with pytest.raises(asyncio.CancelledError):
        s.start(system="two")
    assert s.recorder.recording is not None
    assert s.recorder.recording.start == {"system": "two"}


def test_a_start_that_ended_with_no_reply_takes_the_recording_with_it() -> None:
    s = _Server()
    s.start(system="one")
    s.m.start_raises = True
    with pytest.raises(RuntimeError):
        s.start(system="two")
    assert s.recorder.recording is None


def test_a_machine_the_server_cannot_read_never_fails_the_call_and_cuts_the_export() -> None:
    s = _Server()
    s.start(system="board")
    s.m.unreadable = True
    assert s.write(ref="a", value=1)["status"] == "ok"
    assert s.b.nested == 0
    s.m.unreadable = False
    _doc, out = s.document()
    assert out.cut is not None and "could not read the machine" in out.cut["why"]


def test_close_keeps_the_recording_and_is_no_step() -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=2)
    s.close()
    doc, _out = s.document()
    assert [st["op"] for st in doc["steps"]] == ["run_for"]


def test_a_declaration_that_is_no_export_is_refused_at_registration() -> None:
    s = _Server()
    for bad in ("hex", "drpo", (), ("hex", 2)):
        with pytest.raises(TypeError, match="replay="):
            s.recorder.declare("x", bad, False)  # type: ignore[arg-type]


def test_a_check_whose_reply_lacks_its_fields_is_kept_and_not_counted() -> None:
    s = _Server()
    s.recorder.declare("look", ("hex",), True)
    s.start(system="board")
    s.look()
    doc, out = s.document()
    assert doc["steps"] == [{"op": "look"}] and out.checks == 0


def test_an_export_to_a_home_that_does_not_exist_or_a_directory_is_refused(
        tmp_path: Path) -> None:
    s = _Server()
    s.start(system="board")
    with pytest.raises(Invalid, match="bad_argument|nobody"):
        recording.export(s.recorder, "~nobody-zz-scry/a.json")
    (tmp_path / "taken.json").mkdir()
    with pytest.raises(Invalid, match="is a directory"):
        recording.export(s.recorder, str(tmp_path / "taken.json"))


def test_the_replay_line_quotes_a_path_with_a_space(tmp_path: Path) -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=1)
    (tmp_path / "a b").mkdir()
    got = recording.export(s.recorder, str(tmp_path / "a b" / "s.json"))
    assert shlex.split(got["replay"])[-1] == str(tmp_path / "a b" / "s.json")


def test_a_field_compares_as_json_carries_it() -> None:
    assert recording.diverged({"crop": [1, 2]}, {"crop": (1, 2)}) is None


def test_a_reader_that_moved_the_machine_is_kept_as_a_step_never_dropped() -> None:
    s = _Server()
    s.start(system="board")
    s.peek()
    s.log()
    doc, out = s.document()
    assert doc["steps"] == [{"op": "peek"}] and [d["op"] for d in out.dropped] == ["log"]


def test_a_steps_arguments_leave_out_its_op_and_its_recorded() -> None:
    step = {"op": "read_memory", "ref": "0x0", "recorded": {"hex": "00"}}
    assert recording.step_arguments(step) == {"ref": "0x0"}
    assert recording.refuse_recorded(step) is None and recording.refuse_recorded({}) is None
    assert "a mapping of field to value" in str(recording.refuse_recorded({"recorded": [1]}))


def test_a_divergence_carries_what_the_runner_reads_and_the_steps_own_reply() -> None:
    message, fields = recording.divergence(2, "read_memory", {"hex": "01"}, ("hex", "00", "01"))
    assert message == "step 2 ('read_memory') diverged: `hex` was recorded '00' and came back '01'"
    assert fields == {"failed_at": 2, "failed": {"op": "read_memory", "reply": {"hex": "01"}},
                      "field": "hex", "recorded": "00", "got": "01"}


def test_a_start_whose_plan_failed_with_its_session_up_is_the_sessions_recording() -> None:
    s = _Server(plan="plan")
    s.start(system="one")
    s.write(ref="a", value=1)
    s.m.up = False                             # that session closed; its recording stays
    s.start(system="two", plan=[{"op": "run_for", "frames": 5}, {"op": "write", "ref": "bad",
                                                                 "value": 0}])
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "two"}
    assert [c.op for c in rec.calls] == ["run_for", "write"]


def test_a_start_refused_over_a_live_session_keeps_that_sessions_recording() -> None:
    s = _Server(plan="plan")
    s.start(system="one")
    s.write(ref="a", value=1)
    s.start(system="two", over_live=True)      # its reply says a session is alive: the old one
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "one"}
    assert [c.op for c in rec.calls] == ["write"]


def test_a_start_that_cannot_tell_whether_a_session_was_live_keeps_the_recording() -> None:
    s = _Server(plan="plan")
    s.start(system="one")
    s.write(ref="a", value=1)

    def unreadable() -> bool:
        raise OSError("no answer")
    s.recorder._live = unreadable
    s.start(system="two", plan=[{"op": "write", "ref": "bad", "value": 0}])
    rec = s.recorder.recording
    assert rec is not None and rec.start == {"system": "one"}


def test_a_run_its_wall_clock_bound_ended_cuts_the_document_at_it() -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=90, seconds=0.5)
    doc, out = s.document()
    assert doc["steps"] == []
    assert out.cut is not None and out.cut["op"] == "run_for" and "wall clock" in out.cut["why"]


def test_a_check_of_files_a_dropped_call_wrote_is_dropped_never_a_green_by_construction() -> None:
    s = _Server()
    s.start(system="board")
    s.snapshot(dest="/tmp/goldens/a.png")
    s.golden_check(dir="/tmp/goldens")
    doc, out = s.document()
    assert doc["steps"] == [] and out.checks == 0
    assert "files a dropped call wrote" in out.dropped[-1]["why"], out.dropped


def test_a_wall_tool_that_moved_nothing_is_dropped_and_an_export_of_no_step_is_refused(
        tmp_path: Path) -> None:
    s = _Server()
    s.start(system="board")
    s.stop(already=True)                               # nothing moved: the stop was there
    doc, out = s.document()
    assert doc["steps"] == [] and out.dropped[-1]["op"] == "stop"
    with pytest.raises(Invalid) as e:
        recording.export(s.recorder, str(tmp_path / "s.json"))
    assert e.value.code == "no_recording" and "no step" in str(e.value)
    assert not (tmp_path / "s.json").exists()


@pytest.mark.parametrize("ended_by", ["stop", "a breakpoint a read found", "an advance", "nothing"])
def test_a_release_ends_the_document_whatever_ends_its_run(ended_by: str) -> None:
    """The clock or a breakpoint stops the cpu at a place inside its frame that no replayed
    advance reaches, and every stop after it would inherit the shift: the bench is what came
    before the release, and the cut names the release and why."""
    s = _Server()
    s.start(system="board")
    s.write(ref="a", value=0)
    s.resume()
    s.log()                                            # a read while it ran
    if ended_by == "stop":
        s.stop(frames_then=50)
    elif ended_by == "a breakpoint a read found":
        s.m.stop_at(170)
        s.read_memory(ref="score")
    elif ended_by == "an advance":
        s.m.stop_at(170)
        s.run_for(frames=10)
    s.write(ref="a", value=1)
    doc, out = s.document()
    assert doc["steps"] == [{"op": "write", "ref": "a", "value": 0}]
    assert out.cut == {"call": 2, "op": "resume", "why": recording.RELEASED}, out.cut


def test_a_wall_tool_that_came_back_with_the_machine_moved_cuts_the_document() -> None:
    """A `resume(seconds=)` that came back stopped: the same run inside one call."""
    s = _Server()
    s.start(system="board")
    s.write(ref="a", value=0)
    s.resume(seconds=1.0)
    doc, out = s.document()
    assert doc["steps"] == [{"op": "write", "ref": "a", "value": 0}]
    assert out.cut == {"call": 2, "op": "resume", "why": recording.RUN_STOPPED_INSIDE}, out.cut


@pytest.mark.parametrize("names", ["the manifest", "a file in the directory",
                                   "the manifest its reply named, with no dest"])
def test_a_check_of_a_dropped_series_by_its_manifest_is_dropped(names: str) -> None:
    """A series captured into `dest` and judged by the manifest its reply names: the file the
    check reads sits in what the dropped call wrote, so kept it would hold by construction."""
    s = _Server()
    s.start(system="board")
    if names == "the manifest its reply named, with no dest":
        s.series_capture()
        s.golden_check(manifest="/tmp/s/manifest.json")
    else:
        s.series_capture(dest="/tmp/series")
        s.golden_check(**({"manifest": "/tmp/series/manifest.json"} if names == "the manifest"
                          else {"manifest": "/tmp/series/frames/0001.png"}))
    doc, out = s.document()
    assert doc["steps"] == [] and out.checks == 0
    assert "files a dropped call wrote" in out.dropped[-1]["why"], out.dropped


def test_a_release_ends_the_document_on_a_server_whose_stops_carry_no_fields() -> None:
    """A release moves no stop count and no stop fields: it is still a release."""
    s = _Server()
    s.m.bare = True
    s.start(system="board")
    s.write(ref="a", value=0)
    s.resume()
    s.m.stop_at(170)
    s.write(ref="a", value=1)
    doc, out = s.document()
    assert doc["steps"] == [{"op": "write", "ref": "a", "value": 0}]
    assert out.cut == {"call": 2, "op": "resume", "why": recording.RELEASED}, out.cut


def test_a_refused_call_that_left_the_machine_running_is_a_release() -> None:
    s = _Server()
    s.m.bare = True
    s.start(system="board")
    s.go_refused()
    s.m.stop_at(170)
    s.write(ref="a", value=1)
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "go_refused", out.cut


def test_a_step_that_writes_a_file_the_session_named_cuts_the_document_there() -> None:
    """A replay would find that file there and be refused: what came before is the bench."""
    s = _Server()
    s.start(system="board")
    s.run_for(frames=2)
    s.record(dest="/tmp/take.avi", frames=3)
    s.run_for(frames=1)
    doc, out = s.document()
    assert [st["op"] for st in doc["steps"]] == ["run_for"]
    assert out.cut == {"call": 2, "op": "record",
                       "why": "it writes /tmp/take.avi, a file the session named, which a replay "
                              "finds there already and is refused"}


def test_the_machine_moved_between_two_recorded_calls_cuts_the_document() -> None:
    """Something outside every recorded call moved it (an `after` hook that raised on the success
    path, a call the recording did not take): every recorded answer after would be shifted."""
    s = _Server()
    s.start(system="board")
    s.run_for(frames=2)
    s.m.stop_at(500)                         # moved by nobody the recording saw
    s.run_for(frames=1)
    doc, out = s.document()
    assert len(doc["steps"]) == 1
    assert out.cut is not None and out.cut["call"] == 2
    assert "not where the call before it left it" in out.cut["why"]


def test_a_call_with_nothing_to_add_to_is_this_modules_defect_said_as_one() -> None:
    r = recording.Recorder("x", "x.py", 10, lambda: recording.UNREAD, lambda: False,
                           declarations=dict, stop_fields=(), **VOCABULARY)
    with pytest.raises(RuntimeError, match="was taken with no recording to add it to"):
        r.end("write", None, {}, {"status": "ok"}, recording.UNREAD)


def test_the_document_names_its_entry_file_and_the_declarations_its_start_found() -> None:
    s = _Server()
    s.declared = ["0x40", "w:0x80"]
    s.start(system="board")
    s.declared = ["changed later"]
    s.run_for(frames=2)
    doc, _ = s.document()
    assert doc["entry"] == "double.py"
    assert doc["needs"]["declarations"] == _held(["0x40", "w:0x80"])


def test_a_server_that_cannot_list_its_declarations_records_none() -> None:
    s = _Server()

    def broken() -> dict[str, list[str]]:
        raise OSError("the store cannot be read")
    s.recorder._declarations = broken
    s.start(system="board")
    s.run_for(frames=2)
    assert s.document()[0]["needs"]["declarations"] == {}


def test_the_state_tools_are_the_servers_own_words() -> None:
    s = _Server()
    s.recorder.states = ("save_it", "load_it", "slot")
    s.start(system="board")
    s.state_load(name="theirs")
    doc, _ = s.document()
    assert doc["needs"]["states"] == [], "`state_load` is not this server's load"


def test_unrecorded_takes_nothing() -> None:
    u = recording.Unrecorded()
    u.declare("x", None, True)
    assert u.begin("x", None, {}) is None and u.recording is None
    u.end("x", None, {}, {}, None)
    u.ended("x", None, {}, None)


def test_the_declarations_are_the_stores_before_the_plan_declares_its_own() -> None:
    """A replay's `start` re-arms what the store held before the plan ran: the plan's own
    declarations are steps of the document, which the replay takes after it."""
    s = _Server(plan="plan")
    s.declared = ["0x40"]
    s.start(system="board", plan=[{"op": "declare", "ref": "0x80"}, {"op": "run_for", "frames": 1}])
    doc, _ = s.document()
    assert doc["needs"]["declarations"] == _held(["0x40"])
