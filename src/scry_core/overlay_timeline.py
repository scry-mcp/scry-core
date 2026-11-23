"""What the overlay shows at a given moment, decided here and only animated by the emulator: the
caption of the calls and the keycaps of the keys held. Time is passed in, so the rules are pure.

A caption stays up at least `min_s`. A call that arrives sooner waits, only the latest waiting;
one of the same tool joins the caption shown (`x<n>`), and a call's steps (`perform`, `drive`)
join their caller's caption as a count. Once its call has ended and nothing waits, a caption
leaves `hold_s` after that end. A key released sooner than `min_s` after it went down stays
until then, so a key sent in one call is still seen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from scry_core import abbreviation
from scry_core.naming import Named

Kind = Literal["write", "read", "refused"]


@dataclass(frozen=True)
class Tints:
    """0xRRGGBB per kind of call."""

    write: int
    read: int
    refused: int

    def of(self, kind: Kind) -> int:
        return {"write": self.write, "read": self.read, "refused": self.refused}[kind]


@dataclass(frozen=True)
class Caption:
    """One caption as drawn. `serial` grows with each new caption, so a renderer can tell a new
    one from the same text again; a call joining it keeps it."""

    text: str
    kind: Kind
    rgb: int
    serial: int


@dataclass
class _Entry:
    tool: str
    text: str
    kind: Kind
    repeats: int = 1
    steps: int = 0
    up: float = 0.0
    ended: float | None = None
    serial: int = 0

    def caption(self, tints: Tints) -> Caption:
        names = self.steps > 1 and (self.text.startswith("perform:") or "perform of" in self.text)
        suffix = (f" x{self.repeats}" if self.repeats > 1 else "") \
            + (f" ({self.steps} steps)" if self.steps > 1 and not names else "")
        text = abbreviation.fit(self.text, abbreviation.MAX_BYTES - len(suffix)) + suffix
        return Caption(text, self.kind, tints.of(self.kind), self.serial)


class Captions:
    """The caption timeline of one session."""

    def __init__(self, tints: Tints, min_s: float, hold_s: float) -> None:
        self._tints = tints
        self._min_s = min_s
        self._hold_s = hold_s
        self._shown: _Entry | None = None
        self._waiting: _Entry | None = None
        # The entry standing for the outermost call in flight.
        self._open: _Entry | None = None
        self._serial = 0

    def began(self, tool: str, given: Mapping[str, Any], read_only: bool, nested: bool,
              now: float, text: str | None = None,
              named: Mapping[str, Named] | None = None) -> None:
        """`text` is the caption already made, as a demo's timeline holds it; else `given`'s,
        with what the call's values are `named`."""
        if nested:
            if self._open is not None:
                self._open.steps += 1
            return
        self._advance(now)
        text = abbreviation.caption(tool, given, named) if text is None else text
        kind: Kind = "read" if read_only else "write"
        young = self._shown is not None and now - self._shown.up < self._min_s
        for joined in (self._waiting, self._shown if young and self._waiting is None else None):
            if joined is not None and joined.tool == tool:
                joined.repeats += 1
                joined.text, joined.kind, joined.ended = text, kind, None
                self._open = joined
                return
        entry = _Entry(tool, text, kind)
        if young:
            self._waiting = entry
        else:
            self._up(entry, now)
        self._open = entry

    def ended(self, nested: bool, refused: bool, now: float) -> None:
        if nested or self._open is None:
            return
        if refused:
            self._open.kind = "refused"
        self._open.ended = now
        self._open = None
        self._advance(now)

    def shown(self, now: float) -> Caption | None:
        self._advance(now)
        return self._shown.caption(self._tints) if self._shown is not None else None

    def next_change(self, now: float) -> float | None:
        """When `shown` next changes with no call, or None while nothing is due."""
        self._advance(now)
        shown = self._shown
        if shown is None:
            return None
        if self._waiting is not None:
            return shown.up + self._min_s
        if shown.ended is None:
            return None
        return max(shown.up + self._min_s, shown.ended + self._hold_s)

    def _up(self, entry: _Entry, now: float) -> None:
        self._serial += 1
        entry.up, entry.serial = now, self._serial
        self._shown = entry

    def _advance(self, now: float) -> None:
        shown = self._shown
        if shown is None or now - shown.up < self._min_s:
            return
        if self._waiting is not None:
            self._up(self._waiting, now)
            self._waiting = None
        elif shown.ended is not None and now >= shown.ended + self._hold_s:
            self._shown = None


@dataclass(frozen=True)
class _Key:
    down: float
    released: bool = False


class Keycaps:
    """The keys or fields drawn as held: down, or released less than `min_s` after going down."""

    def __init__(self, min_s: float) -> None:
        self._min_s = min_s
        self._keys: dict[str, _Key] = {}

    def down(self, name: str, now: float) -> None:
        key = self._keys.get(name)
        if key is None or key.released:
            self._keys.pop(name, None)
            self._keys[name] = _Key(now)

    def up(self, name: str, now: float) -> None:
        if (key := self._keys.get(name)) is not None:
            self._keys[name] = replace(key, released=True)
        self._drop(now)

    def shown(self, now: float) -> tuple[str, ...]:
        """In the order they went down."""
        self._drop(now)
        return tuple(self._keys)

    def next_change(self, now: float) -> float | None:
        self._drop(now)
        due = [k.down + self._min_s for k in self._keys.values() if k.released]
        return min(due, default=None)

    def _drop(self, now: float) -> None:
        for name in [n for n, k in self._keys.items()
                     if k.released and now - k.down >= self._min_s]:
            del self._keys[name]
