"""A window request as an emulator's command-line words."""

from __future__ import annotations

import sys

from scry_core.window import WindowRequest
from scry_core.window_size import MAME_HEIGHT_FREE_ON

WINDOW_MARGIN_PX = 40


def dosbox_x(asked: WindowRequest) -> list[str]:
    """A position places a macOS run, `sdl display` alone leaves it on display 0."""
    words = ["-set", f"sdl display={asked.display}"]
    if asked.fullscreen:
        return [*words, "-fullscreen"]
    x, y = asked.origin
    words += ["-set", f"sdl windowposition={x + WINDOW_MARGIN_PX},{y + WINDOW_MARGIN_PX}"]
    if asked.size is not None:
        width, height = (round(side / asked.scale) for side in asked.size)
        words += ["-set", f"sdl windowresolution={width}x{height}"]
    return words


def mame(asked: WindowRequest, resolution: str | None = None, *,
         platform: str = sys.platform) -> list[str]:
    """A window of the stated size, else `resolution`, or the display where it can. Windows' OSD
    reads `-resolution` as a cap under `-nomaximize`, so a stated size drops it there."""
    screen = ["-screen0", f"screen{asked.display}"]
    if asked.fullscreen:
        return ["-nowindow", *screen]
    if asked.size is not None:
        resolution = f"{asked.size[0]}x{asked.size[1]}"
    keep = [] if asked.size is not None and platform == MAME_HEIGHT_FREE_ON else ["-nomaximize"]
    return ["-window", *keep, *(["-resolution", resolution] if resolution else []), *screen]
