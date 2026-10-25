"""`host_program`: a double the host runs by its path, and a FIFO a test can release."""

from __future__ import annotations

import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

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


def test_an_absolute_path_is_one_this_host_calls_absolute() -> None:
    path = Path(host_program.absolute("a", "b"))
    assert path.is_absolute() and path.parts[-2:] == ("a", "b")


def test_a_temporary_path_lies_in_a_directory_that_is_there() -> None:
    path = Path(host_program.temporary("x.bin"))
    assert path.is_absolute() and path.parent.is_dir() and path.name == "x.bin"


@pytest.mark.parametrize("marker", [host_program.MODE_BITS, host_program.POSIX_NAMES,
                                    host_program.POSIX_TASKS])
def test_a_posix_marker_skips_on_windows_alone(marker: pytest.MarkDecorator) -> None:
    assert marker.mark.name == "skipif"
    assert marker.mark.args == (sys.platform == "win32",) and marker.mark.kwargs["reason"]
