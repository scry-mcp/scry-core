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
    """One `method` of a fold: its body, its pre-gate judge and its summary line (the reply
    alone; `fold_line` adds the tool and the method)."""

    body: Callable[..., dict[str, Any]]
    check: Callable[..., None]
    line: Callable[[dict[str, Any]], str]

    def takes(self) -> list[str]:
        return list(inspect.signature(self.body).parameters)

    def run(self, given: Mapping[str, Any]) -> dict[str, Any]:
        """The body on `given`, an argument it requires and was not given passed as `""`, which
        its judge refuses by name."""
        required = {name: "" for name, p in inspect.signature(self.body).parameters.items()
                    if p.default is p.empty}
        return self.body(**{**required, **given})


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


def fold_check(methods: Mapping[str, Method]) -> Callable[..., None]:
    """The fold's pre-gate judge: the chosen method's, on the arguments it was given."""
    def check(**values: Any) -> None:
        method, given = chosen(methods, values)
        method.check(**given)
    return check


def fold_line(tool: str, methods: Mapping[str, Method]) -> Summary:
    """The fold's summary line: `<tool> <method>: ` and the method's own."""
    def line(args: dict[str, Any], reply: dict[str, Any]) -> str:
        return f"{tool} {args['method']}: {methods[args['method']].line(reply)}"
    return line
