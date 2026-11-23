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
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from scry_core import avi, png

# An 8 x 8 picture: the size of the frames of `screen.avi`, so a loop's still can be cut from it.
PIXEL = png.encode(png.Raster(8, 8, bytes(range(192))))

server = MCPServer("demo-fixture")
_held: dict[str, int] = {"value": 0, "frame": 0}


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


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def read() -> CallToolResult:
    body: dict[str, Any] = {"status": "ok", "summary": "read", "value": _held["value"]}
    if note := os.environ.get("DEMO_NOTE"):     # a field the server adds only sometimes
        body["note"] = note
    return _answer(body)


@server.tool()
def press(key: str, frames: int = 4) -> CallToolResult:
    """An input as MAME answers one: the frames the machine ran, and when the key went down and
    up."""
    before = _held["frame"]
    _held["frame"] += frames + 1
    return _answer({"status": "ok", "summary": f"press {key}", "frame_before": before,
                    "frame_after": _held["frame"], "frame_set": before,
                    "frame_released": before + frames, "frame": _held["frame"]})


@server.tool()
def point(x: int, y: int) -> CallToolResult:
    """An input as DOSBox-X answers one: only the frame the machine stopped at."""
    _held["frame"] += 3
    return _answer({"status": "ok", "summary": "point", "pointer": {"x": x, "y": y},
                    "frame": _held["frame"]})


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def peek(ref: str) -> CallToolResult:
    """A reader whose reply names its own argument, as a Scry server's `names` block does, unless
    `DEMO_NO_NAMES` says the session asked for no names."""
    body: dict[str, Any] = {"status": "ok", "summary": f"peek {ref}", "value": _held["value"]}
    if not os.environ.get("DEMO_NO_NAMES"):
        body["names"] = [{"field": "given.ref", "number": "0x9405", "kind": "symbol",
                          "name": ref}]
    return _answer(body)


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
def snap(dest: str) -> CallToolResult:
    """A picture as both servers name one written: its path with its size and digest."""
    Path(dest).write_bytes(PIXEL)
    return _answer({"status": "ok", "summary": "snap", "path": dest, "bytes": len(PIXEL),
                    "sha256": "0" * 64, "width": 1})


@server.tool()
def record(frames: int, dest: str) -> CallToolResult:
    """A recording as both servers answer it: the AVI at `dest`, and the file's own numbers."""
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    recording = (Path(__file__).parent / "screen.avi").read_bytes()
    path.write_bytes(recording)
    return _answer({"status": "ok", "summary": f"record: {frames} frames",
                    "verdict": "ELAPSED", "path": str(path), "frames": frames,
                    "bytes": len(recording), "avi_frames": avi.count(recording),
                    "began": True, "ended": True,
                    "frame_before": 7})


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
