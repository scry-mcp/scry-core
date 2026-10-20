"""CLOSED VOCABULARIES AND RANGES in the input schema (`enum`, `pattern`, `minimum`, `maximum`),
published from the same constants the server's judge reads, so a client sees the words and the
bounds where it builds the call; `one_of` gives a word outside them one sentence on every tool of
both servers. The schema half is never validated by the SDK: the judge refuses, in the server's
own envelope, so a refusal never reads as pydantic's.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scry_core.reply_contract import Invalid

#: The words of a closed vocabulary: names, or integers such as a write's byte lengths.
Words = tuple[str, ...] | tuple[int, ...]


def enum(options: Words) -> Any:
    """The schema half of a closed vocabulary, for `Annotated[str, enum(TUPLE)]` (or `int`, or a
    list's item)."""
    return Field(json_schema_extra={"enum": list(options)})


def folded(options: tuple[str, ...]) -> Any:
    """The schema half of a vocabulary the server takes in ANY case: a `pattern` whose
    alternatives are the canonical words, each letter in either case, because an `enum` of the
    canonical spelling would refuse in a validating client what the server takes."""
    def any_case(word: str) -> str:
        return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else _escaped(c) for c in word)
    return Field(json_schema_extra={"pattern": f"^({'|'.join(any_case(w) for w in options)})$"})


def _escaped(c: str) -> str:
    """One character as a pattern matches it literally."""
    return f"\\{c}" if c in r"\^$.|?*+()[]{}" else c


def bounds(lo: float, hi: float, *, open_lo: bool = False) -> Any:
    """The schema half of a range, `minimum` (`exclusiveMinimum` when `open_lo`, a bound the
    judge refuses itself, as a wait's 0) and `maximum`."""
    low = "exclusiveMinimum" if open_lo else "minimum"
    return Field(json_schema_extra={low: lo, "maximum": hi})


def one_of(name: str, value: object, options: Words, tail: str = "") -> None:
    """A scalar held to a closed vocabulary: `mode is one of (...); got 'x'`, one sentence for
    every scalar closed vocabulary a tool argument has, `tail` added after it; a list's items
    are judged by the list's own sentence. A bool is refused even where 1 is a word, since `True`
    equals 1 and is never what a caller meant."""
    if isinstance(value, bool) or value not in options:
        raise Invalid("bad_argument", f"{name} is one of {options}; got {value!r}{tail}")
