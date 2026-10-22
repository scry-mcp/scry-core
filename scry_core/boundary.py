"""THE CALL BOUNDARY every Scry server wraps its tools in: the one lock over the one machine, how
deep the calls inside it are nested, how a cancelled call ends and is recorded, and the reply every
path closes with. What is the same for every tool on every server is here; what each server says
(how its body is called and which of its errors are answers, how its machine is stopped or
killed, where it keeps the record, its `session` block and its summaries) is handed in as a hook,
so the vocabulary stays the server's.

ONE CANCELLED CALL ENDS ONCE. A call cancelled while it queued for the lock did nothing, so it
applies no end and keeps no record. A call cancelled in its body, a translation of its own errors
included, applies the end it declared (`cancel.OnCancel`) only when it is the OUTERMOST call: a
step of a `perform` cancelled is the sequence's cancel, ended as the sequence declared. The record
waits for the next reply, and only the outermost reply takes it, because a step's reply is not
the one a caller reads.

A CANCEL THAT ARRIVES AS THE BODY RETURNS is looked for once more, after the body and before the
reply is closed, because closing a reply spends one-time accounts and the SDK drops the reply of
a cancelled request: such a call is recorded as cancelled with no end applied (it reached its own
end), the accounts its reply carried go back for the next one, and the session's recording takes
the call as answered, since its reply says where it left the machine. A cancel that arrives after
that poll, while the reply is on its way, is not seen.

THE ACCOUNTS A REPLY NOBODY READS CARRIED GO BACK, through ONE seam (`give_back`), for the next
reply to say: those of a reply cancelled as it returned, those the end of a cancelled call found
(`End` returns them in a reply's own shape), and those of every step that answered inside an
outermost call that was then cancelled (a `perform`'s finished steps).

A LISTENER HEARS EACH OUTERMOST CALL begin and end (`CallListener`), whichever way it ended,
which is what the presence indicator lights and dims the window by.

THE HOOKS ARE BOUND WHEN THE BOUNDARY IS BUILT, once, as the server's own functions: a test or a
runtime that rebinds one of those names afterwards reaches nothing here.
"""

from __future__ import annotations

import functools
import inspect
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from mcp.types import ToolAnnotations

from scry_core import cancel, picture
from scry_core import session_block as blocks
from scry_core import strict_arguments as strict
from scry_core.envelope import Envelope
from scry_core.recording import ExportAs, Machine, Unrecorded

Reply = dict[str, Any]
#: How the server calls a tool's body (the body, and the call's arguments bound ONCE, here, to
#: the body's signature, the server's to read in place) and returns the reply. The server
#: translates ITS OWN errors into replies here; whatever it lets escape is a defect or a
#: cancellation.
Invoke = Callable[[Callable[..., Any], inspect.BoundArguments], Reply]
#: The end a cancelled outermost call declared, applied by the server (the tool's name and its
#: `on_cancel`): what the machine was left as, and the accounts it found in a reply's shape (a
#: stop the machine reached on its own), or None.
End = Callable[[str, cancel.OnCancel], tuple[cancel.Left, "Reply | None"]]
#: What runs after EVERY call inside the lock, a step of a sequence included and whichever way it
#: ended.
After = Callable[[], None]
#: A tool's own one line, from the arguments it ran with and its reply.
Summary = Callable[[dict[str, Any], Reply], str]
#: The one line of a reply that is not `ok`, the server's: the tool's name and its reply.
RefusalLine = Callable[[str, Reply], str]
#: The one-time accounts a reply nobody will read carried, put back for the next reply.
GiveBack = Callable[[Reply], None]


class CallListener(Protocol):
    """What hears every OUTERMOST call begin and end (presence's, on both servers): told the
    tool's name, under the lock, whichever way the call ended. It runs inside the call's own
    bookkeeping, so it must not block; one that raises fails that call, and only that call."""

    def began(self, tool: str) -> None: ...

    def ended(self, tool: str) -> None: ...


