"""`scry_core.boundary`: the cancel poll as a call enters the lock, the nesting, the
outermost-only end of a cancelled call, the after-call hook on every path, and the reply every
path closes with; driven through a double server whose hooks record what the boundary asked of
them."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, cast

import pytest
from mcp.server.mcpserver import Context

from scry_core import boundary, cancel, given, naming, reply_schema
from scry_core.envelope import Envelope
from scry_core.naming import Field, Guarded, Named
from scry_core.reply_contract import OmitEmpty


class _Server:
    """A server of doubles: every hook appends what it was asked to `log`."""

    def __init__(self, listener: boundary.CallListener | None = None,
                 namer: naming.Guarded | None = None,
                 names_on: Callable[[], bool] = lambda: True) -> None:
        self.log: list[tuple[Any, ...]] = []
        self.pending: cancel.Cancelled | None = None
        self.given_back: list[dict[str, Any]] = []
        self.wholes: list[bool] = []         # what each block was asked for: whole or short
        self.lock = boundary.ServerLock()
        self.mcp = Envelope("t", instructions="i", refusal=self.refusal)
        self.b = boundary.Boundary(
            self.mcp, self.lock, invoke=self.invoke, end=self.end, after=self.after,
            refusal_line=lambda name, reply: f"{name} refused",
            session_block=self.block, take_cancelled=self.take,
            keep_cancelled=self.keep, doc=lambda name, text: f"{name}: {text}",
            give_back=self.given_back.append, listener=listener, namer=namer, names_on=names_on)
        self.after_raises = False

    def tool(self, title: str, **kw: Any) -> Callable[[Callable[..., Any]], Any]:
        """`Boundary.tool` with the double's own line: the tool's name and its arguments."""
        def register(fn: Callable[..., Any]) -> Any:
            def line(args: dict[str, Any], reply: dict[str, Any], name: str = fn.__name__) -> str:
                return f"{name} {sorted(args.items())}"
            return self.b.tool(title, summary=line, **kw)(fn)
        return register

    def block(self, whole: bool) -> dict[str, Any]:
        self.wholes.append(whole)
        return {"altered": False}

    def held(self) -> bool:
        return self.lock.held_here()

    def invoke(self, fn: Callable[..., Any], bound: inspect.BoundArguments) -> dict[str, Any]:
        self.log.append(("invoke", fn.__name__, self.held()))
        try:
            return dict(fn(*bound.args, **bound.kwargs))
        except LookupError as e:          # this server's own vocabulary, answered
            return {"status": "INVALID", "code": "lookup", "message": str(e)}

    def end(self, name: str, on_cancel: cancel.OnCancel
            ) -> tuple[cancel.Left, dict[str, Any] | None]:
        self.log.append(("end", name, on_cancel))
        return "stopped", {"found_by": name} if on_cancel != "none" else None

    def after(self) -> None:
        self.log.append(("after", self.b.nested))
        if self.after_raises:
            raise OSError("the hook broke")

    def keep(self, record: cancel.Cancelled) -> None:
        self.pending = record

    def take(self) -> cancel.Cancelled | None:
        record, self.pending = self.pending, None
        return record

    def refusal(self, name: str, arguments: dict[str, Any], cause: Any) -> dict[str, Any]:
        def build() -> dict[str, Any]:
            self.log.append(("build", name, self.held()))
            return {"status": "INVALID", "code": "bad"}
        return self.b.refused(name, arguments, build)


def _cancelled() -> None:
    raise asyncio.CancelledError


def test_a_call_answers_summary_first_and_session_last_from_the_args_it_ran_with() -> None:
    s = _Server()

    @s.tool("Count")
    def count(n: int, by: int = 2) -> dict[str, Any]:
        return {"status": "ok", "n": n * by, "session": {"stale": True}}

    got = count(3)
    assert list(got) == ["summary", "status", "n", "session"]
    assert got["summary"] == "count [('by', 2), ('n', 3)]"
    assert got["session"] == {"altered": False}       # composed after the body, never the body's
    assert s.log == [("invoke", "count", True), ("after", 1)]
    assert s.b.nested == 0


def test_body_session_keeps_the_block_the_body_built() -> None:
    s = _Server()

    @s.tool("Close", body_session=True)
    def close() -> dict[str, Any]:
        return {"status": "ok", "session": {"altered": True}}

    assert close()["session"] == {"altered": True}


def test_body_session_with_no_block_from_the_body_composes_one() -> None:
    s = _Server()

    @s.tool("Close", body_session=True)
    def close() -> dict[str, Any]:
        return {"status": "ok"}

    assert close()["session"] == {"altered": False}


def test_the_ctx_is_kept_out_of_the_summarys_arguments() -> None:
    s = _Server()

    @s.tool("Wait", on_cancel="stop")
    def wait(seconds: int, ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
        return {"status": "ok"}

    assert wait(1, ctx=None)["summary"] == "wait [('seconds', 1)]"


def test_a_tool_that_waits_declares_how_a_cancel_ends_it_or_fails_at_import() -> None:
    s = _Server()

    def wait(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(TypeError, match="declares how a cancel ends it"):
        s.tool("Wait")(wait)
    assert s.mcp._tool_manager.list_tools() == []


def test_registration_fills_the_description_and_the_annotations() -> None:
    s = _Server()

    @s.tool("Read", read_only=True, idempotent=True)
    def read() -> dict[str, Any]:
        """Reads."""
        return {"status": "ok"}

    (registered,) = s.mcp._tool_manager.list_tools()
    assert registered.name == "read"
    assert registered.description == "read: Reads."
    assert registered.title == "Read"
    assert registered.annotations is not None
    assert registered.annotations.read_only_hint and registered.annotations.idempotent_hint


def test_a_call_cancelled_while_it_queued_runs_nothing_and_ends_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        raise AssertionError("the body of a call cancelled in the queue ran")

    monkeypatch.setattr(cancel, "check", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        run()
    assert s.log == []
    assert s.pending is None and s.b.nested == 0


def test_a_call_cancelled_in_its_body_applies_its_end_and_the_next_reply_says_so() -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        _cancelled()
        return {}

    @s.tool("Status")
    def status() -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(asyncio.CancelledError):
        run()
    assert s.log == [("invoke", "run", True), ("end", "run", "stop"), ("after", 1)]
    assert s.given_back == [{"found_by": "run"}], "what the end found goes back through give_back"
    got = status()
    assert got["summary"] == "after a cancelled run (stopped): status []"
    assert got["cancelled"]["tool"] == "run" and got["cancelled"]["left"] == "stopped"
    assert list(got)[-1] == "session"
    assert "cancelled" not in status()                 # said once


def test_a_tool_with_no_declared_end_ends_none() -> None:
    s = _Server()

    @s.tool("Poke")
    def poke() -> dict[str, Any]:
        _cancelled()
        return {}

    with pytest.raises(asyncio.CancelledError):
        poke()
    assert ("end", "poke", "none") in s.log


def test_only_the_outermost_call_ends_and_only_its_reply_takes_the_record() -> None:
    s = _Server()
    inner_replies: list[dict[str, Any]] = []
    s.pending = cancel.recorded(None, "earlier", 0.0, "stopped")

    @s.tool("Step")
    def step() -> dict[str, Any]:
        return {"status": "ok"}

    @s.tool("Leaf", on_cancel="kill")
    def leaf() -> dict[str, Any]:
        _cancelled()
        return {}

    @s.tool("Sequence", on_cancel="stop")
    def sequence(cancel_in_step: bool) -> dict[str, Any]:
        inner_replies.append(step())
        if cancel_in_step:
            leaf()
        return {"status": "ok"}

    got = sequence(False)
    assert "cancelled" not in inner_replies[0]          # a step's reply is not the caller's
    assert got["cancelled"]["tool"] == "earlier"
    s.log.clear()
    with pytest.raises(asyncio.CancelledError):
        sequence(True)
    assert [e for e in s.log if e[0] == "end"] == [("end", "sequence", "stop")]
    assert s.b.nested == 0


def test_an_error_that_is_not_a_cancellation_escapes_with_no_end_and_the_after_hook_runs() -> None:
    s = _Server()

    @s.tool("Broken", on_cancel="stop")
    def broken() -> dict[str, Any]:
        raise ZeroDivisionError

    with pytest.raises(ZeroDivisionError):
        broken()
    assert s.log == [("invoke", "broken", True), ("after", 1)]
    assert s.b.nested == 0


def test_the_servers_own_vocabulary_is_answered_by_its_invoke() -> None:
    s = _Server()

    @s.tool("Find")
    def find() -> dict[str, Any]:
        raise LookupError("nowhere")

    got = find()
    assert got["code"] == "lookup" and got["summary"] == "find refused"


def test_the_schemas_refusal_is_closed_under_the_lock_and_takes_the_record() -> None:
    s = _Server()
    s.pending = cancel.recorded(None, "run", 1.0, "running")
    held: list[bool] = []
    real = s.b.finished

    def spy(*a: Any, **k: Any) -> dict[str, Any]:
        held.append(s.held())
        return real(*a, **k)

    s.b.finished = spy  # type: ignore[method-assign]
    got = s.refusal("count", {"n": "x"}, None)
    assert held == [True] and s.log == [("build", "count", True)]
    assert got["status"] == "INVALID" and got["cancelled"]["tool"] == "run"


def test_a_refusal_whose_call_was_cancelled_while_it_queued_spends_no_account(
        monkeypatch: pytest.MonkeyPatch) -> None:
    s = _Server()
    s.pending = cancel.recorded(None, "run", 1.0, "running")
    monkeypatch.setattr(cancel, "check", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        s.refusal("count", {}, None)
    assert s.pending is not None and s.log == []


def test_an_after_hook_that_raises_still_gives_the_nesting_back() -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run(cancelled: bool) -> dict[str, Any]:
        if cancelled:
            _cancelled()
        return {"status": "ok"}

    s.after_raises = True
    with pytest.raises(OSError):
        run(False)
    s.after_raises = False
    assert s.b.nested == 0
    with pytest.raises(asyncio.CancelledError):
        run(True)
    assert ("end", "run", "stop") in s.log
    assert run(False)["cancelled"]["tool"] == "run"


def test_an_end_that_raises_still_runs_the_after_hook_and_gives_the_nesting_back() -> None:
    s = _Server()

    def broken_end(name: str, on_cancel: cancel.OnCancel
                   ) -> tuple[cancel.Left, dict[str, Any] | None]:
        raise OSError("the end broke")

    s.b._end = broken_end

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        _cancelled()
        return {}

    with pytest.raises(OSError):
        run()
    assert s.log[-1] == ("after", 1) and s.b.nested == 0


def test_a_server_with_nothing_to_do_after_a_call_needs_no_after_hook() -> None:
    lock = boundary.ServerLock()
    b = boundary.Boundary(
        Envelope("t", instructions="i", refusal=lambda *a: {}), lock,
        invoke=lambda fn, bound: dict(fn(*bound.args, **bound.kwargs)),
        end=lambda n, o: ("stopped", None),
        refusal_line=lambda n, r: n, session_block=lambda whole: {"alive": False},
        take_cancelled=lambda: None,
        keep_cancelled=lambda r: None, doc=lambda n, t: t)

    @b.tool("Ping", summary=lambda args, reply: "ping")
    def ping() -> dict[str, Any]:
        return {"status": "ok"}

    assert ping() == {"summary": "ping", "status": "ok", "session": {"alive": False}}


def test_a_second_cancel_before_any_reply_keeps_the_first_ones_name() -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        _cancelled()
        return {}

    for _ in range(2):
        with pytest.raises(asyncio.CancelledError):
            run()
    assert s.pending is not None and s.pending.earlier == ("run",)


def test_a_cancel_seen_after_the_body_returned_records_it_with_no_end_and_gives_its_accounts_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The body reached its own end, so no end is applied; the reply the SDK would drop goes to
    nobody, so what it carried waits for the next one."""
    s = _Server()
    polls = [0]

    def check() -> None:
        polls[0] += 1
        if polls[0] == 2:                      # the poll after the body, not the one on entry
            raise asyncio.CancelledError
    monkeypatch.setattr(cancel, "check", check)

    @s.tool("Read", on_cancel="stop")
    def read() -> dict[str, Any]:
        return {"status": "ok", "stopped_on_its_own": {"stop_seq": 4}}

    with pytest.raises(asyncio.CancelledError):
        read()
    assert [e for e in s.log if e[0] == "end"] == [("end", "read", "none")]
    assert s.given_back == [{"status": "ok", "stopped_on_its_own": {"stop_seq": 4}}]
    assert s.pending is not None and s.pending.tool == "read"


