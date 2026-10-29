"""The declarations file: a JSON object of each guest's key to its rows, one key written at a
time. A failed write's rows are each server's to keep or put back (MAME's debugger already holds
them)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from scry_core import fresh

Refuse = Callable[[str], Exception]


def read(path: Path, refuse: Refuse, then: str = "") -> dict[str, object]:
    """The file as on disk now, empty when absent; `then` ends a refusal."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise refuse(f"the declaration file {path} could not be read: {exc}. It is not "
                     f"discarded: fix or remove it rather than lose what it holds{then}") from None
    if not isinstance(raw, dict):
        raise refuse(f"the declaration file {path} is not a mapping of key to declarations; it "
                     f"holds a {type(raw).__name__}{then}")
    return raw


def rows(raw: dict[str, object], key: str, refuse: Refuse,
         then: str = "") -> list[dict[str, object]]:
    """`key`'s rows, each an object."""
    items = raw.get(key, [])
    if not isinstance(items, list):
        raise refuse(f"key {key!r} maps to a {type(items).__name__}, not a list of "
                     f"declarations{then}")
    for d in items:
        if not isinstance(d, dict):
            raise refuse(f"a declaration under {key!r} is a {type(d).__name__}, not an "
                         f"object: {d!r}{then}")
    return items


def write(path: Path, key: str, held: list[dict[str, object]], refuse: Refuse,
          prune: Callable[[dict[str, object]], None] | None = None) -> None:
    """`key` replaced in the file as re-read, `prune` editing the rest; one writer assumed."""
    raw = read(path, refuse)
    raw[key] = held
    if prune is not None:
        prune(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh.replace(path, json.dumps(raw, indent=2, sort_keys=True).encode(),
                  "the declarations file", named_by_caller=False)
