"""`scripts/windows/bundle.sh` against a host of the test's own: `scp` copies into a local run
root holding a stale `sync.sh`, and the MSYS shell is this host's bash."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the script runs on the Mac side")

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "windows"
REPOS = ("scry-core", "scry-mame", "scry-dosbox-x")
SCP = """#!/bin/bash
cp "$2" "${3#*:}"
"""
CYGPATH = """#!/bin/bash
printf '%s\\n' "$2"
"""
MSYS = """#!/bin/bash
bash -s
"""
STALE = "#!/usr/bin/env bash\necho STALE\n"


def _git(where: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(where), "-c", "user.email=t@t", "-c", "user.name=t",
                           *args], capture_output=True, text=True, check=True).stdout


def _bundle(tmp_path: Path, *, mirrored: bool) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run `bundle.sh` from a scry-core whose `main` carries the tree's `sync.sh` and whose
    working copy of it has an edit no bundle carries; the host has the three mirrors and clones
    only when `mirrored`."""
    code, root, fakes = tmp_path / "code", tmp_path / "host", tmp_path / "bin"
    root.mkdir()
    for repo in REPOS:
        (code / repo).mkdir(parents=True)
        _git(code / repo, "init", "-q", "-b", "main")
        (code / repo / "a.txt").write_text(repo, encoding="utf-8")
    windows = code / "scry-core" / "scripts" / "windows"
    windows.mkdir(parents=True)
    shutil.copy(SCRIPTS / "sync.sh", windows)
    for repo in REPOS:
        _git(code / repo, "add", "-A")
        _git(code / repo, "commit", "-qm", "start")
        if mirrored:
            _git(root, "clone", "-q", "--bare", str(code / repo), f"bare/{repo}.git")
            _git(root, "clone", "-q", f"bare/{repo}.git", repo)
    with (windows / "sync.sh").open("a", encoding="utf-8") as uncommitted:
        uncommitted.write("echo UNCOMMITTED\n")
    shutil.copy(SCRIPTS / "bundle.sh", windows)
    (windows / "msys.sh").write_text(MSYS, encoding="utf-8")
    (windows / "msys.sh").chmod(0o755)
    (root / "sync.sh").write_text(STALE, encoding="utf-8")
    fakes.mkdir()
    for name, body in (("scp", SCP), ("cygpath", CYGPATH)):
        (fakes / name).write_text(body, encoding="utf-8")
        (fakes / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{fakes}{os.pathsep}{os.environ['PATH']}",
           "SCRY_WIN_SSH": "user@host", "SCRY_WIN_ROOT": str(root)}
    ran = subprocess.run(["bash", str(windows / "bundle.sh")], env=env, capture_output=True,
                         text=True, timeout=60, check=False)
    return ran, root


def test_the_host_runs_the_sync_of_the_main_carried_and_its_clones_follow(
        tmp_path: Path) -> None:
    ran, root = _bundle(tmp_path, mirrored=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "STALE" not in ran.stdout and "UNCOMMITTED" not in ran.stdout, ran.stdout
    assert (root / "sync.sh").read_bytes() == (SCRIPTS / "sync.sh").read_bytes()
    assert [line.split(" rc=")[0] for line in ran.stdout.splitlines()] == list(REPOS), ran.stdout


def test_a_sync_that_could_not_bring_a_repository_fails_the_step(tmp_path: Path) -> None:
    """No mirror on the host, so every bundle fetch fails."""
    ran, _ = _bundle(tmp_path, mirrored=False)
    assert "scry-core fetch-bundle rc=" in ran.stdout, ran.stdout + ran.stderr
    assert ran.returncode != 0, ran.stdout
