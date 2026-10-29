"""A reply that answers less than everything, and names what it left out."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from scry_core.reply_contract import Invalid


def omission(omitted: Sequence[str], how: str) -> dict[str, Any]:
    """`omitted` and `how` to spread into a short reply; empty when nothing was left out."""
    if isinstance(omitted, str) or not how.strip():
        raise ValueError("an omission is a list of names and a sentence saying how to ask")
    return {"omitted": list(omitted), "how": how} if omitted else {}


def sections(asked: Sequence[str] | None, known: Sequence[str],
             default: Collection[str]) -> list[str]:
    """The sections a call reads, in `known`'s order; `default` when none was asked."""
    if not default or not set(default) <= set(known):
        raise ValueError(f"the default sections {sorted(default)} are empty or not all known")
    listed = (f"there are: {', '.join(known)}; the default is "
              f"{', '.join(in_order(known, default))}")
    if asked is None:
        return in_order(known, default)
    if isinstance(asked, str) or not asked:
        raise Invalid("bad_argument", f"`sections` is a list naming at least one section, or "
                      f"left out for the default; {listed}")
    if unknown := list(dict.fromkeys(s for s in asked if s not in known)):
        raise Invalid("bad_argument", f"`sections` names {', '.join(map(repr, unknown))}, "
                      f"none of them a section; {listed}")
    return in_order(known, asked)


def in_order(known: Sequence[str], wanted: Collection[str]) -> list[str]:
    """`known` filtered to `wanted`, in `known`'s order."""
    return [s for s in known if s in wanted]
