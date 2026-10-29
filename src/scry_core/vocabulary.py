"""A closed vocabulary or a range, judged and described from one tuple, and the one wait ceiling."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from scry_core.reply_contract import Invalid

#: The words of a closed vocabulary: names, or integers such as a write's byte lengths.
Words = tuple[str, ...] | tuple[int, ...]


def enum(options: Words) -> Any:
    return Field(json_schema_extra={"enum": list(options)})


def folded(options: tuple[str, ...]) -> Any:
    """A case-insensitive `pattern`: an `enum` would make a validating client refuse what the server
    takes."""
    def any_case(word: str) -> str:
        return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else _escaped(c) for c in word)
    return Field(json_schema_extra={"pattern": f"^({'|'.join(any_case(w) for w in options)})$"})


def _escaped(c: str) -> str:
    return f"\\{c}" if c in r"\^$.|?*+()[]{}" else c


def bounds(lo: float, hi: float, *, open_lo: bool = False) -> Any:
    low = "exclusiveMinimum" if open_lo else "minimum"
    return Field(json_schema_extra={low: lo, "maximum": hi})


# The server answers one call at a time, so an unbounded wait would hold every other call.
WAIT_MAX_S = 600.0
#: `WAIT_FROM_ZERO_BOUNDS` is for a wait whose 0 means no wait.
WAIT_BOUNDS = bounds(0, WAIT_MAX_S, open_lo=True)
WAIT_FROM_ZERO_BOUNDS = bounds(0, WAIT_MAX_S)


def check_wait(value: object, name: str = "seconds", zero_means: str = "") -> None:
    """The judge of every wait: seconds, not a bool, above zero (from zero when `zero_means`), at
    most `WAIT_MAX_S`."""
    if not (isinstance(value, int | float) and not isinstance(value, bool)
            and (value >= 0 if zero_means else value > 0) and value <= WAIT_MAX_S):
        floor = f"0 ({zero_means}) or more than zero" if zero_means else "more than zero"
        raise Invalid("bad_argument",
            f"{name}={value!r} is not a bound: a number of seconds, never a bool, {floor} and "
            f"at most {WAIT_MAX_S:g}, because with no ceiling the call would hold the server's "
            f"lock waiting for something that may never arrive")


def check_bool(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise Invalid("bad_argument", f"{name} is true or false; got {value!r}")


def one_of(name: str, value: object, options: Words, tail: str = "") -> None:
    """Hold a scalar to a closed vocabulary; a bool is refused since `True == 1`."""
    if isinstance(value, bool) or value not in options:
        raise Invalid("bad_argument", f"{name} is one of {options}; got {value!r}{tail}")
