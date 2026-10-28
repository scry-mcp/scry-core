"""The reply contract of the two emulator servers, and the class that makes it hold.

One file in the package both servers pin, so there is one contract.

Every reply carries `status`: `ok`, or `INVALID` when the tool examined nothing or cannot vouch
for what it examined. An INVALID carries `code` (a word of the table, for a program) and
`message` (prose, for a person), flat, with the context beside them. `verdict` is a
measurement's word (`VERDICTS`) and `why` a row's or field's reason, so a refusal carries
neither, nor `reason`. No reply carries a null: a datum that could not be read is
`unavailable(why)` in its place.

`Invalid` refuses a code outside the table, an empty message and a reserved field where they
are written, so a malformed refusal never looks like a verdict. `check_envelope` guards the
built reply.

The table splits by what the caller does next: an observation about the guest (`wait_expired`)
is a measurement to report; a broken instrument (`session_broken`) is one to fix first.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, TypeVar, get_args

Code = Literal[
    "no_session",
    "session_live",
    "not_stopped",
    "not_running",
    "no_stop",
    "bad_argument",
    "needs_call",
    "unknown_ref",
    "ambiguous_ref",
    "no_channel",
    "wait_stopped",
    "wait_expired",
    "control_silent",
    "cut_by_other_stop",
    "not_settled",
    "frames_went_backwards",
    "no_progress",
    "readback_refused",
    "session_broken",
    "unexpected_answer",
    "reader_died",
    "console_rerun",
    "host_failed",
    "step_failed",
    "diverged",
    "no_recording",
    "stale_map",
]
CODES: frozenset[str] = frozenset(get_args(Code))

# `cause` is absent on purpose: it is a stop's own field, carried by a refusal that met a stop.
NOT_A_REFUSALS_WORDS: frozenset[str] = frozenset({"verdict", "why", "reason"})
RESERVED: frozenset[str] = frozenset({"summary", "status", "code", "message", "session"}
                                     | NOT_A_REFUSALS_WORDS)


Verdict = Literal["TARGET", "TIMEOUT", "OTHER_STOP", "ELAPSED"]
VERDICTS: frozenset[str] = frozenset(get_args(Verdict))
TARGET: Verdict = "TARGET"
TIMEOUT: Verdict = "TIMEOUT"
OTHER_STOP: Verdict = "OTHER_STOP"
ELAPSED: Verdict = "ELAPSED"

_T = TypeVar("_T")


class _OmitEmpty:
    """`Annotated[T, OmitEmpty]`: the envelope omits the field when empty. Never for an answer
    whose zero is the finding, nor for whether a list or a text came back whole (`truncated`,
    `clipped`), which a reader must never infer from an absence."""

    def __repr__(self) -> str:
        return "OmitEmpty"


OmitEmpty = _OmitEmpty()


def is_empty(value: Any) -> bool:
    """`None`, `""`, `0`, `0.0`, `False`, `[]`, `()` or `{}`."""
    return value is None or (isinstance(value, bool | int | float | str | list | tuple | dict)
                             and not value)


def unavailable(why: str) -> dict[str, Any]:
    """A datum that could not be read, in place of its value."""
    if not isinstance(why, str) or not why.strip():
        raise TypeError(f"an unread datum says why; got {why!r}")
    return {"available": False, "why": why}


def or_unavailable(value: _T | None, why: str) -> _T | dict[str, Any]:
    """`value`, or `unavailable(why)` when there is none."""
    return unavailable(why) if value is None else value


class Invalid(Exception):
    """A refusal, distinct from an honest negative ("the pattern matched no line") and a bug."""

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
        """The refusal's fields in the contract's order; `more` is what the catching layer adds."""
        return {"status": "INVALID", "code": self.code, "message": str(self),
                **self.fields, **more}


def refusal(code: Code, message: str, **fields: Any) -> dict[str, Any]:
    """A refusal's fields without raising; the same class judges it."""
    return Invalid(code, message, **fields).reply()


def check_envelope(reply: dict[str, Any]) -> dict[str, Any]:
    """The guard every built reply passes; returns the reply."""
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
    elif "verdict" in reply and not (isinstance(reply["verdict"], str)
                                     and reply["verdict"] in VERDICTS):
        raise TypeError(f"{reply['verdict']!r} is not a verdict; the measurements' words are "
                        f"{sorted(VERDICTS)}")
    return reply




def check_refusal(name: str, reply: dict[str, Any], code: str | None = None) -> None:
    """Assert a tool's refusal has the contract's shape; names the tool on failure."""
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
    """The code(s) an expression can hold; a name or `x.code` is typed `Code`, so mypy holds it."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _code_literals(node.body) + _code_literals(node.orelse)
    if isinstance(node, ast.Name) or (isinstance(node, ast.Attribute) and node.attr == "code"):
        return ["no_session"]
    return []


def codes_written_in(sources: Iterable[Path]) -> list[tuple[str, int, str]]:
    """Every code written in the sources (refusal-call first argument, any `code=`), read from
    the text so a branch no test reaches is covered; a missing or non-literal code raises."""
    seen: list[tuple[str, int, str]] = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_bytes())):   # its own coding, never the host's
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
