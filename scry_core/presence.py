"""THE PRESENCE INDICATOR: the emulator's window marked while a session holds it, brighter while a
call drives it, so whoever sits at the host can tell at a glance whether to keep their hands off
and whether a session is still there to wait for.

TWO STATES. `held` from the session's start to its close, dim; `acting` while a driving call
runs, bright, fading back to `held` over `Look.fade_s` once the call ends (the emulator fades: it
is the one that repaints). Nothing is sent at a close, because the window ends with the session.
Which calls drive is each server's to declare, and `check_classified` holds that declaration
against the server's registry, so a new tool has to be put on one side. The boundary reports
every outermost call's begin and end through a `Slot`.

THE LOOK IS HELD HERE, ONCE (`LOOK`), for two emulators that draw it in different ways, each
server translating it for its own: a tuning lands in both from this one place. The edge is drawn
by both; the pointer where the emulator has a guest pointer to mark.

DELIVERY IS OFF THE CALL'S PATH. One writer per session sends only the latest state, so a call
never waits on the emulator and two states can never arrive out of order. A driving call over
before the writer woke is still shown, `acting` before the `held` after it, or the quickest calls
would never light the window. A delivery that fails is retried every `RETRY_S` until one lands or
the state moves on, and is said where it is asked for (`Presence.reply`, which `start` and
`status` carry); it never changes a call's own reply, because presence is a display and not a
contract of the call. After a `held` lands the writer asks the adapter to repaint
(`Adapter.repaint`), skipped when a call began meanwhile; a repaint that fails is said the same
way and not retried.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from scry_core.reply_contract import unavailable

State = Literal["held", "acting"]

#: The arrow drawn at the guest's pointer, its hot spot at the top-left corner: `X` the outline,
#: `o` the fill, `.` untouched.
ARROW = (
    "X...........",
    "XX..........",
    "XoX.........",
    "XooX........",
    "XoooX.......",
    "XooooX......",
    "XoooooX.....",
    "XooooooX....",
    "XoooooooX...",
    "XooooooooX..",
    "XoooooooooX.",
    "XooooooXXXXX",
    "XoooXooX....",
    "XooX.XooX...",
    "XoX..XooX...",
    "XX....XooX..",
    "X.....XooX..",
    ".......XooX.",
    ".......XX...",
)


@dataclass(frozen=True)
class Look:
    """How presence is drawn: the edge by both emulators, the pointer where there is a guest
    pointer. Colours are 0xRRGGBB; alphas run 0 to 1."""

    rgb: int = 0xFF8C00
    #: The edge's width, as a fraction of the shorter side of the picture the emulator draws on.
    edge: float = 0.025
    #: The bands the edge's gradient is drawn in, strongest at the rim and fading inwards.
    steps: int = 6
    acting_alpha: float = 0.85
    #: `held` as a share of `acting`: there, but not calling for attention.
    held_share: float = 1 / 3
    #: From the end of a driving call back to `held`.
    fade_s: float = 2.5
    pointer: tuple[str, ...] = ARROW
    pointer_outline_rgb: int = 0x2A1400
    #: The arrow's height, as a fraction of the window's shorter side.
    pointer_size: float = 0.06
    #: How long the pointer takes to glide to where the guest's moved, easing out: it moves the
    #: way a hand does, and nothing waits on it, since it is drawing only.
    pointer_glide_s: float = 0.2

    @property
    def held_alpha(self) -> float:
        return self.acting_alpha * self.held_share


LOOK = Look()

#: `start`'s `presence` argument as its schema describes it, the same on both servers.
ARGUMENT = ("Draw an edge around the emulator's window while this session is open: dim while "
            "idle, bright while a call runs the machine. No capture of this server carries it.")


class Unavailable(Exception):
    """The emulator cannot draw presence at all, and why (no window, a build whose channel has
    no `PRESENCE`): said in the reply in place of `true`."""


class Adapter(Protocol):
    """A server's way of drawing a state in its emulator. `show` raises `Unavailable` when the
    emulator cannot draw, anything else when a delivery failed; both are recorded."""

    def show(self, state: State) -> None: ...

    def repaint(self, still: Callable[[], bool]) -> None:
        """Have a STOPPED emulator draw the `held` just shown: an emulator that repaints only
        when told (MAME at its debugger) would otherwise keep the bright edge of the call's stop.
        It runs on the writer, so it returns promptly, takes the server's lock (between calls)
        and does nothing unless `still()` holds there and the machine is stopped. A no-op for
        an emulator that repaints on its own."""

    def wake(self) -> None:
        """Have a repaint that waits for the lock ask `still()` again now: the writer closed
        under the lock, so no release will come to wake it before `close` gives up waiting.
        A no-op for an adapter whose repaint never waits."""


#: How long `close` waits for a delivery in flight.
CLOSE_WAIT_S = 1.0
#: How long after a failed delivery the writer tries the same state again.
RETRY_S = 1.0


def _names(driving: Collection[str]) -> frozenset[str]:
    """`driving` as a set of names: one string is refused, since it would be read as a set of
    its letters and match no tool, in silence."""
    if isinstance(driving, str):
        raise TypeError(f"the driving tools are a collection of names, never one string; got "
                        f"{driving!r}")
    return frozenset(driving)


class Presence:
    """One session's presence: the state its calls set, and the writer that delivers it. Made
    by `open`, which has delivered the first state and started the writer."""

    def __init__(self, adapter: Adapter, driving: Collection[str]) -> None:
        self._adapter = adapter
        self._driving = _names(driving)
        self._cv = threading.Condition()
        self._want: State = "held"
        # What the emulator was last told, or None when the last delivery failed (so it is sent
        # again) or nothing was ever told.
        self._sent: State | None = None
        self._again = False
        # A driving call began since `acting` was last sent: shown even if it already ended.
        self._pulse = False
        self._closed = False
        self._failure = ""
        self._thread = threading.Thread(target=self._write, name="presence", daemon=True)

    @classmethod
    def open(cls, adapter: Adapter, driving: Collection[str]) -> Shown:
        """The session's presence, its first `held` delivered NOW, before `start` answers, so the
        reply can say whether it is drawn; unavailable with why when it cannot be."""
        p = cls(adapter, driving)
        try:
            adapter.show("held")
        except Unavailable as e:
            return Shown(refused=unavailable(str(e)), adapter=adapter)
        except Exception as e:  # any failure of the first delivery is the reply's to say
            return Shown(refused=unavailable(
                f"the first delivery failed: {type(e).__name__}: {e}"), adapter=adapter)
        p._sent = "held"
        p._thread.start()
        return Shown(held=p, adapter=adapter)

    def began(self, tool: str) -> None:
        """A call to `tool` began: `acting` if it drives."""
        if tool in self._driving:
            self._set("acting")

    def ended(self, tool: str) -> None:
        """A call to `tool` ended: back to `held` if it drove."""
        if tool in self._driving:
            self._set("held")

    @contextmanager
    def driving(self) -> Iterator[None]:
        """`acting` for the block, as a driving call is: for what drives the machine without
        being a call of its own (a plan run inside `start`)."""
        self._set("acting")
        try:
            yield
        finally:
            self._set("held")

    def redeliver(self) -> None:
        """Send the current state again, for an adapter whose own part of the drawing changed
        (DOSBox-X's pointer, turned on by the session's first mouse move)."""
        with self._cv:
            self._again = True
            self._cv.notify()

    def _set(self, state: State) -> None:
        with self._cv:
            self._want = state
            self._pulse = self._pulse or state == "acting"
            self._cv.notify()

    def reply(self) -> bool | dict[str, Any]:
        """What `status` says: `true`, or why the last delivery or repaint did not land."""
        with self._cv:
            failure = self._failure
        return unavailable(failure) if failure else True

    def close(self) -> None:
        """The writer stopped; nothing more is sent, because the window ends with the session.
        A delivery in flight is not waited for past `CLOSE_WAIT_S`: it fails on its own once the
        emulator is gone."""
        with self._cv:
            self._closed = True
            self._cv.notify()
        self._adapter.wake()
        if self._thread.is_alive():
            self._thread.join(CLOSE_WAIT_S)

    def _due(self) -> bool:
        return (self._again or self._want != self._sent
                or (self._pulse and self._sent != "acting"))

    def _write(self) -> None:
        while True:
            with self._cv:
                while not self._closed and not self._due():
                    self._cv.wait()
                if self._closed:
                    return
                # A call that began while the window already showed `acting` was shown by it.
                self._pulse = self._pulse and self._sent != "acting"
                state: State = "acting" if self._pulse else self._want
                # A redeliver waits for the state after a pulse, which is the one it is for.
                self._again = self._again and self._pulse
                self._pulse = False
            try:
                self._adapter.show(state)
                failure = ""
            except Exception as e:  # recorded for `status`: a display never fails a call
                failure = (str(e) if isinstance(e, Unavailable)
                           else f"a delivery failed: {type(e).__name__}: {e}")
            with self._cv:
                self._failure = failure
                if not failure:
                    self._sent = state
                    repaint = state == "held"
                else:
                    # SENT AGAIN, after a pause, unless the state moves on first: a window left
                    # showing the state before a lost delivery would show it until the next call.
                    self._sent = None
                    self._pulse = self._pulse or state == "acting"
                    self._cv.wait(RETRY_S)
                    continue
            if repaint:
                self._repaint()

    def _still_held(self) -> bool:
        """Whether `held` is still the last word and nothing moved on since it was shown."""
        with self._cv:
            return not self._closed and not self._due()

    def _repaint(self) -> None:
        """The adapter's repaint of the `held` just shown, unless a call made it moot; a failure
        is recorded as a delivery's is, and the next state that lands clears it."""
        if not self._still_held():
            return
        try:
            self._adapter.repaint(self._still_held)
        except Exception as e:  # recorded for `status`: a display never fails a call
            with self._cv:
                self._failure = f"a repaint failed: {type(e).__name__}: {e}"


