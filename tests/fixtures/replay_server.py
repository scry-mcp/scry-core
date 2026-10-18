"""A double Scry server for the replay runner: `start`, `state_list`, `perform` and `close` over
stdio. Its `perform` answers each step as an advance landing at `pc` 0x10 and the frame it was
asked to run, and holds each step's `recorded` to that answer as a real server does."""

from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer

from scry_core import recording

mcp = MCPServer("replay-double", instructions="a double")
STATES = [s for s in os.environ.get("REPLAY_DOUBLE_STATES", "boot").split(",") if s]


@mcp.tool()
def start(system: str = "", binary: str = "", rompath: str = "") -> dict[str, Any]:
    if os.environ.get("REPLAY_DOUBLE_REFUSES_START"):
        return {"summary": "start: INVALID", "status": "INVALID", "code": "bad_argument",
                "message": "refused", "session": {}}
    return {"summary": f"started {system} on {binary or 'the ladder'}", "status": "ok",
            "session": {}}


@mcp.tool()
def state_list() -> dict[str, Any]:
    return {"summary": "states", "status": "ok", "states": [{"name": n} for n in STATES],
            "session": {}}


@mcp.tool()
def perform(steps: list[dict[str, Any]], summaries: bool = False) -> dict[str, Any]:
    for i, step in enumerate(steps):
        if step.get("op") == "fails":
            return {"summary": "perform: INVALID", "status": "INVALID", "code": "step_failed",
                    "message": "no such op", "failed_at": i, "steps_completed": i,
                    "session": {}}
        got = {"status": "ok", "pc": "0x10", "frame": step.get("frames", 0)}
        apart = recording.diverged(step.get(recording.RECORDED) or {}, got)
        if apart is not None:
            field, recorded, value = apart
            return {"summary": "perform: INVALID", "status": "INVALID", "code": "diverged",
                    "message": f"step {i} diverged", "failed_at": i, "field": field,
                    "recorded": recorded, "got": value, "steps_completed": i, "session": {}}
    return {"summary": f"perform: {len(steps)} steps", "status": "ok",
            "steps_completed": len(steps), "session": {}}


@mcp.tool()
def close() -> dict[str, Any]:
    return {"summary": "closed", "status": "ok", "session": {}}


if __name__ == "__main__":
    mcp.run()
