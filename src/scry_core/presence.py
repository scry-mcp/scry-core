"""The emulator's window marked while a session holds it: `held` (dim), `acting` (bright) during
a driving call, fading back over `Look.fade_s`; and over that edge the layers of `overlay`,
carried by each delivery's `Payload`: a caption per call, the keys held, the pointer, a mark
while the machine is held stopped, a blinking mark while it records.

One writer per session sends only the latest state and payload, off the call's path, and wakes
on its own when a caption or a keycap is due to change. A driving call that ended before the
writer woke is still shown. Failures are retried every `RETRY_S` and reported by
`Presence.reply`, never in a call's own reply.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from scry_core import boundary
from scry_core import overlay as ov
from scry_core import overlay_timeline as tl
from scry_core.reply_contract import unavailable

State = Literal["held", "acting"]
Kind = Literal["video", "audio"]
Recording = Literal["none", "video", "audio", "both"]


@dataclass(frozen=True)
class Look:
    """Colours are 0xRRGGBB; alphas 0 to 1. A caption is tinted by its call: a call that can
    change the machine `write_rgb`, a reader `read_rgb`, one that did not answer `ok`
    `refused_rgb`. A caption wider than its band scrolls at `scroll_cps` characters a second.
    The recording mark is `record_rgb` and blinks once every `record_blink_s` seconds."""

    rgb: int = 0xFF8C00
    edge: float = 0.025
    steps: int = 6
    acting_alpha: float = 0.85
    held_share: float = 1 / 3
    fade_s: float = 2.5
    read_rgb: int = 0x5AC8FA
    refused_rgb: int = 0xFF453A
    caption_text_rgb: int = 0xFFFFFF
    caption_alpha: float = 0.7
    caption_hold_s: float = 3.0
    scroll_cps: float = 12.0
    keycap_rgb: int = 0x202020
    keycap_text_rgb: int = 0xFFFFFF
    keycap_alpha: float = 0.8
    keycap_min_s: float = 0.4
    record_rgb: int = 0xFF3B30
    record_blink_s: float = 1.0

    @property
    def held_alpha(self) -> float:
        return self.acting_alpha * self.held_share

    @property
    def write_rgb(self) -> int:
        """The edge's own colour."""
        return self.rgb

    @property
    def tints(self) -> tl.Tints:
        return tl.Tints(self.write_rgb, self.read_rgb, self.refused_rgb)


LOOK = Look()

ARGUMENT = ("Draw an edge around the emulator's window while this session is open: dim while "
            "idle, bright while a call runs the machine. No capture of this server carries it.")


class Unavailable(Exception):
    """The emulator cannot draw presence; the reply says why."""


@dataclass(frozen=True)
class Pointer:
    """Where the session last put the guest's pointer, in the guest's pixels, and the buttons it
    holds down, in the order they went down."""

    x: int
    y: int
    buttons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Payload:
    """What a delivery draws over the edge. `layers` are the ones asked (`overlay.Overlay`);
    `caption`, `keys` and `pointer` are empty, and `recording` is `none`, when their layer is
    not asked or nothing is due; `place` is the band the captions take, and the keycaps take the
    other edge."""

    paused: bool = False
    caption: tl.Caption | None = None
    keys: tuple[str, ...] = ()
    pointer: Pointer | None = None
    layers: tuple[ov.Layer, ...] = ("edge",)
    place: ov.Place = "bottom"
    recording: Recording = "none"


class Adapter(Protocol):
    """`show` raises `Unavailable` when it cannot draw, anything else on failure."""

    def show(self, state: State, payload: Payload) -> None: ...

    def repaint(self, still: Callable[[], bool]) -> None:
        """Have a STOPPED emulator draw the `held` just shown. Runs on the writer; takes the
        server's lock and does nothing unless `still()` holds there."""

    def wake(self) -> None:
        """Wake a repaint waiting for the lock; `close` runs under it."""


CLOSE_WAIT_S = 1.0
RETRY_S = 1.0

#: The tools that always run other calls inside one call: `perform` and `drive`. The overlay
#: shows what they run, never the wrapper; `start` is one only when it was given a plan.
BATCH_TOOLS = frozenset({"perform", "drive"})


def _wraps(call: boundary.Call) -> bool:
    """Whether the call is a wrapper, which is never captioned: what it runs is."""
    if call.nested:
        return False
    if call.tool == "start":
        return bool(call.given.get("plan"))
    return call.tool in BATCH_TOOLS


def _names(driving: Collection[str]) -> frozenset[str]:
    """`driving` as a set; a bare string would match no tool in silence, so it is refused."""
    if isinstance(driving, str):
        raise TypeError(f"the driving tools are a collection of names, never one string; got "
                        f"{driving!r}")
    return frozenset(driving)


