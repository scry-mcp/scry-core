"""A double Scry server for the replay runner: `start`, `declaration_list`, `state_list`,
`perform` and `close` over stdio. Its `perform` answers each step as an advance
landing at `pc` 0x10 and the frame it was asked to run, holds each step's `recorded` to that answer
as a real server does, and says how many held. The environment makes it break as a server can:
an error result, a list refused whole, a death mid-call, a count of held steps that lies."""

from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer

from scry_core import recording

mcp = MCPServer("replay-double", instructions="a double")
STATES = [s for s in os.environ.get("REPLAY_DOUBLE_STATES", "boot").split(",") if s]
DECLARED = [s for s in os.environ.get("REPLAY_DOUBLE_DECLARED", "").split(",") if s]


@mcp.tool()
def start(system: str = "", binary: str = "", rompath: str = "") -> dict[str, Any]:
    if os.environ.get("REPLAY_DOUBLE_START_DIES"):
        os._exit(1)
    if os.environ.get("REPLAY_DOUBLE_REFUSES_START"):
        return {"summary": "start: INVALID", "status": "INVALID", "code": "bad_argument",
                "message": "refused", "session": {}}
    return {"summary": f"started {system} on {binary or 'the ladder'}", "status": "ok",
            "session": {}}


@mcp.tool()
def declaration_list() -> dict[str, Any]:
    if os.environ.get("REPLAY_DOUBLE_LISTS_FAIL"):
        return {"summary": "declaration_list: INVALID", "status": "INVALID",
                "code": "no_session", "message": "no session", "session": {}}
    return {"summary": "declarations", "status": "ok",
            "breakpoints": [{"ref": r} for r in DECLARED if not r.startswith("w:")],
            "watches": [{"ref": r} for r in DECLARED if r.startswith("w:")], "session": {}}


@mcp.tool()
def state_list() -> dict[str, Any]:
    if os.environ.get("REPLAY_DOUBLE_STATES_NOT_A_LIST"):
        return {"summary": "states", "status": "ok", "states": None, "session": {}}
    return {"summary": "states", "status": "ok", "states": [{"name": n} for n in STATES],
            "session": {}}


@mcp.tool()
def perform(steps: list[dict[str, Any]], summaries: bool = False) -> dict[str, Any]:
    if os.environ.get("REPLAY_DOUBLE_DIES"):
        os._exit(1)
    if os.environ.get("REPLAY_DOUBLE_RAISES"):
        raise RuntimeError("the double broke")
    if os.environ.get("REPLAY_DOUBLE_REFUSES_LIST"):
        return {"summary": "perform: INVALID", "status": "INVALID", "code": "bad_argument",
                "message": "step 1 names no op this server has", "session": {}}
    held = 0
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
        held += bool(step.get(recording.RECORDED))
    held += bool(os.environ.get("REPLAY_DOUBLE_LIES"))
    # Each server's own word for the count: mame says `steps_completed`, dosbox-x `completed`.
    count = "completed" if os.environ.get("REPLAY_DOUBLE_SAYS_COMPLETED") else "steps_completed"
    if os.environ.get("REPLAY_DOUBLE_ENDS_EARLY"):   # mame's list when a settle wait ran out
        return {"summary": "perform: TIMEOUT", "status": "ok", count: len(steps) - 1,
                "verdict": "TIMEOUT", "note": "the last step was not sent", "session": {}}
    return {"summary": f"perform: {len(steps)} steps", "status": "ok", count: len(steps),
            "held": held, "session": {}}


@mcp.tool()
def close() -> dict[str, Any]:
    return {"summary": "closed", "status": "ok", "session": {}}


if __name__ == "__main__":
    mcp.run()
