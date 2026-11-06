"""The names a call was given, before the schema fills the defaults."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_NAMES: ContextVar[frozenset[str] | None] = ContextVar("given_names", default=None)


def names() -> frozenset[str] | None:
    """The names given, or None outside a call."""
    return _NAMES.get()


@contextmanager
def remembered(names: frozenset[str] | Iterable[str]) -> Iterator[None]:
    """Hold these names for the enclosing call."""
    token: Token[frozenset[str] | None] = _NAMES.set(frozenset(names))
    try:
        yield
    finally:
        _NAMES.reset(token)
