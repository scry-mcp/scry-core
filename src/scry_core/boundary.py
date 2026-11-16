"""The call boundary every Scry server wraps its tools in: one lock over the one machine, call
nesting, how a cancelled call ends and is recorded, and the reply every path closes with. Each
server's own vocabulary arrives as a hook, bound once when the boundary is built.

A call cancelled while queued did nothing: no end, no record. One cancelled in its body applies
its declared end only when outermost; the record waits for the next reply.

A cancel arriving as the body returns is polled once more before the reply is closed, because
closing spends one-time accounts the SDK would drop with the reply: they go back (`give_back`).
"""

from __future__ import annotations

import functools
import inspect
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from mcp.types import ToolAnnotations

from scry_core import cancel, file_names, given, picture
from scry_core import reply_schema as schema
from scry_core import session_block as blocks
from scry_core import strict_arguments as strict
from scry_core.envelope import Envelope
from scry_core.recording import Machine, Replay, Unrecorded

Reply = dict[str, Any]
#: Calls a tool's body with its arguments bound once here; the server translates its own errors
#: into replies, and whatever escapes is a defect or a cancellation.
Invoke = Callable[[Callable[..., Any], inspect.BoundArguments], Reply]
#: Applies a cancelled outermost call's declared end: what the machine was left as, and the
#: accounts it found in a reply's shape, or None.
End = Callable[[str, cancel.OnCancel], tuple[cancel.Left, "Reply | None"]]
#: Runs after every call inside the lock, steps included, however it ended.
After = Callable[[], None]
Summary = Callable[[dict[str, Any], Reply], str]
RefusalLine = Callable[[str, Reply], str]
GiveBack = Callable[[Reply], None]


class CallListener(Protocol):
    """Hears outermost calls begin and end, under the lock: must not block."""

    def began(self, tool: str) -> None: ...

    def ended(self, tool: str) -> None: ...


class Recorded(Protocol):

    def declare(self, tool: str, export_as: Replay | None, read_only: bool) -> None: ...

    def begin(self, tool: str, parent: str | None, given: Mapping[str, Any]
              ) -> Machine | None: ...

    def end(self, tool: str, parent: str | None, given: Mapping[str, Any],
            reply: Mapping[str, Any], began: Machine | None) -> None: ...

    def ended(self, tool: str, parent: str | None, given: Mapping[str, Any],
              began: Machine | None) -> None: ...


def _nothing_after() -> None:
    """Default `After`."""


def _nothing_to_give_back(reply: Reply) -> None:
    """Default `GiveBack`."""


def _summary(name: str, args: dict[str, Any], reply: Reply,
             line: Callable[[str, dict[str, Any], Reply], str] | None = None) -> str:
    """The reply's one line; looked up per call so `reply_shapes_guard` can wrap it."""
    return line(name, args, reply) if line is not None else f"{name}: {reply.get('status')}"


ON_CANCEL_ATTR = "__scry_on_cancel__"