class Recorded(Protocol):
    """What the boundary feeds a session's recording (`scry_core.recording.Recorder`, or
    `Unrecorded` for a server that records nothing)."""

    def declare(self, tool: str, export_as: ExportAs | None, read_only: bool) -> None: ...

    def begin(self, tool: str, parent: str | None, given: Mapping[str, Any]
              ) -> Machine | None: ...

    def end(self, tool: str, parent: str | None, given: Mapping[str, Any],
            reply: Mapping[str, Any], began: Machine | None) -> None: ...

    def ended(self, tool: str, parent: str | None, given: Mapping[str, Any],
              began: Machine | None) -> None: ...


def _nothing_after() -> None:
    """The `After` of a server with nothing to do once a call is over."""


def _nothing_to_give_back(reply: Reply) -> None:
    """The `GiveBack` of a server whose replies carry no one-time account."""


def _summary(name: str, args: dict[str, Any], reply: Reply,
             line: Callable[[str, dict[str, Any], Reply], str] | None = None) -> str:
    """THE TOOL BOUNDARY's one line, which every reply a caller receives passes through COMPLETE
    (`Boundary.finished`): looked up here at each call, so the reply-shape guard
    (`scry_core.reply_shapes_guard`) wraps it where the boundary reads it. Without a boundary's
    `line`, the tool's name and status."""
    return line(name, args, reply) if line is not None else f"{name}: {reply.get('status')}"


#: Where a registered tool's declared end is kept, on the function the MCP layer holds.
ON_CANCEL_ATTR = "__scry_on_cancel__"


