"""An emulator's window as the host shows it (macOS only): found by its owner's pid, captured with
`screencapture -l`, and two captures compared. Without the Screen Recording permission the host
answers with why (`Blocked`) and the cell is BLOCKED, never a FAIL. `sips` converts the PNG to a
BMP so reading it needs only the standard library."""

from __future__ import annotations

import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scry_core import focus_watch
from scry_core.presence import LOOK, Look

CAPTURE_TIMEOUT_S = 15.0


class Blocked(Exception):
    """The host could not capture the window."""


def window_of(pid: int) -> int | None:
    """The window number of the largest layer-0 window `pid` owns that the host has on screen,
    or of the largest when it holds none; None when it owns none at all.

    An app bundle owns more than the machine's window: MAME as a `.app` also has a 500x500
    layer-0 window of one colour, larger than a 320x272 emulator, and only the one the host
    shows is the machine."""
    def area(w: dict[str, object]) -> float:
        bounds = w.get("kCGWindowBounds")
        return (float(bounds["Width"]) * float(bounds["Height"])
                if isinstance(bounds, dict) else 0.0)
    mine = [w for w in focus_watch.windows()
            if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0]
    if not mine:
        return None
    shown = [w for w in mine if w.get("kCGWindowIsOnscreen") is True]
    number = max(shown or mine, key=area).get("kCGWindowNumber")
    return int(number) if isinstance(number, int) else None


Pixel = tuple[int, int, int]


@dataclass(frozen=True)
class Image:
    """A capture as rows of packed RGB bytes, top row first, so equal rows compare whole."""

    width: int
    height: int
    rows: tuple[bytes, ...]

    @classmethod
    def of(cls, pixels: list[list[Pixel]] | tuple[tuple[Pixel, ...], ...]) -> Image:
        """An image from rows of (r, g, b)."""
        return cls(len(pixels[0]) if pixels else 0, len(pixels),
                   tuple(bytes(c for px in row for c in px) for row in pixels))

    def pixels(self, y: int) -> list[Pixel]:
        """Row `y` as (r, g, b)."""
        row = self.rows[y]
        return [(row[i], row[i + 1], row[i + 2]) for i in range(0, len(row), 3)]


