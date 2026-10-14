"""What every server repository checks on its own probe surface, held once: the task set fits the
server, every capture is judged as it was, and every text fits the client's cap.

`refused`, `captures_misjudged` and `over_cap` answer the problems they found, one line each, and
an empty list when there is none, so a repository's test is one assertion on its own server and
the judging stays here; `repository`, `narrowed` and `judge_line` are what they share with a
repository's own cases. What only one server has (its own judge's cases, a tool's path shapes)
stays in that server's suite.

A repository keeps its probe at `SERVERS_FILE` and `TASKS_DIR` under its root, which the hook
reads too, and its captures where the probe derives them.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from scry_core import probe
from scry_core.client_cap import over_the_cap

#: Where a repository keeps its probe, under its root: the servers file and the tasks directory.
SERVERS_FILE = Path("mcp_probe") / "servers.py"
TASKS_DIR = Path("mcp_probe") / "tasks"


def repository(root: Path) -> probe.ProbeRepo:
    """The repository at `root`, read through its `SERVERS_FILE` and `TASKS_DIR`."""
    return probe.configure(root / SERVERS_FILE, root / TASKS_DIR)


def refused(repo: probe.ProbeRepo, server: str) -> list[str]:
    """What `--check` refuses on `server`, one line each."""
    return probe.refusals(probe.load_surface(repo, server), probe.load_tasks(repo, server))


def captures_misjudged(repo: probe.ProbeRepo, server: str) -> list[str]:
    """Every task of `server` judged on the whole surface, as a real run answers it: each task's
    capture judged again with the server's own judge gives back the verdict recorded when it ran,
    and a task with no capture is named."""
    return probe.capture_problems(repo, server, repo.captured_dir / server,
                                  probe.tasks_file(repo, server))


def over_cap(repo: probe.ProbeRepo) -> list[str]:
    """Every `instructions` and tool description of the repository's servers past the client's
    cap, measured on the server objects the probe loads, before the cut the probe makes."""
    return [line for name, module in repo.modules.items()
            for line in over_the_cap(name, module.mcp)]


def narrowed(surface: probe.Surface, tasks: list[dict[str, Any]]) -> probe.Surface:
    """`surface` narrowed to the tools `tasks` name: real descriptions, real signatures, the
    server's real judge, so a handful of tasks is not a coverage hole on the whole surface."""
    names = {probe.on_tool(t) for t in tasks}
    return dataclasses.replace(surface, tools={n: t for n, t in surface.tools.items()
                                               if n in names})


def judge_line(surface: probe.Surface, tasks: list[dict[str, Any]], task_id: str,
               line: str) -> probe.Verdict:
    """One answer line for the task `task_id` of `tasks`, judged on `surface` narrowed to them."""
    task = next(t for t in tasks if t["id"] == task_id)
    return probe.judge(narrowed(surface, tasks), task, probe.parse(line, [task_id])[task_id])
