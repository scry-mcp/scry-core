"""An emulator's window as the host shows it: found by its owner's pid, captured, and two captures
compared. Whatever stops a host from capturing is answered with why (`Blocked`), so the cell is
BLOCKED, never a FAIL.

macOS asks the window server (`screencapture -l`; without the Screen Recording permission it
refuses), and `sips` converts the PNG to a BMP so reading it needs only the standard library.
Windows asks for the window's own picture through Windows.Graphics.Capture, which a window behind
others still has and which a stopped machine's window answers without being asked to paint (a
read of the screen sees only what is in front, and PrintWindow waits on the window's thread)."""

from __future__ import annotations

import ctypes
import struct
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from scry_core import focus_watch, png, window, window_host
from scry_core.presence import LOOK, Look
from scry_core.reply_contract import Invalid

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
    """The window `pid` owns (on Windows its client area), captured into `dest` as a PNG (on macOS
    a BMP beside it); `Blocked` when the host cannot or answers blank. Neither host brings the
    window forward."""
    # Every branch is a platform test, so mypy skips the other hosts' instead of calling them
    # unreachable.
    if sys.platform == "darwin":
        return _capture_on_macos(pid, dest)
    elif sys.platform == "win32":
        return _capture_on_windows(pid, dest)
    else:
        raise Blocked(f"a window is captured on macOS and Windows only, not {sys.platform}")


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
        raise _not_captured(e) from None
    return _shown(image, number)


def _not_captured(e: Exception) -> Blocked:
    return Blocked(f"the window could not be captured: {type(e).__name__}: {e}")


def _shown(image: Image, number: int) -> Image:
    """`image`, or `Blocked` when it holds one colour: some hosts answer a capture they will not
    make with a blank image, not a refusal."""
    if len(set(image.rows)) < 2 and len(set(image.pixels(0))) < 2:
        raise Blocked(f"the capture of window {number} holds one colour, so it shows nothing")
    return image


#: What the Windows half says when the display is off: the frame it would hand back is the last
#: one composed before, so two captures around any change would read as equal.
DISPLAY_OFF = ("the display is off, and while it is Windows composes no new frame of a window "
               "drawn by its GPU: wake the display (a key, the mouse) and capture again")


def _capture_on_windows(pid: int, dest: Path) -> Image:
    try:
        if not _display_on():
            raise Blocked(DISPLAY_OFF)
        seen = window.main_window(pid, window_host.WindowsHost().windows())
        if seen is None:
            raise Blocked(f"pid {pid} owns no window the desktop lists")
        image = _window_frame(seen.number)
        dest.write_bytes(png.encode(png.Raster(image.width, image.height, b"".join(image.rows))))
    except (OSError, ValueError, Invalid) as e:
        raise _not_captured(e) from None
    return _shown(image, seen.number)


