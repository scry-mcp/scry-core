"""`rows migrate`: a draft of an entry in the new shape from the old one and the evidence a check
gathered for it.

Each statement the check found supported becomes a draft row whose quotes are the evidence's
lines, found again in the pinned source and stamped by the tool. A quote whose text is not at the
line the evidence names is dropped and said; a statement that keeps no quote, one the check found
unsupported, and a piece of the old text no statement holds are marked `unanchored` and never
guessed at. The draft is not valid until a person has resolved those marks and set each row's
`on`, which is why `rows check` refuses it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scry_core.knowledge import keys
from scry_core.knowledge.entry import entry_id
from scry_core.knowledge.quote import QUOTE_LINES, Invalid, Quote, Sources, spelled
from scry_core.knowledge.rows import FORMAT, PLACEMENT

_RBIL = re.compile(r"[A-Z0-9_]+\.[A-Z0-9]{1,3}")
_IS_FIELDS = ("key", "name", "aliases", "description")
_TEXT_FIELDS = ("name", "description", "behaviour", "differs")


@dataclass(frozen=True)
class Cite:
    """A quote of the evidence: where it says it is, and the text it quotes."""

    ref: str
    line: int
    text: str
    last: int = 0


@dataclass(frozen=True)
class Statement:
    field: str
    text: str
    span: str
    supported: bool
    verdict: str
    cites: tuple[Cite, ...]


@dataclass(frozen=True)
class Evidence:
    statements: tuple[Statement, ...]
    omissions: tuple[tuple[str, Cite], ...] = ()
    opened: tuple[Cite, ...] = ()


def _scheme(file: str) -> str:
    return "rbil61" if _RBIL.fullmatch(file) else "dosbox-x"


def _ref(src: str) -> str:
    """The ref of an evidence source that names a scheme and a file (`mame:src/...`), or of a
    datasheet by its short name."""
    scheme, _, file = src.partition(":")
    return f"datasheet:{file}.raw.txt" if scheme == "datasheet" else src


def _first(lines: str) -> tuple[int, int]:
    a, _, b = str(lines).partition("-")
    return int(a), int(b or a)


def _checked(raw: dict[str, Any]) -> tuple[Statement, ...]:
    made = []
    for s in raw["statements"]:
        if "claim" in s:     # the shared base's check
            cites = tuple(Cite(_ref(q["src"]), int(q["line"]), q["quote"])
                          for q in s["support"])
            made.append(Statement(s["field"], s["claim"], s.get("span", ""),
                                  s["status"] == "supported", s["status"], cites))
        elif "quotes" in s:  # scry-mame's check
            cites = tuple(Cite(f"mame:{q['file']}", _first(q["lines"])[0], q["text"],
                               _first(q["lines"])[1]) for q in s["quotes"])
            made.append(Statement(s["field"], s["text"], s["text"], bool(s["supported"]),
                                  "supported" if s["supported"] else "unsupported", cites))
        else:                # scry-dosbox-x's check
            cites = tuple(Cite(f"{_scheme(q['file'])}:{q['file']}", int(q["line"]), q["quote"])
                          for q in s["support"])
            made.append(Statement(s["field"], s["text"], s["text"], bool(s["supported"]),
                                  "supported" if s["supported"] else "unsupported", cites))
    return tuple(made)


def read_evidence(path: Path) -> Evidence:
    """The evidence file of any of the three checks, in one shape."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not (isinstance(raw, dict) and raw.get("statements")):
        raise Invalid(f"{path.name} holds no statements: nothing to draft from")
    try:
        return _evidence(raw)
    except (KeyError, TypeError, ValueError, AttributeError) as bad:
        raise Invalid(f"{path.name} is not the evidence of any of the three checks: "
                      f"{type(bad).__name__} {bad}") from bad


def _evidence(raw: dict[str, Any]) -> Evidence:
    omissions: list[tuple[str, Cite]] = []
    for o in raw.get("omissions", []):
        if "fact" in o and o.get("needed"):
            omissions.append((o["fact"], Cite(_ref(o["src"]), int(o["line"]), o["quote"])))
        elif "statement" in o and isinstance(o.get("quote"), dict):
            q = o["quote"]
            omissions.append((o["why"], Cite(f"mame:{q['file']}", _first(q["lines"])[0],
                                             q["text"], _first(q["lines"])[1])))
    opened = tuple(Cite(f"dosbox-x:{c['file']}", int(c["line"]), c["name"])
                   for c in raw.get("calls", []) if c.get("status") == "opened")
    return Evidence(_checked(raw), tuple(omissions), opened)


def _fold(text: str) -> str:
    return " ".join(text.split())


def _window(held: list[str], wanted: str, line: int, floor: int) -> str | None:
    """The shortest span of lines from `line` that holds `wanted` starting inside `line`, spelled
    as a `lines` text."""
    first = len(_fold(held[line - 1]))
    if not first:
        return None
    for last in range(max(line, floor), min(len(held), line + QUOTE_LINES - 1) + 1):
        at = _fold(" ".join(held[line - 1:last])).find(wanted)
        if 0 <= at <= first:
            return spelled(line, last)
    return None


