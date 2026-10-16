"""A reply that answers less than everything, and says so.

A tool whose whole answer is larger than the question it is usually asked answers that question
by default and leaves the rest to an argument. The short reply is never read as whole because it
names what it left out: `omitted`, the names of the fields or sections not in it, beside `how`, a
sentence naming the argument that asks for them. `omission` builds that pair for both servers, so
the two words cannot drift apart between them; `sections` judges the list a caller narrows a
reply by, which a tool takes as its `sections` argument.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from scry_core.reply_contract import Invalid


def omission(omitted: Sequence[str], how: str) -> dict[str, Any]:
    """`omitted` and `how` for a reply that left `omitted` out, to spread into it; nothing when
    nothing was left out. A blank `how` is a `ValueError` either way, so a broken constant fails
    on the whole reply's path too."""
    if isinstance(omitted, str) or not how.strip():
        raise ValueError("an omission is a list of names and a sentence saying how to ask")
    return {"omitted": list(omitted), "how": how} if omitted else {}


def sections(asked: Sequence[str] | None, known: Sequence[str],
             default: Collection[str]) -> list[str]:
    """The sections a call reads, in `known`'s order, each once: `default` when it named none,
    else the ones it named. An empty list, a bare string or a name `known` does not hold is
    refused `bad_argument` before anything is read, naming every section and the default. A
    `default` that is empty or outside `known` is the server's bug, a `ValueError`."""
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
