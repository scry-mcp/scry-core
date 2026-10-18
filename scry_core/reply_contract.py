"""The reply contract of the two emulator servers, and the class that makes it hold.

ONE FILE, IN THE PACKAGE BOTH SERVERS PIN: each server is published on its own, and a contract
held by two copies is two contracts the day one of them is edited alone.

THE CONTRACT. Every reply carries `status`: `ok`, or `INVALID` when the tool examined nothing
or cannot vouch for what it examined. An INVALID carries `code` (one word from the table
below, for a program) and `message` (the prose, for a person), flat, with whatever context
the refusal has beside them (`last_stop`, `posted`, `route`, `control_hits`...). `verdict`
is a MEASUREMENT's word (`TARGET`, `TIMEOUT`, `ELAPSED`, `OTHER_STOP`) and never a refusal's,
and `why` is a row's or a field's reason, never a refusal's prose, so a refusal carries neither
at its top level; `reason` and `cause`, the spellings `message` replaced, are refused there
too, so a reader cannot be handed two dialects.

WHY A CLASS. A convention lives in the reader's memory and a grep; the class refuses a code
outside the table, an empty message and a reserved field WHERE THEY ARE WRITTEN, as a
programmer's error that escapes as an execution failure, so a malformed refusal can never
reach a caller looking like a verdict. `check_envelope` is the same guard on the built reply,
called by each server's envelope function.

THE TABLE, one word per concept. What separates a
refusal from its neighbour is what the CALLER does next: an observation about the guest
(`wait_expired`, `control_silent`) is a measurement to report; a broken instrument
(`session_broken`, `host_failed`, `unexpected_answer`) is one to fix before reporting anything.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, get_args

#: The contract's version: a consumer can assert the contract it was written against.
CONTRACT_VERSION = 5

Code = Literal[
    "no_session",         # no live machine: `start` first
    "session_live",       # `start` over a live session: `close` it first
    "not_stopped",        # the machine runs and this needs it stopped
    "not_running",        # the machine is stopped and this needs it running: a key or a
                          # mouse move into a running DOS guest (MAME's `input` needs a STOP)
    "no_stop",            # no stop yet in this session to answer from
    "bad_argument",       # an argument's shape, range or path
    "needs_call",         # another call has to come first (no scan open, no manifest loaded):
                          # the message names it, where `bad_argument` asks for another value
    "unknown_ref",        # a name or ref that resolves to nothing, or matches no declaration
    "ambiguous_ref",      # a name with several matches, or one already declared another way
    "no_channel",         # the channel asked for does not exist: no log, table, route, window
    "wait_stopped",       # a wait that cannot end because the machine stopped
    "wait_expired",       # the bound expired with nothing matched
    "control_silent",     # the control never fired, so the target's silence means nothing
    "cut_by_other_stop",  # another stop cut the run before the control had its chance
    "not_settled",        # no proof the machine came to rest after a run: it may be running
    "frames_went_backwards",  # the frame counter read lower after the run than before it
    "no_progress",        # the frame counter did not move: nothing was emulated
    "readback_refused",   # what was read back does not show what was asked
    "session_broken",     # the emulator is gone, or its channel died mid-call
    "unexpected_answer",  # the console answered something not of the shape expected
    "reader_died",        # the console's reader died before answering: not evaluated, or not yet
    "console_rerun",      # the console ran the call's own chunk again: it acted twice
    "host_failed",        # a helper of the host failed: a program, a file, the window server
    "step_failed",        # a step of a sequence failed; `failed` carries the step's own code
    "diverged",           # a replayed step's reply does not hold to what the session recorded
    "no_recording",       # nothing is recorded to export: a recording begins at a `start`
]
CODES: frozenset[str] = frozenset(get_args(Code))

# What a refusal may not carry beside the three fields: the envelope's own names, the words
# other parts of a reply own (a measurement's `verdict`, a row's or a field's `why`), and the
# spellings `message` replaced.
NOT_A_REFUSALS_WORDS: frozenset[str] = frozenset({"verdict", "why", "reason", "cause"})
RESERVED: frozenset[str] = frozenset({"summary", "status", "code", "message", "session"}
                                     | NOT_A_REFUSALS_WORDS)


class Invalid(Exception):
    """A refusal: the tool examined nothing, or cannot vouch for what it examined.

    Distinct from an honest negative ("the pattern matched no line" is an answer, "there was
    no log to match against" is not) and from a bug (which escapes as an execution failure).
    `code` is one word of the table, checked here and by the type; `fields` is the context
    the reply carries beside the message.
    """

    def __init__(self, code: Code, message: str, **fields: Any) -> None:
        if code not in CODES:
            raise TypeError(f"{code!r} is not a code of the reply contract; the table is "
                            f"{sorted(CODES)}")
        if not isinstance(message, str) or not message.strip():
            raise TypeError(f"a refusal's message is non-empty prose; got {message!r}")
        taken = sorted(RESERVED & fields.keys())
        if taken:
            raise TypeError(f"{taken} are reserved by the reply contract and cannot be fields "
                            f"of a refusal")
        super().__init__(message)
        self.code: Code = code
        self.fields = fields

    def reply(self, **more: Any) -> dict[str, Any]:
        """The refusal's own fields in the contract's order: `status`, `code`, `message`, then
        the context, `more` last (what the catching layer adds: `last_stop`, the roster)."""
        return {"status": "INVALID", "code": self.code, "message": str(self),
                **self.fields, **more}


def refusal(code: Code, message: str, **fields: Any) -> dict[str, Any]:
    """A refusal's fields without raising, for a tool that answers INVALID as its reply: the
    same class judges it, so nothing reaches an envelope that the class would have refused."""
    return Invalid(code, message, **fields).reply()


def check_envelope(reply: dict[str, Any]) -> dict[str, Any]:
    """The guard every built reply passes: `status` is `ok` or `INVALID`; an INVALID carries a
    code of the table and a message and none of the words that are not a refusal's; an `ok`
    carries neither `code` nor `message`. Returns the reply so it can be wrapped in place."""
    status = reply.get("status")
    if status not in ("ok", "INVALID"):
        raise TypeError(f"status is `ok` or `INVALID`; got {status!r}")
    if status == "INVALID":
        Invalid(reply.get("code", ""), reply.get("message", ""))
        stale = sorted(NOT_A_REFUSALS_WORDS & reply.keys())
        if stale:
            raise TypeError(f"an INVALID reply carries {stale}, which are not a refusal's: its "
                            f"word and its prose live in `code` and `message`")
    elif "code" in reply or "message" in reply:
        raise TypeError("an `ok` reply carries `code` or `message`, which are a refusal's")
    return reply


# ------------------------------------------------------------- the contract's own audit
#
# Two checks every server's suite runs, kept HERE so the two suites cannot drift apart in
# what they hold a refusal to: the shape of a built reply, and the codes written in a tree.


def check_refusal(name: str, reply: dict[str, Any], code: str | None = None) -> None:
    """A tool's refusal as the caller receives it: `summary`, `status`, `code`, `message`
    first, `session` last, a code of the table (`code` when one is expected), prose in the
    message, and none of the words that are not a refusal's. Raises AssertionError naming
    the tool, so a suite can walk every tool through one gate and read one failure."""
    if reply.get("status") != "INVALID":
        raise AssertionError(f"{name}: not a refusal: {reply}")
    if reply.get("code") not in CODES:
        raise AssertionError(f"{name}: code {reply.get('code')!r} is not in the table: {reply}")
    if code is not None and reply["code"] != code:
        raise AssertionError(f"{name}: code {reply['code']!r}, expected {code!r}: {reply}")
    message = reply.get("message")
    if not isinstance(message, str) or not message.strip():
        raise AssertionError(f"{name}: no prose in `message`: {reply}")
    stale = sorted(NOT_A_REFUSALS_WORDS & reply.keys())
    if stale:
        raise AssertionError(f"{name}: a refusal carries {stale}: {reply}")
    keys = list(reply)
    if keys[:4] != ["summary", "status", "code", "message"] or keys[-1] != "session":
        raise AssertionError(f"{name}: the envelope's order is {keys}")
    if not str(reply["summary"]).startswith(f"{name}: INVALID ({reply['code']}), "):
        raise AssertionError(f"{name}: the summary does not open with the refusal: "
                             f"{reply['summary']!r}")


def _code_literals(node: ast.expr) -> list[str]:
    """The code(s) an expression can hold. A bare NAME, or an attribute `x.code`, is
    accepted: both are typed `Code`, and mypy's strict pass holds that a value of that type
    carries one word of the table; the placeholder returned for them is in the table."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _code_literals(node.body) + _code_literals(node.orelse)
    if isinstance(node, ast.Name) or (isinstance(node, ast.Attribute) and node.attr == "code"):
        return ["no_session"]
    return []


def codes_written_in(sources: Iterable[Path]) -> list[tuple[str, int, str]]:
    """Every code written in the sources: the first argument of an `Invalid(...)`,
    `invalid(...)` or `refusal(...)` call, and the value of any `code=` keyword. The class
    checks at RUNTIME; this reads the text so a code typed wrong in a branch no test reaches
    is caught, and a code cannot be computed from a string. A refusal with no code, or one
    that is not a literal of the table's shape, raises AssertionError naming the line."""
    seen: list[tuple[str, int, str]] = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            attr = callee.attr if isinstance(callee, ast.Attribute) else (
                callee.id if isinstance(callee, ast.Name) else "")
            where = f"{path.name}:{node.lineno}"
            if attr in ("Invalid", "invalid", "refusal"):
                first = node.args[0] if node.args else next(
                    (k.value for k in node.keywords if k.arg == "code"), None)
                if first is None:
                    raise AssertionError(f"{where}: a refusal with no code")
                codes = _code_literals(first)
                if not codes:
                    raise AssertionError(f"{where}: the code is not a string literal")
                seen.extend((path.name, node.lineno, c) for c in codes)
            for k in node.keywords:
                if k.arg == "code" and attr not in ("Invalid", "invalid", "refusal"):
                    codes = _code_literals(k.value)
                    if not codes:
                        raise AssertionError(f"{where}: `code=` is not a literal")
                    seen.extend((path.name, node.lineno, c) for c in codes)
    return seen
