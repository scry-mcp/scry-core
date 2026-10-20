"""A step judged against its tool's signature: the refusals both servers' lists hold every step to,
and the arguments handed on to the server's own value checks."""

from __future__ import annotations

from typing import Annotated, Any

import pytest

from scry_core import steps


def tool(count: int, name: str = "", flag: bool = False, rate: float = 1.0,
         maybe: int | None = None, wide: int | str | None = None,
         sized: Annotated[int, "a schema half"] = 1, ctx: Any = None) -> dict[str, Any]:
    return {}


@pytest.mark.parametrize(("args", "said"), [
    ({"count": True}, "count is an integer; got True"),
    ({"count": "3"}, "count is an integer; got '3'"),
    ({"count": 1, "name": 5}, "name is a string; got 5"),
    ({"count": 1, "flag": 1}, "flag is a boolean; got 1"),
    ({"count": 1, "rate": "x"}, "rate is a number; got 'x'"),
    ({"count": 1, "maybe": "2"}, "maybe is an integer; got '2'"),
    ({"count": 1, "sized": "4"}, "sized is an integer; got '4'"),
])
def test_a_scalar_of_the_wrong_type_is_named(args: dict[str, Any], said: str) -> None:
    assert steps.wrong_type(tool, args) == said


@pytest.mark.parametrize("args", [
    {"count": 1}, {"count": 1, "maybe": None}, {"count": 1, "rate": 2},
    {"count": 1, "wide": "0x10"}, {"count": 1, "wide": None}, {"count": 1, "sized": 4}])
def test_what_the_signature_allows_passes(args: dict[str, Any]) -> None:
    assert steps.wrong_type(tool, args) is None


def test_annotated_is_judged_as_the_type_it_wraps() -> None:
    assert steps.unannotated("Annotated[int, x] | None") == "int | None"
    assert steps.unannotated("list[Annotated[str, f(a, [b])]]") == "list[str]"


def test_a_step_is_refused_for_ctx_a_name_the_tool_lacks_and_a_bad_recorded_check() -> None:
    def said(step: dict[str, Any]) -> dict[str, Any] | None:
        return steps.judge(tool, step)[0]
    assert said({"op": "tool", "count": 1}) is None
    ctx = said({"op": "tool", "count": 1, "ctx": 0})
    assert ctx is not None and "`ctx`" in ctx["message"], ctx
    named = said({"op": "tool", "cuont": 1})
    assert named is not None and "has bad arguments" in named["message"], named
    assert "`takes` names `tool`'s" in named["message"], named
    assert named["takes"] == ["count", "name", "flag", "rate", "maybe", "wide", "sized"], named
    recorded = said({"op": "tool", "count": 1, "recorded": 5})
    assert recorded is not None and recorded["code"] == "bad_argument", recorded
    typed = said({"op": "tool", "count": "x"})
    assert typed is not None and typed["message"] == "count is an integer; got 'x'", typed


def test_the_bind_refusal_names_the_op_the_step_named() -> None:
    """The step's `op` is what the caller wrote: a double or a wrapper under another name is
    still named by it."""
    refused, _ = steps.judge(lambda count: {}, {"op": "run_for", "cuont": 1})
    assert refused is not None and "`takes` names `run_for`'s" in refused["message"], refused


def test_a_servers_conversion_reaches_the_type_judge_and_the_value_checks() -> None:
    def integral(params: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        return {n: int(v) if isinstance(v, float) and v.is_integer() else v
                for n, v in args.items()}
    refusal, args = steps.judge(tool, {"op": "tool", "count": 6.0}, prepare=integral)
    assert refusal is None and args == {"count": 6}
    unconverted, _ = steps.judge(tool, {"op": "tool", "count": 6.0})
    assert unconverted is not None and "count is an integer" in unconverted["message"]
