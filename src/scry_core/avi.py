"""An AVI's main header (`avih`): the frame count and size a file declares.

A finished capture's `idx1` names every frame again, so counting `00dc` doubles it; one still
being written has total 0 and no index, so there each `00dc` is a frame.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import NamedTuple

from scry_core.reply_contract import Invalid

TAG = b"avih"
FRAMES_DWORD, WIDTH_DWORD = 4, 8
DWORDS = 14
WITHIN = 4096


class Header(NamedTuple):
    frames: int
    width: int
    height: int


def parse(head: bytes) -> Header | None:
    """The main header in a file's first `WITHIN` bytes, or None."""
    head = head[:WITHIN]
    at = head.find(TAG)
    body = head[at + 8:at + 8 + DWORDS * 4] if at >= 0 else b""
    if head[:4] != b"RIFF" or head[8:12] != b"AVI " or len(body) < DWORDS * 4:
        return None
    total, = struct.unpack_from("<I", body, FRAMES_DWORD * 4)
    width, height = struct.unpack_from("<II", body, WIDTH_DWORD * 4)
    return Header(total, width, height)


def header(path: Path) -> Header | None:
    try:
        with path.open("rb") as f:
            return parse(f.read(WITHIN))
    except OSError:
        return None


def finished(data: bytes) -> bool:
    """Whether the writer closed the file (`idx1` is written last)."""
    return b"idx1" in data


def count(data: bytes) -> int:
    """The frames a whole AVI holds: the header total once finished, else its `00dc` chunks."""
    found = parse(data)
    if found is not None and finished(data):
        return found.frames
    return data.count(b"00dc")


def size(name: str, path: Path) -> tuple[int, int]:
    """The frame size `path`'s header declares, or a refusal naming `name`."""
    try:
        with path.open("rb") as f:
            found = parse(f.read(WITHIN))
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}") from None
    if found is None:
        raise Invalid("bad_argument", f"{name}: {path} has no AVI main header (`avih`) in its "
                      f"first {WITHIN} bytes, so its frame size is unknown")
    if not (found.width and found.height):
        raise Invalid("bad_argument", f"{name}: {path}'s main header (`avih`) declares a "
                      f"{found.width}x{found.height} frame, so its frame size is unknown")
    return found.width, found.height
