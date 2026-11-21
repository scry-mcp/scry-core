"""Where an entry's facts come from: the closed set of source schemes, how a reader opens one, and
the committed index a test holds every entry to.

A `ref` is `<scheme>:<locator>`. The index is captured from the real source by each server's own
tool and committed, so the ordinary tests check a quoted line and a key with no network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

INDEX_FORMAT = "scry-knowledge-sources/1"
ROLES = ("documentation", "emulator")
#: The schemes of the two emulators that may both be cited by one entry, sorted.
EMULATORS = ("dosbox-x", "mame")
_FILE_THEN_SYMBOL = re.compile(r"[A-Za-z0-9_./+-]*\.[A-Za-z0-9_+-]+ \S.*")


@dataclass(frozen=True)
class Scheme:
    """One kind of source: the shape of its locator, whether a machine can open it, and where a
    reader does (`{pin}` is the commit or tag the server pins)."""

    name: str
    locator: re.Pattern[str]
    shape: str
    machine_checked: bool
    opens_at: str


SCHEMES: dict[str, Scheme] = {s.name: s for s in (
    Scheme("rbil61", re.compile(r"[A-Z0-9_]+\.[A-Z0-9]{1,3} \S.*"),
           "file and section, as `INTERRUP.G D-214C`", True,
           "https://www.cs.cmu.edu/~ralf/files.html"),
    Scheme("dosbox-x", _FILE_THEN_SYMBOL, "file and symbol, as `src/dos/dos.cpp DOS_21Handler`",
           True, "https://github.com/joncampbell123/dosbox-x/blob/{pin}/{path}"),
    Scheme("mame", _FILE_THEN_SYMBOL, "file and symbol, as `src/devices/cpu/m6809/m6809.h "
           "VECTOR_IRQ`", True, "https://github.com/mamedev/mame/blob/{pin}/{path}"),
    Scheme("datasheet", re.compile(r"\S.*"), "title, number, table or page, URL", False, ""),
)}


def split(ref: str) -> tuple[str, str]:
    """The scheme and the locator of `ref`, or `ValueError` saying what is wrong."""
    scheme, colon, locator = ref.partition(":")
    if not colon or scheme not in SCHEMES:
        raise ValueError(f"{ref!r} does not start with a known scheme ({', '.join(SCHEMES)}) "
                         "and a colon")
    if not SCHEMES[scheme].locator.fullmatch(locator):
        raise ValueError(f"{ref!r}: the locator of {scheme} is {SCHEMES[scheme].shape}")
    return scheme, locator


def url(ref: str, pins: Mapping[str, str]) -> str:
    """Where a reader opens `ref`, or "" where it names a document rather than a place or the
    scheme's pin is not known."""
    scheme, locator = split(ref)
    opens = SCHEMES[scheme].opens_at
    if "{pin}" not in opens:
        return opens
    return (opens.format(pin=pins[scheme], path=locator.split(" ", 1)[0])
            if scheme in pins else "")


@dataclass(frozen=True)
class Row:
    """What the real source says at a locator: its line, the number the locator itself carries
    (when it carries one), and its read or write marks (`R`, `W`, `RW`)."""

    line: str
    key: str = ""
    marks: str = ""


@dataclass(frozen=True)
class SourceIndex:
    """The rows the dictionaries cite, by `ref`, the lists they must cover, by the name the
    dictionary's `complete_against` gives, and the pin of each scheme that has one."""

    rows: Mapping[str, Row] = field(default_factory=dict)
    lists: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    pins: Mapping[str, str] = field(default_factory=dict)


def parse_index(text: str, where: str = "source index") -> SourceIndex:
    """The index a tool wrote, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    if not isinstance(doc, dict) or doc.get("format") != INDEX_FORMAT:
        raise ValueError(f"{where} is not a `{INDEX_FORMAT}` document")
    rows: dict[str, Row] = {}
    for ref, raw in _mapping(doc, "rows", where).items():
        if not isinstance(raw, dict) or not isinstance(raw.get("line"), str):
            raise ValueError(f"{where}: row {ref!r} has no `line` text")
        rows[ref] = Row(raw["line"], str(raw.get("key", "")), str(raw.get("marks", "")))
    lists = {name: tuple(keys) for name, keys in _mapping(doc, "lists", where).items()
             if isinstance(keys, list) and all(isinstance(k, str) for k in keys)}
    if len(lists) != len(_mapping(doc, "lists", where)):
        raise ValueError(f"{where}: a list is not a list of key texts")
    return SourceIndex(rows, lists, {k: str(v) for k, v in _mapping(doc, "pins", where).items()})


def _mapping(doc: Mapping[str, Any], name: str, where: str) -> Mapping[str, Any]:
    value = doc.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{where}: `{name}` is an object")
    return value


def read_index(path: Path) -> SourceIndex:
    return parse_index(path.read_text(encoding="utf-8"), str(path.name))
