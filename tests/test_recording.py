"""`scry_core.recording`: what a recording takes, what an export keeps, drops and cuts, and the
check a replayed step holds to; driven through a call boundary over a double machine."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from scry_core import boundary, cancel, recording
from scry_core.envelope import Envelope
from scry_core.reply_contract import Invalid


class _Machine:
    """The machine the double's tools move: running or not, its frame and its stop's number."""

    def __init__(self) -> None:
        self.running = False
        self.frame: int | None = 100
        self.seq = 1
        self.unreadable = False

    def read(self) -> recording.Machine:
        if self.unreadable:
            raise OSError("the console did not answer")
        stop = {} if self.running else {"pc": f"0x{self.seq:x}", "frame": self.frame}
        return recording.Machine(self.running, None if self.running else self.frame, self.seq,
                                 stop)

    def stop_at(self, frame: int | None) -> None:
        self.running, self.frame, self.seq = False, frame, self.seq + 1


class _Server:
    """A boundary with a recorder and the tools a session uses, each moving `_Machine`."""

    def __init__(self, plan: str | None = None) -> None:
        self.m = _Machine()
        self.recorder = recording.Recorder("double", self.m.read, stop_fields=("pc", "frame"),
                                        plan=plan)
        self.b = boundary.Boundary(
            Envelope("t", instructions="i", refusal=lambda *a: {}), threading.RLock(),
            invoke=lambda fn, sig, a, k: dict(fn(*a, **k)), end=lambda n, o: ("stopped", None),
            line=lambda n, a, r: n, session_block=lambda: {}, take_cancelled=lambda: None,
            keep_cancelled=lambda r: None, doc=lambda n, t: t, recorder=self.recorder)
        b, m = self.b, self.m

        def stopped() -> dict[str, Any]:
            return {"status": "ok", "pc": f"0x{m.seq:x}", "frame": m.frame}

        @b.tool("start")
        def start(system: str, plan: list[dict[str, Any]] | None = None,
                  fails: bool = False) -> dict[str, Any]:
            if fails:
                return {"status": "INVALID", "code": "bad_argument", "message": "no"}
            m.running, m.frame, m.seq = False, 100, 1
            for step in plan or []:
                ops[step["op"]](**{k: v for k, v in step.items() if k != "op"})
            return {"status": "ok"}

        @b.tool("run_for")
        def run_for(frames: int) -> dict[str, Any]:
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
        def stop(frames_then: int = 50) -> dict[str, Any]:
            m.stop_at(None if m.frame is None else m.frame + frames_then)
            return stopped()

        @b.tool("write")
        def write(ref: str, value: int) -> dict[str, Any]:
            if ref == "bad":
                return {"status": "INVALID", "code": "unknown_ref", "message": "no such ref"}
            return {"status": "ok"}

        @b.tool("poke")
        def poke(ref: str, stops_at: int) -> dict[str, Any]:
            m.stop_at(stops_at)    # the first contact finds the stop the machine made itself
            return {"status": "ok"}

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
        def snapshot() -> dict[str, Any]:
            return {"status": "ok", "path": "/tmp/x.png"}

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

        ops = {"run_for": run_for, "write": write, "read_memory": read_memory, "resume": resume}
        self.tools = {f.__name__: f for f in (start, run_for, resume, stop, write, poke, peek,
                                              look,
                                              wait_out, crashes, close, read_memory, log,
                                              poke_and_look, snapshot, state_save, state_load,
                                              perform, perform_export)}

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


def test_the_recording_stops_at_its_cap_and_the_export_says_where(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recording, "RECORD_MAX", 3)
    s = _Server()
    s.start(system="board")
    for v in range(5):
        s.write(ref="a", value=v)
    doc, out = s.document()
    assert len(doc["steps"]) == 3
    assert out.cut == {"call": 4, "op": None, "why": "the recording holds at most 3 calls"}


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
    assert doc["version"] == 1 and doc["server"] == "double" and doc["needs"] == {"states": []}


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
    assert "a write to the host only" in out.dropped[2]["why"]


def test_a_release_and_the_stop_that_ended_it_become_the_frames_the_run_took() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    s.log()                                            # a read while it ran, dropped
    s.stop(frames_then=50)
    s.write(ref="a", value=1)
    doc, out = s.document()
    assert doc["steps"][0] == {"op": "run_for", "frames": 50,
                               "recorded": {"pc": "0x2", "frame": 150}}
    assert doc["steps"][1] == {"op": "write", "ref": "a", "value": 1}
    replaced = [d for d in out.dropped if "replaced by run_for(frames=50)" in d["why"]]
    assert [d["op"] for d in replaced] == ["resume", "stop"]


def test_a_run_the_wall_clock_ended_inside_one_call_becomes_its_frames() -> None:
    s = _Server()
    s.start(system="board")
    s.resume(seconds=2, frames_then=120)
    doc, _out = s.document()
    assert doc["steps"] == [{"op": "run_for", "frames": 120,
                             "recorded": {"pc": "0x2", "frame": 220}}]


def test_a_call_made_while_the_machine_ran_cuts_the_document_there() -> None:
    s = _Server()
    s.start(system="board")
    s.run_for(frames=1)
    s.resume()
    s.write(ref="a", value=1)
    s.stop()
    doc, out = s.document()
    assert [st["op"] for st in doc["steps"]] == ["run_for"]
    assert out.cut is not None and out.cut["call"] == 3 and out.cut["op"] == "write"
    assert "while the machine ran" in out.cut["why"]


def test_a_release_no_call_saw_end_cuts_the_document_at_the_release() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "resume"


def test_a_run_the_wall_ended_on_a_server_with_no_frame_counter_cuts_the_document() -> None:
    s = _Server()
    s.start(system="board")
    s.m.frame = None
    s.write(ref="a", value=1)
    s.resume()
    s.stop()
    s.write(ref="a", value=2)
    doc, out = s.document()
    assert [st["op"] for st in doc["steps"]] == ["write"]
    assert out.cut is not None and out.cut["op"] == "resume" and "no frame" in out.cut["why"]


def test_a_wall_ended_call_on_a_server_with_no_frame_counter_cuts_the_document() -> None:
    s = _Server()
    s.start(system="board")
    s.m.frame = None
    s.resume(seconds=2)
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "resume"


def test_a_state_loaded_and_not_saved_in_the_recording_is_what_the_document_needs() -> None:
    s = _Server()
    s.start(system="board")
    s.state_save(name="mine")
    s.state_load(name="mine")
    s.state_load(name="theirs")
    doc, _out = s.document()
    assert doc["needs"] == {"states": ["theirs"]}


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
    assert got["replay"] == f"uv run python -m scry_core.replay {path}"
    assert json.loads(path.read_text())["steps"][0]["frames"] == 3
    assert s.recorder.recording is not None
    assert all(c.op != recording.EXPORT_TOOL for c in s.recorder.recording.calls)


@pytest.mark.parametrize("path, says", [
    ("relative.json", "absolute or starts with `~`"),
    ("/tmp/session.txt", "ends in `.json`"),
    ("/no/such/dir/session.json", "is not a directory"),
])
def test_an_export_to_a_path_it_cannot_take_is_refused(path: str, says: str) -> None:
    s = _Server()
    s.start(system="board")
    with pytest.raises(Invalid, match=says):
        recording.export(s.recorder, path)


def test_an_export_over_a_file_needs_overwrite_and_one_with_nothing_recorded_is_refused(
        tmp_path: Path) -> None:
    s = _Server()
    with pytest.raises(Invalid) as e:
        recording.export(s.recorder, str(tmp_path / "x.json"))
    assert e.value.code == "no_recording"
    s.start(system="board")
    taken = tmp_path / "taken.json"
    taken.write_text("{}")
    with pytest.raises(Invalid, match="is there already"):
        recording.export(s.recorder, str(taken))
    assert recording.export(s.recorder, str(taken), overwrite=True)["steps"] == 0


def test_an_export_led_by_a_tilde_lands_under_the_home(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    s = _Server()
    s.start(system="board")
    assert recording.export(s.recorder, "~/s.json")["path"] == str(tmp_path / "s.json")


def test_a_step_holds_to_every_recorded_field_and_names_the_first_it_does_not() -> None:
    assert recording.diverged({"pc": "0x10", "frame": 5}, {"pc": "0x10", "frame": 5}) is None
    assert recording.diverged({"pc": "0x10", "frame": 5}, {"pc": "0x10", "frame": 6}) == \
        ("frame", 5, 6)
    assert recording.diverged({"hex": "ab"}, {}) == ("hex", "ab", None)





def test_a_run_the_machine_ended_by_itself_keeps_the_calls_that_found_it_stopped() -> None:
    """A breakpoint stops the released machine; the next calls (a write, a check) did their own
    work on the stopped machine, so the run is exported up to that stop and they stay after it."""
    s = _Server()
    s.start(system="board")
    s.resume()
    s.m.stop_at(170)                                    # the machine's own breakpoint
    s.write(ref="a", value=1)
    s.read_memory(ref="score")
    doc, out = s.document()
    assert doc["steps"] == [{"op": "run_for", "frames": 70,
                             "recorded": {"pc": "0x2", "frame": 170}},
                            {"op": "write", "ref": "a", "value": 1},
                            {"op": "read_memory", "ref": "score", "recorded": {"hex": "beef"}}]
    assert out.checks == 1 and out.cut is None


def test_a_run_that_does_not_go_forward_cuts_the_document() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    s.m.stop_at(40)                                     # a state of an earlier frame, say
    s.stop(frames_then=0)
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "resume"
    assert "not after frame 100" in out.cut["why"]


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


def test_a_start_that_ended_with_no_reply_takes_the_recording_with_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
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
    (tmp_path / "a b").mkdir()
    got = recording.export(s.recorder, str(tmp_path / "a b" / "s.json"))
    assert got["replay"].endswith(f"'{tmp_path}/a b/s.json'")


def test_a_field_compares_as_json_carries_it() -> None:
    assert recording.diverged({"crop": [1, 2]}, {"crop": (1, 2)}) is None


def test_a_stop_a_call_finds_inside_itself_ends_the_run_and_the_call_stays() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    s.poke(ref="a", stops_at=150)
    doc, _out = s.document()
    assert doc["steps"] == [{"op": "run_for", "frames": 50,
                             "recorded": {"pc": "0x2", "frame": 150}},
                            {"op": "poke", "ref": "a", "stops_at": 150}]


def test_an_advance_made_after_the_machine_stopped_by_itself_follows_the_run() -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    s.m.stop_at(170)
    s.run_for(frames=10)
    doc, out = s.document()
    assert doc["steps"] == [{"op": "run_for", "frames": 70,
                             "recorded": {"pc": "0x2", "frame": 170}},
                            {"op": "run_for", "frames": 10,
                             "recorded": {"pc": "0x3", "frame": 180}}]
    assert out.cut is None


def test_an_advance_that_began_on_the_running_machine_cuts_the_document() -> None:
    """Where the machine stopped between its run and the advance's own stop is not recorded."""
    s = _Server()
    s.start(system="board")
    s.resume()
    s.run_for(frames=10)
    doc, out = s.document()
    assert doc["steps"] == [] and out.cut is not None and out.cut["op"] == "run_for"
    assert "whose run had just stopped" in out.cut["why"]


def test_a_reader_that_moved_the_machine_is_kept_as_a_step_never_dropped() -> None:
    s = _Server()
    s.start(system="board")
    s.peek()
    s.log()
    doc, out = s.document()
    assert doc["steps"] == [{"op": "peek"}] and [d["op"] for d in out.dropped] == ["log"]


def test_a_run_no_call_saw_end_ends_at_the_stop_the_export_finds(tmp_path: Path) -> None:
    s = _Server()
    s.start(system="board")
    s.resume()
    s.m.stop_at(160)                                    # a breakpoint, nobody asked since
    got = s.perform_export(path=str(tmp_path / "s.json"))
    doc = json.loads(Path(got["path"]).read_text())
    assert doc["steps"] == [{"op": "run_for", "frames": 60,
                             "recorded": {"pc": "0x2", "frame": 160}}] and got["cut"] is None


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