class Presence:
    """One session's presence state and the writer that delivers it."""

    def __init__(self, adapter: Adapter, driving: Collection[str],
                 overlay: ov.Overlay = ov.OVERLAY, look: Look = LOOK) -> None:
        self._adapter = adapter
        self._driving = _names(driving)
        self._asked = overlay.asked()
        # The band never moves: an overlay asking for `auto` gets the bottom edge.
        self._place: ov.Place = "top" if overlay.place == "top" else "bottom"
        self._captions = tl.Captions(look.tints, look.caption_hold_s)
        self._keys = tl.Keycaps(look.keycap_min_s)
        self._pointer: Pointer | None = None
        self._paused = False
        self._recording: frozenset[Kind] = frozenset()
        self._cv = threading.Condition()
        self._want: State = "held"
        # None when nothing was sent or the last delivery failed.
        self._sent: tuple[State, Payload] | None = None
        self._again = False
        # A driving call began since `acting` was last sent: shown even if already ended.
        self._pulse = False
        self._closed = False
        self._failure = ""
        self._thread = threading.Thread(target=self._write, name="presence", daemon=True)

    @classmethod
    def open(cls, adapter: Adapter, driving: Collection[str],
             overlay: ov.Overlay = ov.OVERLAY, look: Look = LOOK) -> Shown:
        """Deliver the first `held` before `start` answers."""
        p = cls(adapter, driving, overlay, look)
        first = p._payload(time.monotonic())
        try:
            adapter.show("held", first)
        except Unavailable as e:
            return Shown(refused=unavailable(str(e)), adapter=adapter)
        except Exception as e:  # any failure of the first delivery is the reply's to say
            return Shown(refused=unavailable(
                f"the first delivery failed: {type(e).__name__}: {e}"), adapter=adapter)
        p._sent = ("held", first)
        p._thread.start()
        return Shown(held=p, adapter=adapter)

    def began(self, call: boundary.Call) -> None:
        with self._cv:
            if not call.nested and call.tool in self._driving:
                self._want = "acting"
                self._pulse = True
            if "calls" in self._asked and not _wraps(call):
                self._captions.began(call.tool, call.given, call.read_only, call.nested,
                                     time.monotonic(), named=call.named)
            self._cv.notify()

    def ended(self, call: boundary.Call, outcome: boundary.Outcome) -> None:
        with self._cv:
            if not call.nested and call.tool in self._driving:
                self._want = "held"
            if "calls" in self._asked and not _wraps(call):
                self._captions.ended(call.nested, outcome == "refused", time.monotonic())
            self._cv.notify()

    def key(self, name: str, down: bool) -> None:
        """A key, or on MAME a port field, went down or up."""
        with self._cv:
            if down:
                self._keys.down(name, time.monotonic())
            else:
                self._keys.up(name, time.monotonic())
            self._cv.notify()

    def moved(self, x: int, y: int) -> None:
        """The session put the guest's pointer at `x`, `y`."""
        with self._cv:
            held = self._pointer.buttons if self._pointer is not None else ()
            self._pointer = Pointer(x, y, held)
            self._cv.notify()

    def button(self, name: str, down: bool) -> None:
        """A pointer button went down or up; nothing until the pointer has moved."""
        with self._cv:
            if self._pointer is None:
                return
            rest = tuple(b for b in self._pointer.buttons if b != name)
            self._pointer = Pointer(self._pointer.x, self._pointer.y,
                                    (*rest, name) if down else rest)
            self._cv.notify()

    def paused(self, stopped: bool) -> None:
        """Whether the session holds the machine stopped."""
        with self._cv:
            self._paused = stopped
            self._cv.notify()

    def recording(self, kind: Kind, on: bool) -> None:
        """The session started (`on`) or ended a recording of `kind`; the other kind goes on."""
        with self._cv:
            self._recording = self._recording | {kind} if on else self._recording - {kind}
            self._cv.notify()

    @contextmanager
    def driving(self) -> Iterator[None]:
        """`acting` for the block (driving that is no call, e.g. a plan in `start`)."""
        self._set("acting")
        try:
            yield
        finally:
            self._set("held")

    def redeliver(self) -> None:
        """Send the current state again, for an adapter whose drawn content changed under it."""
        with self._cv:
            self._again = True
            self._cv.notify()

    def _set(self, state: State) -> None:
        with self._cv:
            self._want = state
            self._pulse = self._pulse or state == "acting"
            self._cv.notify()

    def reply(self) -> bool | dict[str, Any]:
        with self._cv:
            failure = self._failure
        return unavailable(failure) if failure else True

    def close(self) -> None:
        """Stop the writer; the window ends with the session, so nothing is sent."""
        with self._cv:
            self._closed = True
            self._cv.notify()
        self._adapter.wake()
        if self._thread.is_alive():
            self._thread.join(CLOSE_WAIT_S)

    def _payload(self, now: float) -> Payload:
        """Under the condition."""
        asked = self._asked
        return Payload(
            paused=self._paused and "pause" in asked,
            caption=self._captions.shown(now),
            keys=self._keys.shown(now) if "keys" in asked else (),
            pointer=self._pointer if "pointer" in asked else None,
            recording=self._recording_word() if "record" in asked else "none",
            layers=asked, place=self._place)

    def _recording_word(self) -> Recording:
        """Under the condition."""
        if self._recording == {"video", "audio"}:
            return "both"
        return next(iter(self._recording), "none")

    def _wait_s(self, now: float) -> float | None:
        """Until a caption or a keycap changes on its own, or None while none will."""
        due = [t for t in (self._captions.next_change(now), self._keys.next_change(now))
               if t is not None]
        return max(0.0, min(due) - now) if due else None

    def _due(self, payload: Payload) -> bool:
        sent = self._sent[0] if self._sent is not None else None
        return (self._again or self._sent is None or self._want != sent
                or payload != self._sent[1] or (self._pulse and sent != "acting"))

    def _write(self) -> None:
        while True:
            with self._cv:
                while True:
                    if self._closed:
                        return
                    now = time.monotonic()
                    payload = self._payload(now)
                    if self._due(payload):
                        break
                    self._cv.wait(self._wait_s(now))
                sent = self._sent[0] if self._sent is not None else None
                # A call that began while `acting` was showing was shown by it.
                self._pulse = self._pulse and sent != "acting"
                state: State = "acting" if self._pulse else self._want
                # A redeliver waits for the state after a pulse.
                self._again = self._again and self._pulse
                self._pulse = False
            try:
                self._adapter.show(state, payload)
                failure = ""
            except Exception as e:  # recorded for `status`: a display never fails a call
                failure = (str(e) if isinstance(e, Unavailable)
                           else f"a delivery failed: {type(e).__name__}: {e}")
            with self._cv:
                self._failure = failure
                if not failure:
                    self._sent = (state, payload)
                    repaint = state == "held"
                else:
                    # Resent after a pause unless the state moves on, else the old state
                    # would show until the next call.
                    self._sent = None
                    self._pulse = self._pulse or state == "acting"
                    self._cv.wait(RETRY_S)
                    continue
            if repaint:
                self._repaint()

    def _still_held(self) -> bool:
        with self._cv:
            return not self._closed and not self._due(self._payload(time.monotonic()))

    def _repaint(self) -> None:
        """Repaint the `held` just shown unless a call made it moot; a failure is recorded."""
        if not self._still_held():
            return
        try:
            self._adapter.repaint(self._still_held)
        except Exception as e:  # recorded for `status`: a display never fails a call
            with self._cv:
                self._failure = f"a repaint failed: {type(e).__name__}: {e}"


