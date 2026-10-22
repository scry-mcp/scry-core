"""The ALGEBRA of a probe task's expected values: JSON equality that keeps a bool from passing
for a number, and `{"any_of": [...]}`, a set of alternatives accepted at any depth of an
expected call. The probe judges an answer with it (`scry_core.probe`) and a capture is compared
with its task through it (`scry_core.probe_captures`).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def is_any_of(value: Any) -> bool:
    """Whether `value` is `{"any_of": [...]}`, a set of alternatives a task accepts."""
    return isinstance(value, dict) and set(value) == {"any_of"}


def same(a: Any, b: Any) -> bool:
    """JSON equality that does not let `True` pass for `1`, and does let `5` pass for `5.0`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and bool(a == b)


def matches(expected: Any, got: Any) -> bool:
    """`same`, with `{"any_of": [...]}` accepted at any depth of the expected value."""
    if is_any_of(expected):
        return any(matches(e, got) for e in expected["any_of"])
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(matches(expected[k], got[k]) for k in got)
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(
            matches(e, g) for e, g in zip(expected, got, strict=True))
    return same(expected, got)


def concrete(expected: Any) -> Any:
    """The expected value with each `any_of` taken at its first alternative: a call to test."""
    if is_any_of(expected):
        return concrete(expected["any_of"][0])
    if isinstance(expected, dict):
        return {k: concrete(v) for k, v in expected.items()}
    if isinstance(expected, list):
        return [concrete(v) for v in expected]
    return expected


def calls(args: Any) -> list[Any]:
    """The whole calls a task accepts: one, or each of an `any_of` of calls."""
    return list(args["any_of"]) if is_any_of(args) else [args]


def leaves(value: Any) -> Iterator[Any]:
    """Every scalar of `value`, through dicts, lists and each alternative of an `any_of`."""
    if isinstance(value, dict):
        for v in (value["any_of"] if is_any_of(value) else value.values()):
            yield from leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from leaves(v)
    else:
        yield value


def has_empty_any_of(value: Any) -> bool:
    """Whether an `any_of` anywhere in `value` is not a list of at least one alternative."""
    if is_any_of(value):
        held = value["any_of"]
        return not isinstance(held, list) or not held or any(has_empty_any_of(v) for v in held)
    if isinstance(value, dict):
        return any(has_empty_any_of(v) for v in value.values())
    if isinstance(value, list):
        return any(has_empty_any_of(v) for v in value)
    return False
