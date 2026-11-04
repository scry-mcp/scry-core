"""A window request as an emulator's command-line words."""

from __future__ import annotations

import math
import sys

from scry_core.window import WindowRequest
from scry_core.window_size import WINDOW_MARGIN_PX, WINDOWS_FRAME_PX


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
    origin_x, origin_y = asked.origin
    x, y = origin_x + margin, origin_y + margin
    divisor = asked.scale if unaware else 1
    sized = asked.size is not None
    width, height = (round(side / divisor) for side in asked.size) if asked.size else (0, 0)
    if asked.usable is not None:
        left, top, usable_width, usable_height = asked.usable
        if windows:
            # The position is the client's; the outer window wears a border on three sides and
            # the title bar and menu above, and none of it may leave the usable area. Measured
            # from the display's own corner, in the unit the words are sent in.
            border = math.ceil(WINDOWS_FRAME_PX[0] * asked.scale / divisor / 2)
            above = math.ceil(WINDOWS_FRAME_PX[1] * asked.scale / divisor) - border
            near_x, near_y = round((left - origin_x) / divisor), round((top - origin_y) / divisor)
            x = max(x, origin_x + near_x + border)
            y = max(y, origin_y + near_y + above)
            if sized:
                x = min(x, origin_x + near_x + round(usable_width / divisor) - width - border)
                y = min(y, origin_y + near_y + round(usable_height / divisor) - height - border)
        elif sized:     # AppKit keeps a window under the menu bar, not inside the width
            x = min(x, round((left + usable_width) / divisor) - width)
    words += ["-set", f"sdl windowposition={x},{y}"]
    if sized:
        words += ["-set", f"sdl windowresolution={width}x{height}"]
    return words


def mame(asked: WindowRequest) -> list[str]:
    """A window of the stated size. Windows ignores `-resolution` under `-nomaximize`, so a
    request with a free height drops it."""
    screen = ["-screen0", f"screen{asked.display}"]
    if asked.fullscreen:
        return ["-nowindow", *screen]
    keep = [] if asked.size is not None and asked.height_free else ["-nomaximize"]
    size = ["-resolution", f"{asked.size[0]}x{asked.size[1]}"] if asked.size is not None else []
    return ["-window", *keep, *size, *screen]
