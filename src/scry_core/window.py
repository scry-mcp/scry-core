"""The window a server was asked to open, as the host shows it: asked for (`request`), found
(`state_of`), read as it stands (`observe`), waited for (`wait_visible`) and brought forward
(`bring_front`).

A request carries the display's index and origin; this reads back where the window landed.
`WindowState.block()` is a reply's `window` block.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from scry_core import window_size
from scry_core.live_host import BACKGROUND_VAR as BACKGROUND_VAR
from scry_core.reply_contract import Invalid

Rect = tuple[int, int, int, int]       # x, y, width, height, in the host's own units

#: `WindowState.display` of a window whose centre is on none of the host's displays.
NO_DISPLAY = -1
#: Seconds between two readings of the host's window list.
POLL_S = 0.25
#: Seconds a watched start, and the `window` tool, wait on the host's window list.
WAIT_S = 10.0


@dataclass(frozen=True)
class Display:
    """A display by the OS's index (0 is the main one). `usable` excludes menu bar, Dock and
    taskbar (None: the host did not say); `scale` is the host's unit per logical pixel."""

    index: int
    bounds: Rect
    usable: Rect | None = None
    scale: float = 1.0

    @property
    def work(self) -> Rect:
        return self.bounds if self.usable is None else self.usable


@dataclass(frozen=True)
class Seen:
    """One window as the host lists it. `number` is the host's own handle for it."""

    pid: int
    number: int
    bounds: Rect
    onscreen: bool
    #: Width and height inside the frame (Windows); None where there is no client area.
    client: tuple[int, int] | None = None


class Host(Protocol):
    """What the host answers: displays, ordinary windows, those above one, and an activation."""

    def displays(self) -> list[Display]: ...

    def windows(self) -> list[Seen]: ...

    def above(self, window: Seen) -> list[Seen]:
        """The windows on screen above `window`."""
        ...

    def activate(self, window: Seen) -> str: ...


@dataclass(frozen=True)
class WindowRequest:
    display: int
    fullscreen: bool
    origin: tuple[int, int]
    #: In the host's unit; None leaves it to the emulator.
    size: tuple[int, int] | None = None
    scale: float = 1.0
    usable: Rect | None = None
    #: The emulator fits the height to its aspect (MAME on Windows).
    height_free: bool = False
    #: The server chose `size`: the words carry it, `window` does not judge it.
    fitted: bool = False


def _count(n: int) -> str:
    return f"{n} display{'' if n == 1 else 's'} ({'0' if n == 1 else f'0 to {n - 1}'})"


def request(display: int | None, fullscreen: bool | None, *, shared: bool,
            displays: list[Display], size: str | None = None, emulator: str | None = None,
            platform: str | None = None, halted: bool = True) -> WindowRequest | None:
    """The window a `start` asked for, or None for a run nobody watches.

    An omitted display is the main one. The window arguments act only on a watched start and are
    refused on any other. Naming the `emulator` judges its full-screen rule for `platform` here,
    once; `halted` is a start parked at its debugger."""
    if not shared:
        given = [name for name, value in (("display", display), ("fullscreen", fullscreen),
                                          ("size", size))
                 if value is not None]
        if given:
            raise Invalid("bad_argument",
                          f"`{'` and `'.join(given)}` place a window nobody asked to open: they "
                          f"act with `shared=true`; leave {'it' if len(given) == 1 else 'them'} "
                          f"out for an unwatched run")
        return None
    if not displays:
        raise Invalid("host_failed",
                      "the host reports no display online, so there is nowhere to open a window: "
                      "wake the displays and ask again")
    chosen = 0 if display is None else display
    where = next((d for d in displays if d.index == chosen), None)
    if where is None:
        raise Invalid("bad_argument",
                      f"`display` {chosen} does not exist: this host has {_count(len(displays))}")
    platform = platform or sys.platform
    if emulator is not None and fullscreen:
        window_size.refuse_fullscreen(emulator, chosen, platform, halted=halted)
    asked = None if size is None else window_size.parse(size)
    if asked is not None:
        if fullscreen:
            raise Invalid("bad_argument", "`size` and `fullscreen` contradict: full screen is the "
                          "display's own size; leave one out")
        window_size.refuse_unfit(asked, where.work, where.scale, platform)
    return WindowRequest(chosen, bool(fullscreen), where.bounds[:2], asked, where.scale,
                         where.work,
                         window_size.height_free(emulator, platform) and asked is not None)


