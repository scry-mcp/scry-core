"""A window request as an emulator's command-line words."""

from __future__ import annotations

import sys

from scry_core.window import WindowRequest
from scry_core.window_size import WINDOW_MARGIN_PX


def dosbox_x(asked: WindowRequest, platform: str | None = None) -> list[str]:
    """A position places a macOS run. The size is in logical pixels where DOSBox-X is not DPI
    aware (on Windows, `dpi aware=false`, or `auto` from 200 %), and in points on macOS."""
    words = ["-set", f"sdl display={asked.display}"]
    if asked.fullscreen:
        return [*words, "-fullscreen"]
    x, y = asked.origin
    words += ["-set", f"sdl windowposition={x + WINDOW_MARGIN_PX},{y + WINDOW_MARGIN_PX}"]
    if asked.size is not None:
        unaware = asked.dpi_aware is False or (asked.dpi_aware is None and asked.scale >= 2)
        divisor = asked.scale if (platform or sys.platform) == "win32" and unaware else 1
        width, height = (round(side / divisor) for side in asked.size)
        words += ["-set", f"sdl windowresolution={width}x{height}"]
    return words


def mame(asked: WindowRequest, resolution: str | None = None) -> list[str]:
    """A window of the stated size, else `resolution`. Windows ignores `-resolution` under
    `-nomaximize`, so a request with a free height drops it."""
    screen = ["-screen0", f"screen{asked.display}"]
    if asked.fullscreen:
        return ["-nowindow", *screen]
    if asked.size is not None:
        resolution = f"{asked.size[0]}x{asked.size[1]}"
    keep = [] if asked.size is not None and asked.height_free else ["-nomaximize"]
    return ["-window", *keep, *(["-resolution", resolution] if resolution else []), *screen]
