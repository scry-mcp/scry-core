"""Test-time guard: every reply a server's battery builds holds one shape per word and its tool's
declared model (`scry_core.reply_schema`). The `reply_shapes` pytest plugin runs it.

A suite declares the modules to wrap:

    [tool.pytest.ini_options]
    reply_shapes_anchors = ["scry_core.reply_contract", "scry_core.boundary"]

No declaration is a usage error; a run importing none of them says it judged nothing. Test-time
only: in production a new field called `truncated` would crash a caller.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from scry_core import reply_schema
from scry_core.reply_shapes import ANCHORS_INI

# A row is added only once two replies have spelled a word with two shapes, never for a guess.
SHAPES: dict[str, type] = {"truncated": bool}

Envelope = Callable[[dict[str, Any]], dict[str, Any]]
Summary = Callable[..., str]
Factory = Callable[[Any], Any]

# `check_envelope` misses replies that skipped it; `_summary` (`scry_core.boundary`) sees all.


def _judge(value: Any, where: str) -> None:
    """Hold `SHAPES` keys to their shape and refuse any null."""
    nulls: list[str] = []
    _walk(value, where, nulls)
    if nulls:
        raise AssertionError(f"a null at {', '.join(nulls)}; no reply carries a null: a datum "
                             f"that could not be read or does not apply is `unavailable(why)` "
                             f"in its place")


def _walk(value: Any, where: str, nulls: list[str]) -> None:
    """Check `SHAPES` keys at any depth and collect null paths.

    A bool would pass for an `int` row, a trap for the day the table has one.
    """
    if value is None:
        nulls.append(where)
    elif isinstance(value, dict):
        for key, sub in value.items():
            want = SHAPES.get(key)
            if want is not None and not isinstance(sub, want):
                raise AssertionError(
                    f"{where}[{key!r}] is {sub!r}, of type {type(sub).__name__}; every "
                    f"server holds `{key}` to {want.__name__} everywhere it is spelled. One word, "
                    f"one shape: give the other meaning its own name")
            _walk(sub, f"{where}[{key!r}]", nulls)
    elif isinstance(value, list | tuple):
        # Tuples too: the battery reads replies before serialisation.
        for i, sub in enumerate(value):
            _walk(sub, f"{where}[{i}]", nulls)


def _wrap_envelope(original: Envelope) -> Envelope:
    """The contract's guard runs first, so a malformed refusal still raises its `TypeError`."""
    def checked(reply: dict[str, Any]) -> dict[str, Any]:
        out = original(reply)
        _judge(out, "reply")
        return out
    return checked


def _wrap_summary(original: Summary) -> Summary:
    """Judge the complete reply against the table and the tool's declared model."""
    def checked(name: str, args: dict[str, Any], reply: dict[str, Any], *rest: Any) -> str:
        _judge(reply, f"{name}'s reply")
        try:
            reply_schema.check(name, reply)
        except ValidationError as e:
            raise AssertionError(f"{name}'s reply is not the shape its model declares, so its "
                                 f"published schema would lie: {e}. Name the field in the "
                                 f"tool's reply model, or give it the declared type") from None
        except reply_schema.MissingFields as e:
            raise AssertionError(f"{e}. A field that always comes is built on every `ok` path "
                                 f"(a datum not read is `unavailable(why)`); one that comes "
                                 f"only sometimes is `When(...)` in the model") from None
        return original(name, args, reply, *rest)
    return checked


# Each row: attribute, wrapper, probe args.
ANCHORS: tuple[tuple[str, Factory, tuple[Any, ...]], ...] = (
    ("check_envelope", _wrap_envelope, ({"status": "ok"},)),
    ("_summary", _wrap_summary,
     ("probe", {}, {"status": "INVALID", "code": "bad_argument", "message": "probe"})),
)

#: What the run's fixture found, for the terminal summary to report.
_JUDGED = pytest.StashKey[list[str]]()


def declared(config: pytest.Config) -> list[str]:
    """The declared anchors; a usage error when none, or one no import can find (a misspelling)."""
    names: list[str] = config.getini(ANCHORS_INI)
    if not names:
        raise pytest.UsageError(
            f"the shape guard (scry_core.reply_shapes) has no `{ANCHORS_INI}` to wrap: declare "
            "the modules whose replies it judges in [tool.pytest.ini_options], or this run "
            "would report green having judged nothing. For example:\n"
            f'    {ANCHORS_INI} = ["scry_core.reply_contract", "scry_core.boundary"]')
    if lost := [name for name in names if not _findable(name)]:
        raise pytest.UsageError(
            f"`{ANCHORS_INI}` names {', '.join(lost)}, which no import can find: a misspelt "
            "anchor wraps nothing, and the run would read as one that imported none")
    return names


def _findable(name: str) -> bool:
    try:
        return name in sys.modules or importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def summary_line(config: pytest.Config) -> str:
    """The terminal line for a run that imported no declared anchor, else empty."""
    judged = config.stash.get(_JUDGED, None)
    if judged is None or judged:
        return ""
    return (f"reply_shapes: none of {', '.join(declared(config))} was imported, so this run "
            "judged no reply's shape")


def one_word_one_shape(config: pytest.Config) -> Iterator[None]:
    """Wrap each imported declared module's anchors, firing each wrap once on a probe.

    A patch that matched nothing would read as a clean battery. The teardown fails naming a
    declared module imported after installation.
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
                wrapped = factory(original)

                def probe(*a: Any, _key: tuple[str, str] = key, _w: Any = wrapped) -> Any:
                    fired.add(_key)
                    return _w(*a)

                setattr(mod, attr, probe)
                installed.append(probe)
                # Through the module attribute: proves the assignment landed where code reads it.
                getattr(mod, attr)(*probe_args)
                if key not in fired:
                    raise RuntimeError(f"the shape guard did not take on {name}.{attr}: this run "
                                       f"would have judged nothing and reported green")
                judged.append(f"{name}.{attr}")
    except BaseException:
        _restore(originals)
        raise
    yield
    # By identity: a freed object's `id()` can be reused.
    late = [f"{name}.{attr}"
            for name in anchors if (mod := sys.modules.get(name)) is not None
            for attr, _, _ in ANCHORS if callable(getattr(mod, attr, None))
            and not any(getattr(mod, attr) is p for p in installed)]
    _restore(originals)
    if late:
        raise RuntimeError(f"a declared anchor was imported after the shape guard was installed "
                           f"and escaped it: {late}. Every reply built through it went unjudged; "
                           "import it in the suite's conftest.py, so it exists when the guard "
                           "is installed")


def _restore(originals: dict[tuple[str, str], tuple[Any, Any]]) -> None:
    # On the patched module object, which a test may have dropped from `sys.modules`.
    for (_name, attr), (mod, original) in originals.items():
        setattr(mod, attr, original)
