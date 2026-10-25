"""`host_program`: a double the host runs by its path, and a FIFO a test can release."""

from __future__ import annotations

import stat
import subprocess
import threading
from pathlib import Path

from scry_core import host_program


def test_the_program_runs_by_its_path_with_its_arguments_and_its_exit_code(
        tmp_path: Path) -> None:
    exe = host_program.write(tmp_path / "sub" / "emu", "import sys\n"
                             "print(' '.join(sys.argv[1:]))\nsys.exit(len(sys.argv) - 1)\n")
    done = subprocess.run([str(exe), "-version", "two words"], capture_output=True, text=True,
                          check=False)
    assert (done.returncode, done.stdout.strip()) == (2, "-version two words"), done


def test_a_fifo_blocks_its_reader_until_it_is_released(tmp_path: Path) -> None:
    path = tmp_path / "f"
    host_program.fifo(path)
    assert stat.S_ISFIFO(path.stat().st_mode)
    read: list[bytes] = []
    reader = threading.Thread(target=lambda: read.append(path.read_bytes()), daemon=True)
    reader.start()
    reader.join(0.2)
    assert reader.is_alive(), "the control: an unreleased FIFO holds its reader"
    host_program.release_fifo(path)
    reader.join(5)
    assert read == [b""], "the reader was not released"


def test_releasing_what_no_reader_holds_is_no_error(tmp_path: Path) -> None:
    host_program.release_fifo(tmp_path / "absent")
