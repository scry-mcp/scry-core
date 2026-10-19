"""`scry_core.boundary`: the cancel poll as a call enters the lock, the nesting, the
outermost-only end of a cancelled call, the after-call hook on every path, and the reply every
path closes with; driven through a double server whose hooks record what the boundary asked of
them."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from typing import Any

import pytest
from mcp.server.mcpserver import Context

from scry_core import boundary, cancel
from scry_core.envelope import Envelope


class _Server:
    """A server of doubles: every hook appends what it was asked to `log`."""

    def __init__(self) -> None:
        self.log: list[tuple[Any, ...]] = []
        self.pending: cancel.Cancelled | None = None
        self.given_back: list[dict[str, Any]] = []
        self.lock = threading.RLock()
        self.mcp = Envelope("t", instructions="i", refusal=self.refusal)
        self.b = boundary.Boundary(
            self.mcp, self.lock, invoke=self.invoke, end=self.end, after=self.after,
            refusal_line=lambda name, reply: f"{name} refused",
            session_block=lambda: {"altered": False}, take_cancelled=self.take,
            keep_cancelled=self.keep, doc=lambda name, text: f"{name}: {text}",
            give_back=self.given_back.append)
        self.after_raises = False

    def tool(self, title: str, **kw: Any) -> Callable[[Callable[..., Any]], Any]:
        """`Boundary.tool` with the double's own line: the tool's name and its arguments."""
        def register(fn: Callable[..., Any]) -> Any:
            def line(args: dict[str, Any], reply: dict[str, Any], name: str = fn.__name__) -> str:
                return f"{name} {sorted(args.items())}"
            return self.b.tool(title, summary=line, **kw)(fn)
        return register

    def held(self) -> bool:
        return bool(self.lock._is_owned())  # type: ignore[attr-defined]

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


def test_session_before_keeps_the_block_the_body_built() -> None:
    s = _Server()

    @s.tool("Close", session_before=True)
    def close() -> dict[str, Any]:
        return {"status": "ok", "session": {"altered": True}}

    assert close()["session"] == {"altered": True}


def test_session_before_with_no_block_from_the_body_composes_one() -> None:
    s = _Server()

    @s.tool("Close", session_before=True)
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
    lock = threading.RLock()
    b = boundary.Boundary(
        Envelope("t", instructions="i", refusal=lambda *a: {}), lock,
        invoke=lambda fn, bound: dict(fn(*bound.args, **bound.kwargs)),
        end=lambda n, o: ("stopped", None),
        refusal_line=lambda n, r: n, session_block=lambda: None, take_cancelled=lambda: None,
        keep_cancelled=lambda r: None, doc=lambda n, t: t)

    @b.tool("Ping", summary=lambda args, reply: "ping")
    def ping() -> dict[str, Any]:
        return {"status": "ok"}

    assert ping() == {"summary": "ping", "status": "ok", "session": None}


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