class Boundary:
    """One server's call boundary; the server keeps the cancelled-call record."""

    def __init__(self, mcp: Envelope, lock: ServerLock, *, invoke: Invoke,
                 end: End,
                 refusal_line: RefusalLine, session_block: Callable[[bool], dict[str, Any]],
                 take_cancelled: Callable[[], cancel.Cancelled | None],
                 keep_cancelled: Callable[[cancel.Cancelled], None],
                 doc: Callable[[str, str], str], after: After = _nothing_after,
                 give_back: GiveBack = _nothing_to_give_back,
                 recorder: Recorded | None = None,
                 listener: CallListener | None = None) -> None:
        self.mcp = mcp
        self._lock = lock
        self._invoke = invoke
        self._end = end
        self._after = after
        self._give_back = give_back
        self.recorder: Recorded = recorder if recorder is not None else Unrecorded()
        self._listener = listener
        # Calls in flight, outermost first; read and written under the lock.
        self._calls: list[str] = []
        # Step replies inside the outermost call; their accounts go back if it is cancelled.
        self._answered: list[Reply] = []
        self._refusal_line = refusal_line
        self.summaries: dict[str, Summary] = {}
        #: Unwrapped bodies by name, for a server's pre-gate.
        self.bodies: dict[str, Callable[..., Any]] = {}
        self._session_block = session_block
        self._take_cancelled = take_cancelled
        self._keep_cancelled = keep_cancelled
        self._doc = doc

    @property
    def nested(self) -> int:
        """0 between calls, 1 for an outermost call."""
        return len(self._calls)

    @property
    def declared_ends(self) -> dict[str, cancel.OnCancel]:
        """How each registered tool ends on a cancel."""
        return {t.name: getattr(t.fn, ON_CANCEL_ATTR)
                for t in strict.registered(self.mcp)
                if hasattr(t.fn, ON_CANCEL_ATTR)}

    def _invoked(self, fn: Callable[..., Any], bound: inspect.BoundArguments) -> Reply:
        """The body, with the names this call was given held for it: the client's, where the MCP
        boundary already read them, or else the ones a call in process passed."""
        if given.names() is not None:
            return self._invoke(fn, bound)
        with given.remembered(name for name in bound.arguments if name != "ctx"):
            return self._invoke(fn, bound)

    def line(self, name: str, args: dict[str, Any], reply: Reply) -> str:
        """The refusal line for a reply that is not `ok`, the tool's own otherwise."""
        if reply.get("status") != "ok":
            return self._refusal_line(name, reply)
        return self.summaries[name](args, reply)

    def finished(self, name: str, args: dict[str, Any], reply: Reply,
                 body_session: bool = False, outer: bool = True) -> Reply:
        """Close a reply for every path: `summary` first, the tool's fields, `session` last.

        The `session` block is composed after the body; `body_session` keeps the one the body
        wrote (`close` composes its own, after it ended the session)."""
        body = {k: v for k, v in schema.omit_empty(name, reply).items() if k != "session"}
        kept = reply.get("session") if body_session else None
        session = (kept if kept is not None
                   else self._session_block(blocks.whole_for(name)))
        summary = _summary(name, args, reply, self.line)
        if outer and (record := self._take_cancelled()) is not None:
            return {"summary": record.summary(summary), **body, "cancelled": record.note(),
                    "session": session}
        return {"summary": summary, **body, "session": session}

    def refused(self, name: str, arguments: dict[str, Any], build: Callable[[], Reply]) -> Reply:
        """The schema's refusal, closed under the lock because closing hands over one-time
        accounts; a call cancelled while queued never calls `build`."""
        with self._lock:
            cancel.check()
            return self.finished(name, arguments, build())

    def tool(self, title: str, *, summary: Summary, read_only: bool = False,
             idempotent: bool = False, body_session: bool = False,
             on_cancel: cancel.OnCancel | None = None, replay: Replay | None = None,
             names_file: str | None = None,
             ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register `fn` as an MCP tool serialised over the one machine.

        `read_only` is `readOnlyHint`: anything that advances or writes to the machine or a file
        is not one. `idempotent` is `idempotentHint`: a repeat changes nothing and answers the
        same. A tool taking `ctx` must declare `on_cancel`. `names_file` is the argument that
        names a file the tool writes: an `ok` reply's `note` says when its name is written
        otherwise."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            signature = inspect.signature(fn)
            if "ctx" in signature.parameters and on_cancel is None:
                raise TypeError(f"{fn.__name__} waits and reports its progress, so it declares "
                                "how a cancel ends it (`on_cancel`)")
            if names_file is not None and names_file not in signature.parameters:
                raise TypeError(f"{fn.__name__} takes no {names_file!r}, so names_file="
                                f"{names_file!r} names no file it writes")
            self.recorder.declare(fn.__name__, replay, read_only)
            self.summaries[fn.__name__] = summary
            self.bodies[fn.__name__] = fn

            @functools.wraps(fn)
            def wrapped(*a: Any, **k: Any) -> Any:
                with self._lock:
                    cancel.check()
                    began = time.monotonic()
                    parent = self._calls[-1] if self._calls else None
                    bound = signature.bind_partial(*a, **k)
                    given = {n: v for n, v in bound.arguments.items() if n != "ctx"}
                    # Before the push, so nothing between can leave the stack high.
                    taken = self.recorder.begin(fn.__name__, parent, given)
                    self._calls.append(fn.__name__)
                    if parent is None:
                        self._answered = []
                    reply: Reply | None = None
                    back: list[Reply] = []
                    try:
                        if parent is None and self._listener is not None:
                            self._listener.began(fn.__name__)
                        reply = self._invoked(fn, bound)
                        if parent is not None:
                            reply = picture.unattached_below(reply, top=False)
                        if self.nested == 1:
                            cancel.check()           # a cancel that came as the body returned
                    except BaseException as e:
                        if reply is not None:
                            self.recorder.end(fn.__name__, parent, given, reply, taken)
                        else:
                            self.recorder.ended(fn.__name__, parent, given, taken)
                        if cancel.is_cancellation(e) and self.nested == 1:
                            back = [*self._answered, *([reply] if reply else [])]
                            found = self._cancelled(fn.__name__, "none" if reply is not None
                                                    else on_cancel or "none", began)
                            back += [found] if found else []
                        raise
                    finally:
                        # Popped whatever the hook does: a leftover would make every later call a
                        # step.
                        try:
                            self._after()
                        finally:
                            self._calls.pop()
                            if parent is None:
                                self._answered = []
                            # After the call's hook, which closes its accounts.
                            try:
                                for account in back:
                                    self._give_back(account)
                            finally:
                                # The listener never hears of a call still in flight.
                                if parent is None and self._listener is not None:
                                    self._listener.ended(fn.__name__)
                    self.recorder.end(fn.__name__, parent, given, reply, taken)
                    if names_file is not None:
                        _say_written_as(reply, names_file, given.get(names_file))
                    if parent is not None:
                        self._answered.append(reply)
                    bound.apply_defaults()
                    args = {n: v for n, v in bound.arguments.items() if n != "ctx"}
                    return self.finished(fn.__name__, args, reply, body_session,
                                         outer=self.nested == 0)

            setattr(wrapped, ON_CANCEL_ATTR, on_cancel or "none")

            # A docstring composed with `+` is an expression, so `__doc__` would be None.
            wrapped.__doc__ = self._doc(fn.__name__, fn.__doc__ or "")
            return self.mcp.tool(title=title,
                                 annotations=ToolAnnotations(read_only_hint=read_only,
                                                             idempotent_hint=idempotent))(wrapped)

        return register

    def _cancelled(self, name: str, on_cancel: cancel.OnCancel, began: float) -> Reply | None:
        """Apply the end, keep the record; returns the accounts the end found."""
        left, found = self._end(name, on_cancel)
        self._keep_cancelled(cancel.recorded(self._take_cancelled(), name,
                                             time.monotonic() - began, left))
        return found


def _say_written_as(reply: Reply, what: str, value: object) -> None:
    """An `ok` reply that names the file `value` asked for, written under another name, says so
    in its `note`; a reply that wrote no file (nothing yet, nothing to write) says nothing."""
    if reply.get("status") != "ok" or not isinstance(value, str) or not value:
        return
    said = file_names.written_as(what, value)
    if said is None or not _names(reply, file_names.caller_file(Path(value), what).name):
        return
    reply["note"] = f"{str(reply['note']).rstrip('.')}. {said}" if reply.get("note") else said


def _names(value: object, name: str) -> bool:
    """`value` holds, at any depth, a path whose last component is `name`."""
    if isinstance(value, str):
        return Path(value).name == name
    if isinstance(value, dict):
        return any(_names(v, name) for v in value.values())
    if isinstance(value, list):
        return any(_names(v, name) for v in value)
    return False


class ServerLock:
    """Re-entrant; its last release wakes `acquire_while` waiters."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._freed = threading.Condition(threading.Lock())
        self._depth = 0          # how deep the holder is: the lock is free again only at 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        took = self._lock.acquire(blocking, timeout)
        if took:
            self._depth += 1
        return took

    def release(self) -> None:
        self._depth -= 1
        freed = self._depth == 0
        self._lock.release()
        if freed:
            with self._freed:
                self._freed.notify_all()

    def __enter__(self) -> ServerLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    def held_here(self) -> bool:
        return bool(self._lock._is_owned())  # type: ignore[attr-defined]

    def wake(self) -> None:
        """Make `acquire_while` waiters re-ask `due()` now."""
        with self._freed:
            self._freed.notify_all()

    def acquire_while(self, due: Callable[[], bool]) -> bool:
        """Take the lock while `due()` holds: True with it held, False once moot."""
        with self._freed:
            while due():
                if self.acquire(blocking=False):
                    return True
                self._freed.wait()
        return False
