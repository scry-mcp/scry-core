"""Stand-in windows for the window tier: a window of its own, then a full-screen application taking
the display's Space over it, so `bring_front` is proved against the case that failed in the field.

The tier opens windows and switches the owner's Space, so it carries the `window` marker and runs
only on a Mac with `SCRY_FOCUS_CONTROL=1` (`on_the_desk`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from scry_core import focus_gate
from scry_core import window as w
from scry_core import window_host as wh

SOURCES = Path(__file__).parent
POLL_S = 0.25
RETURN_S = 1.5

_DESK = [pytest.mark.window,
         pytest.mark.skipif(sys.platform != "darwin", reason="the host under test is macOS"),
         pytest.mark.skipif(os.environ.get(focus_gate.OPT_IN_VAR) != "1",
                            reason=f"moves the owner's desk: set {focus_gate.OPT_IN_VAR}=1 on an "
                                   f"idle machine"),
         pytest.mark.skipif(shutil.which("swiftc") is None,
                            reason="the stand-in windows need swiftc")]


def on_the_desk(test: Any) -> Any:
    """Mark a test as window tier: deselected by default, skipped unless the desk may be moved."""
    for mark in _DESK:
        test = mark(test)
    return test


def built(tmp_path: Path, name: str) -> Path:  # needs the desk
    out = tmp_path / name
    run = subprocess.run(["swiftc", "-O", str(SOURCES / f"{name}.swift"), "-o", str(out)],
                         capture_output=True, text=True, timeout=300, check=False)
    assert run.returncode == 0, run.stderr
    return out


def until(what: str, ok: Any, bound_s: float = 12.0) -> None:  # needs the desk
    end = time.monotonic() + bound_s
    while not ok():
        assert time.monotonic() < end, f"{what}: not true within {bound_s:g} s"
        time.sleep(POLL_S)


def shown(pid: int, host: wh.MacHost) -> bool | None:  # needs the desk
    """Whether the window of `pid` is on screen, or None while it lists none."""
    state = w.state_of(pid, host.windows(), host.displays(), host.above)
    return None if state is None else state.onscreen


@contextmanager
def under_a_cover(pid: int, tmp_path: Path) -> Iterator[None]:  # needs the desk
    """A full-screen application taking the Space the window of `pid` is on, for the block."""
    host = wh.MacHost()
    cover = subprocess.Popen([str(built(tmp_path, "cover"))])
    try:
        until("the full-screen application taking the Space", lambda: shown(pid, host) is False)
        yield
    finally:
        cover.terminate()
        cover.wait(timeout=10)
        time.sleep(RETURN_S)     # the display returns to the owner's Space


def behind_a_fullscreen_app(  # needs the desk
        tmp_path: Path) -> Iterator[tuple[int, wh.MacHost]]:
    """A window of its own, then a full-screen application taking the display's Space over it."""
    target = subprocess.Popen([str(built(tmp_path, "target"))])
    try:
        host = wh.MacHost()
        until("the target window listed on screen", lambda: shown(target.pid, host) is True)
        with under_a_cover(target.pid, tmp_path):
            yield target.pid, host
    finally:
        target.terminate()
        target.wait(timeout=10)


def comes_forward(window: Callable[..., dict[str, Any]]) -> None:  # needs the desk
    """`window` (a server's tool) answers the window behind the cover, and `front=True` brings it
    back."""
    behind = window()["window"]
    assert behind["onscreen"] is False, behind
    front = window(front=True)
    assert front["status"] == "ok", front
    assert front["window"]["onscreen"] is True and front["window"]["front"] is True, front
