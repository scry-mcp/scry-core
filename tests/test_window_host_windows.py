"""`WindowsHost` against a real Windows desktop: the displays user32 reports, windows this test
opens in processes of their own, and the activation. Opens windows, so `-m window`; skipped
elsewhere."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Iterator

import pytest

from scry_core import window as w
from scry_core.window_host import WindowsHost

pytestmark = [pytest.mark.window,
              pytest.mark.skipif(sys.platform != "win32", reason="needs a Windows desktop")]

# A window at a place the test can recognise, pumping messages until stdin closes (a window that
# does not is treated as hung and never reordered). It reports its own pid: under a venv the
# launcher is a different process from the interpreter that owns the window.
OPENER = (
    "import ctypes, os, sys, threading, tkinter\n"
    "ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))\n"
    "root = tkinter.Tk()\n"
    "root.geometry('420x300+120+90')\n"
    "root.update()\n"
    "print(os.getpid(), flush=True)\n"
    "closed = []\n"
    "threading.Thread(target=lambda: (sys.stdin.read(), closed.append(1)), daemon=True).start()\n"
    "def poll():\n"
    "    root.quit() if closed else root.after(50, poll)\n"
    "poll()\n"
    "root.mainloop()\n"
)
BOUND_S = 10.0
# What an emulator reads: aware first, then the displays through the host.
AWARE_DISPLAYS = (
    "import ctypes\n"
    "ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))\n"
    "from scry_core.window_host import WindowsHost\n"
    "print([(d.index, d.bounds) for d in WindowsHost().displays()])\n"
)


@pytest.fixture
def opener() -> Iterator[Callable[[], int]]:
    procs: list[subprocess.Popen[str]] = []

    def open_one() -> int:
        proc = subprocess.Popen([sys.executable, "-c", OPENER], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)
        procs.append(proc)
        assert proc.stdout is not None
        return int(proc.stdout.readline())

    yield open_one
    for proc in procs:
        if proc.stdin is not None:
            proc.stdin.close()
        proc.kill()
        proc.wait(timeout=BOUND_S)


def _mine(host: WindowsHost, pid: int) -> w.Seen:
    deadline = time.monotonic() + BOUND_S
    while time.monotonic() < deadline:
        found = w.main_window(pid, host.windows())
        if found is not None:
            return found
        time.sleep(0.1)
    raise AssertionError(f"no window of pid {pid} in {host.windows()}")


def test_the_displays_start_with_the_primary_one_at_the_origin() -> None:
    shown = WindowsHost().displays()
    assert shown and [d.index for d in shown] == list(range(len(shown)))
    assert shown[0].bounds[:2] == (0, 0) and shown[0].bounds[2] > 0 < shown[0].bounds[3]


def test_a_window_is_listed_where_it_was_placed_and_on_screen(
        opener: Callable[[], int]) -> None:
    host = WindowsHost()
    pid = opener()
    seen = _mine(host, pid)
    assert seen.onscreen and seen.bounds[2] >= 420 and seen.bounds[3] >= 300
    assert abs(seen.bounds[0] - 120) < 20 and abs(seen.bounds[1] - 90) < 20, seen
    state = w.state_of(pid, host.windows(), host.displays(), host.above)
    assert state is not None and state.display == 0 and state.onscreen


def test_activating_a_covered_window_puts_it_in_front_of_what_covered_it(
        opener: Callable[[], int]) -> None:
    host = WindowsHost()
    under, over = opener(), opener()
    covered = _mine(host, under)
    _mine(host, over)
    # The interactive task's own console may sit above both; `over` must be among what covers it.
    def covering() -> list[int]:
        return [s.pid for s in host.above(_mine(host, under))]

    assert over in covering(), "the control: it is covered"
    assert host.activate(covered) == ""
    deadline = time.monotonic() + BOUND_S
    while time.monotonic() < deadline and over in covering():
        time.sleep(0.1)
    # The topmost taskbar is always listed: only `over` must have gone below.
    assert over not in covering()


def test_a_pid_with_no_window_is_not_found() -> None:
    listed = WindowsHost().windows()
    assert listed, "the control: the desktop lists windows"
    assert w.main_window(2 ** 22 - 4, listed) is None


def test_displays_are_in_the_pixels_an_emulator_places_its_window_in() -> None:
    """An unaware host reads scaled pixels: its display origins would be false."""
    read = subprocess.run([sys.executable, "-c", AWARE_DISPLAYS], capture_output=True, text=True,
                          timeout=BOUND_S, check=True).stdout.strip()
    assert str([(d.index, d.bounds) for d in WindowsHost().displays()]) == read
