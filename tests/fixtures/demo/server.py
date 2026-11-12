"""A tiny real MCP server for the demo runner's tests: the real `mcp` library over stdio, its
tools answering the way a Scry server does (a structured document, its JSON as text, an image
part when there is a picture). `DEMO_LOG` names a file each structured reply is appended to,
as JSON, so a test can see which of those tools answered."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent

# A one-pixel PNG.
PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
                         "60e6kgAAAABJRU5ErkJggg==")

server = MCPServer("demo-fixture")
_held: dict[str, int] = {"value": 0}


def _answer(body: dict[str, Any], *extra: Any) -> CallToolResult:
    log = os.environ.get("DEMO_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(body) + "\n")
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body)), *extra],
                          structured_content=body)


@server.tool()
def start(value: int = 7, binary: str = "", shared: bool = False,
          display: int | None = None) -> CallToolResult:
    _held["value"] = value
    body: dict[str, Any] = {"status": "ok", "summary": "started", "pid": os.getpid(),
                            "value": value, "binary": binary, "where": str(Path.cwd())}
    if shared:
        body["shared"] = shared
    if display is not None:
        body["display"] = display
    return _answer(body)


@server.tool()
def read() -> CallToolResult:
    return _answer({"status": "ok", "summary": "read", "value": _held["value"]})


@server.tool()
def refuse() -> CallToolResult:
    return _answer({"status": "INVALID", "code": "bad_argument", "message": "refused on purpose"})


@server.tool()
def picture(dest: str) -> CallToolResult:
    Path(dest).write_bytes(PIXEL)
    return _answer({"status": "ok", "summary": "picture", "path": dest},
                   ImageContent(type="image", data=base64.b64encode(PIXEL).decode("ascii"),
                                mime_type="image/png"))


@server.tool()
def record(frames: int, dest: str) -> CallToolResult:
    """A recording as both servers answer it: the AVI at `dest`, and the file's own numbers."""
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    avi = (Path(__file__).parent / "screen.avi").read_bytes()
    path.write_bytes(avi)
    return _answer({"status": "ok", "summary": f"record: {frames} frames",
                    "path": str(path), "frames": frames, "bytes": len(avi),
                    "avi_frames": 2, "began": True, "ended": True, "frame_before": 7})


@server.tool()
def plain(text: str = "not a document") -> CallToolResult:
    """Text only, with no structured document: what a client must still read."""
    return CallToolResult(content=[TextContent(type="text", text=text)])


@server.tool()
def boom() -> CallToolResult:
    raise RuntimeError("kaboom")


@server.tool()
def sleep(seconds: float) -> CallToolResult:
    time.sleep(seconds)
    return _answer({"status": "ok", "summary": "slept"})


@server.tool()
def die() -> CallToolResult:
    os._exit(1)


@server.tool()
def close() -> CallToolResult:
    return _answer({"status": "ok", "summary": "closed", "closed": True})


if __name__ == "__main__":
    server.run("stdio")
