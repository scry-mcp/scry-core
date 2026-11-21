"""The format `scry-knowledge/1`: a dictionary file's header, an entry, and the digest that keeps a
checked entry from being reworded.

A file holds one dictionary: a header (what it covers, the list it must cover, how a program
reaches its registers) and its entries, each one thing with its sources. `parse_entry` judges one
entry and returns every fault it has, so a person fixes a file in one pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scry_core.knowledge import keys, sources

FORMAT = "scry-knowledge/1"
NAME_MAX, ALIAS_MAX, ALIASES_MAX = 24, 32, 6
DESCRIPTION_WORDS, BEHAVIOUR_WORDS, BEHAVIOUR_SENTENCES, DIFFERS_WORDS = 30, 60, 3, 40
ACCESS = ("read", "write")
#: What decides that two sources both exist for a dictionary (`both` in its header).
BOTH = ("documentation", "emulator")

_HEADER_FIELDS = {"format", "dictionary", "kind", "scope", "covers", "complete_against",
                  "left_out", "reached", "both", "entries"}
_ENTRY_FIELDS = {"key", "name", "aliases", "description", "behaviour", "checked", "sources",
                 "differs", "address", "length", "access", "device", "ports", "irq", "dma",
                 "contains", "classes", "handlers"}
_DEVICE_ONLY = ("ports", "irq", "dma", "contains", "classes", "handlers")
_WITH_DEVICE = ("port", "irq", "memory")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_SESSION = re.compile(r"\S.{0,119}")


@dataclass(frozen=True)
class Header:
    """The part of a dictionary file that is the dictionary's and not an entry's."""

    file: str
    dictionary: str
    kind: str
    scope: str
    covers: str
    complete_against: str
    left_out: tuple[tuple[str, str], ...]
    reached: Mapping[str, Any] | None
    both: bool


@dataclass(frozen=True)
class Source:
    role: str
    ref: str
    cites: str


@dataclass(frozen=True)
class Check:
    """The record of a check (decision 37): who checked, who wrote (another session), the lines
    compared per source `ref`, and the digest of the text that was checked."""

    by: str
    writer: str
    against: tuple[tuple[str, str], ...]
    digest: str


@dataclass(frozen=True)
class Entry:
    """One thing the base knows, as loaded: the fields of the file, its `id`, and the numbers a
    range query compares. `lo` and `hi` are the key's numbers; `a_lo` and `a_hi` the addresses it
    sits at, when it sits at some."""

    id: str
    scope: str
    kind: str
    key: str
    name: str
    description: str
    behaviour: str
    sources: tuple[Source, ...]
    dictionary: str
    digest: str
    aliases: tuple[str, ...] = ()
    differs: str = ""
    address: int | None = None
    length: int | None = None
    access: str = ""
    device: str = ""
    ports: tuple[tuple[int, int], ...] = ()
    irq: tuple[int, ...] = ()
    dma: tuple[int, ...] = ()
    contains: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    handlers: Mapping[str, str] | None = None
    reached: Mapping[str, Any] | None = None
    checked: Check | None = None
    lo: int | None = None
    hi: int | None = None
    a_lo: int | None = None
    a_hi: int | None = None

    def short(self) -> dict[str, Any]:
        """The row a list shows: `id`, `kind`, `key`, `name`, `scope`, and `device`."""
        return {"id": self.id, "kind": self.kind, "key": self.key, "name": self.name,
                "scope": self.scope, **({"device": self.device} if self.device else {})}


def entry_id(scope: str, kind: str, key: str, access: str = "") -> str:
    """`<scope>:<kind>:<key>`, with `:<access>` when the entry has one."""
    return f"{scope}:{kind}:{key}" + (f":{access}" if access else "")


def digest(scope: str, kind: str, raw: Mapping[str, Any]) -> str:
    """The digest of an entry's text: its scope, its kind and every field but `checked`, as JSON
    in one canonical spelling. A checked entry holds it; the contract fails when the text no
    longer gives it."""
    body = {k: v for k, v in raw.items() if k != "checked"}
    text = json.dumps({"scope": scope, "kind": kind, "entry": body}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _text(raw: Mapping[str, Any], name: str, faults: list[str], required: bool = True) -> str:
    value = raw.get(name, "")
    if not isinstance(value, str) or (required and not value.strip()):
        faults.append(f"`{name}` is {'text' if required else 'text or absent'}")
        return ""
    if value != value.strip() and name != "cites":
        faults.append(f"`{name}` has space around it")
    return value


def _words(text: str, limit: int, name: str, faults: list[str]) -> None:
    if len(text.split()) > limit:
        faults.append(f"`{name}` is {len(text.split())} words, over {limit}")


def _ints(raw: Mapping[str, Any], name: str, faults: list[str], low: int = 0) -> tuple[int, ...]:
    value = raw.get(name, [])
    if not (isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool)
                                            and v >= low for v in value)):
        faults.append(f"`{name}` is a list of whole numbers from {low}")
        return ()
    return tuple(value)


def _strings(raw: Mapping[str, Any], name: str, faults: list[str]) -> tuple[str, ...]:
    value = raw.get(name, [])
    if not (isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)):
        faults.append(f"`{name}` is a list of text")
        return ()
    return tuple(value)


def _sources(raw: Mapping[str, Any], faults: list[str]) -> tuple[Source, ...]:
    listed = raw.get("sources")
    if not isinstance(listed, list) or not 1 <= len(listed) <= 2:
        faults.append("no source; an entry with none is not written (one or two, each with "
                      "`role`, `ref` and `cites`)")
        return ()
    made: list[Source] = []
    for i, one in enumerate(listed):
        where = f"source {i + 1}"
        if not (isinstance(one, dict) and set(one) == {"role", "ref", "cites"}
                and all(isinstance(v, str) for v in one.values())):
            faults.append(f"{where} is `role`, `ref` and `cites`, all text")
            continue
        if one["role"] not in sources.ROLES:
            faults.append(f"{where}: `role` is one of {', '.join(sources.ROLES)}")
        try:
            sources.split(one["ref"])
        except ValueError as bad:
            faults.append(f"{where}: {bad}")
        if not one["cites"].strip():
            faults.append(f"{where}: `cites` is the source's own line, not empty")
        made.append(Source(one["role"], one["ref"], one["cites"]))
    if len({s.role for s in made}) != len(made):
        faults.append("two sources of one role: one `documentation` and one `emulator` at most")
    return tuple(made)


def _checked(raw: Mapping[str, Any], listed: tuple[Source, ...],
             faults: list[str]) -> Check | None:
    if "checked" not in raw:
        return None
    one = raw["checked"]
    shape = {"by", "writer", "against", "digest"}
    if not (isinstance(one, dict) and set(one) == shape and isinstance(one["by"], str)
            and isinstance(one["writer"], str) and isinstance(one["digest"], str)
            and isinstance(one["against"], list)):
        faults.append("`checked` is `by`, `writer`, `against` and `digest`")
        return None
    if not (_SESSION.fullmatch(one["by"]) and _SESSION.fullmatch(one["writer"])):
        faults.append("`checked` names the session that checked and the one that wrote")
    elif one["by"] == one["writer"]:
        faults.append(f"`checked`: {one['by']!r} wrote this entry and cannot check it; a "
                      "different session does (decision 37)")
    against = tuple((a.get("ref", ""), a.get("line", "")) for a in one["against"]
                    if isinstance(a, dict) and set(a) == {"ref", "line"})
    if len(against) != len(one["against"]) or any(
            not isinstance(r, str) or not isinstance(line, str) or not line.strip()
            for r, line in against):
        faults.append("`checked.against` is a list of `ref` and `line`, the line compared")
    elif {r for r, _ in against} != {s.ref for s in listed} or len(against) != len(listed):
        faults.append("`checked.against` names each source `ref` once and no other")
    return Check(one["by"], one["writer"], against, one["digest"])


def _numbers(raw: Mapping[str, Any], header: Header,
             faults: list[str]) -> tuple[int | None, int | None]:
    address, length = raw.get("address"), raw.get("length")
    for name, value in (("address", address), ("length", length)):
        if value is not None and not (isinstance(value, int) and not isinstance(value, bool)
                                      and value >= (1 if name == "length" else 0)
                                      and keys.fits(value)):
            faults.append(f"`{name}` is a whole number")
            return None, None
    if (address is None) != (length is None) and header.kind in ("vector", "memory"):
        faults.append("`address` and `length` come together, or neither")
    if (address is not None or length is not None) and header.kind not in ("vector", "memory"):
        faults.append("`address` and `length` are for `memory` and `vector`")
    return address, length


def _ports(raw: Mapping[str, Any], faults: list[str]) -> tuple[tuple[int, int], ...]:
    listed = raw.get("ports", [])
    out: list[tuple[int, int]] = []
    for one in listed if isinstance(listed, list) else [None]:
        try:
            if not (isinstance(one, dict) and set(one) == {"base", "length"}
                    and isinstance(one["length"], int) and one["length"] >= 1
                    and keys.fits(one["length"])):
                raise keys.KeyFault("a port range is `base` and `length`, a whole number from 1")
            base = keys.span("port", keys.canonical("port", one["base"])).lo
            out.append((base or 0, one["length"]))
        except keys.KeyFault as bad:
            faults.append(f"`ports`: {bad}")
    return tuple(out)


def parse_entry(raw: object, header: Header) -> tuple[Entry | None, list[str]]:
    """The entry of `raw` under `header`, or None, and every fault, each one a sentence about
    the entry as its file spells it."""
    faults: list[str] = []
    if not isinstance(raw, dict):
        return None, ["an entry is an object"]
    for name in sorted(set(raw) - _ENTRY_FIELDS):
        faults.append(f"unknown field `{name}`")
    key, canon, made = raw.get("key"), "", keys.Span(None, None)
    try:
        canon = keys.canonical(header.kind, key)  # type: ignore[arg-type]
        if canon != key:
            faults.append(f"`key` {key!r} is spelled {canon!r} in this kind")
        made = keys.span(header.kind, canon)
    except keys.KeyFault as bad:
        faults.append(f"`key`: {bad}")
    name = _text(raw, "name", faults)
    if name and not (len(name) <= NAME_MAX and name.isascii() and name.isprintable()):
        faults.append(f"`name` is 1 to {NAME_MAX} printable ASCII characters")
    aliases = _strings(raw, "aliases", faults)
    if len(aliases) > ALIASES_MAX or any(len(a) > ALIAS_MAX for a in aliases):
        faults.append(f"`aliases` are at most {ALIASES_MAX}, each up to {ALIAS_MAX} characters")
    description = _text(raw, "description", faults)
    _words(description, DESCRIPTION_WORDS, "description", faults)
    behaviour = _text(raw, "behaviour", faults)
    _words(behaviour, BEHAVIOUR_WORDS, "behaviour", faults)
    if len(_SENTENCE_END.findall(behaviour)) > BEHAVIOUR_SENTENCES:
        faults.append(f"`behaviour` is at most {BEHAVIOUR_SENTENCES} sentences")
    differs = _text(raw, "differs", faults, required=False)
    _words(differs, DIFFERS_WORDS, "differs", faults)
    listed = _sources(raw, faults)
    now = digest(header.scope, header.kind, raw)
    checked = _checked(raw, listed, faults)
    address, length = _numbers(raw, header, faults)
    access, device = raw.get("access", ""), raw.get("device", "")
    if not isinstance(access, str) or (access and (header.kind != "port"
                                                   or access not in ACCESS)):
        faults.append("`access` is `read` or `write`, and only for a port")
        access = ""
    if "device" in raw:
        try:
            if header.kind not in _WITH_DEVICE:
                raise keys.KeyFault(f"`device` is for {', '.join(_WITH_DEVICE)}")
            keys.canonical("device", device)
        except keys.KeyFault as bad:
            faults.append(str(bad))
            device = ""
    extra = {n: raw[n] for n in _DEVICE_ONLY if n in raw}
    if extra and header.kind != "device":
        faults.append(f"{', '.join(f'`{n}`' for n in extra)} belong to a `device` entry")
    classes = _strings(raw, "classes", faults)
    handlers = raw.get("handlers")
    if handlers is not None and not (isinstance(handlers, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in handlers.items())):
        faults.append("`handlers` maps a handler to its meaning, both text")
    contains = _strings(raw, "contains", faults)
    ports, irq, dma = _ports(raw, faults), _ints(raw, "irq", faults), _ints(raw, "dma", faults)
    if faults:
        return None, faults
    lo, hi = made.lo, made.hi
    a_lo = a_hi = None
    if address is not None:
        a_lo, a_hi = address, address + (length or 1) - 1
    elif header.kind == "memory":
        a_lo, a_hi = lo, hi
    return Entry(
        id=entry_id(header.scope, header.kind, canon, access), scope=header.scope,
        kind=header.kind, key=canon, name=name, description=description, behaviour=behaviour,
        sources=listed, dictionary=header.dictionary, digest=now, aliases=aliases,
        differs=differs, address=address, length=length, access=access, device=device,
        ports=ports, irq=irq, dma=dma,
        contains=contains, classes=classes, handlers=handlers, reached=header.reached,
        checked=checked, lo=lo, hi=hi, a_lo=a_lo, a_hi=a_hi), faults


def parse_header(doc: object, file: str) -> tuple[Header | None, list[str]]:
    """The header of a dictionary file, or None, and its faults."""
    if not isinstance(doc, dict):
        return None, [f"{file}: a dictionary is a JSON object"]
    faults: list[str] = []
    if doc.get("format") != FORMAT:
        faults.append(f"`format` is {FORMAT!r}")
    for name in sorted(set(doc) - _HEADER_FIELDS):
        faults.append(f"unknown field `{name}`")
    kind = doc.get("kind")
    if kind not in keys.KINDS:
        faults.append(f"`kind` is one of {', '.join(keys.KINDS)}")
    for name in ("dictionary", "scope", "covers", "complete_against"):
        if not (isinstance(doc.get(name), str) and doc[name].strip()):
            faults.append(f"`{name}` is text")
    if not isinstance(doc.get("entries"), list):
        faults.append("`entries` is a list")
    left = doc.get("left_out", [])
    out: list[tuple[str, str]] = []
    for one in left if isinstance(left, list) else [None]:
        if isinstance(one, dict) and set(one) == {"key", "why"} and all(
                isinstance(v, str) and v.strip() for v in one.values()):
            out.append((one["key"], one["why"]))
        else:
            faults.append("`left_out` is a list of `key` and `why`, each key with its reason")
    reached = doc.get("reached")
    if reached is not None and not (isinstance(reached, dict) and set(reached) <= {"index", "data"}
                                    and all(isinstance(v, str) or (isinstance(v, list) and all(
                                        isinstance(i, str) for i in v)) for v in reached.values())):
        faults.append("`reached` is `index` and `data`, each a port or the names of handlers")
        reached = None
    if "both" in doc and not isinstance(doc["both"], bool):
        faults.append("`both` is true or false")
    if faults:
        return None, [f"{file}: {f}" for f in faults]
    return Header(file, doc["dictionary"], doc["kind"], doc["scope"], doc["covers"],
                  doc["complete_against"], tuple(out), reached, bool(doc.get("both"))), []
