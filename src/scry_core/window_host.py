"""The window system as `scry_core.window` asks it: macOS through CoreGraphics, Windows through
user32, one class each. Anything else is a `host_failed` refusal naming the platform.

macOS brings a window forward in two steps, and neither alone is enough. The window's display is
switched to the Space that holds it (the window server's private
`CGSManagedDisplaySetCurrentSpace`, the symbol family `focus_watch` already reads), and its
application is made frontmost through System Events by pid. Frontmost by pid alone answers rc 0
and moves nothing while the window sits on another Space, which is where a full-screen
application in front leaves it; the Space switch alone leaves it under the other windows of the
Space; `NSRunningApplication` activation does not raise it either.
The two shims that act on the desk carry the marker the coverage config excludes; the choices
around them are tested.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import subprocess
import sys
import time
from typing import Any, NoReturn

from scry_core import focus_watch
from scry_core.reply_contract import Invalid
from scry_core.window import Display, Rect, Seen, above_in_order

# CoreGraphics' limit on active displays read at once.
MAX_DISPLAYS = 16
# Windows below this are chrome (a menu bar strip, a shadow), never an emulator's window.
MIN_SIDE = 64
# The Space switch is animated: wait up to this for the window to be listed on screen, then this
# long for the transition to settle before the application is asked to come to the front.
SWITCH_BOUND_S, SWITCH_POLL_S, SWITCH_SETTLE_S = 4.0, 0.1, 0.5
# `kCGWindowListOptionOnScreenAboveWindow`.
ABOVE_WINDOW = 2
# `CGSCopySpacesForWindows` mask: every Space the window is on.
ALL_SPACES = 0x7
# CFString encoding UTF-8; CFNumber type kCFNumberIntType.
UTF8, INT_TYPE = 0x08000100, 9


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("width", ctypes.c_double), ("height", ctypes.c_double)]


def _rounded(r: _Rect) -> Rect:
    return round(r.x), round(r.y), round(r.width), round(r.height)


def plan_switch(space: int, managed: list[Any]) -> tuple[str, int] | None:
    """The (display identifier, Space) to switch to so `space` is shown, or None when it already
    is, or when no display holds it."""
    for display in managed:
        try:
            held = [int(s["ManagedSpaceID"]) for s in display["Spaces"]]
            current = int(display["Current Space"]["ManagedSpaceID"])
            ident = str(display["Display Identifier"])
        except (KeyError, TypeError, ValueError):
            continue
        if space in held:
            return None if current == space else (ident, space)
    return None


def seen_from(listing: list[dict[str, Any]]) -> list[Seen]:
    """Ordinary windows (layer 0, visible, not chrome) of the window server's listing, kept in
    its front-to-back order."""
    found = []
    for entry in listing:
        bounds = entry.get("kCGWindowBounds")
        pid, number = entry.get("kCGWindowOwnerPID"), entry.get("kCGWindowNumber")
        if (entry.get("kCGWindowLayer") != 0 or not isinstance(bounds, dict)
                or not isinstance(pid, int) or not isinstance(number, int)
                or entry.get("kCGWindowAlpha", 1.0) == 0):
            continue
        width, height = round(bounds["Width"]), round(bounds["Height"])
        if min(width, height) < MIN_SIDE:
            continue
        found.append(Seen(pid=pid, number=number,
                          bounds=(round(bounds["X"]), round(bounds["Y"]), width, height),
                          onscreen=bool(entry.get("kCGWindowIsOnscreen"))))
    return found


class MacHost:
    """`scry_core.window.Host` on macOS."""

    def displays(self) -> list[Display]:
        libs = focus_watch._graphics()
        if libs is None:
            return []
        cg = libs[0]
        ids = (ctypes.c_uint32 * MAX_DISPLAYS)()
        count = ctypes.c_uint32(0)
        cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayBounds.restype = _Rect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGGetActiveDisplayList(MAX_DISPLAYS, ids, ctypes.byref(count))     # a failure leaves 0
        main = cg.CGMainDisplayID()
        order = sorted(ids[:count.value], key=lambda i: i != main)          # the main one first
        return [Display(n, _rounded(cg.CGDisplayBounds(i))) for n, i in enumerate(order)]

    def windows(self) -> list[Seen]:
        return seen_from(focus_watch.windows())

    def above(self, window: Seen) -> list[Seen]:
        """The windows the window server says are on screen over `window` (it does not mix the
        Spaces the way the full listing's order does: a full-screen window of a Space not shown
        stays listed on screen, ahead of everything, for as long as its application lives)."""
        libs = focus_watch._graphics()
        if libs is None:
            return []
        cg, cf = libs
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        listed = cg.CGWindowListCopyWindowInfo(ABOVE_WINDOW, window.number)
        found = focus_watch.plist_of(cf, listed) if listed else None
        return seen_from(found) if isinstance(found, list) else []

    def space_of(self, window: Seen) -> int | None:
        """The Space the window server says holds `window`, or None."""
        libs = focus_watch._graphics()
        if libs is None or focus_watch.spaces_missing(libs[0]):
            return None
        cg, cf = libs
        number = ctypes.c_int(window.number)
        cf.CFNumberCreate.restype = ctypes.c_void_p
        cf.CFNumberCreate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        cf.CFArrayCreate.restype = ctypes.c_void_p
        cf.CFArrayCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long,
                                     ctypes.c_void_p]
        cg.CGSCopySpacesForWindows.restype = ctypes.c_void_p
        cg.CGSCopySpacesForWindows.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        item = cf.CFNumberCreate(None, INT_TYPE, ctypes.byref(number))
        array = cf.CFArrayCreate(None, (ctypes.c_void_p * 1)(item), 1, None)
        listed = cg.CGSCopySpacesForWindows(cg.CGSMainConnectionID(), ALL_SPACES, array)
        cf.CFRelease(array)
        cf.CFRelease(item)
        spaces = focus_watch.plist_of(cf, listed) if listed else None
        return int(spaces[0]) if isinstance(spaces, list) and spaces else None

    def activate(self, window: Seen) -> str:
        """Switch to the window's Space, then make its application frontmost; why not, or ''."""
        space = self.space_of(window)
        managed = focus_watch._managed()
        if space is None or managed is None:
            return ("the window server would not say which Space holds the window "
                    f"(missing: {focus_watch.spaces_missing() or 'the listing itself'})")
        if (step := plan_switch(space, managed)) is not None:
            switch_space(*step)
            self._until_shown(window)
        return activate_app(window.pid)

    def _until_shown(self, window: Seen) -> None:
        """Wait for the Space switch to finish: the application is made frontmost only once its
        window is on screen, because earlier the request lands mid-transition and does nothing."""
        end = time.monotonic() + SWITCH_BOUND_S
        while time.monotonic() < end:
            if any(s.number == window.number and s.onscreen for s in self.windows()):
                time.sleep(SWITCH_SETTLE_S)
                return
            time.sleep(SWITCH_POLL_S)