def test_only_the_outermost_call_polls_after_its_body(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _Server()
    polls = [0]

    def check() -> None:
        polls[0] += 1
    monkeypatch.setattr(cancel, "check", check)

    @s.tool("Step")
    def step() -> dict[str, Any]:
        return {"status": "ok"}

    @s.tool("Sequence")
    def sequence() -> dict[str, Any]:
        step()
        return {"status": "ok"}

    sequence()
    assert polls == [3]       # the outer call's entry, the step's entry, the outer call's end


def test_each_tools_declared_end_is_kept_by_name() -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
        return {"status": "ok"}

    @s.tool("Read")
    def read() -> dict[str, Any]:
        return {"status": "ok"}

    assert s.b.declared_ends == {"run": "stop", "read": "none"}


def test_the_arguments_are_bound_once_and_the_server_reads_them_in_place() -> None:
    """The server's invoke gets the one binding; what it reads in place is what the body runs
    with and what the summary shows."""
    s = _Server()
    seen: list[inspect.BoundArguments] = []

    def invoke(fn: Callable[..., Any], bound: inspect.BoundArguments) -> dict[str, Any]:
        seen.append(bound)
        bound.arguments["n"] = int(bound.arguments["n"])      # a server reading a number
        return dict(fn(*bound.args, **bound.kwargs))
    s.b._invoke = invoke

    @s.tool("Count")
    def count(n: int, by: int = 2) -> dict[str, Any]:
        return {"status": "ok", "n": n}

    got = count("3")
    assert len(seen) == 1 and got["n"] == 3
    assert got["summary"] == "count [('by', 2), ('n', 3)]"


def test_a_reply_that_is_not_ok_takes_the_servers_line_whatever_its_status() -> None:
    """One refusal predicate for both servers: any status but `ok` (an `INVALID`, an `error`)
    is the server's refusal line, never the tool's own, which would read fields it lacks."""
    s = _Server()

    @s.tool("Broken")
    def broken() -> dict[str, Any]:
        return {"status": "error", "message": "x"}

    assert broken()["summary"] == "broken refused"


def test_the_declared_ends_are_read_off_the_registrations() -> None:
    s = _Server()

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        return {"status": "ok"}

    assert s.b.declared_ends == {"run": "stop"}
    s.mcp._tool_manager._tools.pop("run")
    assert s.b.declared_ends == {}, "a tool the server no longer registers has no end"


def test_a_call_cancelled_with_its_reply_in_hand_is_recorded_as_answered(
        monkeypatch: pytest.MonkeyPatch) -> None:
    s = _Server()
    took: list[str] = []

    class Recorder:
        def declare(self, *a: Any) -> None: ...
        def begin(self, *a: Any) -> None: ...
        def end(self, tool: str, *a: Any) -> None:
            took.append(f"end {tool}")
        def ended(self, tool: str, *a: Any) -> None:
            took.append(f"ended {tool}")
    s.b.recorder = Recorder()
    calls = [0]
    real = cancel.check

    def as_it_returns() -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise asyncio.CancelledError
        real()
    monkeypatch.setattr(cancel, "check", as_it_returns)

    @s.tool("Answer")
    def answer() -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(asyncio.CancelledError):
        answer()
    assert took == ["end answer"]


def test_a_cancelled_sequence_gives_back_the_accounts_of_the_steps_that_answered() -> None:
    """A `perform` cancelled after two steps answered: their replies go to nobody, so what they
    applied or found is said by the next reply instead."""
    s = _Server()

    @s.tool("Step")
    def step(n: int) -> dict[str, Any]:
        return {"status": "ok", "applied_on_stop": {f"bp{n}": "armed"}}

    @s.tool("Perform", on_cancel="stop")
    def perform() -> dict[str, Any]:
        step(1)
        step(2)
        _cancelled()
        return {}

    with pytest.raises(asyncio.CancelledError):
        perform()
    assert [r.get("applied_on_stop") for r in s.given_back] == [{"bp1": "armed"},
                                                                {"bp2": "armed"}, None]
    assert s.given_back[-1] == {"found_by": "perform"}
    step(3)
    assert s.given_back[-1] == {"found_by": "perform"}, "an outermost call that answered gives none"


def test_the_accounts_go_back_after_the_calls_own_hook_closed_its_accounts() -> None:
    """A server's `After` closes the one-time accounts of the call that ended; what goes back
    is for the NEXT reply, so it is handed over after that hook, never before it."""
    s = _Server()
    order: list[str] = []
    s.b._after = lambda: order.append("after")
    s.b._give_back = lambda reply: order.append("give_back")

    @s.tool("Run", on_cancel="stop")
    def run() -> dict[str, Any]:
        _cancelled()
        return {}

    with pytest.raises(asyncio.CancelledError):
        run()
    assert order == ["after", "give_back"]


def test_a_steps_picture_is_marked_unattached_before_its_line_and_its_record_read_it() -> None:
    """Only a reply's own picture is attached: a step's says so in its block, and the step's
    summary line, which a compact row of a sequence keeps alone, reads the marked block."""
    s = _Server()
    lines: list[str] = []
    picture_block = {"path": "/s.png", "inline": True, "width": 2, "height": 2}

    def line(args: dict[str, Any], reply: dict[str, Any]) -> str:
        text = f"view {'inline' if reply['image']['inline'] else 'not inlined'}"
        lines.append(text)
        return text

    @s.b.tool("View", summary=line)
    def view() -> dict[str, Any]:
        return {"status": "ok", "image": dict(picture_block)}

    @s.tool("Sequence")
    def sequence() -> dict[str, Any]:
        return {"status": "ok", "ran": [view()]}

    alone = view()
    assert alone["image"]["inline"] is True and lines == ["view inline"]
    got = sequence()
    step = got["ran"][0]
    assert step["image"]["inline"] is False and step["image"]["not_inlined"] == "nested"
    assert step["summary"] == "view not inlined" == lines[-1]


class _Heard:
    """A `CallListener` that records what it heard, and whether the lock was held when it did;
    `calls` keeps each call as heard, `outcomes` each end's outcome."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str, bool]] = []
        self.calls: list[boundary.Call] = []
        self.outcomes: list[boundary.Outcome] = []
        self.server: _Server | None = None

    def began(self, call: boundary.Call) -> None:
        assert self.server is not None
        self.log.append(("began", call.tool, self.server.held()))
        self.calls.append(call)

    def ended(self, call: boundary.Call, outcome: boundary.Outcome) -> None:
        assert self.server is not None
        self.log.append(("ended", call.tool, self.server.held()))
        self.outcomes.append(outcome)


def test_every_call_is_heard_beginning_and_ending_under_the_lock_its_steps_as_nested() -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s

    @s.tool("Step", read_only=True)
    def step(n: int, label: str = "") -> dict[str, Any]:
        return {"status": "ok"}

    @s.tool("Sequence")
    def sequence() -> dict[str, Any]:
        step(1)
        step(2, label="b")
        return {"status": "ok"}

    sequence()
    assert heard.log == [("began", "sequence", True), ("began", "step", True),
                         ("ended", "step", True), ("began", "step", True),
                         ("ended", "step", True), ("ended", "sequence", True)]
    assert [(c.tool, dict(c.given), c.nested, c.read_only) for c in heard.calls] == [
        ("sequence", {}, False, False), ("step", {"n": 1}, True, True),
        ("step", {"n": 2, "label": "b"}, True, True)]
    assert heard.outcomes == ["ok", "ok", "ok"]
    with pytest.raises(TypeError):
        heard.calls[1].given["n"] = 3      # type: ignore[index]


def test_a_call_that_raised_or_answered_a_refusal_is_heard_ending_too() -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s

    @s.tool("Lookup")
    def lookup() -> dict[str, Any]:
        raise LookupError("nothing there")

    @s.tool("Broken")
    def broken() -> dict[str, Any]:
        raise RuntimeError("a defect")

    assert lookup()["status"] == "INVALID"
    with pytest.raises(RuntimeError):
        broken()
    assert [e[:2] for e in heard.log] == [("began", "lookup"), ("ended", "lookup"),
                                          ("began", "broken"), ("ended", "broken")]
    assert heard.outcomes == ["refused", "refused"]


def test_a_cancelled_call_is_heard_ending_so_presence_never_stays_lit() -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s

    @s.tool("Wait", on_cancel="stop")
    def wait(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
        _cancelled()
        return {"status": "ok"}

    with pytest.raises(asyncio.CancelledError):
        wait()
    assert [e[:2] for e in heard.log] == [("began", "wait"), ("ended", "wait")]
    assert heard.outcomes == ["refused"]


def test_a_call_whose_after_hook_or_give_back_raised_is_heard_ending_refused() -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s
    s.after_raises = True

    @s.tool("Answer")
    def answer() -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(OSError, match="hook broke"):
        answer()
    assert heard.outcomes == ["refused"]


def test_a_call_cancelled_with_an_ok_reply_in_hand_is_heard_ending_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s
    calls = [0]
    real = cancel.check

    def as_it_returns() -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise asyncio.CancelledError
        real()
    monkeypatch.setattr(cancel, "check", as_it_returns)

    @s.tool("Answer")
    def answer() -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(asyncio.CancelledError):
        answer()
    assert heard.outcomes == ["refused"]


def test_a_listener_that_raises_fails_its_call_and_leaves_the_boundary_whole() -> None:
    class Broken:
        def began(self, call: boundary.Call) -> None:
            raise OSError("the listener broke")

        def ended(self, call: boundary.Call, outcome: boundary.Outcome) -> None:
            pass

    s = _Server(listener=Broken())

    @s.tool("Count")
    def count() -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(OSError, match="listener broke"):
        count()
    assert s.b.nested == 0, "the call was left on the stack, and every later call is a step"


def test_a_give_back_that_raises_still_lets_the_listener_hear_the_end() -> None:
    heard = _Heard()
    s = _Server(listener=heard)
    heard.server = s

    def refuses(_account: dict[str, Any]) -> None:
        raise OSError("the give-back broke")
    s.b._give_back = refuses

    @s.tool("Wait", on_cancel="stop")
    def wait(ctx: Context[Any, Any] | None = None) -> dict[str, Any]:
        _cancelled()
        return {"status": "ok"}

    with pytest.raises(OSError, match="give-back broke"):
        wait()
    assert [e[:2] for e in heard.log] == [("began", "wait"), ("ended", "wait")]
    assert heard.outcomes == ["refused"]


def test_the_block_is_asked_whole_for_start_and_status_and_short_for_every_other_tool() -> None:
    s = _Server()
    s.b.summaries.update({n: lambda args, reply: "line" for n in ("start", "status",
                                                                  "read_memory", "close")})
    for name in ("start", "status", "read_memory"):
        s.b.finished(name, {}, {"status": "ok"})
    assert s.wholes == [True, True, False]
    s.b.finished("close", {}, {"status": "ok", "session": {"kept": 1}}, body_session=True)
    assert s.wholes == [True, True, False]       # close keeps the block its body wrote


def test_the_closed_reply_leaves_out_a_marked_field_that_is_empty() -> None:
    class Reply(reply_schema.ReplyEnvelope, total=False):
        hits: int
        resent: Annotated[int, OmitEmpty]

    s = _Server()

    @s.tool("Count")
    def count() -> dict[str, Any]:
        return {"status": "ok", "hits": 0, "resent": 0}

    reply_schema.declare(s.mcp, {"count": Reply})
    try:
        assert list(count()) == ["summary", "status", "hits", "session"]
    finally:
        reply_schema._JUDGES.pop("count", None)
        reply_schema._OMIT_EMPTY.pop("count", None)


def test_a_tool_called_directly_knows_the_names_it_was_passed() -> None:
    s = _Server()
    seen: list[Any] = []

    @s.tool("Peek")
    def peek(x: int = 1, y: str = "d") -> dict[str, Any]:
        seen.append(given.names())
        return {"status": "ok"}

    peek(3)
    assert seen == [frozenset({"x"})]
    assert given.names() is None                 # the names end with the call


def test_a_tool_that_names_a_file_says_when_the_name_it_was_given_is_written_otherwise() -> None:
    s = _Server()

    @s.tool("Write", names_file="dest")
    def write(dest: str = "", note: str = "", refuse: bool = False) -> dict[str, Any]:
        if refuse:
            return {"status": "INVALID", "code": "bad", "message": "no"}
        return {"status": "ok", "path": dest.replace("Shot_1.PNG", "shot-1.png"),
                **({"note": note} if note else {})}

    said = "dest 'Shot_1.PNG' is written as 'shot-1.png'"
    got = write("/d/Shot_1.PNG")
    assert list(got) == ["summary", "status", "path", "note", "session"]
    assert got["note"].startswith(said)
    for own in ("its own", "its own."):
        assert write("/d/Shot_1.PNG", note=own)["note"].startswith(f"its own. {said}")
    for quiet in (write("/d/shot-1.png"), write(""), write("/d/Shot_1.PNG", refuse=True)):
        assert "note" not in quiet, quiet


def test_the_sentence_rides_only_on_a_reply_that_names_the_file_written() -> None:
    s = _Server()

    @s.tool("Write", names_file="dest")
    def write(dest: str, path: Any = None) -> dict[str, Any]:
        return {"status": "ok", **({} if path is None else {"trace": {"path": path}})}

    assert "note" in write("/d/Run_1.LOG", "/d/run-1.log"), "a nested path names it"
    for unwritten in (None, {"available": False, "why": "no event"}, "/d/other.log"):
        assert "note" not in write("/d/Run_1.LOG", unwritten), unwritten


def test_a_step_of_a_sequence_says_its_file_was_written_otherwise() -> None:
    s = _Server()

    @s.tool("Write", names_file="dest")
    def write(dest: str) -> dict[str, Any]:
        return {"status": "ok", "path": dest.replace("Shot_1.PNG", "shot-1.png")}

    @s.tool("Steps")
    def steps() -> dict[str, Any]:
        return {"status": "ok", "ran": [write("/d/Shot_1.PNG")]}

    assert steps()["ran"][0]["note"].startswith("dest 'Shot_1.PNG' is written as")


def test_a_tool_names_a_file_only_by_an_argument_it_takes() -> None:
    s = _Server()
    with pytest.raises(TypeError, match="names_file='dest'"):
        @s.tool("Read", names_file="dest")
        def read(path: str) -> dict[str, Any]:
            return {"status": "ok"}


class _Names:
    """A server's namer over its own tables: a port is named by number, an argument `ref` by the
    symbol table, and the reply's `port` and `hits[]` by the fields the server declares."""

    FIELDS = (Field("port", "port"), Field("hits[]", "symbol"))

    def __init__(self) -> None:
        self.symbols = {"score": 0x9405}
        self.ports = {0x3C8: "DAC write address"}
        self.raises = False

    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        if self.raises:
            raise RuntimeError("the symbol table moved")
        out: dict[str, Named] = {}
        if (ref := given.get("ref")) in self.symbols:
            out["ref"] = Named("symbol", ref, f"0x{self.symbols[ref]:04X}")
        if given.get("port") in self.ports:
            out["port"] = Named("port", self.ports[given["port"]], f"0x{given['port']:04X}",
                                id="ibm-pc:port:0x3C8")
        return out

    def reply(self, tool: str, reply: Mapping[str, Any]) -> Sequence[tuple[str, Named]]:
        if self.raises:
            raise RuntimeError("the symbol table moved")
        names = {a: n for n, a in self.symbols.items()}
        return [(s.path, Named("symbol", names[s.value], f"0x{s.value:04X}"))
                for s in naming.walk(reply, self.FIELDS) if s.value in names]


def _named_server(listener: boundary.CallListener | None = None,
                  names_on: Callable[[], bool] = lambda: True
                  ) -> tuple[_Server, _Names, Guarded]:
    namer = _Names()
    guard = Guarded(namer)
    return _Server(listener=listener, namer=guard, names_on=names_on), namer, guard


def test_a_call_is_named_once_before_the_listener_hears_it_and_the_listener_sees_the_names(
        ) -> None:
    heard = _Heard()
    s, namer, _ = _named_server(listener=heard)
    heard.server = s
    asked: list[str] = []
    original = namer.arguments

    def counted(tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        asked.append(tool)
        return original(tool, given)

    namer.arguments = counted        # type: ignore[method-assign]

    @s.tool("Read")
    def read(ref: str, port: int = 0) -> dict[str, Any]:
        return {"status": "ok"}

    read("score", port=0x3C8)
    assert asked == ["read"]
    assert heard.calls[0].named == {
        "ref": Named("symbol", "score", "0x9405"),
        "port": Named("port", "DAC write address", "0x03C8", id="ibm-pc:port:0x3C8")}


def test_a_reply_names_the_calls_arguments_and_the_numbers_it_shows_beside_its_fields() -> None:
    s, _, _ = _named_server()

    @s.tool("Find")
    def find(ref: str) -> dict[str, Any]:
        return {"status": "ok", "hits": [0x9405, 0x1234]}

    got = find("score")
    assert list(got) == ["summary", "status", "hits", "names", "session"]
    assert got["names"] == [
        {"field": "given.ref", "number": "0x9405", "kind": "symbol", "name": "score"}]
    assert "names_cut" not in got
    assert got["summary"] == "find [('ref', 'score')]"


def test_the_summary_names_the_numbers_it_prints() -> None:
    s, _, _ = _named_server()

    @s.tool("Port")
    def port(port: int) -> dict[str, Any]:
        return {"status": "ok"}

    s.b.summaries["port"] = lambda args, reply: f"port 0x{args['port']:04X} read"
    got = port(0x3C8)
    assert got["summary"] == "port 0x03C8 (DAC write address) read"
    assert [i["field"] for i in got["names"]] == ["given.port"]


def test_the_ceiling_of_the_block_shows_in_names_cut() -> None:
    s, namer, _ = _named_server()
    namer.symbols = {f"s{n}": 0x1000 + n for n in range(30)}

    @s.tool("Find")
    def find() -> dict[str, Any]:
        return {"status": "ok", "hits": [0x1000 + n for n in range(30)]}

    got = find()
    assert len(got["names"]) == 24 and got["names_cut"] == 6
    assert list(got)[-3:] == ["names", "names_cut", "session"]


def test_a_namer_that_raises_leaves_the_reply_exactly_as_it_is_with_no_namer() -> None:
    """The control: the same call on a server with no namer gives the same bytes."""
    s, namer, guard = _named_server()
    bare = _Server()
    namer.raises = True

    def make(server: _Server) -> Callable[..., Any]:
        @server.tool("Find")
        def find(ref: str) -> dict[str, Any]:
            return {"status": "ok", "hits": [0x9405]}
        return cast(Callable[..., Any], find)

    mine, theirs = make(s), make(bare)
    assert mine("score") == theirs("score")
    failed = guard.failed()
    assert failed is not None and failed["count"] == 2 and "symbol table moved" in failed["last"]


def test_the_names_are_off_for_a_session_that_asked_for_none_and_the_caption_still_has_them(
        ) -> None:
    heard = _Heard()
    on = [True]
    s, _, guard = _named_server(listener=heard, names_on=lambda: on[0])
    heard.server = s

    @s.tool("Find")
    def find(ref: str) -> dict[str, Any]:
        return {"status": "ok", "hits": [0x9405]}

    on[0] = False
    got = find("score")
    assert list(got) == ["summary", "status", "hits", "session"]
    assert got["summary"] == "find [('ref', 'score')]"
    assert heard.calls[0].named == {"ref": Named("symbol", "score", "0x9405")}, \
        "a caption is not a reply: the switch leaves it alone"
    on[0] = True
    assert "names" in find("score")
    assert guard.failed() is None


def test_a_summary_names_no_number_while_the_names_are_off() -> None:
    on = [False]
    s, _, _ = _named_server(names_on=lambda: on[0])

    @s.tool("Port")
    def port(port: int) -> dict[str, Any]:
        return {"status": "ok"}

    s.b.summaries["port"] = lambda args, reply: f"port 0x{args['port']:04X} read"
    assert port(0x3C8)["summary"] == "port 0x03C8 read"
    on[0] = True
    assert port(0x3C8)["summary"] == "port 0x03C8 (DAC write address) read"


def test_a_namer_that_is_interrupted_leaves_the_boundary_with_no_call_in_flight() -> None:
    s, namer, _ = _named_server()

    def interrupted(tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        raise KeyboardInterrupt

    namer.arguments = interrupted        # type: ignore[method-assign]

    @s.tool("Find")
    def find(ref: str) -> dict[str, Any]:
        return {"status": "ok"}

    with pytest.raises(KeyboardInterrupt):
        find("score")
    assert s.b.nested == 0


def test_a_refusal_the_schema_made_carries_no_names_and_a_refused_body_carries_the_arguments(
        ) -> None:
    s, _, _ = _named_server()

    @s.tool("Find")
    def find(ref: str) -> dict[str, Any]:
        raise LookupError("no such place")

    got = find("score")
    assert got["status"] == "INVALID"
    assert got["names"][0]["field"] == "given.ref"
    schema = s.refusal("find", {"ref": "score"}, None)
    assert "names" not in schema


def test_a_step_is_named_too_so_a_sequence_row_can_carry_its_names() -> None:
    s, _, _ = _named_server()

    @s.tool("Find")
    def find(ref: str) -> dict[str, Any]:
        return {"status": "ok"}

    @s.tool("Run")
    def run() -> dict[str, Any]:
        inner = find("score")
        return {"status": "ok", "ran": [inner]}

    got = run()
    assert got["ran"][0]["names"][0]["name"] == "score" and "names" not in got
