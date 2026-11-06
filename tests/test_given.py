"""The arguments a call was given, before the schema fills the defaults: a profile fills only
the names the caller did not give."""

from __future__ import annotations

import asyncio
from typing import Any

from scry_core import given
from scry_core.envelope import Envelope


def _server(seen: list[Any]) -> Envelope:
    """An envelope whose one tool records the names its call was given."""
    env = Envelope("t", instructions="an instruction",
                   refusal=lambda name, arguments, cause: {"status": "INVALID"})

    @env.tool()
    def peek(x: int = 1, y: str = "d") -> dict[str, Any]:
        """Peek at nothing."""
        seen.append(given.names())
        return {"status": "ok"}

    return env


def test_outside_a_call_no_names_are_known() -> None:
    assert given.names() is None


def test_a_tool_sees_the_names_the_client_sent_and_not_the_defaults() -> None:
    seen: list[Any] = []
    asyncio.run(_server(seen).call_tool("peek", {"x": 3}))
    assert seen == [frozenset({"x"})]


def test_a_client_that_sent_nothing_named_has_given_nothing() -> None:
    seen: list[Any] = []
    asyncio.run(_server(seen).call_tool("peek", {}))
    assert seen == [frozenset()]


def test_the_names_end_with_the_call() -> None:
    seen: list[Any] = []
    env = _server(seen)
    asyncio.run(env.call_tool("peek", {"x": 3}))
    assert given.names() is None