def locate(sources: Sources, cite: Cite) -> Quote | None:
    """The quote that holds `cite`'s text starting at its line, stamped from the source; None
    when the text is not there (a paraphrase, another line). A datasheet is numbered in whatever
    rendering the check read, so its text is searched in the capture and taken only where it
    occurs once."""
    wanted = _fold(cite.text)
    if not wanted or cite.line < 1:
        return None
    held = sources.lines(cite.ref)
    if cite.ref.startswith("datasheet:"):
        word = wanted.split()[0]
        found = [w for n in range(1, len(held) + 1) if word in held[n - 1]
                 and (w := _window(held, wanted, n, 0))]
        return sources.stamped(cite.ref, found[0]) if len(found) == 1 else None
    if cite.line > len(held):
        return None
    here = _window(held, wanted, cite.line, cite.last)
    return sources.stamped(cite.ref, here) if here else None


def _regions(header: dict[str, Any], evidence: Evidence) -> list[dict[str, str]]:
    regions = []
    got = header.get("complete_against", "")
    match = re.fullmatch(r"(mame|dosbox-x):(\S+) (\S+)", got)
    if match:
        regions.append({"ref": f"{match.group(1)}:{match.group(2)}", "function": match.group(3)})
    for cite in evidence.opened:
        regions.append({"ref": cite.ref, "function": cite.text})
    return regions


def _uncovered(old: dict[str, Any], evidence: Evidence) -> list[tuple[str, str]]:
    """The pieces of the old text that no statement of the evidence holds, as `(field, text)`."""
    out = []
    for name in _TEXT_FIELDS:
        text = _fold(str(old.get(name, "")))
        for s in evidence.statements:
            if s.field == name and _fold(s.span or s.text):
                text = text.replace(_fold(s.span or s.text), "|", 1)
        for piece in text.split("|"):
            if re.search(r"[A-Za-z0-9]", piece):
                out.append((name, piece.strip(" .,;:")))
    return out


@dataclass
class Draft:
    document: dict[str, Any]
    anchored: int = 0
    marked: int = 0
    omissions: int = 0
    dropped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        rows = len(self.document["entries"][0]["rows"])
        return (f"{self.document['entries'][0]['key']}: {self.anchored} statements anchored, "
                f"{self.marked} marked unanchored, {self.omissions} omissions as rows, {rows} "
                f"draft rows, {len(self.dropped)} quotes dropped")


def _on(name: str) -> str:
    if name in _IS_FIELDS:
        return "is"
    if name.split(".")[0] in PLACEMENT:
        return "place"
    return ""


def draft(dictionary: Path, wanted: str, evidence_file: Path, sources: Sources) -> Draft:
    """The draft of entry `wanted` of the old-shape `dictionary`, from its evidence file."""
    old_doc = json.loads(dictionary.read_text(encoding="utf-8"))
    kind, scope = old_doc["kind"], old_doc["scope"]
    found = [e for e in old_doc["entries"]
             if entry_id(scope, kind, keys.canonical(kind, e["key"]), e.get("access", ""))
             == wanted]
    if not found:
        raise Invalid(f"no entry {wanted or '(none given)'} in {dictionary.name}")
    old = found[0]
    evidence = read_evidence(evidence_file)
    out = Draft({})
    rows: list[dict[str, Any]] = []
    marks: list[dict[str, str]] = []

    def row(on: str, text: str, quotes: list[Quote], source: str) -> None:
        rows.append({"n": str(len(rows) + 1), "on": on, "of": sorted({q.party for q in quotes}),
                     "text": text, "quotes": [q.as_json() for q in quotes], "from": source})

    for s in evidence.statements:
        if not s.supported:
            marks.append({"statement": s.text, "field": s.field,
                          "why": f"the check found it {s.verdict}"})
            out.marked += 1
            continue
        kept = []
        for c in s.cites:
            q = locate(sources, c)
            if q is None:
                out.dropped.append(f"{c.ref}:{c.line} ({s.field}: {s.text[:40]})")
            elif q not in kept:
                kept.append(q)
        if kept:
            row(_on(s.field), s.text, kept, s.field)
            out.anchored += 1
        else:
            marks.append({"statement": s.text, "field": s.field,
                          "why": "none of its quotes is at the line the evidence names"})
            out.marked += 1
    for fact, cite in evidence.omissions:
        q = locate(sources, cite)
        if q is None:
            marks.append({"statement": fact, "field": "omission",
                          "why": "its quote is not at the line the evidence names"})
            out.marked += 1
        else:
            row("", fact, [q], "omission")
            out.omissions += 1
    for name, piece in _uncovered(old, evidence):
        marks.append({"statement": piece, "field": name,
                      "why": "no statement of the evidence holds this part of the old text"})
        out.marked += 1
    entry: dict[str, Any] = {"key": keys.canonical(kind, old["key"]), "name": old["name"],
                             "aliases": old.get("aliases", [])}
    for name in ("access", *PLACEMENT):
        if name in old:
            entry[name] = old[name]
    entry |= {"regions": _regions(old_doc, evidence), "rows": rows, "closed": [],
              "unanchored": marks, "dropped": out.dropped}
    out.document = {"format": FORMAT, "dictionary": old_doc.get("dictionary", scope),
                    "kind": kind, "scope": scope, "covers": old_doc.get("covers", ""),
                    "entries": [entry]}
    return out
