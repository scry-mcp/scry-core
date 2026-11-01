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
import functools
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


def plan_switch(spaces: list[int], managed: list[Any]) -> tuple[str, int] | None:
    """The (display identifier, Space) to switch to so one of `spaces` is shown, or None when one
    already is, or when no display holds any."""
    target: tuple[str, int] | None = None
    for display in managed:
        try:
            held = {int(s["ManagedSpaceID"]) for s in display["Spaces"]}
            current = int(display["Current Space"]["ManagedSpaceID"])
            ident = str(display["Display Identifier"])
        except (KeyError, TypeError, ValueError):
            continue
        if current in spaces:
            return None
        if target is None:
            target = next(((ident, n) for n in spaces if n in held), None)
    return target


def _space_ids(managed: list[Any] | None) -> set[int]:
    """Every Space ID the desk lists. The window server also reports IDs that name no Space (0 for a
    window on every desktop, on the reports found), and those say nothing of where a window is."""
    found: set[int] = set()
    for display in managed or []:
        try:
            found.update(int(s["ManagedSpaceID"]) for s in display["Spaces"])
        except (KeyError, TypeError, ValueError):
            continue
    return found


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
        """The windows over `window` on the Space it is on. The window server lists a full-screen
        application's window on screen, and above, for as long as the application lives, though the
        display shows another Space: only a Space known to differ clears a window."""
        known = _space_ids(focus_watch._managed())
        mine = known.intersection(self.spaces_of(window))
        return [s for s in self._over(window)
                if not mine or not (theirs := known.intersection(self.spaces_of(s)))
                or mine & theirs]

    def _over(self, window: Seen) -> list[Seen]:
        """The windows the window server says are on screen over `window`, on any Space."""
        libs = focus_watch._graphics()
        if libs is None:
            return []
        cg, cf = libs
        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        listed = cg.CGWindowListCopyWindowInfo(ABOVE_WINDOW, window.number)
        found = focus_watch.plist_of(cf, listed) if listed else None
        return seen_from(found) if isinstance(found, list) else []

    def spaces_of(self, window: Seen) -> list[int]:
        """Every Space the window server says holds `window`; none when it will not say."""
        libs = focus_watch._graphics()
        if libs is None or focus_watch.spaces_missing(libs[0]):
            return []
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
        return [int(n) for n in spaces] if isinstance(spaces, list) else []

    def activate(self, window: Seen) -> str:
        """Switch to the window's Space, then make its application frontmost; why not, or ''."""
        spaces = self.spaces_of(window)
        managed = focus_watch._managed()
        if not spaces or managed is None:
            return ("the window server would not say which Space holds the window "
                    f"(missing: {focus_watch.spaces_missing() or 'the listing itself'})")
        if (step := plan_switch(spaces, managed)) is not None:
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
    """`scry_core.window.Host` on Windows: user32 through ctypes, in real pixels."""

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

    @functools.cache
    def _per_monitor_aware() -> None:
        """An unaware process is lied to in scaled pixels (1280x720 on a 4K panel at 300 %), and
        an emulator places its window in real ones. A refusal means the process already chose."""
        ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

    def _win_displays() -> list[Display]:
        _per_monitor_aware()
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
        _per_monitor_aware()
        user32 = ctypes.WinDLL("user32")
        found: list[Seen] = []
        callback = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd: Any, _data: Any) -> int:
            rect, pid = wintypes.RECT(), wintypes.DWORD()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            width, height = rect.right - rect.left, rect.bottom - rect.top
            shown, iconic = bool(user32.IsWindowVisible(hwnd)), bool(user32.IsIconic(hwnd))
            # A window neither shown nor minimised is a helper (IME, toolkit root), never one
            # the owner could see: listing it would make `main_window` pick it by size.
            if (min(width, height) >= MIN_SIDE and not user32.GetWindow(hwnd, 4)   # GW_OWNER
                    and (shown or iconic)):
                found.append(Seen(pid=pid.value, number=int(hwnd),
                                  bounds=(rect.left, rect.top, width, height),
                                  onscreen=shown and not iconic))
            return 1

        user32.EnumWindows(callback(each), 0)         # top of the z-order first
        return found

    def _win_activate(number: int) -> str:
        _per_monitor_aware()
        user32 = ctypes.WinDLL("user32")
        kernel32 = ctypes.WinDLL("kernel32")
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = wintypes.HWND(number)
        user32.ShowWindow(hwnd, 9)                                  # SW_RESTORE
        # Windows refuses a foreground change from a process that is not in the foreground, and
        # a process started by the task scheduler never is. Joining the foreground thread's input
        # queue lets it through, but blocks when that thread pumps no messages: skip a hung one.
        front = user32.GetForegroundWindow()
        theirs = (user32.GetWindowThreadProcessId(front, None)
                  if front and not user32.IsHungAppWindow(front) else 0)
        ours = kernel32.GetCurrentThreadId()
        joined = bool(theirs) and theirs != ours and user32.AttachThreadInput(ours, theirs, True)
        try:
            user32.keybd_event(0x12, 0, 0, 0)                       # an Alt press lets it through
            user32.keybd_event(0x12, 0, 2, 0)
            user32.BringWindowToTop(hwnd)
            user32.SwitchToThisWindow(hwnd, True)
            user32.SetForegroundWindow(hwnd)
        finally:
            if joined:
                user32.AttachThreadInput(ours, theirs, False)
        return "" if (user32.GetForegroundWindow() or 0) == number else (
            "the window did not become the foreground window")
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