@dataclass
class Shown:
    """A session's presence: the writer, else `refused` (`false` when asked off, or why not).
    The input reports reach the writer, and nothing without one."""

    held: Presence | None = None
    refused: bool | dict[str, Any] = False
    adapter: Adapter | None = field(default=None, repr=False)

    def reply(self) -> bool | dict[str, Any]:
        return self.held.reply() if self.held is not None else self.refused

    @contextmanager
    def driving(self) -> Iterator[None]:
        if self.held is None:
            yield
            return
        with self.held.driving():
            yield

    def key(self, name: str, down: bool) -> None:
        if self.held is not None:
            self.held.key(name, down)

    def moved(self, x: int, y: int) -> None:
        if self.held is not None:
            self.held.moved(x, y)

    def button(self, name: str, down: bool) -> None:
        if self.held is not None:
            self.held.button(name, down)

    def paused(self, stopped: bool) -> None:
        if self.held is not None:
            self.held.paused(stopped)

    def recording(self, kind: Kind, on: bool) -> None:
        if self.held is not None:
            self.held.recording(kind, on)

    def close(self) -> None:
        if self.held is not None:
            self.held.close()


class Slot:
    """The boundary's `CallListener`; reads the presence through `current` at each call."""

    def __init__(self, current: Callable[[], Presence | None]) -> None:
        self._current = current

    def began(self, call: boundary.Call) -> None:
        if (p := self._current()) is not None:
            p.began(call)

    def ended(self, call: boundary.Call, outcome: boundary.Outcome) -> None:
        if (p := self._current()) is not None:
            p.ended(call, outcome)


def check_classified(registered: Iterable[str], driving: Collection[str],
                     still: Collection[str]) -> list[str]:
    """Problems in a driving/still declaration, each side written out so a new tool is placed on
    purpose; driving (`acting`) is a call that can move or change the guest, or cannot be told
    from one."""
    names, drive, rest = set(registered), _names(driving), _names(still)
    problems = [f"{n}: registered but declared neither driving nor still"
                for n in sorted(names - drive - rest)]
    problems += [f"{n}: declared but not registered" for n in sorted((drive | rest) - names)]
    problems += [f"{n}: declared both driving and still" for n in sorted(drive & rest)]
    return problems
