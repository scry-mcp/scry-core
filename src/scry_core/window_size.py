"""The size of a window, in the host's own unit (points on macOS, real pixels on Windows): parsed,
fitted to a display's usable area and judged against what the host lists; and the full-screen
rule of each emulator per platform."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Protocol

from scry_core.reply_contract import Invalid

if TYPE_CHECKING:
    from scry_core.window import Display

Size = tuple[int, int]

#: The allowance on a macOS window's outer height: it has no client area.
TITLE_BAR_PX = 32
#: The widest frame an emulator window wears on Windows per unit of scale (menu included).
WINDOWS_FRAME_PX = (16, 59)

MAME_NO_FULLSCREEN_ON = ("darwin", "win32")
DOSBOX_X_HALTED_MAIN_ONLY_ON = "darwin"
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


def refuse_unfit(asked: Size, display: Display) -> None:
    """`bad_argument` naming the display's usable size when `asked` does not fit it."""
    _, _, width, height = display.work
    if asked[0] > width or asked[1] > height:
        raise Invalid("bad_argument",
                      f"`size` {asked[0]}x{asked[1]} does not fit display {display.index}, whose "
                      f"usable area (menu bar, Dock and taskbar excluded) is {width}x{height}")


def _frame(platform: str, scale: float) -> Size:
    if platform == "darwin":
        return 0, TITLE_BAR_PX
    if platform == "win32":
        return (math.ceil(WINDOWS_FRAME_PX[0] * scale), math.ceil(WINDOWS_FRAME_PX[1] * scale))
    raise Invalid("host_failed", f"a window is sized on macOS and Windows hosts, not {platform}")


def _room(display: Display, platform: str) -> Size:
    frame = _frame(platform, display.scale)
    return display.work[2] - frame[0], display.work[3] - frame[1]


def integer_fit(native: Size, display: Display, platform: str) -> Size:
    """The largest whole multiple of `native` that fits the usable area, never below `native`."""
    width, height = _room(display, platform)
    n = max(1, min(width // native[0], height // native[1]))
    return native[0] * n, native[1] * n


def aspect_fit(aspect: Size, display: Display, platform: str) -> Size:
    """The largest window of the `aspect` (width, height) that fits the usable area."""
    width, height = _room(display, platform)
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
