"""A window request as an emulator's command-line words."""

from __future__ import annotations

import sys

from scry_core.reply_contract import Invalid
from scry_core.window import WindowRequest

#: How far inside its display a windowed run opens.
WINDOW_MARGIN_PX = 40

#: Where MAME's `-nowindow` opens a window the work area holds, never the display.
MAME_NO_FULLSCREEN_ON = ("darwin", "win32")


def dosbox_x(asked: WindowRequest) -> list[str]:
    """On macOS `sdl display` alone leaves a windowed run on display 0; a position places it."""
    words = ["-set", f"sdl display={asked.display}"]
    if asked.fullscreen:
        return [*words, "-fullscreen"]
    x, y = asked.origin
    return [*words, "-set", f"sdl windowposition={x + WINDOW_MARGIN_PX},{y + WINDOW_MARGIN_PX}"]


def refuse_mame_fullscreen(asked: WindowRequest) -> None:
    if asked.fullscreen and sys.platform in MAME_NO_FULLSCREEN_ON:
        raise Invalid("bad_argument",
                      "`fullscreen` cannot be proved on this host: MAME's `-nowindow` opens a "
                      "window the display's work area holds, never the display itself. Start "
                      "with `fullscreen=false`; the window is scaled to be seen")


def mame(asked: WindowRequest, resolution: str | None = None) -> list[str]:
    """A window of `resolution` (MAME's own when None), or the display where it can."""
    refuse_mame_fullscreen(asked)
    screen = ["-screen0", f"screen{asked.display}"]
    if asked.fullscreen:
        return ["-nowindow", *screen]
    return ["-window", "-nomaximize", *(["-resolution", resolution] if resolution else []),
            *screen]
