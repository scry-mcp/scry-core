"""An AVI's main header (`avih`), read once for every server: how many frames the file declares
and their size.

WHY THE HEADER AND NOT THE CHUNKS. A video frame's chunk is tagged `00dc`, and a finished AVI
ends with an index (`idx1`) that names every frame again, so counting the tag reads about twice
the frames a finished capture holds. `avih` is written by the recorder when it closes the file,
and its fifth DWORD is the total it stands by. A capture still being written carries the header
with that total at 0 and no index yet, so there each `00dc` is one frame: `count` reads a file by
whichever of the two it is.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import NamedTuple

from scry_core.reply_contract import Invalid

TAG = b"avih"
#: Where the total frames, the width and the height lie among the header's fourteen DWORDs.
FRAMES_DWORD, WIDTH_DWORD = 4, 8
DWORDS = 14
#: How far into the file the header is looked for: it is the first chunk of `hdrl`.
WITHIN = 4096


class Header(NamedTuple):
    """What a finished AVI's main header declares."""

    frames: int
    width: int
    height: int


def parse(head: bytes) -> Header | None:
    """The main header in `head`, a file's first `WITHIN` bytes, or None when they are no RIFF
    AVI or carry no whole `avih`."""
    head = head[:WITHIN]
    at = head.find(TAG)
    body = head[at + 8:at + 8 + DWORDS * 4] if at >= 0 else b""
    if head[:4] != b"RIFF" or head[8:12] != b"AVI " or len(body) < DWORDS * 4:
        return None
    total, = struct.unpack_from("<I", body, FRAMES_DWORD * 4)
    width, height = struct.unpack_from("<II", body, WIDTH_DWORD * 4)
    return Header(total, width, height)


def header(path: Path) -> Header | None:
    """`parse` of the file at `path`, or None when it cannot be read."""
    try:
        with path.open("rb") as f:
            return parse(f.read(WITHIN))
    except OSError:
        return None


def finished(data: bytes) -> bool:
    """Whether a whole AVI was closed by its writer: the index (`idx1`) is written last."""
    return b"idx1" in data


def count(data: bytes) -> int:
    """The frames a whole AVI holds: its header's total once it is `finished`, and its `00dc`
    chunks while it is still being written (the module docstring says why)."""
    found = parse(data)
    if found is not None and finished(data):
        return found.frames
    return data.count(b"00dc")


def size(name: str, path: Path) -> tuple[int, int]:
    """The frame size `path`'s header declares, or the refusal naming `name` and what is
    missing."""
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