def client_box(frame: tuple[int, int], corner: tuple[int, int], client: tuple[int, int],
               content: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where a client area of size `client` whose top-left corner is at `corner` on the screen sits
    in a captured frame of size `content` that starts at `frame`: (x, y, width, height), cut to
    the frame on every side."""
    box = []
    for at, start, size, whole in zip(frame, corner, client, content, strict=True):
        first, last = max(0, start - at), min(whole, start - at + size)
        box.append((first, last - first))
    (x, width), (y, height) = box
    return x, y, width, height


def bgra_image(row_of: Callable[[int], bytes], width: int, height: int) -> Image:
    """An image from `height` rows of BGRA bytes, `row_of(y)` giving row `y` (top first)."""
    rows = []
    for y in range(height):
        stored = row_of(y)
        if len(stored) < width * 4:
            raise ValueError(f"row {y} holds {len(stored)} bytes, not the {width * 4} of "
                             f"{width} BGRA pixels")
        row = bytearray(width * 3)
        row[0::3], row[1::3], row[2::3] = stored[2:width * 4:4], stored[1:width * 4:4], \
            stored[0:width * 4:4]
        rows.append(bytes(row))
    return Image(width, height, tuple(rows))


@dataclass(frozen=True)
class Difference:
    """Where two captures differ: pixel count, the inclusive box (`x0, y0, x1, y1`) and its span as
    a share of the capture, the deepest pixel from its nearest side (fraction of the box's shorter
    side), pixels nearest each side (top, bottom, left, right), and the mean change per channel.
    The box is the reference, not the capture, which on macOS also holds a title bar nothing draws
    on."""

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
#: Least share of the capture a drawn edge's box spans: the content, not a title bar (macOS's
#: capture holds one).
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


#: How long Windows has to answer the display's state, which it sends once a listener registers.
DISPLAY_ANSWER_S = 1.0
#: `GUID_CONSOLE_DISPLAY_STATE`'s answer while the display is off.
DISPLAY_IS_OFF = 0


if sys.platform == "win32":
    import threading
    from ctypes import (
        POINTER,
        Structure,
        byref,
        c_int,
        c_ubyte,
        c_uint,
        c_ulong,
        c_void_p,
        wintypes,
    )

    _HRESULT = ctypes.c_long
    _B8G8R8A8 = 87                         # DXGI_FORMAT_B8G8R8A8_UNORM, what the pool hands back

    # Interface ids and vtable slots as the Windows SDK's headers declare them
    # (windows.graphics.capture.idl, its interop idl, d3d11.h, dxgi.h).
    _IID = {
        "IDXGIDevice": "54ec77fa-1377-44e6-8c32-88fd5f44c84c",
        "ID3D11Texture2D": "6f15aaf2-d208-4e89-9ab4-489535d34f9c",
        "IDirect3DDevice": "a37624ab-8d5f-4650-9d3e-9eae3d9bc670",
        "IDirect3DDxgiInterfaceAccess": "a9b3d012-3df2-4ee3-b8d1-8695f457d3c1",
        "IGraphicsCaptureItemInterop": "3628e81b-3cac-4c60-b7f4-23ce0e0c3356",
        "IGraphicsCaptureItem": "79c3f95b-31f7-4ec2-a464-632ef5d30760",
        "IDirect3D11CaptureFramePoolStatics2": "589b103f-6bbc-5df5-a991-02e28b3b66d5",
        "IGraphicsCaptureSession2": "2c39ae40-7d2e-5044-804e-8b6799d4cf9e",
        "IGraphicsCaptureSession3": "f2cdd966-22ae-5ea1-9596-3a289344c3be",
        "IClosable": "30d5a829-7fa4-4026-83bb-d75bae4ea99e",
        "GUID_CONSOLE_DISPLAY_STATE": "6fe69556-704a-47a0-8f24-c28d936fda47",
    }

    class _Guid(Structure):
        _fields_ = [("raw", c_ubyte * 16)]

    def _guid(name: str) -> _Guid:
        g = _Guid()
        ctypes.memmove(byref(g), uuid.UUID(_IID[name]).bytes_le, 16)
        return g

    class _Size(Structure):
        _fields_ = [("width", ctypes.c_int32), ("height", ctypes.c_int32)]

    class _TextureDesc(Structure):
        _fields_ = [("width", c_uint), ("height", c_uint), ("mips", c_uint), ("array", c_uint),
                    ("format", c_int), ("samples", c_uint), ("quality", c_uint),
                    ("usage", c_int), ("bind", c_uint), ("cpu_access", c_uint),
                    ("misc", c_uint)]

    class _Mapped(Structure):
        _fields_ = [("data", c_void_p), ("pitch", c_uint), ("depth_pitch", c_uint)]

    def _method(obj: c_void_p, slot: int, *argtypes: Any, restype: Any = _HRESULT) -> Any:
        table = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(table[slot])

    def _call(obj: c_void_p, slot: int, what: str, argtypes: list[Any], *args: Any) -> None:
        hr = _method(obj, slot, *argtypes)(obj, *args)
        if hr < 0:
            raise OSError(f"{what} answered HRESULT {hr & 0xFFFFFFFF:#010x}")

    def _query(obj: c_void_p, name: str) -> c_void_p:
        out = c_void_p()
        _call(obj, 0, f"QueryInterface({name})", [POINTER(_Guid), POINTER(c_void_p)],
              byref(_guid(name)), byref(out))
        return out

    class _Held:
        """COM references released in reverse order on the way out, whatever happened, after the
        capture's objects (`closing`) are closed, which stops a started capture. A failed close
        is raised only when nothing else was."""

        def __init__(self) -> None:
            self.objs: list[c_void_p] = []
            self.closables: list[c_void_p] = []

        def __call__(self, obj: c_void_p) -> c_void_p:
            self.objs.append(obj)
            return obj

        def closing(self, obj: c_void_p) -> c_void_p:
            self.closables.append(self(obj))
            return obj

        def __enter__(self) -> _Held:
            return self

        def __exit__(self, failed: object, *_: object) -> None:
            unclosed: OSError | None = None
            for obj in reversed(self.closables):
                try:
                    _call(self(_query(obj, "IClosable")), 6, "Close", [])
                except OSError as e:
                    unclosed = unclosed or e
            for obj in reversed(self.objs):
                if obj.value:
                    _method(obj, 2, restype=c_ulong)(obj)
            if unclosed is not None and failed is None:
                raise unclosed

    def _factory(held: _Held, runtime_class: str, name: str) -> c_void_p:
        combase = ctypes.WinDLL("combase")
        combase.WindowsCreateString.argtypes = [ctypes.c_wchar_p, c_uint, POINTER(c_void_p)]
        combase.WindowsDeleteString.argtypes = [c_void_p]
        combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(_Guid), POINTER(c_void_p)]
        text = c_void_p()
        if combase.WindowsCreateString(runtime_class, len(runtime_class), byref(text)) < 0:
            raise OSError(f"no string for {runtime_class}")
        try:
            out = c_void_p()
            hr = combase.RoGetActivationFactory(text, byref(_guid(name)), byref(out))
        finally:
            combase.WindowsDeleteString(text)
        if hr < 0:
            raise OSError(f"{runtime_class} is not available here "
                          f"(HRESULT {hr & 0xFFFFFFFF:#010x})")
        return held(out)

    _ANSWERED: list[int] = []
    _HEARD = threading.Event()

    def _heard(_context: Any, kind: int, setting: Any) -> int:
        # PBT_POWERSETTINGCHANGE; the setting is a GUID, a DWORD length and the value.
        if kind == 0x8013 and setting and ctypes.c_uint.from_address(setting + 16).value >= 4:
            _ANSWERED.append(ctypes.c_uint.from_address(setting + 20).value)
            _HEARD.set()
        return 0

    # Module-level, so a notification Windows delivers after the listener left finds it alive.
    _NOTIFY = ctypes.WINFUNCTYPE(c_ulong, c_void_p, c_ulong, c_void_p)(_heard)

    class _Subscription(Structure):
        _fields_ = [("callback", type(_NOTIFY)), ("context", c_void_p)]

    def _display_on() -> bool:
        """Whether the console's display is on (or dimmed), as Windows sends it to a listener the
        moment it registers."""
        powrprof = ctypes.WinDLL("powrprof")
        _ANSWERED.clear()
        _HEARD.clear()
        subscription = _Subscription(_NOTIFY, None)
        handle = c_void_p()
        rc = powrprof.PowerSettingRegisterNotification(
            byref(_guid("GUID_CONSOLE_DISPLAY_STATE")), 2, byref(subscription), byref(handle))
        if rc != 0:
            raise OSError(f"the display's state could not be asked for (error {rc})")
        try:
            _HEARD.wait(DISPLAY_ANSWER_S)
        finally:
            powrprof.PowerSettingUnregisterNotification(handle)
        if not _ANSWERED:
            raise OSError(f"Windows sent no display state within {DISPLAY_ANSWER_S} s")
        return _ANSWERED[0] != DISPLAY_IS_OFF

    def _window_frame(hwnd: int) -> Image:
        """The next frame Windows.Graphics.Capture gives of `hwnd`, cursor left out."""
        combase = ctypes.WinDLL("combase")
        initialised = combase.RoInitialize(1) >= 0          # RO_INIT_MULTITHREADED
        try:
            with _Held() as held:
                return _frame_of(held, hwnd)
        finally:
            if initialised:
                combase.RoUninitialize()

    def _frame_of(held: _Held, hwnd: int) -> Image:
        d3d11 = ctypes.WinDLL("d3d11")
        d3d11.D3D11CreateDevice.argtypes = [c_void_p, c_int, c_void_p, c_uint, c_void_p, c_uint,
                                            c_uint, POINTER(c_void_p), c_void_p,
                                            POINTER(c_void_p)]
        d3d11.CreateDirect3D11DeviceFromDXGIDevice.argtypes = [c_void_p, POINTER(c_void_p)]
        device, context = c_void_p(), c_void_p()
        # A hardware device, BGRA support asked, D3D11_SDK_VERSION 7.
        hr = d3d11.D3D11CreateDevice(None, 1, None, 0x20, None, 0, 7, byref(device), None,
                                     byref(context))
        if hr < 0:
            raise OSError(f"D3D11CreateDevice answered HRESULT {hr & 0xFFFFFFFF:#010x}")
        held(device)
        held(context)
        inspectable = c_void_p()
        hr = d3d11.CreateDirect3D11DeviceFromDXGIDevice(held(_query(device, "IDXGIDevice")),
                                                        byref(inspectable))
        if hr < 0:
            raise OSError(f"CreateDirect3D11DeviceFromDXGIDevice answered HRESULT "
                          f"{hr & 0xFFFFFFFF:#010x}")
        runtime_device = held(_query(held(inspectable), "IDirect3DDevice"))
        interop = _factory(held, "Windows.Graphics.Capture.GraphicsCaptureItem",
                           "IGraphicsCaptureItemInterop")
        item = c_void_p()
        _call(interop, 3, "CreateForWindow", [wintypes.HWND, POINTER(_Guid), POINTER(c_void_p)],
              hwnd, byref(_guid("IGraphicsCaptureItem")), byref(item))
        held(item)
        size = _Size()
        _call(item, 7, "GraphicsCaptureItem.Size", [POINTER(_Size)], byref(size))
        statics = _factory(held, "Windows.Graphics.Capture.Direct3D11CaptureFramePool",
                           "IDirect3D11CaptureFramePoolStatics2")
        pool = c_void_p()
        _call(statics, 6, "CreateFreeThreaded", [c_void_p, c_int, c_int, _Size, POINTER(c_void_p)],
              runtime_device, _B8G8R8A8, 1, size, byref(pool))
        held.closing(pool)
        session = c_void_p()
        _call(pool, 10, "CreateCaptureSession", [c_void_p, POINTER(c_void_p)], item,
              byref(session))
        held.closing(session)
        _call(held(_query(session, "IGraphicsCaptureSession2")), 7, "IsCursorCaptureEnabled",
              [c_ubyte], 0)
        # The border Windows draws round a captured window shows on the desk, never in the frame:
        # asked away where the interface exists (Windows 11), and its answer is not needed.
        try:
            bordered = held(_query(session, "IGraphicsCaptureSession3"))
            _method(bordered, 7, c_ubyte)(bordered, 0)
        except OSError:
            pass
        _call(session, 6, "StartCapture", [])
        frame = c_void_p()
        deadline = time.monotonic() + CAPTURE_TIMEOUT_S
        while True:
            _call(pool, 7, "TryGetNextFrame", [POINTER(c_void_p)], byref(frame))
            if frame.value:
                break
            if time.monotonic() > deadline:
                raise OSError(f"no frame of window {hwnd} within {CAPTURE_TIMEOUT_S} s")
            time.sleep(0.005)
        held.closing(frame)
        content = _Size()
        _call(frame, 8, "ContentSize", [POINTER(_Size)], byref(content))
        box = _client_box(hwnd, content)
        surface = c_void_p()
        _call(frame, 6, "Surface", [POINTER(c_void_p)], byref(surface))
        access = held(_query(held(surface), "IDirect3DDxgiInterfaceAccess"))
        texture = c_void_p()
        _call(access, 3, "GetInterface", [POINTER(_Guid), POINTER(c_void_p)],
              byref(_guid("ID3D11Texture2D")), byref(texture))
        return _read_texture(held, device, context, held(texture), box)

    def _client_box(hwnd: int, content: _Size) -> tuple[int, int, int, int]:
        """Where the client area sits in the frame (x, y, width, height), the frame starting at
        the window's visible bounds: a title bar's share of a window grows with the display's
        scale, and nothing an emulator draws lands on it."""
        user32 = ctypes.WinDLL("user32")
        dwmapi = ctypes.WinDLL("dwmapi")
        frame = wintypes.RECT()
        # DWMWA_EXTENDED_FRAME_BOUNDS: the bounds the capture's frame covers.
        hr = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, byref(frame),
                                          ctypes.sizeof(frame))
        client, corner = wintypes.RECT(), wintypes.POINT(0, 0)
        if (hr != 0 or not user32.GetClientRect(wintypes.HWND(hwnd), byref(client))
                or not user32.ClientToScreen(wintypes.HWND(hwnd), byref(corner))):
            raise OSError(f"the client area of window {hwnd} could not be placed (DWM {hr:#x})")
        return client_box((frame.left, frame.top), (corner.x, corner.y),
                          (client.right, client.bottom), (content.width, content.height))

    def _read_texture(held: _Held, device: c_void_p, context: c_void_p, texture: c_void_p,
                      box: tuple[int, int, int, int]) -> Image:
        """`box` (x, y, width, height) of `texture`, through a copy the CPU can map."""
        desc = _TextureDesc()
        _method(texture, 10, POINTER(_TextureDesc), restype=None)(texture, byref(desc))
        if desc.format != _B8G8R8A8:
            raise OSError(f"the frame is in DXGI format {desc.format}, not B8G8R8A8")
        x, y, width, height = box
        if width <= 0 or height <= 0 or x + width > desc.width or y + height > desc.height:
            raise OSError(f"the client area {box} lies outside the {desc.width}x{desc.height} "
                          f"frame")
        # D3D11_USAGE_STAGING, no bind flags, D3D11_CPU_ACCESS_READ.
        staged = _TextureDesc(desc.width, desc.height, 1, 1, desc.format, 1, 0, 3, 0, 0x20000, 0)
        staging = c_void_p()
        _call(device, 5, "CreateTexture2D", [POINTER(_TextureDesc), c_void_p, POINTER(c_void_p)],
              byref(staged), None, byref(staging))
        held(staging)
        _method(context, 47, c_void_p, c_void_p, restype=None)(context, staging, texture)
        mapped = _Mapped()
        _call(context, 14, "Map", [c_void_p, c_uint, c_int, c_uint, POINTER(_Mapped)], staging,
              0, 1, 0, byref(mapped))
        try:
            base, pitch = int(mapped.data or 0) + x * 4, mapped.pitch
            return bgra_image(lambda row: ctypes.string_at(base + (y + row) * pitch, width * 4),
                              width, height)
        finally:
            _method(context, 15, c_void_p, c_uint, restype=None)(context, staging, 0)
else:
    def _not_windows() -> NoReturn:
        raise AssertionError("the Windows capture is built on Windows only")

    def _display_on() -> bool:
        _not_windows()

    def _window_frame(hwnd: int) -> Image:
        _not_windows()
