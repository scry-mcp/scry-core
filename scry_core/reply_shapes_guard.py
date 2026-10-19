"""One spelling, one shape: the guard that holds every reply a server's battery builds to it.

`reply_shapes` is the pytest plugin that runs it; this module is what it runs, imported only once
a session has begun (the plugin says why).

WHY IT IS IN THE CORE. The axis it judges is ACROSS servers: a word that means a count in one
server and a boolean in the other is a defect a reader of either one alone cannot see. Each
server's suite runs in its own repository and sees only itself, so the table below is what
spans them: both pin this package, and a row added here binds every server at its next pin.

HOW A SUITE LOADS IT: it does not. `reply_shapes` is a pytest plugin, registered through the
`pytest11` entry point, so pytest loads it in any environment that installs this package,
whatever the rootdir or the file asked for. What a suite does is DECLARE its anchors, the modules
the guard wraps, by name in its own pytest configuration:

    [tool.pytest.ini_options]
    reply_shapes_anchors = ["scry_core.reply_contract", "server"]

A run with no declaration is a usage error: a plugin that wraps nothing would report green having
judged nothing. A run that imported none of the declared modules (one file that touches no
server) judges nothing and says so in one line of its terminal summary, and is not an error: a
partial run is not the battery. A declared module that was imported and is not wrapped at the end
of the run is red, naming it.

WHY A FIXTURE AND NOT A TEST THAT LISTS THE TOOLS. A test enumerating "the tools that return
`truncated`" is a hand-written list, and a hand-written list goes quietly short: its green then
says nothing about whatever is not in it. Wrapping a function every reply goes through reaches
them all instead, with nobody enumerating anything. Coverage does not save the list either,
because coverage counts lines EXECUTED, not asserted.

WHY TEST-TIME ONLY. In production this would be a type check in the hot path forever, and a
future field that happened to be called `truncated` would crash a caller instead of being
discussed. Here it fails a run, which is where the discussion belongs.

"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from scry_core import reply_contract as contract
from scry_core.reply_shapes import ANCHORS_INI

# THE TABLE HOLDS A WORD ONLY ONCE TWO REPLIES HAVE SPELLED IT WITH TWO SHAPES: `truncated`, a
# count in one tool and a boolean in the rest, is a boolean everywhere. A row is added for a
# measured case, never for a guess.
SHAPES: dict[str, type] = {"truncated": bool}

Envelope = Callable[[dict[str, Any]], dict[str, Any]]
Summary = Callable[..., str]
Factory = Callable[[Any], Any]

# THE TWO ANCHORS, AND WHY ONE IS NOT ENOUGH.
#
# `check_envelope` is the contract's own guard, and it sees a reply at the moment it is BUILT,
# which is where a shape defect is easiest to read. It does not see everything: a tool may
# return a dict that never went through the envelope, and a tool may bolt fields onto a reply
# the envelope already passed.
#
# `_summary` is the TOOL BOUNDARY (`scry_core.boundary._summary`): the boundary calls it once per
# call with the reply COMPLETE, then hands that same reply back with the summary line in front.
# Nothing a caller receives gets past it, whatever route it took to be built.
#
# A DECLARED MODULE IS WRAPPED ON EACH ANCHOR IT DEFINES: the contract, a module that imported
# `check_envelope` under its own name (which binds a second name the wrap has to reach), a server.


def _judge(value: Any, where: str) -> None:
    """Every `SHAPES` key anywhere in a reply carries the shape the table gives it (`_shapes`),
    and no value anywhere is a null: a datum that could not be read or does not apply is the
    contract's `unavailable(why)` in its place, so a null is a reply that skipped the one
    spelling. The nulls are the contract's own walk (`nulls_in`), every one named at once."""
    _shapes(value, where)
    if found := contract.nulls_in(value):
        raise AssertionError(f"{where} carries a null at {', '.join(found)}; no reply carries a "
                             f"null: a datum that could not be read or does not apply is "
                             f"`unavailable(why)` in its place")


