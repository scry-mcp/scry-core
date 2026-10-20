"""What the host shows of an emulator's window, for a live tier that has to see something drawn
there and nowhere else (the presence edge): the window found by its owner's pid, captured by the
host, and two captures compared by where they differ. macOS only.

THE CAPTURE IS THE HOST'S OWN (`screencapture -l`, the window's own buffer whatever covers it),
so it needs the Screen Recording permission for the process running the tier. Nothing here asks
for it: a host that has not granted it answers with why (`Blocked`), and the cell that needed the
capture is BLOCKED, never a FAIL. The PNG is converted to an uncompressed BMP by `sips`, which
ships with the system, so reading it needs nothing more than the standard library.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import plistlib
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: How long a host capture or a conversion may take before it is a capture that failed.
CAPTURE_TIMEOUT_S = 15.0


class Blocked(Exception):
    """The host could not capture the window, and why: the cell is BLOCKED."""


def _windows() -> list[dict[str, object]]:
    """Every window the window server lists, as CoreGraphics describes them."""
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics") or "CoreGraphics")
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation") or "CoreFoundation")
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFPropertyListCreateData.restype = ctypes.c_void_p
    cf.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                            ctypes.c_long, ctypes.c_void_p]
    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    listed = cg.CGWindowListCopyWindowInfo(0, 0)        # every window, on screen or not
    if not listed:
        return []
    try:
        data = cf.CFPropertyListCreateData(None, listed, 200, 0, None)
        try:
            raw = ctypes.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))
        finally:
            cf.CFRelease(data)
    finally:
        cf.CFRelease(listed)
    windows: list[dict[str, object]] = plistlib.loads(raw)
    return windows


def window_of(pid: int) -> int | None:
    """The window number of the largest layer-0 window `pid` owns, or None."""
    def area(w: dict[str, object]) -> float:
        bounds = w.get("kCGWindowBounds")
        return (float(bounds["Width"]) * float(bounds["Height"])
                if isinstance(bounds, dict) else 0.0)
    mine = [w for w in _windows()
            if w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowLayer") == 0]
    if not mine:
        return None
    number = max(mine, key=area).get("kCGWindowNumber")
    return int(number) if isinstance(number, int) else None


@dataclass(frozen=True)
class Image:
    """A capture as rows of (r, g, b), top row first."""

    width: int
    height: int
    rows: tuple[tuple[tuple[int, int, int], ...], ...]


def read_bmp(path: Path) -> Image:
    """A 24- or 32-bit BMP in blue-green-red order, as `sips` writes one; any other layout, or a
    file shorter than its header says, is a ValueError."""
    data = path.read_bytes()
    if data[:2] != b"BM":
        raise ValueError(f"{path} is not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp, compression = struct.unpack_from("<HI", data, 28)
    # BITFIELDS is read only with the masks of blue-green-red order, the ones `sips` writes for a
    # capture with an alpha channel; any other order would swap the channels in silence.
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
        row = tuple((data[start + x * step + 2], data[start + x * step + 1],
                     data[start + x * step]) for x in range(width))
        rows.append(row)
    if height > 0:                      # stored bottom-up
        rows.reverse()
    return Image(width, abs(height), tuple(rows))


def capture(pid: int, dest: Path) -> Image:
    """The window `pid` owns, captured by the host into `dest` (a PNG, with its BMP beside it)
    and read back; `Blocked` when the host cannot, or answers with a blank image."""
    if sys.platform != "darwin":
        raise Blocked(f"a window is captured on macOS only, not {sys.platform}")
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
        # WHATEVER THE HOST'S TOOLS DO WRONG is a capture this host could not make.
        raise Blocked(f"the window could not be captured: {type(e).__name__}: {e}") from None
    if len({px for row in image.rows for px in row}) < 2:
        # A capture of one colour shows no window content: some hosts answer a capture they
        # will not make with a blank image rather than a refusal.
        raise Blocked(f"the capture of window {number} holds one colour, so it shows nothing")
    return image


@dataclass(frozen=True)
class Difference:
    """Where two captures of one window differ: how many pixels, the box they span
    (`x0, y0, x1, y1`, inclusive) as a share of the capture's width and height, the farthest any
    of them lies inside that box from its nearest side (a fraction of the box's shorter side), how
    many lie nearest each side (top, bottom, left, right), and the mean change of each channel
    over them. A frame drawn on a window's inner edges spans
    nearly the whole content and stays shallow; the box, not the capture, is the reference,
    because the capture also holds the window's title bar, which nothing draws on."""

    changed: int
    box: tuple[int, int, int, int]
    span: tuple[float, float]
    deepest: float
    sides: tuple[int, int, int, int]
    delta: tuple[float, float, float]


def difference(before: Image, after: Image) -> Difference:
    """`after` against `before`, pixel by pixel; captures of different sizes are a ValueError."""
    if (before.width, before.height) != (after.width, after.height):
        raise ValueError(f"the captures differ in size: {before.width}x{before.height} against "
                         f"{after.width}x{after.height}")
    points: list[tuple[int, int]] = []
    sums = [0, 0, 0]
    for y, (row_a, row_b) in enumerate(zip(before.rows, after.rows, strict=True)):
        for x, (a, b) in enumerate(zip(row_a, row_b, strict=True)):
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
