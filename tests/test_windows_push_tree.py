"""`scripts/windows/push-tree.sh` against a host of the test's own: `scp` copies into a local run
root, and the MSYS shell is this host's bash in that root."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the script runs on the Mac side")

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "windows"
SCP = """#!/bin/bash
cp "$2" "${3#*:}"
"""
CYGPATH = """#!/bin/bash
printf '%s\\n' "$2"
"""
MSYS = """#!/bin/bash
bash -s
"""


def _git(where: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t", "-c", "user.name=t",
                           *args], capture_output=True, text=True, check=True).stdout


def _push(tmp_path: Path, change: str) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    code, root, fakes = tmp_path / "code", tmp_path / "host", tmp_path / "bin"
    windows = code / "scry-core" / "scripts" / "windows"
    windows.mkdir(parents=True)
    shutil.copy(SCRIPTS / "push-tree.sh", windows)
    (windows / "msys.sh").write_text(MSYS, encoding="utf-8")
    (windows / "msys.sh").chmod(0o755)
    fakes.mkdir()
    for name, body in (("scp", SCP), ("cygpath", CYGPATH)):
        (fakes / name).write_text(body, encoding="utf-8")
        (fakes / name).chmod(0o755)
    repo = code / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name in ("a.txt", "m.txt", "z.txt"):
        (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "start")
    root.mkdir()
    _git(root, "clone", "-q", str(repo), "repo")
    (repo / change).unlink()
    env = {**os.environ, "PATH": f"{fakes}{os.pathsep}{os.environ['PATH']}",
           "SCRY_WIN_SSH": "user@host", "SCRY_WIN_ROOT": str(root)}
    ran = subprocess.run(["bash", str(windows / "push-tree.sh"), "repo"], env=env,
                         capture_output=True, text=True, timeout=60, check=False)
    return ran, repo, root / "repo"


@pytest.mark.parametrize("change", ["m.txt", "z.txt"])
def test_a_tracked_file_deleted_here_is_deleted_on_the_host(tmp_path: Path, change: str) -> None:
    """In the middle of the listing, or last, where a skipped file once ended the copy."""
    ran, repo, clone = _push(tmp_path, change)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert sorted(p.name for p in clone.iterdir() if p.name != ".git") == sorted(
        p.name for p in repo.iterdir() if p.name != ".git"), ran.stdout