@dataclass(frozen=True)
class WindowState:
    """Where the window is and whether it is shown; `front` is no other application's window
    covering its centre."""

    display: int
    bounds: Rect
    onscreen: bool
    front: bool
    fullscreen: bool
    client: tuple[int, int] | None = None

    def block(self) -> dict[str, Any]:
        x, y, width, height = self.bounds
        return {"display": self.display,
                "bounds": {"x": x, "y": y, "width": width, "height": height},
                "onscreen": self.onscreen, "front": self.front, "fullscreen": self.fullscreen}


def _centre(r: Rect) -> tuple[float, float]:
    return r[0] + r[2] / 2, r[1] + r[3] / 2


def _holds(r: Rect, point: tuple[float, float]) -> bool:
    return r[0] <= point[0] < r[0] + r[2] and r[1] <= point[1] < r[1] + r[3]


def above_in_order(listed: list[Seen]) -> Callable[[Seen], list[Seen]]:
    """`Host.above` for a host whose list is already front to back (Windows). The window is
    found by its handle: its bounds may have moved since the reading `window` came from."""
    def above(window: Seen) -> list[Seen]:
        at = next((n for n, s in enumerate(listed) if s.number == window.number), None)
        return [] if at is None else [s for s in listed[:at] if s.onscreen]
    return above


def main_window(pid: int, listed: list[Seen]) -> Seen | None:
    """The largest window `pid` owns; an emulator also lists small auxiliary ones."""
    mine = [s for s in listed if s.pid == pid]
    return max(mine, key=lambda s: s.bounds[2] * s.bounds[3]) if mine else None


def state_of(pid: int, listed: list[Seen], displays: list[Display],
             above: Callable[[Seen], list[Seen]]) -> WindowState | None:
    """The largest window `pid` owns among `listed`, or None when it owns none. `above` answers
    which windows are over a given one."""
    window = main_window(pid, listed)
    if window is None:
        return None
    centre = _centre(window.bounds)
    on = next((d for d in displays if _holds(d.bounds, centre)), None)
    covered = not window.onscreen or any(
        s.onscreen and s.pid != pid and _holds(s.bounds, centre) for s in above(window))
    return WindowState(display=NO_DISPLAY if on is None else on.index, bounds=window.bounds,
                       onscreen=window.onscreen, front=not covered,
                       fullscreen=on is not None and window.bounds == on.bounds,
                       client=window.client)


def _not_visible(message: str, **fields: Any) -> Invalid:
    return Invalid("window_not_visible", message, **fields)


def _read(pid: int, host: Host) -> WindowState | None:
    return state_of(pid, host.windows(), host.displays(), host.above)


def observe(pid: int, host: Host) -> WindowState:
    """The window `pid` owns, on whatever display; `window_not_visible` when it owns none."""
    state = _read(pid, host)
    if state is None:
        raise _not_visible(f"no window of pid {pid} is listed: the emulator has none open, or the "
                           f"host's window list cannot be read; call `status`")
    return state


def _wait(pid: int, host: Host, bound_s: float, clock: Callable[[], float],
          sleep: Callable[[float], None],
          done: Callable[[WindowState | None], bool]) -> WindowState | None:
    """The last reading, once `done` accepts one or the bound passes."""
    end = clock() + bound_s
    while True:
        state = _read(pid, host)
        if done(state) or clock() >= end:
            return state
        sleep(POLL_S)


def wait_visible(pid: int, display: int, bound_s: float, host: Host,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, *,
                 shell: bool = False) -> WindowState:
    """The window `pid` opened on `display`, waited for up to `bound_s` seconds.

    A window listed but not shown (`onscreen` false) is returned and says so; one that never
    appears, or appears on another display, is `window_not_visible`. `shell` words the next step
    for a caller with no server's tools (the `window_cli` program)."""
    state = _wait(pid, host, bound_s, clock, sleep,
                  lambda s: s is not None and s.display == display)
    if state is None:
        raise _not_visible(
            f"no window of pid {pid} appeared within {bound_s:g} s: the emulator did not open "
            f"one, or the host's window list cannot be read (a sleeping display lists none); "
            + ("read the emulator's own output" if shell
               else "call `status` and read the emulator's log"), asked_display=display)
    if state.display != display:
        where = ("on none of the host's displays" if state.display == NO_DISPLAY
                 else f"on display {state.display}")
        raise _not_visible(
            f"the window of pid {pid} opened {where}, not on display {display}: "
            + ("stop the process and run again with the display it should be seen on" if shell
               else "close the session and start again with `display` set to where it should "
                    "be seen"),
            asked_display=display, seen=state.block())
    return state


