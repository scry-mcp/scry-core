"""A test double's program as this host runs one: Python behind its launcher."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path


def write(path: Path, body: str) -> Path:
    """The path that runs `body`, written at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        # no `#!`, no mode bit; cmd.exe re-reads args
        path.write_text(body, encoding="utf-8")
        launcher = path.with_name(path.name + ".cmd")
        launcher.write_text(f'@"{sys.executable}" "{path}" %*\r\n', encoding="utf-8")
        return launcher
    else:
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path


def fifo(path: Path) -> None:
    """A FIFO at `path`, or the test skipped where there is none."""
    import pytest

    if sys.platform == "win32":
        pytest.skip("Windows has no FIFO")
    else:
        os.mkfifo(path)


def release_fifo(path: Path) -> None:
    """A reader blocked on the FIFO at `path`, released."""
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