class Boundary:
    """One server's call boundary over its `Envelope`, its lock and its hooks. The record of a
    cancelled call is the server's to keep (`take_cancelled` hands it over and clears it,
    `keep_cancelled` stores a new one), because its state is what a caller's `status` reads."""

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
        #: The session's recording (`scry_core.recording`), fed with every call it takes.
        self.recorder: Recorded = recorder if recorder is not None else Unrecorded()
        self._listener = listener
        # THE CALLS IN FLIGHT INSIDE THE LOCK, outermost first: a call's parent is the one above,
        # and how many there are is how deep the call is nested. Read and written under the lock.
        self._calls: list[str] = []
        # The replies of the steps that answered inside the outermost call in flight, whose
        # accounts go back if it is cancelled.
        self._answered: list[Reply] = []
        self._refusal_line = refusal_line
        #: Each registered tool's own line (`Summary`), by name.
        self.summaries: dict[str, Summary] = {}
        #: Each registered tool's own body, unwrapped, by name: what a server's pre-gate judges a
        #: probe's call against (its defaults, its annotations).
        self.bodies: dict[str, Callable[..., Any]] = {}
        self._session_block = session_block
        self._take_cancelled = take_cancelled
        self._keep_cancelled = keep_cancelled
        self._doc = doc

    @property
    def nested(self) -> int:
        """How deep the call in flight is nested: 0 between calls, 1 for an outermost call."""
        return len(self._calls)

    @property
    def declared_ends(self) -> dict[str, cancel.OnCancel]:
        """How each tool the server registers ends when a cancel meets it, read off the
        registrations themselves (`none` for one that declared nothing): what a server's suite
        holds against its reference (`ends_table`)."""
        return {t.name: getattr(t.fn, ON_CANCEL_ATTR)
                for t in strict.registered(self.mcp)
                if hasattr(t.fn, ON_CANCEL_ATTR)}

    def line(self, name: str, args: dict[str, Any], reply: Reply) -> str:
        """The one line a caller reads first: the server's for a reply that is not `ok`, the
        tool's own otherwise."""
        if reply.get("status") != "ok":
            return self._refusal_line(name, reply)
        return self.summaries[name](args, reply)

    def finished(self, name: str, args: dict[str, Any], reply: Reply,
                 session_before: bool = False, outer: bool = True) -> Reply:
        """The reply a caller reads, closed in ONE place for every path (the wrapper's and the
        schema's refusal): `summary` first, the tool's own fields, `session` last.

        THE `session` BLOCK IS COMPOSED HERE, AFTER THE BODY, from the state the server holds: a
        body that released the machine once its envelope was built would otherwise hand back a
        block describing the machine before it did. The block is whole on the tools that answer
        what the session is, short on the rest (`scry_core.session_block`). `session_before`
        keeps the block the body built: `close`'s, the state BEFORE the close."""
        body = {k: v for k, v in reply.items() if k != "session"}
        kept = reply.get("session") if session_before else None
        session = (kept if kept is not None
                   else self._session_block(blocks.whole_for(name)))
        summary = _summary(name, args, reply, self.line)
        if outer and (record := self._take_cancelled()) is not None:
            # WHAT A CANCELLED CALL LEFT, said first by the next reply: the cancelled call had none.
            return {"summary": record.summary(summary), **body, "cancelled": record.note(),
                    "session": session}
        return {"summary": summary, **body, "session": session}

    def refused(self, name: str, arguments: dict[str, Any], build: Callable[[], Reply]) -> Reply:
        """The schema's refusal (`Envelope`'s `refusal`), built and closed under the lock like
        every other reply, because closing a reply hands over one-time accounts. Its call never
        reached a wrapper (the schema refuses before the body), so nothing here already holds
        the lock. A refusal whose call was cancelled while it queued answers nobody, so `build`
        is not called and no account is spent."""
        with self._lock:
            cancel.check()
            return self.finished(name, arguments, build())

    def tool(self, title: str, *, summary: Summary, read_only: bool = False,
             idempotent: bool = False, session_before: bool = False,
             on_cancel: cancel.OnCancel | None = None, replay: ExportAs | None = None,
             ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register `fn` as an MCP tool serialised over the one machine, its reply led by the
        line `summary` writes (REQUIRED, so a tool registered without one fails at import).
        `title` is what the client shows. `read_only` becomes `readOnlyHint`, which lets a client
        run readers in parallel (honest, since every tool takes the lock): anything that advances
        the machine, writes to it or writes a FILE is not one. `idempotent` becomes
        `idempotentHint`, a STRONGER claim (calling again changes nothing AND answers the same),
        false unless the tool's own data cannot change: declared wrongly it invites a client to
        repeat a call whose answer moved underneath it. `session_before` keeps the `session`
        block the body built (`close`'s, the state before the kill). A tool that takes a `ctx` (the
        protocol's `Context`, for the progress line of a bounded wait) must declare `on_cancel`
        or fails at import, because a wait cancelled with no declared end would leave the machine
        in a state nobody chose; any other tool ends `none` when a cancel meets it. The `ctx` is
        kept out of the summary's arguments, which are the ones the call RAN with, defaults
        applied. `replay` is what the tool's calls become in an export (`scry_core.recording`)."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            signature = inspect.signature(fn)
            if "ctx" in signature.parameters and on_cancel is None:
                raise TypeError(f"{fn.__name__} waits and reports its progress, so it declares "
                                "how a cancel ends it (`on_cancel`)")
            self.recorder.declare(fn.__name__, replay, read_only)
            self.summaries[fn.__name__] = summary
            self.bodies[fn.__name__] = fn

            @functools.wraps(fn)
            def wrapped(*a: Any, **k: Any) -> Any:
                with self._lock:
                    # A CALL CANCELLED WHILE IT WAITED FOR THE LOCK did nothing, so it has no end
                    # to apply and nothing to record.
                    cancel.check()
                    began = time.monotonic()
                    parent = self._calls[-1] if self._calls else None
                    # THE ARGUMENTS ARE BOUND ONCE: the recorder keeps them as given, the server
                    # reads them in place, and the summary reads them with the defaults applied.
                    bound = signature.bind_partial(*a, **k)
                    given = {n: v for n, v in bound.arguments.items() if n != "ctx"}
                    # FED BEFORE THE CALL IS PUSHED, so nothing between the two can leave it high.
                    taken = self.recorder.begin(fn.__name__, parent, given)
                    self._calls.append(fn.__name__)
                    if parent is None:
                        self._answered = []
                    reply: Reply | None = None
                    back: list[Reply] = []
                    try:
                        if parent is None and self._listener is not None:
                            self._listener.began(fn.__name__)
                        reply = self._invoke(fn, bound)
                        if parent is not None:
                            # A STEP'S PICTURE IS NEVER ATTACHED, only a reply's own: said in
                            # the step's block before its summary line or its record reads it.
                            reply = picture.unattached_below(reply, top=False)
                        if self.nested == 1:
                            cancel.check()           # a cancel that came as the body returned
                    except BaseException as e:
                        if reply is not None:
                            # ANSWERED, then cancelled: the reply says where it left the machine.
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
                        # The call is popped whatever the hook does: a call left on the stack
                        # would make every later call a step, and no cancel would ever end again.
                        try:
                            self._after()
                        finally:
                            self._calls.pop()
                            if parent is None:
                                self._answered = []
                            # AFTER the call's own hook, which closes the call's one-time
                            # accounts: what goes back is for the NEXT reply.
                            try:
                                for account in back:
                                    self._give_back(account)
                            finally:
                                # After the hook and the give-back, whatever they did: the
                                # listener never hears of a call still in flight, nor misses
                                # the end of one.
                                if parent is None and self._listener is not None:
                                    self._listener.ended(fn.__name__)
                    self.recorder.end(fn.__name__, parent, given, reply, taken)
                    if parent is not None:
                        self._answered.append(reply)
                    bound.apply_defaults()
                    args = {n: v for n, v in bound.arguments.items() if n != "ctx"}
                    # Under the lock: the `session` block is read off the one machine's state.
                    return self.finished(fn.__name__, args, reply, session_before,
                                         outer=self.nested == 0)

            setattr(wrapped, ON_CANCEL_ATTR, on_cancel or "none")

            # THE DOCSTRING IS A LITERAL WITH PLACEHOLDERS, filled here: a string composed with
            # `+` is an expression, not a docstring, so `__doc__` would come out None.
            wrapped.__doc__ = self._doc(fn.__name__, fn.__doc__ or "")
            return self.mcp.tool(title=title,
                                 annotations=ToolAnnotations(read_only_hint=read_only,
                                                             idempotent_hint=idempotent))(wrapped)

        return register

    def _cancelled(self, name: str, on_cancel: cancel.OnCancel, began: float) -> Reply | None:
        """The end applied and the record kept, with the names of the cancelled calls before it
        that no reply reported (`cancel.recorded`); answered: the accounts the end found."""
        left, found = self._end(name, on_cancel)
        self._keep_cancelled(cancel.recorded(self._take_cancelled(), name,
                                             time.monotonic() - began, left))
        return found


class ServerLock:
    """THE ONE LOCK OVER THE ONE MACHINE, re-entrant, whose last release wakes whoever waits for
    it to be free (`acquire_while`): a writer between calls (the presence's repaint) sleeps
    until a call ends, never asking twenty times a second through a long still call."""

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
        """Whether the calling thread holds the lock."""
        # `RLock` knows its owner and says so only through this private method; the public
        # surface has no other way to ask (`threading.RLock`'s own source).
        return bool(self._lock._is_owned())  # type: ignore[attr-defined]

    def wake(self) -> None:
        """Have whoever waits in `acquire_while` ask its `due()` again now, without the lock
        being freed: what made the wait moot (a writer closed) happened under the lock."""
        with self._freed:
            self._freed.notify_all()

    def acquire_while(self, due: Callable[[], bool]) -> bool:
        """The lock taken while `due()` holds, asked once now and again at each release that
        frees it: True with the lock held (the caller releases it), False once it went moot.
        The check and the sleep are one step under the condition, so no release slips between
        them."""
        with self._freed:
            while due():
                if self.acquire(blocking=False):
                    return True
                self._freed.wait()
        return False
