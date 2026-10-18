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
end), and the accounts its reply carried go back for the next one (`give_back`). A cancel that
arrives after that poll, while the reply is on its way, is not seen.
"""

from __future__ import annotations

import functools
import inspect
import threading
import time
from collections.abc import Callable
from typing import Any

from mcp.types import ToolAnnotations

from scry_core import cancel
from scry_core.envelope import Envelope

Reply = dict[str, Any]
#: How the server calls a tool's body (the body, its signature, the call's positional and keyword
#: arguments) and returns the reply. The server reads its arguments and translates ITS OWN errors
#: into replies here; whatever it lets escape is a defect or a cancellation.
Invoke = Callable[[Callable[..., Any], inspect.Signature, tuple[Any, ...], dict[str, Any]], Reply]
#: The end a cancelled outermost call declared, applied by the server (the tool's name and its
#: `on_cancel`): what the machine was left as, and an account to hand to `After`, or None.
End = Callable[[str, cancel.OnCancel], tuple[cancel.Left, object]]
#: What runs after EVERY call inside the lock, a step of a sequence included and whichever way it
#: ended: the account `End` returned for a cancelled call, None otherwise.
After = Callable[[object], None]
#: The one line a caller reads first: the tool's name, the arguments it ran with, its reply.
ReplyLine = Callable[[str, dict[str, Any], Reply], str]
#: The one-time accounts a reply nobody will read carried, put back for the next reply.
GiveBack = Callable[[Reply], None]


def _nothing_after(kept: object) -> None:
    """The `After` of a server with nothing to do once a call is over."""


def _nothing_to_give_back(reply: Reply) -> None:
    """The `GiveBack` of a server that builds no one-time account into a reply's body: its
    accounts are handed over by `End` and `After` instead."""


class Boundary:
    """One server's call boundary over its `Envelope`, its lock and its hooks. The record of a
    cancelled call is the server's to keep (`take_cancelled` hands it over and clears it,
    `keep_cancelled` stores a new one), because its state is what a caller's `status` reads."""

    def __init__(self, mcp: Envelope, lock: threading.RLock, *, invoke: Invoke, end: End,
                 line: ReplyLine, session_block: Callable[[], dict[str, Any] | None],
                 take_cancelled: Callable[[], cancel.Cancelled | None],
                 keep_cancelled: Callable[[cancel.Cancelled], None],
                 doc: Callable[[str, str], str], after: After = _nothing_after,
                 give_back: GiveBack = _nothing_to_give_back) -> None:
        self.mcp = mcp
        self._lock = lock
        self._invoke = invoke
        self._end = end
        self._after = after
        self._give_back = give_back
        self._line = line
        self._session_block = session_block
        self._take_cancelled = take_cancelled
        self._keep_cancelled = keep_cancelled
        self._doc = doc
        # HOW DEEP THE CALLS INSIDE THE LOCK ARE NESTED, read and written only while holding it.
        self.nested = 0
        #: Each registered tool's `on_cancel` as declared, None where it declared none (and so
        #: ends `none`): what a server's suite holds against its reference (`ends_table`).
        self.declared_ends: dict[str, cancel.OnCancel | None] = {}

    def finished(self, name: str, args: dict[str, Any], reply: Reply,
                 session_before: bool = False, outer: bool = True) -> Reply:
        """The reply a caller reads, closed in ONE place for every path (the wrapper's and the
        schema's refusal): `summary` first, the tool's own fields, `session` last.

        THE `session` BLOCK IS COMPOSED HERE, AFTER THE BODY, from the state the server holds: a
        body that released the machine once its envelope was built would otherwise hand back a
        block describing the machine before it did. `session_before` keeps the block the body
        built: `close`'s, the state BEFORE the close."""
        body = {k: v for k, v in reply.items() if k != "session"}
        kept = reply.get("session") if session_before else None
        session = kept if kept is not None else self._session_block()
        summary = self._line(name, args, reply)
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

    def tool(self, title: str, *, read_only: bool = False, idempotent: bool = False,
             session_before: bool = False, on_cancel: cancel.OnCancel | None = None,
             ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register `fn` as an MCP tool serialised over the one machine. `read_only` and
        `idempotent` become the protocol's hints. A tool that takes a `ctx` (the protocol's
        `Context`, for the progress line of a bounded wait) must declare `on_cancel` or fails at
        import, because a wait cancelled with no declared end would leave the machine in a state
        nobody chose; any other tool ends `none` when a cancel meets it. The `ctx` is kept out of
        the summary's arguments, which are the ones the call RAN with, defaults applied."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            signature = inspect.signature(fn)
            if "ctx" in signature.parameters and on_cancel is None:
                raise TypeError(f"{fn.__name__} waits and reports its progress, so it declares "
                                "how a cancel ends it (`on_cancel`)")
            self.declared_ends[fn.__name__] = on_cancel

            @functools.wraps(fn)
            def wrapped(*a: Any, **k: Any) -> Any:
                with self._lock:
                    # A CALL CANCELLED WHILE IT WAITED FOR THE LOCK did nothing, so it has no end
                    # to apply and nothing to record.
                    cancel.check()
                    began = time.monotonic()
                    self.nested += 1
                    kept: object = None
                    reply: Reply | None = None
                    try:
                        reply = self._invoke(fn, signature, a, k)
                        if self.nested == 1:
                            cancel.check()           # a cancel that came as the body returned
                    except BaseException as e:
                        if cancel.is_cancellation(e) and self.nested == 1:
                            if reply is not None:
                                self._give_back(reply)
                            kept = self._cancelled(fn.__name__, "none" if reply is not None
                                                   else on_cancel or "none", began)
                        raise
                    finally:
                        # The count goes back whatever the hook does: a count left high would
                        # make every later call a step, and no cancel would ever end again.
                        try:
                            self._after(kept)
                        finally:
                            self.nested -= 1
                    bound = signature.bind_partial(*a, **k)
                    bound.apply_defaults()
                    args = dict(bound.arguments)
                    args.pop("ctx", None)
                    # Under the lock: the `session` block is read off the one machine's state.
                    return self.finished(fn.__name__, args, reply, session_before,
                                         outer=self.nested == 0)

            # THE DOCSTRING IS A LITERAL WITH PLACEHOLDERS, filled here: a string composed with
            # `+` is an expression, not a docstring, so `__doc__` would come out None.
            wrapped.__doc__ = self._doc(fn.__name__, fn.__doc__ or "")
            return self.mcp.tool(title=title,
                                 annotations=ToolAnnotations(read_only_hint=read_only,
                                                             idempotent_hint=idempotent))(wrapped)

        return register

    def _cancelled(self, name: str, on_cancel: cancel.OnCancel, began: float) -> object:
        """The end applied and the record kept, with the names of the cancelled calls before it
        that no reply reported (`cancel.recorded`); the account the end returned goes back."""
        left, kept = self._end(name, on_cancel)
        self._keep_cancelled(cancel.recorded(self._take_cancelled(), name,
                                             time.monotonic() - began, left))
        return kept
