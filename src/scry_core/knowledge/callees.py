"""The callee table: what each function a handler calls means to coverage, decided once.

A line is `<scheme>:<name>` (or `<scheme>:<file> <name>` where one name means two things in two
files) and its decision is used by every entry that meets the call: `open` (the callee's body
joins the region of the entry that holds it, and the call is owed to that entry in any other),
`shared:<entry id>`, `engine` (not covered), `writes` (it writes the guest's memory or flags, so
a call to it is a store) or `none:<reason>`; a call with several bodies lists each as
`<file> <function>`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

FORMAT = "scry-knowledge-callees/1"
NONE_REASONS = ("log", "libc", "accessor", "macro", "copy", "assert")
_DECISION = re.compile(
    r"open(?::[A-Za-z_][\w:]*)?|engine|writes|shared:\S+|none:(?:" + "|".join(NONE_REASONS)
    + ")")
_KEY = re.compile(r"(mame|dosbox-x):(?:\S+ )?[A-Za-z_][\w:]*")
_IMPLEMENTATION = re.compile(r"(\S+) ([A-Za-z_][\w:]*)")


def last_name(name: str) -> str:
    """The function a call names, without its object, class or namespace."""
    return re.split(r"::|\.|->", name)[-1]


@dataclass(frozen=True)
class Decision:
    kind: str     # open, shared, engine, writes, none or virtual
    detail: str = ""
    implementations: tuple[tuple[str, str], ...] = ()

    def spelled(self) -> str:
        return f"{self.kind}:{self.detail}" if self.detail else self.kind


def decision(text: str) -> Decision:
    """A decision from its text, or `ValueError`."""
    if not _DECISION.fullmatch(text):
        raise ValueError(f"{text!r} is no decision: open, open:<function>, engine, writes, "
                         f"shared:<entry id> or none:<{'|'.join(NONE_REASONS)}>")
    kind, _, detail = text.partition(":")
    return Decision(kind, detail)


class Callees:
    """The table: a decision per function, found by the file first and by the name after."""

    def __init__(self, table: Mapping[str, Decision] | None = None) -> None:
        self.table = dict(table or {})

    def of(self, scheme: str, file: str, name: str) -> Decision | None:
        """The decision for `name` called in `file` of `scheme`, or None when nobody decided."""
        last = last_name(name)
        for key in (f"{scheme}:{file} {name}", f"{scheme}:{file} {last}", f"{scheme}:{name}",
                    f"{scheme}:{last}"):
            if key in self.table:
                return self.table[key]
        return None


def virtual(listed: object) -> Decision:
    """The decision of a call with several bodies, or `ValueError`."""
    if not (isinstance(listed, list) and len(listed) >= 2
            and all(isinstance(x, str) and _IMPLEMENTATION.fullmatch(x) for x in listed)):
        raise ValueError("a call with several bodies lists at least two, each `<file> <function>`")
    if len(set(listed)) != len(listed):
        raise ValueError("a call with several bodies names one of them twice")
    found = (_IMPLEMENTATION.fullmatch(x) for x in listed)
    return Decision("virtual", implementations=tuple((m[1], m[2]) for m in found if m))


def parse(text: str, where: str = "callee table") -> Callees:
    """The table a file holds, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError(f"{where} is not a `{FORMAT}` document")
    raw = doc.get("callees")
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: `callees` is an object")
    table: dict[str, Decision] = {}
    for key, how in raw.items():
        if not _KEY.fullmatch(key):
            raise ValueError(f"{where}: {key!r} is `<scheme>:<name>` or `<scheme>:<file> <name>`, "
                             "the scheme `mame` or `dosbox-x`")
        if not isinstance(how, (str, list)):
            raise ValueError(f"{where}: the decision for {key!r} is text, or a list of the "
                             "bodies it may reach")
        try:
            table[key] = decision(how) if isinstance(how, str) else virtual(how)
        except ValueError as bad:
            raise ValueError(f"{where}: {key!r}: {bad}") from bad
    return Callees(table)

