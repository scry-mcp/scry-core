"""A server with no emulator behind it, written only on what `scry_core.window` offers, and two
that break one rule each. `scry_core.conformance` is what tells them apart."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scry_core import session_block
from scry_core import window as w
from scry_core.knowledge import Device, Scope, Support, quote, read_index, sealed
from scry_core.knowledge import base as rows_base
from scry_core.reply_contract import Invalid

PID = 4242
KNOWLEDGE = Path(__file__).parent / "fixtures" / "knowledge"


class NullServer:
    shows_fullscreen = True
    takes_fullscreen = True

    def __init__(self) -> None:
        self.live = False
        self.requested: w.WindowRequest | None = None
        self.background = False

    def asked(self) -> tuple[int, w.WindowRequest] | None:
        return (PID, self.requested) if self.live and self.requested else None

    def has_session(self) -> bool:
        return self.live

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        try:
            asked = self._ask(shared, display, fullscreen)
            self.live, self.requested = True, asked
            self.background = w.judge_background(background, shared)
            return {"status": "ok", **({} if asked is None
                                       else {"window": w.prove(PID, asked).block()})}
        except Invalid as refused:
            return refused.reply()

    def _ask(self, shared: bool, display: int | None,
             fullscreen: bool | None) -> w.WindowRequest | None:
        return w.requested(shared, display, fullscreen)

    def window(self, front: bool = False) -> dict[str, Any]:
        try:
            if not self.live:
                raise Invalid("no_session", "no session is live: call `start`")
            return {"status": "ok", **w.answer(PID, self.requested, front=front,
                                               launched_behind=self.background)}
        except Invalid as refused:
            return refused.reply()

    def close(self) -> dict[str, Any]:
        was, self.live, self.requested = self.live, False, None
        if not was:
            return {"status": "ok", "closed": False, "ended_by": "none",
                    "note": session_block.NO_SESSION_CLOSE_NOTE,
                    "summary": session_block.NO_SESSION_CLOSE}
        return {"status": "ok", "closed": True, "ended_by": "quit"}

    def status(self) -> dict[str, Any]:
        if not self.live:
            return {"status": "ok", "summary": session_block.NO_SESSION_STATUS,
                    "session": {"alive": False}}
        return {"status": "ok", "system": "null", "session": {"alive": True}}


class NoFullscreenServer(NullServer):
    """Its `start` has no `fullscreen` argument, because no host of its emulator shows one."""

    takes_fullscreen = False
    shows_fullscreen = False

    # The missing argument is what this server models.
    def start(  # type: ignore[override]
            self, shared: bool = False, display: int | None = None,
            background: bool | None = None) -> dict[str, Any]:
        return super().start(shared, display, None, background)


class RefusesFullscreenServer(NullServer):
    """Takes `fullscreen` because its emulator can, and refuses it by name on this host."""

    shows_fullscreen = False

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        if fullscreen and shared:
            return Invalid("bad_argument", "fullscreen: this host shows no full-screen window"
                           ).reply()
        return super().start(shared, display, fullscreen, background)


class WithoutWindowTool(NullServer):
    """Has no `window` tool: the call is refused as an unknown argument, whatever the session."""

    def window(self, front: bool = False) -> dict[str, Any]:
        return Invalid("bad_argument", "no tool `window`").reply()


class IgnoresDisplayUnwatched(NullServer):
    """Takes `display` and `fullscreen` on a run nobody watches and says nothing."""

    def _ask(self, shared: bool, display: int | None,
             fullscreen: bool | None) -> w.WindowRequest | None:
        return super()._ask(shared, None, None) if not shared else super()._ask(
            shared, display, fullscreen)


class AlwaysBehind(NullServer):
    """Tells every `window` call its session was launched behind, whatever it was."""

    def window(self, front: bool = False) -> dict[str, Any]:
        self.background = True
        return super().window(front)


class SkipsProve(NullServer):
    """Answers a watched `start` without waiting for the window it asked for."""

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        try:
            self.requested = self._ask(shared, display, fullscreen)
        except Invalid as refused:
            return refused.reply()
        self.live = True
        self.background = w.judge_background(background, shared)
        return {"status": "ok"}


class CachesStartBlock(NullServer):
    """Answers `window` with the block `start` read, never reading the host again."""

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        self.block = super().start(shared, display, fullscreen, background).get("window")
        return {"status": "ok", **({} if self.block is None else {"window": self.block})}

    def window(self, front: bool = False) -> dict[str, Any]:
        return {"status": "ok", "window": self.block} if self.live and self.block else (
            super().window(front))


class RefusesToCloseNothing(NullServer):
    """Answers a `close` with no session as a refusal."""

    def close(self) -> dict[str, Any]:
        if not self.live:
            return Invalid("no_session", "close: no session is live").reply()
        return super().close()


class StatusInventsASession(NullServer):
    """Answers a `status` with no session as if one were alive."""

    def status(self) -> dict[str, Any]:
        return {"status": "ok", "system": "null", "session": {"alive": True}}


class StatusDeniesASession(NullServer):
    """Answers a `status` with a live session as if there were none."""

    def status(self) -> dict[str, Any]:
        return {"status": "ok", "summary": session_block.NO_SESSION_STATUS,
                "session": {"alive": False}}


class NullKnowledge:
    """Two fixture entries written as rows, one sealed in all its parts and served, the other
    held back; `rows` and `rows_locked` name copies, for variants that break one rule."""

    def __init__(self, declared: Support | None = None,
                 code: Iterable[str] = ("ibm-pc",),
                 rows: Path = KNOWLEDGE / "null-rows",
                 rows_locked: Path = KNOWLEDGE / "null-rows-lock.json") -> None:
        self.code = tuple(code)
        self.rows, self.rows_locked = rows, rows_locked
        self.declared = declared or Support(
            scopes=(Scope("ibm-pc", written=("call", "port", "device")),),
            devices=(Device("vga-seq", written=("register",)),))

    def support(self) -> Support:
        return self.declared

    def code_scopes(self) -> Iterable[str]:
        return self.code

    def rows_base(self, fts5: bool | None = None) -> rows_base.Base:
        return rows_base.Base.load(*self.rows_sources(), lock=self.rows_lock(), fts5=fts5)

    def rows_sources(self) -> tuple[Path, ...]:
        return (self.rows,)

    def rows_lock(self) -> sealed.Lock:
        return sealed.read_lock(self.rows_locked)

    def rows_index(self) -> quote.Quotes:
        return quote.parse_quotes((KNOWLEDGE / quote.QUOTES_NAME).read_text(encoding="utf-8"),
                                  quote.QUOTES_NAME)


EXIT_REF = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4c"


def an_entry(key: str, name: str, **fields: Any) -> dict[str, Any]:
    """A fixture entry: it cites the one real source line `EXIT_REF` names."""
    line = read_index(KNOWLEDGE / "null-sources.json").rows[EXIT_REF].line
    return {"key": key, "name": name, "description": f"Fixture entry {name}.",
            "behaviour": f"Fixture behaviour of {name}.",
            "sources": [{"role": "emulator", "ref": EXIT_REF, "cites": line}], **fields}


def write_dictionary(folder: Path, dictionary: str, kind: str, scope: str,
                     entries: list[dict[str, Any]], **header: Any) -> Path:
    """A dictionary file in `folder`, marked as a fixture in its `covers`."""
    path = folder / f"{dictionary}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format": "scry-knowledge/1", "dictionary": dictionary, "kind": kind, "scope": scope,
        "covers": "FIXTURE of a test", "complete_against": EXIT_REF.rsplit(" case", 1)[0],
        "entries": entries, **header}), encoding="utf-8")
    return path


#: A quote's digest is only compared when a source is read, so a fixture may give any 64 hex.
FIXTURE_SHA = "0" * 64


def a_row(n: int, on: str, text: str, *, of: str = "doc",
          quotes: Iterable[tuple[str, str]] = ((EXIT_REF, "1"),)) -> dict[str, Any]:
    """One row of a dictionary of rows, citing a fixture line."""
    return {"n": str(n), "on": on, "of": of, "text": text,
            "quotes": [{"ref": ref, "lines": lines, "sha": FIXTURE_SHA}
                       for ref, lines in quotes]}


def write_rows(folder: Path, dictionary: str, kind: str, scope: str,
               entries: list[dict[str, Any]], *, title: str = "A synthetic dictionary",
               source: str = "official", **header: Any) -> Path:
    """A dictionary of rows (`scry-knowledge/2`) in `folder`, marked as a fixture in its
    `covers`."""
    path = folder / f"{dictionary}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "format": "scry-knowledge/2", "dictionary": dictionary, "title": title, "kind": kind,
        "scope": scope, "covers": "FIXTURE of a test", "source": source, "entries": entries,
        **header}), encoding="utf-8")
    return path


def rows_of(folder: Path, *names: str) -> rows_base.Base:
    """A base of rows holding every entry of the fixtures `names` (`rows/<name>`), copied into
    `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes((KNOWLEDGE / "rows" / name).read_bytes())
    base = rows_base.Base((folder,), None)
    assert base.faults() == [] and len(base) == len(names)
    return base

