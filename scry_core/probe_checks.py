"""Probe checks shared by server repositories; each returns problem lines.

Configure the probe at test collection: the shape guard fails on an anchor imported after it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from scry_core import client_cap, probe, probe_captures

SERVERS_FILE = Path("mcp_probe") / "servers.py"
TASKS_DIR = Path("mcp_probe") / "tasks"


def repository(root: Path) -> probe.ProbeRepo:
    return probe.configure(root / SERVERS_FILE, root / TASKS_DIR)


def refused(repo: probe.ProbeRepo, server: str) -> list[str]:
    return probe.refusals(probe.load_surface(repo, server), probe.load_tasks(repo, server))


def captures_misjudged(repo: probe.ProbeRepo, server: str) -> list[str]:
    """Tasks whose rejudged capture differs from the recorded verdict, or that have none."""
    return probe_captures.capture_problems(repo, server, repo.captured_dir / server,
                                           probe.tasks_file(repo, server))


def over_cap(repo: probe.ProbeRepo) -> list[str]:
    """Every `instructions` and tool description past the client's cap, before the probe's cut."""
    return [line for name, module in repo.modules.items()
            for line in client_cap.over_the_cap(name, module.mcp)]


MARGINS_SHOWN = 8


def margins(repo: probe.ProbeRepo) -> list[str]:
    """The `MARGINS_SHOWN` texts per server nearest the cap; informational."""
    return [line for name, module in repo.modules.items()
            for line in client_cap.margins(name, module.mcp, MARGINS_SHOWN)]


def narrowed(surface: probe.Surface, tasks: list[dict[str, Any]]) -> probe.Surface:
    names = {probe.on_tool(t) for t in tasks}
    return dataclasses.replace(surface, tools={n: t for n, t in surface.tools.items()
                                               if n in names})


def judge_line(surface: probe.Surface, tasks: list[dict[str, Any]], task_id: str,
               line: str) -> probe.Verdict:
    """Judge `line` for `task_id` on `surface` narrowed to `tasks`."""
    task = next(t for t in tasks if t["id"] == task_id)
    return probe.judge(narrowed(surface, tasks), task, probe.parse(line, [task_id])[task_id])
