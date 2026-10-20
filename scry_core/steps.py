"""A step of a list judged against the tool it names, before any step of the list runs: what both
servers' `perform` (and `drive`'s act, and `start`'s plan) hold every step to, whatever the
server's own vocabulary and value checks add after it.

A step is `{"op": <tool>, ...its arguments}`. This judges what any tool's signature already says:
a `recorded` check of the right shape, no `ctx` (the client's, never a step's), argument names
the tool takes, and the scalar ones of the declared type. The op itself, and every value a tool
judges further, are the server's.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from scry_core import recording

#: The scalar annotations a step's value is held to, and how a refusal names each.
TYPED: dict[str, tuple[type | tuple[type, ...], str]] = {
    "int": (int, "an integer"), "float": ((int, float), "a number"),
    "str": (str, "a string"), "bool": (bool, "a boolean"),
}


def unannotated(annotation: str) -> str:
    """A parameter's annotation, as source text, with every `Annotated[T, ...]` written as its
    `T`: the schema half rides on the type and changes nothing about what the value is, so a
    reader of the text judges `Annotated[int, ...]` as the `int` it wraps."""
    out, at = [], 0
    while (start := annotation.find("Annotated[", at)) != -1:
        out.append(annotation[at:start])
        depth, i, comma = 1, start + len("Annotated["), -1
        while depth:
            c = annotation[i]
            depth += (c == "[") - (c == "]")
            if c == "," and depth == 1 and comma == -1:
                comma = i
            i += 1
        out.append(unannotated(annotation[start + len("Annotated["):comma]).strip())
        at = i
    return "".join(out) + annotation[at:]


def wrong_type(fn: Callable[..., Any], args: dict[str, Any]) -> str | None:
    """The first argument whose value is not what the tool's own signature declares, as the
    refusal names it, or None. A bool is never an integer here: `True` for a count is a
    mistake, not a 1. The scalar annotations are judged, and a scalar `| None` too (a `None`
    passes it, anything else is judged as the scalar); a step's remaining shapes are the
    server's checks' business."""
    for name, param in inspect.signature(fn).parameters.items():
        if name not in args:
            continue
        ann = unannotated(param.annotation) if isinstance(param.annotation, str) \
            else getattr(param.annotation, "__name__", "")
        parts = [part.strip() for part in ann.split("|")]
        value = args[name]
        if "None" in parts and len(parts) == 2:
            if value is None:
                continue
            parts.remove("None")
        typed = TYPED.get(parts[0]) if len(parts) == 1 else None
        if typed is None:
            continue
        want, word = typed
        if (isinstance(value, bool) and want is not bool) or not isinstance(value, want):
            return f"{name} is {word}; got {value!r}"
    return None


def _as_given(params: dict[str, inspect.Parameter], args: dict[str, Any]) -> dict[str, Any]:
    """Arguments taken as given: a server with no conversion of its own."""
    return args


def judge(fn: Callable[..., Any], step: dict[str, Any], *,
          prepare: Callable[[dict[str, inspect.Parameter], dict[str, Any]], dict[str, Any]]
          = _as_given) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """`step` against `fn`, the tool its `op` names: the refusal (`code`, `message`, and `takes`
    when the names do not bind) or None, and the step's arguments as `prepare` hands them to the
    server's value checks (a server that converts a value its tool wrapper would, MAME's integral
    floats, says so here). The bind is against the REAL signature (`functools.wraps` exposes it),
    so a bad NAME is the list's fault to report, and a TypeError raised inside a tool later is not
    swallowed as "bad arguments" but escapes as the bug it is."""
    args = recording.step_arguments(step)
    if (why := recording.refuse_recorded(step)) is not None:
        return {"code": "bad_argument", "message": why}, args
    if "ctx" in args:
        return {"code": "bad_argument",
                "message": "carries `ctx`, which is not a step argument: the client's context "
                           "is not something a step names"}, args
    params = dict(inspect.signature(fn).parameters)
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        takes = [n for n in params if n != "ctx"]
        said = f"has bad arguments: {e}; `takes` names `{step.get('op')}`'s"
        return {"code": "bad_argument", "message": said, "takes": takes}, args
    args = prepare(params, args)
    if (wrong := wrong_type(fn, args)) is not None:
        return {"code": "bad_argument", "message": wrong}, args
    return None, args