@dataclass
class Shown:
    """One session's presence as a server keeps it: the writer when it is drawn (`held`), else
    what `start` answered about it (`refused`: `false` asked off, or why it could not be), and
    the adapter it was opened on."""

    held: Presence | None = None
    refused: bool | dict[str, Any] = False
    adapter: Adapter | None = field(default=None, repr=False)

    def reply(self) -> bool | dict[str, Any]:
        """What `start` and `status` say: `true` drawn, `false` asked off, or why not (the last
        delivery's failure included)."""
        return self.held.reply() if self.held is not None else self.refused

    @contextmanager
    def driving(self) -> Iterator[None]:
        """`Presence.driving`, or nothing when it is not drawn."""
        if self.held is None:
            yield
            return
        with self.held.driving():
            yield

    def close(self) -> None:
        if self.held is not None:
            self.held.close()


class Slot:
    """What the boundary reports a call to (`scry_core.boundary.CallListener`): the presence of
    the session in place, read through `current` at each call, so the server's session state
    stays the one place it is held."""

    def __init__(self, current: Callable[[], Presence | None]) -> None:
        self._current = current

    def began(self, tool: str) -> None:
        """Forwarded to the session's presence, if it has one."""
        if (p := self._current()) is not None:
            p.began(tool)

    def ended(self, tool: str) -> None:
        """Forwarded to the session's presence, if it has one."""
        if (p := self._current()) is not None:
            p.ended(tool)


def check_classified(registered: Iterable[str], driving: Collection[str],
                     still: Collection[str]) -> list[str]:
    """What is wrong with a server's declaration of which tools drive the machine, every tool it
    registers on exactly one side: [] when nothing is."""
    names, drive, rest = set(registered), _names(driving), _names(still)
    problems = [f"{n}: registered but declared neither driving nor still"
                for n in sorted(names - drive - rest)]
    problems += [f"{n}: declared but not registered" for n in sorted((drive | rest) - names)]
    problems += [f"{n}: declared both driving and still" for n in sorted(drive & rest)]
    return problems