def read_bmp(path: Path) -> Image:
    """A 24- or 32-bit BGR BMP as `sips` writes it; any other layout or a short file is a
    ValueError."""
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise ValueError(f"{path} is not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp, compression = struct.unpack_from("<HI", data, 28)
    # Only the BGR masks: any other BITFIELDS order would swap channels in silence.
    bgr = compression == 3 and struct.unpack_from("<III", data, 54) == (0xFF0000, 0xFF00, 0xFF)
    if bpp not in (24, 32) or not (compression == 0 or bgr) or width <= 0 or height == 0:
        raise ValueError(f"{path}: {bpp}-bit, compression {compression}, {width}x{height}, is not "
                         f"read here")
    step = bpp // 8
    stride = (width * step + 3) & ~3
    if offset + stride * abs(height) > len(data):
        raise ValueError(f"{path} is shorter than its {width}x{abs(height)} rows")
    rows = []
    for y in range(abs(height)):
        start = offset + y * stride
        stored = data[start:start + width * step]
        row = bytearray(width * 3)
        row[0::3], row[1::3], row[2::3] = stored[2::step], stored[1::step], stored[0::step]
        rows.append(bytes(row))
    if height > 0:                      # stored bottom-up
        rows.reverse()
    return Image(width, abs(height), tuple(rows))


def capture(pid: int, dest: Path) -> Image:
    """The window `pid` owns, captured into `dest` (PNG, BMP beside it); `Blocked` when the host
    cannot or answers blank."""
    if sys.platform != "darwin":
        raise Blocked(f"a window is captured on macOS only, not {sys.platform}")
    else:  # an `else`, so mypy skips this branch elsewhere instead of calling it unreachable
        return _capture_on_macos(pid, dest)


def _capture_on_macos(pid: int, dest: Path) -> Image:
    try:
        number = window_of(pid)
        if number is None:
            raise Blocked(f"pid {pid} owns no window the window server lists")
        run = subprocess.run(["screencapture", "-x", "-o", "-l", str(number), str(dest)],
                             capture_output=True, text=True, timeout=CAPTURE_TIMEOUT_S,
                             check=False)
        if run.returncode != 0 or not dest.is_file():
            raise Blocked(f"screencapture refused window {number} (rc {run.returncode}: "
                          f"{run.stderr.strip() or 'no file written'}); a host that has not "
                          f"granted Screen Recording to this process answers this way")
        bmp = dest.with_suffix(".bmp")
        conv = subprocess.run(["sips", "-s", "format", "bmp", str(dest), "--out", str(bmp)],
                              capture_output=True, text=True, timeout=CAPTURE_TIMEOUT_S,
                              check=False)
        if conv.returncode != 0 or not bmp.is_file():
            raise Blocked(f"sips could not convert {dest} (rc {conv.returncode}: "
                          f"{conv.stderr.strip()})")
        image = read_bmp(bmp)
    except (OSError, subprocess.TimeoutExpired, ValueError, struct.error, IndexError,
            KeyError) as e:
        raise Blocked(f"the window could not be captured: {type(e).__name__}: {e}") from None
    if len(set(image.rows)) < 2 and len(set(image.pixels(0))) < 2:
        # Some hosts answer a capture they will not make with a blank image, not a refusal.
        raise Blocked(f"the capture of window {number} holds one colour, so it shows nothing")
    return image


@dataclass(frozen=True)
class Difference:
    """Where two captures differ: pixel count, the inclusive box (`x0, y0, x1, y1`) and its span as
    a share of the capture, the deepest pixel from its nearest side (fraction of the box's shorter
    side), pixels nearest each side (top, bottom, left, right), and the mean change per channel.
    The box is the reference, not the capture, which also holds a title bar nothing draws on."""

    changed: int
    box: tuple[int, int, int, int]
    span: tuple[float, float]
    deepest: float
    sides: tuple[int, int, int, int]
    delta: tuple[float, float, float]


def difference(before: Image, after: Image) -> Difference:
    """`after` against `before`; captures of different sizes are a ValueError."""
    if (before.width, before.height) != (after.width, after.height):
        raise ValueError(f"the captures differ in size: {before.width}x{before.height} against "
                         f"{after.width}x{after.height}")
    points: list[tuple[int, int]] = []
    sums = [0, 0, 0]
    for y, (row_a, row_b) in enumerate(zip(before.rows, after.rows, strict=True)):
        if row_a == row_b:
            continue
        for x in range(before.width):
            a, b = row_a[3 * x:3 * x + 3], row_b[3 * x:3 * x + 3]
            if a != b:
                points.append((x, y))
                for i in range(3):
                    sums[i] += b[i] - a[i]
    if not points:
        return Difference(0, (0, 0, 0, 0), (0.0, 0.0), 0.0, (0, 0, 0, 0), (0.0, 0.0, 0.0))
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    side = max(1, min(x1 - x0, y1 - y0))
    sides = [0, 0, 0, 0]
    deepest = 0
    for x, y in points:
        insets = (y - y0, y1 - y, x - x0, x1 - x)
        nearest = min(insets)
        sides[insets.index(nearest)] += 1
        deepest = max(deepest, nearest)
    n = len(points)
    return Difference(n, (x0, y0, x1, y1),
                      ((x1 - x0 + 1) / before.width, (y1 - y0 + 1) / before.height),
                      deepest / side, (sides[0], sides[1], sides[2], sides[3]),
                      (sums[0] / n, sums[1] / n, sums[2] / n))


#: Farthest the edge may reach from a side, in edge widths, with room for scaling.
EDGE_REACH = 2.5
#: Least share of the window a drawn edge's box spans: the content, not the title bar.
CONTENT_SPAN = 0.75


def edge_verdict(d: Difference, look: Look = LOOK) -> tuple[bool, str]:
    """Whether `d` (edge drawn against not) is the edge: an orange-ward frame on all four sides,
    no deeper than the edge reaches; and what was measured."""
    x0, y0, x1, y1 = d.box
    perimeter = 2 * ((x1 - x0) + (y1 - y0))
    reach = EDGE_REACH * look.edge
    drawn = (d.changed >= perimeter and min(d.span) >= CONTENT_SPAN and min(d.sides) > 0
             and d.deepest <= reach and d.delta[0] > d.delta[1] > d.delta[2])
    return drawn, (f"{d.changed} pixels changed (a frame of the box needs {perimeter}) over "
                   f"{d.span[0]:.2f} x {d.span[1]:.2f} of the window, by side {d.sides}, the "
                   f"deepest {d.deepest:.4f} of the box's shorter side in (bound {reach:.4f}), "
                   f"mean change ({d.delta[0]:.1f}, {d.delta[1]:.1f}, {d.delta[2]:.1f})")
