"""One spelling, one shape: the guard that holds every reply a server's battery builds to it.

WHY IT IS IN THE CORE. The axis it judges is ACROSS servers: a word that means a count in one
server and a boolean in the other is a defect a reader of either one alone cannot see. Each
server's suite runs in its own repository and sees only itself, so the table below is what
spans them: both pin this package, and a row added here binds every server at its next pin.

HOW A SUITE LOADS IT: its root `conftest.py` imports `one_word_one_shape`, which makes the
session fixture below autouse for the whole run. A run whose rootdir is not that root reads no
such conftest and judges nothing here, which is why the battery's invocation is the verdict and
a partial run is not.

WHY A FIXTURE AND NOT A TEST THAT LISTS THE TOOLS. A test enumerating "the tools that return
`truncated`" is a hand-written list, and a hand-written list goes quietly short: its green then
says nothing about whatever is not in it. Wrapping a function every reply goes through reaches
them all instead, with nobody enumerating anything. Coverage does not save the list either,
because coverage counts lines EXECUTED, not asserted.

AND "EVERY REPLY" IS A CLAIM THAT HAD TO BE EARNED: it takes TWO anchors, and which two, and
why one is not enough, is written beside them below.

WHY TEST-TIME ONLY. In production this would be a type check in the hot path forever, and a
future field that happened to be called `truncated` would crash a caller instead of being
discussed. Here it fails a run, which is where the discussion belongs.

"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any

import pytest

# THE TABLE, SEEDED WITH THE ONE ROW THERE IS EVIDENCE FOR. `truncated` was a COUNT in
# `symbols_load` and a boolean everywhere else, which is the defect this table was built to
# stop coming back; the boolean is the shape that won, so the boolean is what is written here.
# A second row needs its own measured case: the shape of the table is what makes adding one
# cheap, not an invitation to guess at more.
SHAPES: dict[str, type] = {"truncated": bool}

Envelope = Callable[[dict[str, Any]], dict[str, Any]]
Summary = Callable[[str, dict[str, Any], dict[str, Any]], str]
Finder = Callable[[], dict[str, ModuleType]]
Factory = Callable[[Any], Any]

# THE TWO ANCHORS, AND WHY ONE IS NOT ENOUGH.
#
# `check_envelope` is the contract's own guard, and it sees a reply at the moment it is BUILT,
# which is where a shape defect is easiest to read. It does not see everything: a tool may
# return a dict that never went through the envelope, and a tool may bolt fields onto a reply
# the envelope already passed. Both shapes are live in the servers, in the session lifecycle
# tools, which are precisely the ones that compose a reply by hand.
#
# `_summary` is the TOOL BOUNDARY: the servers' decorator calls it once per call with the
# reply COMPLETE, then hands that same reply back with the summary line in front. Nothing a
# caller receives gets past it, whatever route it took to be built.
#
# NEITHER IS NAMED, BOTH ARE FOUND. The contract is whatever loaded module defines
# `check_envelope`; a server is whatever defines both the `tool` decorator and the `_summary` its
# wrapper calls. Searching lands on what is actually loaded,
# can never name a module that is not there, and does not go short the day a third one arrives.


def _judge(value: Any, where: str) -> None:
    """Every `SHAPES` key anywhere in a reply carries the shape the table gives it.

    IT WALKS, and does not stop at the top level: a key's shape is a property of the word,
    not of how deep in the reply it happens to sit, so a row inside `symbols` answering
    `truncated` with a number is the same defect as a top-level one. Walking finds those
    without anybody drawing a boundary by hand.

    `isinstance` is the right test for `bool` in the direction that matters: `isinstance(1,
    bool)` is False, so an int cannot pass for the boolean. (The reverse -- a bool passing
    for an `int` row -- is a trap the day this table grows one, and it belongs to that row's
    own case.)
    """
    if isinstance(value, dict):
        for key, sub in value.items():
            want = SHAPES.get(key)
            if want is not None and not isinstance(sub, want):
                raise AssertionError(
                    f"{where}[{key!r}] is {sub!r}, of type {type(sub).__name__}; every "
                    f"server holds `{key}` to {want.__name__} everywhere it is spelled. One word, "
                    f"one shape: give the other meaning its own name")
            _judge(sub, f"{where}[{key!r}]")
    elif isinstance(value, list | tuple):
        # A TUPLE TOO, because the battery reads a reply BEFORE it is serialised: on the wire
        # everything is JSON and a tuple cannot survive, but in process it can, and in process
        # is where every case here looks.
        for i, sub in enumerate(value):
            _judge(sub, f"{where}[{i}]")


def _wrap_envelope(original: Envelope) -> Envelope:
    """The contract's own guard runs FIRST and unchanged, so a malformed refusal still raises
    the `TypeError` its own cases assert; the shape table is judged after it, on a reply the
    contract has already accepted."""
    def checked(reply: dict[str, Any]) -> dict[str, Any]:
        out = original(reply)
        _judge(out, "reply")
        return out
    return checked


def _wrap_summary(original: Summary) -> Summary:
    """The reply as the CALLER receives it, judged before the summary line is composed from
    it. This anchor is what makes the claim above true rather than nearly true."""
    def checked(name: str, args: dict[str, Any], reply: dict[str, Any]) -> str:
        _judge(reply, f"{name}'s reply")
        return original(name, args, reply)
    return checked


def _contract_modules() -> dict[str, ModuleType]:
    """Wherever the reply contract is loaded, under whatever module name."""
    return {name: mod for name, mod in list(sys.modules.items())
            if hasattr(mod, "check_envelope")}


def _server_modules() -> dict[str, ModuleType]:
    """The MCP servers, found by what they ARE and not by their names: a module that defines
    both the `tool` decorator and the `_summary` its wrapper calls IS one. A list of two names
    would be a list, and a list is what goes short the day a third server arrives."""
    return {name: mod for name, mod in list(sys.modules.items())
            if callable(getattr(mod, "tool", None))
            and callable(getattr(mod, "_summary", None))}


# ONE ROW PER ANCHOR, and it is a table rather than two call sites because the install loop
# and the teardown's late-import check both walk it: written twice, a third anchor would have
# to be added in two places and the one that was forgotten would go quiet rather than red.
# Each row is where to find it, what it is called, how to wrap it, and the probe that proves
# the wrap landed where the code reads it.
ANCHORS: tuple[tuple[Finder, str, Factory, tuple[Any, ...]], ...] = (
    (_contract_modules, "check_envelope", _wrap_envelope, ({"status": "ok"},)),
    (_server_modules, "_summary", _wrap_summary,
     ("probe", {}, {"status": "INVALID", "code": "bad_argument", "message": "probe"})),
)


@pytest.fixture(scope="session", autouse=True)
def one_word_one_shape() -> Iterator[None]:
    """Wrap `check_envelope` and each server's `_summary` wherever they live, and refuse to be a
    green that examined nothing.

    THE PATCH IS VERIFIED, NOT ASSUMED. A patch that silently matched nothing is
    indistinguishable from a battery with no shape defect in it, and that is the false green
    this repository refuses everywhere else: each wrap is fired once here, on a probe reply,
    and a wrap that does not fire is a broken instrument rather than a pass.

    AND THE LATE IMPORT IS CLOSED AT THE OTHER END. This fixture runs after collection, so a
    module imported inside a test body afterwards would build its replies outside the wrap. The
    teardown looks again and fails naming any `check_envelope` that is not one of ours, so that
    hole is a red line rather than a silence.
    """
    fired: set[tuple[str, str]] = set()
    originals: dict[tuple[str, str], Any] = {}
    installed: list[Any] = []

    def install(finder: Finder, attr: str, factory: Factory,
                probe_args: tuple[Any, ...]) -> None:
        for name, mod in finder().items():
            key = (name, attr)
            original = getattr(mod, attr)
            originals[key] = original
            # THE WRAPPER IS BUILT ONCE, out here, and not per call: these sit on the path
            # every reply of the battery takes, and rebuilding a closure for each of them
            # would be a cost paid thousands of times to compute the same function.
            wrapped = factory(original)

            def probe(*a: Any, _key: tuple[str, str] = key, _w: Any = wrapped) -> Any:
                fired.add(_key)
                return _w(*a)

            setattr(mod, attr, probe)
            installed.append(probe)
            # THROUGH THE MODULE ATTRIBUTE AND NOT THROUGH `probe`: calling the closure
            # proves the closure works and says nothing about whether the assignment above
            # landed where the code reads it, which is the only thing this check is for. The
            # summary's probe reply declares itself INVALID because each server's `_summary`
            # answers a refusal from its first lines, so it cannot reach a tool-specific branch
            # or touch state.
            getattr(mod, attr)(*probe_args)
            if key not in fired:
                raise RuntimeError(f"the shape guard did not take on {name}.{attr}: this run "
                                   f"would have judged nothing and reported green")

    for anchor in ANCHORS:
        install(*anchor)
    yield
    # BY IDENTITY against the objects installed, not by `id()`: an id is a number that a
    # freed object's successor can be handed, and identity is the question actually being
    # asked -- is this attribute one of the ones put there above?
    late = [f"{name}.{attr}"
            for finder, attr, _, _ in ANCHORS
            for name, mod in finder().items()
            if not any(getattr(mod, attr) is p for p in installed)]
    for (name, attr), original in originals.items():
        setattr(sys.modules[name], attr, original)
    if late:
        raise RuntimeError(f"an anchor was imported after the shape guard was installed and "
                           f"escaped it: {late}. Every reply built through it went unjudged")
