"""What the overlay shows at a moment: a call's caption and the keys held, decided here and
animated by the emulator. Time is passed in, so the rules are pure.

A call is captioned when it begins: nothing queues it and the next replaces it. One of the same
tool joins it (`x<n>`). A caption leaves `hold_s` after its call ends, and knows the span a
renderer fits a scroll in. A wrapper's inner calls are captioned one by one; the wrapper never.
Of the keys let go, only the most recent stays `min_s` after its press, fading over `fade_s`;
a new press ends it.
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
    one from the same text again; a call joining it keeps it. `span` is the seconds its call ran
    for, when known."""

    text: str
    kind: Kind
    rgb: int
    serial: int
    span: float | None = None


@dataclass
class _Entry:
    tool: str
    text: str
    kind: Kind
    repeats: int = 1
    up: float = 0.0
    ended: float | None = None
    serial: int = 0
    span: float | None = None

    def caption(self, tints: Tints) -> Caption:
        suffix = f" x{self.repeats}" if self.repeats > 1 else ""
        text = abbreviation.fit(self.text, abbreviation.MAX_BYTES - len(suffix)) + suffix
        return Caption(text, self.kind, tints.of(self.kind), self.serial, self._span())

    def _span(self) -> float | None:
        """What its first call was told, or what it took from going up to its call's end."""
        if self.span is not None:
            return self.span
        return None if self.ended is None else max(0.0, self.ended - self.up)


class Captions:
    """The caption timeline of one session."""

    def __init__(self, tints: Tints, hold_s: float) -> None:
        self._tints = tints
        self._hold_s = hold_s
        self._shown: _Entry | None = None
        # The calls in flight, outermost first; `ended` pops the last.
        self._open: list[_Entry] = []
        self._serial = 0

    def began(self, tool: str, given: Mapping[str, Any], read_only: bool, nested: bool,
              now: float, text: str | None = None,
              named: Mapping[str, Named] | None = None,
              span: float | None = None) -> None:
        """`text` is the caption already made, as a demo's timeline holds it; else `given`'s,
        with what the call's values are `named`. `span` is the seconds the call runs for, when
        known. A `nested` call is a step of a wrapper: captioned like any other, and what the
        wrapper is shown as."""
        self._advance(now)
        if nested and any(self._shown is entry for entry in self._open):
            # A wrapper: what it ran is shown, never it.
            self._shown = None
        text = abbreviation.caption(tool, given, named) if text is None else text
        kind: Kind = "read" if read_only else "write"
        joined = self._shown if self._shown is not None and self._shown.tool == tool else None
        entry = joined if joined is not None else _Entry(tool, text, kind)
        entry.text, entry.kind = text, kind
        entry.ended = None
        if span is not None:
            entry.span = span + (now - entry.up) if joined is not None else span
        self._open.append(entry)
        if joined is not None:
            joined.repeats += 1
            return
        self._up(entry, now)

    def ended(self, refused: bool, now: float) -> None:
        if not self._open:
            return
        entry = self._open.pop()
        if refused:
            entry.kind = "refused"
        entry.ended = now
        self._advance(now)

    def shown(self, now: float) -> Caption | None:
        self._advance(now)
        return self._shown.caption(self._tints) if self._shown is not None else None

    def next_change(self, now: float) -> float | None:
        """When `shown` next changes with no call, or None while nothing is due."""
        self._advance(now)
        shown = self._shown
        if shown is None or shown.ended is None:
            return None
        return shown.ended + self._hold_s

    def _up(self, entry: _Entry, now: float) -> None:
        self._serial += 1
        entry.up, entry.serial = now, self._serial
        self._shown = entry

    def _advance(self, now: float) -> None:
        shown = self._shown
        if shown is not None and shown.ended is not None and now >= shown.ended + self._hold_s:
            self._shown = None


@dataclass(frozen=True)
class _Key:
    down: float
    released_at: float | None = None


#: The marks as `snapshot` hands them back: opaque to everything but `restore`.
KeyState = dict[str, Any]

#: The steps a fading mark's alpha is quantised to.
FADE_LEVELS = 8


class Keycaps:
    """Keys drawn as held, or let go less than `min_s` after the press, fading over `fade_s`."""

    def __init__(self, min_s: float, fade_s: float = 0.0) -> None:
        self._min_s = min_s
        # A fade never outlasts the stay it is the tail of.
        self._fade_s = max(0.0, min(fade_s, min_s))
        self._keys: dict[str, _Key] = {}

    def down(self, name: str, now: float) -> None:
        # A new press ends the mark a key already let go kept, so a caption and its mark agree.
        for gone in [n for n, k in self._keys.items() if k.released_at is not None]:
            del self._keys[gone]
        key = self._keys.get(name)
        if key is None or key.released_at is not None:
            self._keys.pop(name, None)
            self._keys[name] = _Key(now)

    def up(self, name: str, now: float, linger: bool = True) -> None:
        """Let the key go: a key lingers its minimum, a click does not."""
        key = self._keys.get(name)
        if key is not None and not linger:
            del self._keys[name]
        elif key is not None:
            self._keys[name] = replace(key, released_at=now)
            # Only the last key let go lingers.
            for gone in [n for n, k in self._keys.items()
                         if k.released_at is not None and n != name]:
                del self._keys[gone]
        self._drop(now)

    def snapshot(self) -> KeyState:
        """The marks as they stand."""
        return dict(self._keys)

    def restore(self, state: KeyState) -> None:
        """The marks `snapshot` handed back."""
        self._keys = dict(state)

    def marks(self, now: float) -> tuple[tuple[str, float], ...]:
        self._drop(now)
        keep = self._kept()
        return tuple((n, self.alpha(n, now)) for n, k in self._keys.items()
                     if k.released_at is None or n == keep)

    def shown(self, now: float) -> tuple[str, ...]:
        """Every key drawn at `now`, in order, and of those let go only the last released."""
        return tuple(name for name, _ in self.marks(now))

    def alphas(self, now: float) -> tuple[float, ...]:
        return tuple(alpha for _, alpha in self.marks(now))

    def alpha(self, name: str, now: float) -> float:
        """`name`'s alpha at `now`: 1 while held, its fade once let go, 0 when gone."""
        key = self._keys.get(name)
        if key is None:
            return 0.0
        if key.released_at is None or self._fade_s <= 0:
            return 1.0
        return max(0.0, min(1.0, (self._end(key) - now) / self._fade_s))

    def next_change(self, now: float) -> float | None:
        """When the drawn marks next change, or None."""
        self._drop(now)
        keep = self._kept()
        if keep is None:
            return None
        end = self._end(self._keys[keep])
        start = end - self._fade_s
        if now < start:
            return start
        if self._fade_s <= 0:
            return end
        return min(end, now + self._fade_s / FADE_LEVELS)

    def _end(self, key: _Key) -> float:
        """When a mark let go is gone."""
        assert key.released_at is not None
        return max(key.down + self._min_s, key.released_at + self._fade_s)

    def _kept(self) -> str | None:
        """The key let go last; a tie goes to the last pressed."""
        best: str | None = None
        best_at = float("-inf")
        for name, key in self._keys.items():
            at = key.released_at
            if at is not None and at >= best_at:
                best, best_at = name, at
        return best

    def _drop(self, now: float) -> None:
        for name in [n for n, k in self._keys.items()
                     if k.released_at is not None and now >= self._end(k)]:
            del self._keys[name]
