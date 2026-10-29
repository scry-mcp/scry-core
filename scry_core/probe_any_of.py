"""Expected-value algebra for probe tasks: strict JSON equality, `{"any_of": [...]}`
alternatives and `{"regex": {...}}`, a pattern judged by the lines of a captured text it selects."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any


def is_any_of(value: Any) -> bool:
    """Whether `value` is an `{"any_of": [...]}` node."""
    return isinstance(value, dict) and set(value) == {"any_of"}


def is_regex(value: Any) -> bool:
    """Whether `value` is a `{"regex": {"lines", "hits", "example"}}` node: a pattern is right when
    it selects every one of the `hits` (indices) among `lines` and, beside them, only lines the
    optional `also` allows, whatever its spelling."""
    return isinstance(value, dict) and set(value) == {"regex"}


def selects(node: dict[str, Any], pattern: Any) -> bool:
    """Whether `pattern` selects all the node's hits among its lines, and nothing but `also`."""
    spec = node["regex"]
    if not isinstance(pattern, str):
        return False
    try:
        found = re.compile(pattern)
    except re.error:
        return False
    chosen = {i for i, line in enumerate(spec["lines"]) if found.search(line)}
    hits = set(spec["hits"])
    return hits <= chosen <= hits | set(spec.get("also", []))


def regex_problems(value: Any) -> list[str]:
    """What is wrong with the `regex` nodes inside `value`, each as a sentence."""
    if is_regex(value):
        spec = value["regex"]
        lines = spec.get("lines") if isinstance(spec, dict) else None
        if not isinstance(lines, list) or not lines or not all(isinstance(x, str) for x in lines):
            return ["`lines` is a non-empty list of strings"]
        hits = spec.get("hits")
        if not isinstance(hits, list) or not all(type(h) is int for h in hits):
            return ["`hits` is a list of line indices"]
        also = spec.get("also", [])
        if not isinstance(also, list) or not all(type(a) is int for a in also):
            return ["`also` is a list of line indices"]
        out = [f"hit {h} is not a line of {len(lines)}" for h in [*hits, *also]
               if not 0 <= h < len(lines)]
        if set(hits) & set(also):
            out.append("a line is both a hit and allowed beside the hits")
        held = {"regex": {**spec, "hits": [h for h in hits if 0 <= h < len(lines)],
                          "also": [a for a in also if 0 <= a < len(lines)]}}
        if not selects(held, spec.get("example")):
            out.append("its own example does not select its hits")
        return out
    if isinstance(value, dict):
        return [p for v in value.values() for p in regex_problems(v)]
    if isinstance(value, list):
        return [p for v in value for p in regex_problems(v)]
    return []


def same(a: Any, b: Any) -> bool:
    """JSON equality: `True` is not `1`, `5` is `5.0`."""
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
    if is_regex(expected):
        return selects(expected, got)
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(matches(expected[k], got[k]) for k in got)
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(
            matches(e, g) for e, g in zip(expected, got, strict=True))
    return same(expected, got)


def concrete(expected: Any) -> Any:
    """The expected value with each `any_of` replaced by its first alternative."""
    if is_any_of(expected):
        return concrete(expected["any_of"][0])
    if is_regex(expected):
        return expected["regex"]["example"]
    if isinstance(expected, dict):
        return {k: concrete(v) for k, v in expected.items()}
    if isinstance(expected, list):
        return [concrete(v) for v in expected]
    return expected


def calls(args: Any) -> list[Any]:
    """The whole calls a task accepts."""
    return list(args["any_of"]) if is_any_of(args) else [args]


def leaves(value: Any) -> Iterator[Any]:
    """Every scalar of `value`, through every alternative of an `any_of`; a `regex` node's lines
    are data, not words the model was told."""
    if is_regex(value):
        return
    if isinstance(value, dict):
        for v in (value["any_of"] if is_any_of(value) else value.values()):
            yield from leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from leaves(v)
    else:
        yield value


def has_empty_any_of(value: Any) -> bool:
    """Whether any `any_of` in `value` is not a non-empty list."""
    if is_any_of(value):
        held = value["any_of"]
        return not isinstance(held, list) or not held or any(has_empty_any_of(v) for v in held)
    if isinstance(value, dict):
        return any(has_empty_any_of(v) for v in value.values())
    if isinstance(value, list):
        return any(has_empty_any_of(v) for v in value)
    return False