def switch_space(display_identifier: str, space: int) -> None:  # needs the desk
    cg, cf = focus_watch._graphics()    # type: ignore[misc]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cg.CGSManagedDisplaySetCurrentSpace.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64]
    name = cf.CFStringCreateWithCString(None, display_identifier.encode(), UTF8)
    cg.CGSManagedDisplaySetCurrentSpace(cg.CGSMainConnectionID(), name, space)
    cf.CFRelease(name)


def activation_error(run: subprocess.CompletedProcess[str] | str) -> str:
    """Why an activation's `osascript` run failed, or ''."""
    if isinstance(run, str):
        return run
    return "" if run.returncode == 0 else f"activation refused: {run.stderr.strip()}"


def activate_app(pid: int) -> str:  # needs the desk
    """Make the application owning `pid` frontmost: why not, or ''."""
    return activation_error(focus_watch.osascript(
        f'tell application "System Events" to set frontmost of '
        f"(first process whose unix id is {pid}) to true"))


class WindowsHost:
    """`scry_core.window.Host` on Windows: user32 through ctypes. Written against the Win32
    documentation and not yet run on Windows."""

    def displays(self) -> list[Display]:
        return _win_displays()

    def windows(self) -> list[Seen]:
        return _win_windows()

    def above(self, window: Seen) -> list[Seen]:
        return above_in_order(_win_windows())(window)

    def activate(self, window: Seen) -> str:
        return _win_activate(window.number)


if sys.platform == "win32":
    from ctypes import wintypes

    def _win_displays() -> list[Display]:
        user32 = ctypes.WinDLL("user32")
        found: list[tuple[bool, Rect]] = []

        class Info(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        callback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

        def each(handle: Any, _dc: Any, _rect: Any, _data: Any) -> int:
            info = Info()
            info.size = ctypes.sizeof(Info)
            user32.GetMonitorInfoW(handle, ctypes.byref(info))
            r = info.monitor
            found.append((bool(info.flags & 1), (r.left, r.top, r.right - r.left,
                                                  r.bottom - r.top)))
            return 1

        user32.EnumDisplayMonitors(None, None, callback(each), 0)
        found.sort(key=lambda m: not m[0])          # the primary monitor first
        return [Display(n, bounds) for n, (_, bounds) in enumerate(found)]

    def _win_windows() -> list[Seen]:
        user32 = ctypes.WinDLL("user32")
        found: list[Seen] = []
        callback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd: Any, _data: Any) -> int:
            rect, pid = wintypes.RECT(), wintypes.DWORD()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if min(width, height) >= MIN_SIDE and not user32.GetWindow(hwnd, 4):    # GW_OWNER
                found.append(Seen(pid=pid.value, number=int(hwnd),
                                  bounds=(rect.left, rect.top, width, height),
                                  onscreen=bool(user32.IsWindowVisible(hwnd))
                                  and not user32.IsIconic(hwnd)))
            return 1

        user32.EnumWindows(callback(each), 0)         # top of the z-order first
        return found

    def _win_activate(number: int) -> str:
        user32 = ctypes.WinDLL("user32")
        user32.ShowWindow(wintypes.HWND(number), 9)                 # SW_RESTORE
        # Windows refuses a foreground change from a process that is not in the foreground
        # unless an Alt key event has just passed through the input queue.
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        return "" if user32.SetForegroundWindow(wintypes.HWND(number)) else (
            "SetForegroundWindow refused the window")
else:
    def _not_windows() -> NoReturn:
        raise AssertionError("the Windows host is built on Windows only")

    def _win_displays() -> list[Display]:
        _not_windows()

    def _win_windows() -> list[Seen]:
        _not_windows()

    def _win_activate(number: int) -> str:
        _not_windows()


def for_platform(platform: str) -> MacHost | WindowsHost:
    """The host of `platform` (`sys.platform`'s spelling)."""
    if platform == "darwin":
        return MacHost()
    if platform == "win32":
        return WindowsHost()
    raise Invalid("host_failed", f"a window is read and placed on macOS and Windows hosts, not "
                  f"{platform}")
