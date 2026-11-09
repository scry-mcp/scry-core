"""Read or set the primary display's DPI scale, as the Settings slider does.

`DisplayConfigSetDeviceInfo` types -3 (get) and -4 (set) are undocumented and widely used. `read`
prints the percent; `set <pct>` sets it and reads it back.
"""

import ctypes
import sys
from ctypes import wintypes

STEPS = [100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500]
user32 = ctypes.windll.user32


class Luid(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]


class Header(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("size", wintypes.UINT),
        ("adapter", Luid),
        ("id", wintypes.UINT),
    ]


class Get(ctypes.Structure):
    _fields_ = [("h", Header), ("min", ctypes.c_int), ("cur", ctypes.c_int), ("max", ctypes.c_int)]


class Set(ctypes.Structure):
    _fields_ = [("h", Header), ("rel", ctypes.c_int)]


class Path(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_byte * 72)]


def primary_target():
    n_paths, n_modes = wintypes.UINT(), wintypes.UINT()
    assert user32.GetDisplayConfigBufferSizes(2, ctypes.byref(n_paths), ctypes.byref(n_modes)) == 0
    paths = (Path * n_paths.value)()
    modes = (ctypes.c_byte * (64 * n_modes.value))()
    assert (
        user32.QueryDisplayConfig(
            2, ctypes.byref(n_paths), paths, ctypes.byref(n_modes), modes, None
        )
        == 0
    )
    raw = bytes(paths[0].raw)
    adapter = Luid.from_buffer_copy(raw[0:8])  # sourceInfo.adapterId
    source_id = int.from_bytes(raw[8:12], "little")
    return adapter, source_id


def current() -> tuple[int, int]:
    adapter, source = primary_target()
    g = Get(Header(-3, ctypes.sizeof(Get), adapter, source))
    assert user32.DisplayConfigGetDeviceInfo(ctypes.byref(g)) == 0, "get failed"
    return g.min, g.cur


def percent() -> int:
    lo, cur = current()
    return STEPS[cur - lo]


def set_percent(pct: int) -> None:
    adapter, source = primary_target()
    lo, cur = current()
    rec = -lo  # the recommended step sits at index -min in STEPS
    s = Set(Header(-4, ctypes.sizeof(Set), adapter, source), STEPS.index(pct) - rec)
    rc = user32.DisplayConfigSetDeviceInfo(ctypes.byref(s))
    assert rc == 0, f"set rc={rc}"


if __name__ == "__main__":
    if sys.argv[1] == "read":
        print(f"scale={percent()}")
    else:
        set_percent(int(sys.argv[2]))
        print(f"scale={percent()}")