def _shapes(value: Any, where: str) -> None:
    """Every `SHAPES` key anywhere in `value` carries the shape the table gives it.

    IT WALKS, and does not stop at the top level: a key's shape is a property of the word,
    not of how deep in the reply it happens to sit, so a row inside `symbols` answering
    `truncated` with a number is the same defect as a top-level one. Walking finds those
    without anybody drawing a boundary by hand.

    `isinstance` is the right test for `bool` in the direction that matters: `isinstance(1,
    bool)` is False, so an int cannot pass for the boolean. (The reverse, a bool passing for an
    `int` row, is a trap the day this table grows one, and it belongs to that row's own case.)
    """
    if isinstance(value, dict):
        for key, sub in value.items():
            want = SHAPES.get(key)
            if want is not None and not isinstance(sub, want):
                raise AssertionError(
                    f"{where}[{key!r}] is {sub!r}, of type {type(sub).__name__}; every "
                    f"server holds `{key}` to {want.__name__} everywhere it is spelled. One word, "
                    f"one shape: give the other meaning its own name")
            _shapes(sub, f"{where}[{key!r}]")
    elif isinstance(value, list | tuple):
        # A TUPLE TOO, because the battery reads a reply BEFORE it is serialised: on the wire
        # everything is JSON and a tuple cannot survive, but in process it can, and in process
        # is where every case here looks.
        for i, sub in enumerate(value):
            _shapes(sub, f"{where}[{i}]")


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
    it."""
    def checked(name: str, args: dict[str, Any], reply: dict[str, Any], *rest: Any) -> str:
        _judge(reply, f"{name}'s reply")
        return original(name, args, reply, *rest)
    return checked


# ONE ROW PER ANCHOR, and it is a table rather than two call sites because the install loop
# and the teardown's late-import check both walk it: written twice, a third anchor would have
# to be added in two places and the one that was forgotten would go quiet rather than red.
# Each row is the attribute, how to wrap it, and the probe that proves the wrap landed where the
# code reads it.
ANCHORS: tuple[tuple[str, Factory, tuple[Any, ...]], ...] = (
    ("check_envelope", _wrap_envelope, ({"status": "ok"},)),
    ("_summary", _wrap_summary,
     ("probe", {}, {"status": "INVALID", "code": "bad_argument", "message": "probe"})),
)

#: What the run's fixture found, for the terminal summary to report.
_JUDGED = pytest.StashKey[list[str]]()


def declared(config: pytest.Config) -> list[str]:
    """The suite's declared anchors, or a usage error when it declares none."""
    names: list[str] = config.getini(ANCHORS_INI)
    if not names:
        raise pytest.UsageError(
            f"the shape guard (scry_core.reply_shapes) has no `{ANCHORS_INI}` to wrap: declare "
            "the modules whose replies it judges in [tool.pytest.ini_options], or this run "
            "would report green having judged nothing")
    return names


def summary_line(config: pytest.Config) -> str:
    """The terminal summary's one line for a run that imported no declared anchor, else empty."""
    judged = config.stash.get(_JUDGED, None)
    if judged is None or judged:
        return ""
    return (f"reply_shapes: none of {', '.join(declared(config))} was imported, so this run "
            "judged no reply's shape")


def one_word_one_shape(config: pytest.Config) -> Iterator[None]:
    """Wrap each declared module that is imported, on each anchor it defines; a wrap that does
    not take is an error.

    THE PATCH IS VERIFIED, NOT ASSUMED. A patch that silently matched nothing is
    indistinguishable from a battery with no shape defect in it, and that is the false green
    this repository refuses everywhere else: each wrap is fired once here, on a probe reply,
    and a wrap that does not fire is a broken instrument rather than a pass.

    AND THE LATE IMPORT IS CLOSED AT THE OTHER END. This fixture runs after collection, so a
    declared module imported inside a test body afterwards would build its replies outside the
    wrap. The teardown looks again and fails naming it, so that hole is a red line rather than a
    silence.
    """
    anchors = declared(config)
    fired: set[tuple[str, str]] = set()
    originals: dict[tuple[str, str], tuple[Any, Any]] = {}
    installed: list[Any] = []
    judged: list[str] = []
    config.stash[_JUDGED] = judged

    try:
        for name in anchors:
            mod = sys.modules.get(name)
            if mod is None:
                continue
            held = [row for row in ANCHORS if callable(getattr(mod, row[0], None))]
            if not held:
                raise RuntimeError(f"{ANCHORS_INI} names {name}, which defines none of "
                                   f"{', '.join(a for a, _, _ in ANCHORS)}: it is no anchor")
            for attr, factory, probe_args in held:
                key = (name, attr)
                original = getattr(mod, attr)
                originals[key] = (mod, original)
                # Built once, not per call: every reply of the battery passes through it.
                wrapped = factory(original)

                def probe(*a: Any, _key: tuple[str, str] = key, _w: Any = wrapped) -> Any:
                    fired.add(_key)
                    return _w(*a)

                setattr(mod, attr, probe)
                installed.append(probe)
                # THROUGH THE MODULE ATTRIBUTE AND NOT THROUGH `probe`: calling the closure
                # proves the closure works and says nothing about whether the assignment above
                # landed where the code reads it, which is the only thing this check is for. The
                # summary's probe reply declares itself INVALID and names no boundary, so it reaches
                # no tool's line and touches no state.
                getattr(mod, attr)(*probe_args)
                if key not in fired:
                    raise RuntimeError(f"the shape guard did not take on {name}.{attr}: this run "
                                       f"would have judged nothing and reported green")
                judged.append(f"{name}.{attr}")
    except BaseException:
        # A failed install leaves nothing wrapped: the modules hand back their originals.
        _restore(originals)
        raise
    yield
    # By identity, not `id()`, which a freed object's successor can be handed.
    late = [f"{name}.{attr}"
            for name in anchors if (mod := sys.modules.get(name)) is not None
            for attr, _, _ in ANCHORS if callable(getattr(mod, attr, None))
            and not any(getattr(mod, attr) is p for p in installed)]
    _restore(originals)
    if late:
        raise RuntimeError(f"a declared anchor was imported after the shape guard was installed "
                           f"and escaped it: {late}. Every reply built through it went unjudged")


def _restore(originals: dict[tuple[str, str], tuple[Any, Any]]) -> None:
    # On the module object that was patched, which a test may have dropped from `sys.modules`.
    for (_name, attr), (mod, original) in originals.items():
        setattr(mod, attr, original)
