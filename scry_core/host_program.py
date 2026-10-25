"""Test doubles and paths as this host runs and spells them."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

#: Itself the process it runs: a venv's `python.exe` on Windows is a launcher.
INTERPRETER = getattr(sys, "_base_executable", sys.executable)


def write(path: Path, body: str) -> Path:
    """The path that runs `body`, written at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        # no `#!`, no mode bit; cmd.exe re-reads args
        path.write_text(body, encoding="utf-8")
        launcher = path.with_name(path.name + ".cmd")
        launcher.write_text(f'@"{INTERPRETER}" "{path}" %*\r\n', encoding="utf-8")
        return launcher
    else:
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)
        return path


def absolute(*parts: str) -> str:
    return str(Path(Path.cwd().anchor, *parts))


def temporary(name: str) -> str:
    return str(Path(tempfile.gettempdir(), name))

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
