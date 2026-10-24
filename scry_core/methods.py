"""A tool whose operation is a `method` argument, the way GitHub's MCP server folds a resource's
operations into one reader and one writer (`issue_read`, `pull_request_read`).

The tool's schema is the union of its methods' arguments, so an argument another method takes
passes the schema: `chosen` refuses it naming the method, and treats a fold's `""` and `None`
as "not given", so each method's own defaults apply.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from scry_core import strict_arguments as strict
from scry_core import vocabulary as vocab
from scry_core.reply_contract import Invalid

Summary = Callable[[dict[str, Any], dict[str, Any]], str]


@dataclass(frozen=True)
class Method:
    """One `method` of a fold: its body, its pre-gate judge and its summary line, which
    `fold_line` opens with the tool and the method."""

    body: Callable[..., dict[str, Any]]
    check: Callable[..., object]
    line: Summary

    def takes(self) -> list[str]:
        """The arguments a caller may give it: a keyword-only one is the server's (`run`)."""
        return [name for name, p in inspect.signature(self.body).parameters.items()
                if p.kind is not p.KEYWORD_ONLY]

    def filled(self, given: Mapping[str, Any]) -> dict[str, Any]:
        """`given`, with `""` for an argument the body requires and was not given, which its
        judge refuses by name."""
        params = inspect.signature(self.body).parameters
        return {**{name: "" for name in self.takes() if params[name].default is params[name].empty},
                **given}

    def run(self, given: Mapping[str, Any], extra: Mapping[str, Any] | None = None
            ) -> dict[str, Any]:
        """The body on `filled(given)` and each of `extra` (what the server hands a body, never
        a caller: a progress line) that it takes keyword-only."""
        params = inspect.signature(self.body).parameters
        own = {k: v for k, v in (extra or {}).items()
               if k in params and params[k].kind is params[k].KEYWORD_ONLY}
        return self.body(**self.filled(given), **own)


def chosen(methods: Mapping[str, Method], values: Mapping[str, Any]
           ) -> tuple[Method, dict[str, Any]]:
    """The method `values["method"]` names and the arguments it was given; one it does not take
    is refused `bad_argument`."""
    name = values.get("method")
    vocab.one_of("method", name, tuple(methods))
    method = methods[str(name)]
    given = {k: v for k, v in values.items() if k != "method" and v is not None and v != ""}
    if why := strict.method_refusal(str(name), given, method.takes()):
        raise Invalid("bad_argument", why)
    return method, given


def dispatch(methods: Mapping[str, Method], values: Mapping[str, Any],
             extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The chosen method run on the arguments it was given (`Method.run` says what `extra`
    is)."""
    method, given = chosen(methods, values)
    return method.run(given, extra)


def fold_check(methods: Mapping[str, Method]) -> Callable[..., None]:
    """The fold's pre-gate judge: the chosen method's, on the arguments it was given."""
    def check(**values: Any) -> None:
        method, given = chosen(methods, values)
        method.check(**method.filled(given))
    return check


def fold_line(tool: str, methods: Mapping[str, Method]) -> Summary:
    """The fold's summary line: `<tool> <method>: ` and the method's own."""
    def line(args: dict[str, Any], reply: dict[str, Any]) -> str:
        return f"{tool} {args['method']}: {methods[args['method']].line(args, reply)}"
    return line
