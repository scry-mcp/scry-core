"""A cancellation over the real wire: a server in a process of its own, speaking stdio, whose
synchronous tool waits on `progress.Ticker` and reports through `progress.bridge`, cancelled by a
real client. What a Scry server owes its caller when a wait is cancelled is checked here once,
on the transport the servers run on, so each server's own cases only judge how its tools end."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = '''
import sys, threading, time
from pathlib import Path
from typing import Any
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from scry_core import cancel, progress

mcp = MCPServer("t")
OUT = Path(sys.argv[1])
# ONE MACHINE, as a Scry server holds it: every tool takes the lock, so the next call answers
# only once the cancelled one has let go.
LOCK = threading.RLock()

@mcp.tool()
def wait(seconds: float, ctx: Context[Any, Any] | None = None) -> str:
    with LOCK:
        t = progress.Ticker(seconds, progress.bridge(ctx))
        try:
            while not t.expired():
                t.tick("wait: {elapsed:.0f}s of " + f"{seconds:g}s")
                time.sleep(0.05)
            return "expired"
        except BaseException as e:
            if cancel.is_cancellation(e):
                OUT.write_text(f"{time.monotonic() - t.began:.2f}")
            raise

@mcp.tool()
def ping() -> str:
    with LOCK:
        return "pong"

mcp.run()
'''

CANCEL_AFTER_S = 2.5
#: The bound the next call must answer within after the cancel: the wait's own poll is 50 ms,
#: so anything near this is a wait that ran on.
NEXT_CALL_S = 2.0


def test_a_cancelled_wait_ends_at_its_next_poll_answers_nothing_and_frees_the_server(
        tmp_path: Path) -> None:
    script, out = tmp_path / "server.py", tmp_path / "cancelled.txt"
    script.write_text(SERVER, encoding="utf-8")
    progress_seen: list[float] = []
    after: dict[str, float] = {}

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        progress_seen.append(time.monotonic())

    async def main() -> None:
        params = StdioServerParameters(command=sys.executable, args=[str(script), str(out)],
                                       env=dict(os.environ))
        with (tmp_path / "stderr.txt").open("w") as errlog:
            async with Client(stdio_client(params, errlog=errlog),
                              read_timeout_seconds=60) as client:
                answered = None
                with anyio.move_on_after(CANCEL_AFTER_S):
                    answered = await client.call_tool("wait", {"seconds": 30},
                                                      progress_callback=on_progress)
                after["cancelled_at"] = time.monotonic()
                assert answered is None, "the wait answered instead of being cancelled"
                got = await client.call_tool("ping", {})
                after["next_answered"] = time.monotonic() - after["cancelled_at"]
                assert "pong" in str(got.content)
                # Read while the client is still connected: its leaving would cancel the wait too.
                after["unwound_after"] = float(out.read_text()) if out.exists() else -1.0
                after["seen_by_then"] = len(progress_seen)

    anyio.run(main)
    assert after["next_answered"] < NEXT_CALL_S, after
    assert 0 < after["unwound_after"] < CANCEL_AFTER_S + NEXT_CALL_S, (
        "the tool did not unwind as cancelled at the client's cancel", after)
    assert 1 <= after["seen_by_then"] <= CANCEL_AFTER_S + 1, after   # one a second, at most
    assert len(progress_seen) == after["seen_by_then"], "progress arrived after the cancel"
