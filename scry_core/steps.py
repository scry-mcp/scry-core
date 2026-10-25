"""A step of a list judged against the tool it names, before any step runs."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterable
from typing import Any

from scry_core import recording
from scry_core import strict_arguments as strict

TYPED: dict[str, tuple[type | tuple[type, ...], str]] = {
    "int": (int, "an integer"), "float": ((int, float), "a number"),
    "str": (str, "a string"), "bool": (bool, "true or false"),
}


def unannotated(annotation: str) -> str:
    """A parameter's annotation as source text, with `Annotated[T, ...]` written as `T`."""
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


def step_ops(server: Any, here: dict[str, Any], not_steps: Iterable[str]
             ) -> dict[str, Callable[..., dict[str, Any]]]:
    """Op name -> the wrapped tool a step dispatches to, read off the registry at call time.

    `here` is read first so a step reaches whatever the server module calls the tool now.
    """
    skipped = frozenset(not_steps)
    return {t.name: here.get(t.name, t.fn) for t in strict.registered(server)
            if t.name not in skipped}


@functools.cache
def signature_of(fn: Callable[..., Any], eval_str: bool = False) -> inspect.Signature:
    """`fn`'s signature, read once: it never changes while the server runs."""
    return inspect.signature(fn, eval_str=eval_str)


def wrong_type(fn: Callable[..., Any], args: dict[str, Any]) -> str | None:
    """The first argument whose value is not the scalar its signature declares, or None.

    A bool is never an integer here.
    """
    for name, param in signature_of(fn).parameters.items():
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
    """Arguments taken as given."""
    return args


def judge(fn: Callable[..., Any], step: dict[str, Any], *,
          prepare: Callable[[dict[str, inspect.Parameter], dict[str, Any]], dict[str, Any]]
          = _as_given) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """`step` against `fn`, the tool its `op` names: the refusal or None, and the arguments after
    `prepare`.

    The bind is against the real signature, so a TypeError raised inside a tool later escapes
    as the bug it is.
    """
    args = recording.step_arguments(step)
    if (why := recording.refuse_recorded(step)) is not None:
        return {"code": "bad_argument", "message": why}, args
    if "ctx" in args:
        return {"code": "bad_argument",
                "message": "carries `ctx`, which is not a step argument: the client's context "
                           "is not something a step names"}, args
    params = dict(signature_of(fn).parameters)
    try:
        signature_of(fn).bind(**args)
    except TypeError as e:
        takes = [n for n in params if n != "ctx"]
        said = f"has bad arguments: {e}; `takes` names `{step.get('op')}`'s"
        return {"code": "bad_argument", "message": said, "takes": takes}, args
    args = prepare(params, args)
    if (wrong := wrong_type(fn, args)) is not None:
        return {"code": "bad_argument", "message": wrong}, args
    return None, args