def bring_front(pid: int, host: Host, bound_s: float,
                clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep, *,
                launched_behind: bool) -> WindowState:
    """The window of `pid` in front of whatever covers it, read back; `window_not_visible` when it
    is still not shown or still covered after `bound_s` seconds. `launched_behind` marks a session
    started as a background application."""
    first = _read(pid, host)
    if first is not None and first.front:
        return first
    why = ""
    if (listed := main_window(pid, host.windows())) is not None:
        why = host.activate(listed)
    state = _wait(pid, host, bound_s, clock, sleep, lambda s: s is not None and s.front)
    if state is not None and state.front:
        return state
    if state is None:
        raise _not_visible(f"no window of pid {pid} is listed to bring forward: call `status`",
                           activation=why or "none was tried")
    problem = ("the window is not on screen" if not state.onscreen
               else "the window is covered by another application's window")
    cause = ("; this session was started with `background=true`, which may be what keeps it "
             "behind: `close` and `start` again with `background=false`" if launched_behind else "")
    raise _not_visible(
        f"{problem} after the activation ({why or 'which reported no error'}): it is on a "
        f"Space that is not shown, or something is in front of it{cause}", seen=state.block())


def requested(shared: bool, display: int | None, fullscreen: bool | None, size: str | None = None,
              emulator: str | None = None, halted: bool = True) -> WindowRequest | None:
    """`request` for a server's `start`; the host's displays are read only when watched."""
    return request(display, fullscreen, shared=shared, size=size, emulator=emulator,
                   halted=halted, displays=host().displays() if shared else [])


def prove(pid: int, asked: WindowRequest, bound_s: float | None = None,
          where: Host | None = None, *, shell: bool = False) -> WindowState:
    """The window `pid` opened as `asked`, waited for up to `bound_s`; a `fullscreen` that does not
    fill its display is refused. The refusal leaves the session live, so `window` and `close`
    still act. `shell` words the next steps for a caller with no server's tools."""
    where = where or host()
    bound_s = WAIT_S if bound_s is None else bound_s
    began = time.monotonic()
    proved = wait_visible(pid, asked.display, bound_s, where, shell=shell)
    unfilled = asked.fullscreen and not proved.fullscreen
    if unfilled:
        # An emulator placed by position shows its window first and fills the display after.
        left = max(0.0, bound_s - (time.monotonic() - began))
        def filled(s: WindowState | None) -> bool:
            return s is not None and s.display == asked.display and s.fullscreen

        later = _wait(pid, where, left, time.monotonic, time.sleep, filled)
        if later is not None and filled(later):
            proved, unfilled = later, False
    if unfilled:
        raise _not_visible("the window opened on the asked display but does not fill it, which "
                           "`fullscreen` asked for. An emulator parked at its debugger fills the "
                           "display only once it runs: "
                           + ("prove it again once it runs; if it still does not fill, run it "
                              "again without `--fullscreen`" if shell else
                              "`resume` it and read `window` again; if it still does not fill, "
                              "`close` and start again with `fullscreen=false`"),
                           asked_display=asked.display, seen=proved.block())
    return proved


def answer(pid: int, asked: WindowRequest | None, *, front: bool,
           launched_behind: bool) -> dict[str, Any]:
    """The `window` tool's reply fields: where the window is, brought forward on `front`;
    `no_channel` for a session started without a window request."""
    if asked is None:
        raise Invalid("no_channel", "this session was started without `shared=true`, so the "
                      "server placed no window and proves none: close it and start again with "
                      "`shared=true`")
    where = host()
    state = (bring_front(pid, where, WAIT_S, launched_behind=launched_behind) if front
             else observe(pid, where))
    reply: dict[str, Any] = {"window": state.block()}
    if asked.size is not None and not asked.fitted:
        reply["size"] = window_size.judge(asked.size, state, asked.scale,
                                          height_free=asked.height_free)
    return reply


def summary(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """The one line `window` answers with in a transcript."""
    seen = reply.get("window") or {}
    return (f"window: display {seen.get('display')}, "
            f"{'on screen' if seen.get('onscreen') else 'off screen'}, "
            f"{'in front' if seen.get('front') else 'covered'}")


def judge_background(background: bool | None, watched: bool) -> bool:
    """Whether an emulator launches behind: `background` when given, else unless watched."""
    return not watched if background is None else background


def launch_environment(base: Mapping[str, str], background: bool) -> dict[str, str]:
    """`base` with the background hint (`BACKGROUND_VAR`) set or removed, never inherited, so a
    launch behind never takes the owner's front application and a watched one may."""
    spawned = dict(base)
    if background:
        spawned[BACKGROUND_VAR] = "1"
    else:
        spawned.pop(BACKGROUND_VAR, None)
    return spawned


def host(platform: str = sys.platform) -> Host:
    """The host of `platform`; any other is a `host_failed` refusal naming it."""
    from scry_core import window_host
    return window_host.for_platform(platform)
