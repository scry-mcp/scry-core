"""The base of the format `scry-knowledge/1`: every dictionary a server ships, loaded once into
the database of `scry_core.knowledge.index`.

The files are text in git and the only copy; nothing is written to disk and nothing is rebuilt by
hand. Given a `Confirmation`, the base loads the confirmed entries only: an entry held back is
counted and its id, kind and key are kept to say it exists, and nothing else of it, so no query
shape can return it and no relation can point at it. `faults` lists what a file or an entry got
wrong: a run is lenient (the bad entry is skipped and counted) and the tests are strict
(`faults()` must be empty).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core.knowledge import entry as fmt
from scry_core.knowledge import sources as cited
from scry_core.knowledge import text
from scry_core.knowledge.confirmed import Confirmation
from scry_core.knowledge.index import Found, Index, files, order

__all__ = ["DIRECTORY", "Base", "Found", "Relations"]

#: A package's dictionaries sit in its `knowledge` directory, subdirectories included.
DIRECTORY = "knowledge"
_FTS = ("CREATE VIRTUAL TABLE entry_text USING fts5 (name, aliases, description, behaviour, "
        "content='', tokenize='unicode61 remove_diacritics 2', detail=column)")
@dataclass(frozen=True)
class Relations:
    """What ties an entry to its hardware: its device, what a device holds, who uses it, and the
    ports a register is reached through."""

    device: fmt.Entry | None
    contains: tuple[fmt.Entry, ...]
    used_by: tuple[fmt.Entry, ...]
    reached: Mapping[str, tuple[str, ...]]

def _body(e: fmt.Entry) -> str:
    """The fields of `e` no query reads, as compact JSON: the part of the row `_entry` reverses."""
    body: dict[str, Any] = {"description": e.description, "behaviour": e.behaviour,
                            "digest": e.digest,
                            "sources": [[s.role, s.ref, s.cites] for s in e.sources]}
    for name in ("aliases", "differs", "address", "length", "ports", "irq", "dma", "contains",
                 "classes"):
        value = getattr(e, name)
        if value not in ((), "", None):
            body[name] = value
    if e.handlers is not None:
        body["handlers"] = dict(e.handlers)
    if e.checked is not None:
        body["checked"] = [e.checked.by, e.checked.writer, e.checked.digest,
                           [list(a) for a in e.checked.against]]
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

class Base(Index[fmt.Entry]):
    """The dictionaries of `sources` (a package name, whose `knowledge` directory is read, or a
    directory), in the database. `fts5` is None to use FTS5 where the host has it, False to force
    the index of our own. `pins` are the commit or tag each source scheme is pinned to.
    `confirmation` is what a server serves under: with none, every entry is loaded, which is the
    view the checks of the files take (`unfiltered`) and never a server's."""

    FIELDS = text.FIELDS
    EXTRA = ("body TEXT NOT NULL",)

    def __init__(self, sources: Sequence[str | Path] = (), fts5: bool | None = None,
                 pins: Mapping[str, str] | None = None,
                 confirmation: Confirmation | None = None) -> None:
        self._sources = tuple(sources)
        self._fts5_asked = fts5
        self._confirming = confirmation
        self.dictionaries: list[fmt.Header] = []
        super().__init__(fts5, pins)
        for source in sources:
            self._read(source)
        if confirmation is not None:
            self._held_twin_faults()
            self._drop_held_relations()
            self._confirming = None
        self._finish()

    def _fts(self) -> str:
        return _FTS

    @classmethod
    def load(cls, *sources: str | Path, fts5: bool | None = None,
             pins: Mapping[str, str] | None = None,
             confirmation: Confirmation | None = None) -> Base:
        return cls(sources, fts5, pins, confirmation)

    def unfiltered(self) -> Base:
        """The same dictionaries with every entry loaded, held back or not: what the checks of
        the files judge. A server never serves it."""
        return Base(self._sources, self._fts5_asked, self.pins)

    def _read(self, source: str | Path) -> None:
        try:
            for name, body in files(source, DIRECTORY):
                self._read_file(f"{source}/{name}" if isinstance(source, str) else name, body)
        except (OSError, ModuleNotFoundError) as bad:
            self.file_faults.append(f"{source}: no dictionaries could be read: {bad}")

    def _read_file(self, label: str, body: str) -> None:
        try:
            doc = json.loads(body)
        except json.JSONDecodeError as bad:
            self.file_faults.append(f"{label}: not JSON: {bad}")
            return
        header, bad_header = fmt.parse_header(doc, label)
        self.file_faults.extend(bad_header)
        if header is None:
            return
        self.dictionaries.append(header)
        for raw in doc["entries"]:
            self._add(header, len(self.dictionaries) - 1, raw)

    def _add(self, header: fmt.Header, h: int, raw: object) -> None:
        got, faults = fmt.parse_entry(raw, header)
        where = f"{header.dictionary} {raw.get('key', '?') if isinstance(raw, dict) else '?'}"
        self.entry_faults.extend(f"{where}: {f}" for f in faults)
        if got is None:
            return
        if self._confirming is not None and not self._confirming.confirms(got):
            self._hold(got)
            return
        clash = self._clash(got, h)
        if clash:
            self.load_faults.append(f"{where}: {clash}")
            return
        n = self._insert(got, h, (_body(got),), got.aliases, {
            "name": got.name, "aliases": " ".join(got.aliases),
            "description": got.description, "behaviour": got.behaviour}, got.a_hi)
        if n is None:
            self.load_faults.append(f"{where}: the id {got.id} is already an entry; the "
                                    "second is skipped")
            return
        self._db.executemany("INSERT OR IGNORE INTO relation VALUES (?,?,?)", [
            (n, rel, str(t)) for rel, ts in (("contains", got.contains), ("irq", got.irq),
                                             ("dma", got.dma)) for t in ts])
        self._db.executemany("INSERT INTO device_port VALUES (?,?,?)",
                             [(n, b, b + length - 1) for b, length in got.ports])

    def _held_twin_faults(self) -> None:
        """An id held back that another file serves is a fault of the files, not a held entry."""
        twins = [i for (i,) in self._db.execute(
            "SELECT id FROM held WHERE id IN (SELECT id FROM entry) ORDER BY id")]
        for id_ in twins:
            self.load_faults.append(f"{id_} is in two files and one of them is held back; "
                                    "the other is served")
            self._db.execute("DELETE FROM held WHERE id = ?", (id_,))

    def _held_device(self, scope: str, key: str) -> bool:
        """Whether the device `key`, as seen from `scope`, is an entry held back: the resolution
        of `device_entry` over the entries loaded and the entries held back together."""
        served = {of for (of,) in self._db.execute(
            "SELECT scope FROM entry WHERE kind = 'device' AND key = ?", (key,))}
        held = {of for (of,) in self._db.execute(
            "SELECT scope FROM held WHERE kind = 'device' AND key = ?", (key,))}
        for wanted in (scope, "chip"):
            if wanted in served:
                return False
            if wanted in held:
                return True
        return not served and len(held) == 1

    def _drop_held_relations(self) -> None:
        """Forget what an entry loaded says of an entry held back: a `device` that names one and
        a device's `contains` that lists one, so no reply points at an entry it cannot serve."""
        if not self._db.execute("SELECT 1 FROM held WHERE kind = 'device' LIMIT 1").fetchone():
            return
        for n, scope, device in self._db.execute(
                "SELECT n, scope, device FROM entry WHERE device != ''").fetchall():
            if self._held_device(scope, device):
                self._db.execute("UPDATE entry SET device = '' WHERE n = ?", (n,))
        for n, scope, body in self._db.execute(
                "SELECT n, scope, body FROM entry WHERE kind = 'device'").fetchall():
            got = json.loads(body)
            gone = [k for k in got.get("contains", ()) if self._held_device(scope, k)]
            if gone:
                got["contains"] = [k for k in got["contains"] if k not in gone]
                self._db.execute("UPDATE entry SET body = ? WHERE n = ?", (
                    json.dumps(got, ensure_ascii=False, separators=(",", ":")), n))
                self._db.executemany("DELETE FROM relation WHERE n = ? AND rel = 'contains' "
                                     "AND target = ?", [(n, k) for k in gone])

    def _entry(self, row: Sequence[Any]) -> fmt.Entry:
        """The entry of one row of the columns `Index` selects."""
        n, id_, scope, kind, key, access, lo, hi, a_lo, a_hi, name, device, h, body = row
        got = json.loads(body)
        header = self.dictionaries[h]
        check = got.get("checked")
        return fmt.Entry(
            id=id_, scope=scope, kind=kind, key=key, name=name, description=got["description"],
            behaviour=got["behaviour"],
            sources=tuple(fmt.Source(*s) for s in got["sources"]), dictionary=header.dictionary,
            digest=got["digest"], aliases=tuple(got.get("aliases", ())),
            differs=got.get("differs", ""), address=got.get("address"),
            length=got.get("length"), access=access, device=device,
            ports=tuple((b, length) for b, length in got.get("ports", ())),
            irq=tuple(got.get("irq", ())), dma=tuple(got.get("dma", ())),
            contains=tuple(got.get("contains", ())), classes=tuple(got.get("classes", ())),
            handlers=got.get("handlers"), reached=header.reached,
            checked=fmt.Check(check[0], check[1], tuple((r, line) for r, line in check[3]),
                              check[2]) if check else None, lo=lo, hi=hi, a_lo=a_lo, a_hi=a_hi)

    def related(self, e: fmt.Entry) -> Relations:
        """The device of `e`, what it holds, who uses it, and the ports its registers go by."""
        device = None
        if e.device:
            device = self.device_entry(e.scope, e.device)
        elif e.kind in ("register", "command"):
            device = self.device_entry("", e.scope)
        contains = tuple(d for k in e.contains if (d := self.device_entry(e.scope, k)))
        used: list[fmt.Entry] = []
        if e.kind == "device":
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT n FROM entry WHERE device = ?", (e.key,))]
        elif e.kind == "irq" and e.lo is not None:
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT n FROM relation WHERE rel = 'irq' AND target = ?", (str(e.lo),))]
        elif e.kind == "port" and e.lo is not None:
            used = [self._of(n) for (n,) in self._db.execute(
                "SELECT DISTINCT n FROM device_port WHERE lo <= ? AND hi >= ?", (e.lo, e.lo))]
        reached: dict[str, tuple[str, ...]] = {}
        owner = e.scope if e.kind in ("register", "command") else e.device
        for way, value in (e.reached or {}).items():
            names = [value] if isinstance(value, str) else list(value)
            reached[way] = tuple(i for n in names
                                 if (i := self._port_id(owner, n)) is not None)
        return Relations(device, contains, tuple(sorted(used, key=order)), reached)

    def _port_id(self, owner: str, name: str) -> str | None:
        """The id of the port entry a `reached` word names, else the word (a handler's name), or
        None when the port is an entry held back: the owner's own port first, as the files
        read, so a held-back port of the owner is never replaced by another device's."""
        if not name.lower().startswith("0x"):
            return name
        try:
            wanted = f"0x{int(name, 16):02X}"
        except ValueError:
            return name
        hits = self._db.execute("SELECT id, device FROM entry WHERE kind = 'port' AND key = ? "
                                "ORDER BY n", (wanted,)).fetchall()
        mine = [i for i, of in hits if owner and of == owner]
        if mine:
            return str(mine[0])
        held = self._db.execute("SELECT device FROM held WHERE kind = 'port' AND key = ?",
                                (wanted,)).fetchall()
        if owner and any(of == owner for (of,) in held):
            return None
        if hits:
            return str(hits[0][0])
        return None if held else name

    def whole(self, e: fmt.Entry) -> dict[str, Any]:
        """An entry whole: its fields, each source with its `url`, and what ties it to hardware."""
        related = self.related(e)
        out: dict[str, Any] = {**e.short()}
        for name, value in (
                ("aliases", list(e.aliases)), ("description", e.description),
                ("behaviour", e.behaviour), ("differs", e.differs),
                ("address", f"0x{e.address:06X}" if e.address is not None else ""),
                ("length", e.length or 0), ("access", e.access),
                ("ports", [{"base": f"0x{b:02X}", "length": n} for b, n in e.ports]),
                ("irq", list(e.irq)), ("dma", list(e.dma)), ("contains", list(e.contains)),
                ("classes", list(e.classes)), ("handlers", dict(e.handlers or {})),
                ("reached", {k: list(v) for k, v in related.reached.items()}),
                ("used_by", [u.id for u in related.used_by]),
                ("checked", e.checked is not None)):
            if value:
                out[name] = value
        out["sources"] = [{"role": s.role, "ref": s.ref, "cites": s.cites,
                           **({"url": u} if (u := cited.url(s.ref, self.pins)) else {})}
                          for s in e.sources]
        return out

    def row(self, id: str) -> dict[str, Any] | None:
        """An entry of this shape has no rows: no `<id>#<n>` names one."""
        return None
