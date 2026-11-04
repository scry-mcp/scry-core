"""The size of a window, in the host's own unit (points on macOS, real pixels on Windows): parsed,
fitted to a display's usable area and judged against what the host lists; and the full-screen
rule of each emulator per platform."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Protocol

from scry_core.reply_contract import Invalid

if TYPE_CHECKING:
    from scry_core.window import Rect

Size = tuple[int, int]

#: The allowance on a macOS window's outer height: it has no client area.
TITLE_BAR_PX = 32
#: The widest frame an emulator window wears on Windows per unit of scale (menu included).
WINDOWS_FRAME_PX = (16, 59)

MAME_NO_FULLSCREEN_ON = ("darwin", "win32")
DOSBOX_X_HALTED_MAIN_ONLY_ON = "darwin"
DOSBOX_X_DROPS_NEGATIVE_POSITION_ON = "darwin"
#: Where a window sits inside its display's corner, clear of the menu bar and the edge.
WINDOW_MARGIN_PX = 40
MAME_HEIGHT_FREE_ON = "win32"


class Listed(Protocol):
    """A listed window: its outer rectangle and, where the host has one, its client area."""

    @property
    def bounds(self) -> tuple[int, int, int, int]: ...

    @property
    def client(self) -> Size | None: ...


def parse(text: str) -> Size:
    """`WIDTHxHEIGHT` in whole positive numbers; anything else is `bad_argument`."""
    parts = text.lower().split("x")
    if len(parts) == 2 and all(p.isascii() and p.isdigit() and int(p) > 0 for p in parts):
        return int(parts[0]), int(parts[1])
    raise Invalid("bad_argument", f"`size` is WIDTHxHEIGHT in whole positive numbers, "
                  f"like 1280x960; got {text!r}")


def refuse_unfit(asked: Size, usable: Rect, scale: float, platform: str) -> None:
    """`bad_argument` naming the usable size when `asked` plus the window's frame exceeds it."""
    room = _room(usable, scale, platform)
    if asked[0] > room[0] or asked[1] > room[1]:
        frame = _frame(platform, scale)
        raise Invalid("bad_argument",
                      f"`size` {asked[0]}x{asked[1]} does not fit: the usable area (menu bar, Dock "
                      f"and taskbar excluded) is {usable[2]}x{usable[3]} and a window frame takes "
                      f"up to {frame[0]}x{frame[1]} of it, so the largest size is "
                      f"{room[0]}x{room[1]}")


def unsupported_platform(verb: str, platform: str) -> Invalid:
    """The refusal of a host that is neither macOS nor Windows, said once for every module."""
    return Invalid("host_failed", f"a window is {verb} on macOS and Windows hosts, not {platform}")


def _frame(platform: str, scale: float) -> Size:
    if platform == "darwin":
        return 0, TITLE_BAR_PX
    if platform == "win32":
        return (math.ceil(WINDOWS_FRAME_PX[0] * scale), math.ceil(WINDOWS_FRAME_PX[1] * scale))
    raise unsupported_platform("sized", platform)


def _room(usable: Rect, scale: float, platform: str) -> Size:
    frame = _frame(platform, scale)
    return usable[2] - frame[0], usable[3] - frame[1]


def integer_fit(native: Size, usable: Rect, scale: float, platform: str) -> Size:
    """The largest whole multiple of `native` that fits the usable area, never below `native`."""
    width, height = _room(usable, scale, platform)
    n = max(1, min(width // native[0], height // native[1]))
    return native[0] * n, native[1] * n


def aspect_fit(aspect: Size, usable: Rect, scale: float, platform: str) -> Size:
    """The largest window of the `aspect` (width, height) that fits the usable area."""
    width, height = _room(usable, scale, platform)
    h = min(height, width * aspect[1] // aspect[0])
    return h * aspect[0] // aspect[1], h


def tolerance_px(scale: float) -> int:
    """How far a listed size may differ from the asked one."""
    return max(2, math.ceil(scale))


def height_free(emulator: str | None, platform: str) -> bool:
    return emulator == "mame" and platform == MAME_HEIGHT_FREE_ON


def refuse_fullscreen(emulator: str, display: int, platform: str, *, halted: bool) -> None:
    """The one place a platform fact about full screen is judged."""
    if emulator == "mame" and platform in MAME_NO_FULLSCREEN_ON:
        raise Invalid("bad_argument",
                      "`fullscreen` cannot be proved on this host: MAME's `-nowindow` opens a "
                      "window the display's work area holds, never the display itself. Start "
                      "with `fullscreen=false`; the window is scaled to be seen")
    if (emulator == "dosbox-x" and halted and display != 0
            and platform == DOSBOX_X_HALTED_MAIN_ONLY_ON):
        raise Invalid("bad_argument",
                      "`fullscreen` on a display other than 0 needs the emulator running, and "
                      "a start is halted at its first instruction, so the window would stay "
                      "windowed: use `display=0` for full screen, or `fullscreen=false` on "
                      f"display {display}")


def refuse_dropped_position(emulator: str, display: int, origin: tuple[int, int],
                            platform: str, *, halted: bool) -> None:
    """DOSBox-X ignores a `windowposition` with a negative coordinate (its source keeps only
    `posx >= 0 && posy >= 0`) and centres the window on the main display. Measured on macOS; the
    same guard is in its Windows code, which has not been measured. Full screen needs no position,
    but a halted start refuses it off display 0, so it is advised only to a running one."""
    if (emulator == "dosbox-x" and platform == DOSBOX_X_DROPS_NEGATIVE_POSITION_ON
            and min(origin) + WINDOW_MARGIN_PX < 0):
        way_out = ("use `display=0`, or a display at or right of and below the main one" if halted
                   else f"use `fullscreen=true` on display {display}, or a display at or right "
                        "of and below the main one")
        raise Invalid("bad_argument",
                      f"display {display} sits left of or above the main one, and DOSBox-X "
                      "ignores a negative window position, so its window would open on the main "
                      f"display: {way_out}")


def judge(asked: Size, seen: Listed, scale: float, *,
          height_free: bool = False) -> dict[str, Any]:
    """The listed window against the size asked, with the rectangle compared and the tolerance.
    Without a client area the outer width is compared and the height may add a title bar."""
    tol = tolerance_px(scale)
    if seen.client is not None:
        compared, (got_w, got_h) = "client", seen.client
        wide = abs(got_w - asked[0]) <= tol
        high = abs(got_h - asked[1]) <= tol
    else:
        compared, got_w, got_h = "outer", seen.bounds[2], seen.bounds[3]
        wide = abs(got_w - asked[0]) <= tol
        high = -tol <= got_h - asked[1] <= TITLE_BAR_PX + tol
    return {"asked": {"width": asked[0], "height": asked[1]},
            "seen": {"width": got_w, "height": got_h},
            "compared": compared, "tolerance_px": tol, "height_free": height_free,
            "matches": wide and (high or height_free)}
