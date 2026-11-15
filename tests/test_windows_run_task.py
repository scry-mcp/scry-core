"""`scripts/windows/run-task.sh` against a host of the test's own: an `ssh` and an `scp` that
record what they were asked."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the script runs on the Mac side")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "windows" / "run-task.sh"
SSH = """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
case "$*" in
  *Get-ScheduledTask*) echo 0;;
  *launch.ps1*) [ -n "${LAUNCH_FAILS:-}" ] && exit 255; echo "${LAUNCH_SAYS:-DONE}";;
esac
"""
SCP = """#!/bin/bash
[ -n "${SCP_FAILS:-}" ] && exit 1
dest="${@: -1}"
mkdir -p "$dest/build" && echo fetched > "$dest/build/battery.log"
"""


def _run(tmp_path: Path, step: str = "build",
         **extra: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fakes = tmp_path / "bin"
    fakes.mkdir()
    for name, body in (("ssh", SSH), ("scp", SCP)):
        (fakes / name).write_text(body, encoding="utf-8")
        (fakes / name).chmod(0o755)
    calls = tmp_path / "calls"
    made = tmp_path / "temp"
    made.mkdir()
    env = {**os.environ, "PATH": f"{fakes}{os.pathsep}{os.environ['PATH']}", "CALLS": str(calls),
           "TMPDIR": str(made), "SCRY_WIN_SSH": "user@host", "SCRY_WIN_ROOT": "C:/run", **extra}
    ran = subprocess.run(["bash", str(SCRIPT), step, "5"], env=env, capture_output=True,
                         text=True, timeout=60, check=False)
    return ran, calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def test_a_step_that_is_no_plain_name_is_refused_before_the_host_is_reached(
        tmp_path: Path) -> None:
    ran, calls = _run(tmp_path, step="..")
    assert ran.returncode == 2 and calls == [] and "usage" in ran.stderr, ran.stderr


def test_a_fetched_steps_logs_are_removed_from_the_host(tmp_path: Path) -> None:
    ran, calls = _run(tmp_path)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    removal = [c for c in calls if "Remove-Item" in c]
    assert len(removal) == 1, calls
    removed = removal[0].split("SilentlyContinue ", 1)[1].split(", ")
    assert removed == ["C:\\run\\logs\\build", "C:\\run\\logs\\build.log",
                       "C:\\run\\logs\\build.done"], removed
    assert "host_logs_removed_rc=0" in ran.stdout, ran.stdout


def test_logs_that_were_not_fetched_stay_on_the_host(tmp_path: Path) -> None:
    ran, calls = _run(tmp_path, SCP_FAILS="1")
    assert not [c for c in calls if "Remove-Item" in c], calls
    assert "fetch_rc=1" in ran.stdout, ran.stdout


@pytest.mark.parametrize("how", [{"LAUNCH_FAILS": "1"}, {"LAUNCH_SAYS": "TIMEOUT"}])
def test_a_step_that_did_not_end_keeps_its_logs_on_the_host(
        tmp_path: Path, how: dict[str, str]) -> None:
    """Its log came back cut, or it may still be writing."""
    _, calls = _run(tmp_path, **how)
    assert not [c for c in calls if "Remove-Item" in c], calls


def test_the_fetch_lands_in_a_folder_of_its_own_under_the_callers_temporary_folder(
        tmp_path: Path) -> None:
    ran, _ = _run(tmp_path)
    out = Path(ran.stdout.split("out=")[1].split()[0])
    assert out.parent == tmp_path / "temp" and out.name.startswith("scry-win-"), out
    assert (out / "build" / "battery.log").read_text(encoding="utf-8") == "fetched\n"
