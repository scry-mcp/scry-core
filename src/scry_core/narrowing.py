"""A reply that answers less than everything, and names what it left out."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from scry_core import fresh
from scry_core.reply_contract import Invalid

#: How a short `machine_map` asks for the rest: the sections it left out, or every row of a cut
#: list.
MAP_HOW = ("sections=[...] names the sections to read; dest=<absolute path> writes every section "
           "read whole")
MAP_CUT_HOW = "dest=<absolute path> writes every row of every section read"


def omission(omitted: Sequence[str], how: str) -> dict[str, Any]:
    """`omitted` and `how` to spread into a short reply; empty when nothing was left out."""
    if isinstance(omitted, str) or not how.strip():
        raise ValueError("an omission is a list of names and a sentence saying how to ask")
    return {"omitted": list(omitted), "how": how} if omitted else {}


def last_words(tails: Mapping[str, Any], *, clean: bool, detail: bool, how: str) -> dict[str, Any]:
    """The emulator's last words as a `close` reply carries them: kept when asked for or when the
    end was not a clean quit, else named as omitted with `how` to ask."""
    return dict(tails) if detail or not clean else omission(list(tails), how)


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


def map_rest(left: Sequence[str], *, truncated: bool, written: bool) -> dict[str, Any]:
    """What a `machine_map` reply says to get the rest: the sections `left` out, else, for a cut
    list that no `dest` holds whole, the `dest` that writes every row."""
    if left:
        return omission(left, MAP_HOW)
    return {"how": MAP_CUT_HOW} if truncated and not written else {}


def write_whole(path: Path, whole: Mapping[str, Any]) -> str:
    """`whole`, every row uncut, as JSON at the caller's new `path`; the path written."""
    fresh.create(path, json.dumps(whole, indent=1).encode(), "the map", named_by_caller=True)
    return str(path)
