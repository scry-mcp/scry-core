"""A window request as an emulator's command-line words."""

from __future__ import annotations

import sys

from scry_core.window import WindowRequest
from scry_core.window_size import WINDOW_MARGIN_PX


def dosbox_x(asked: WindowRequest, platform: str | None = None) -> list[str]:
    """On Windows DOSBox-X is DPI unaware with `dpi aware=false`, or `auto` and the primary display
    from 200 %: size and position are then logical pixels. Aware, they are real pixels and the
    margin grows with the scale, or the title bar sits above the display."""
    words = ["-set", f"sdl display={asked.display}"]
    if asked.fullscreen:
        return [*words, "-fullscreen"]
    windows = (platform or sys.platform) == "win32"
    system = asked.scale if asked.system_scale is None else asked.system_scale
    unaware = windows and (asked.dpi_aware is False or (asked.dpi_aware is None and system >= 2))
    margin = round(WINDOW_MARGIN_PX * asked.scale) if windows and not unaware else WINDOW_MARGIN_PX
    x, y = asked.origin
    words += ["-set", f"sdl windowposition={x + margin},{y + margin}"]
    if asked.size is not None:
        divisor = asked.scale if unaware else 1
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
