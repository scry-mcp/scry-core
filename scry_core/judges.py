"""The argument judges the media layer shares: whole numbers, rectangles, shifts, paths and the
picture a path names. Each refuses `bad_argument` in a sentence naming the argument, so a server
tool and a file tool reject one mistake in one voice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TypeGuard

from scry_core import png
from scry_core.reply_contract import Invalid

Rect = tuple[int, int, int, int]


def whole(value: object, lo: int = 0, hi: int | None = None) -> TypeGuard[int]:
    """`value` is an int in `lo..hi`. A JSON `true` is a Python int and is never one here."""
    return (isinstance(value, int) and not isinstance(value, bool) and value >= lo
            and (hi is None or value <= hi))


def rect(name: str, value: object) -> Rect:
    """`value` as `[x, y, width, height]`, x and y at or above zero, width and height above it,
    or the refusal naming `name`."""
    if not (isinstance(value, list | tuple) and len(value) == 4
            and all(whole(v) for v in value[:2]) and all(whole(v, 1) for v in value[2:])):
        raise Invalid("bad_argument", f"{name}={value!r} is [x, y, width, height]: x and y at or "
                      "above zero, a width and a height above it")
    x, y, w, h = value
    return x, y, w, h


def shift(value: object) -> tuple[int, int]:
    """`value` as `[dx, dy]`, two whole numbers of any sign, or the refusal."""
    if not (isinstance(value, list | tuple) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
        raise Invalid("bad_argument", f"shift={value!r} is [dx, dy], two whole numbers")
    return value[0], value[1]


def absolute(name: str, value: object) -> Path:
    """A path argument: a string naming an absolute path, or the refusal naming `name`."""
    if not isinstance(value, str) or not value or "\x00" in value or not Path(value).is_absolute():
        raise Invalid("bad_argument", f"{name}={value!r} is an absolute path")
    return Path(value)


def existing_file(name: str, value: object) -> Path:
    """`absolute`, and a file is there."""
    path = absolute(name, value)
    if not path.is_file():
        raise Invalid("bad_argument", f"{name}: {path} is not a file")
    return path


def picture_file(name: str, path: Path, sha256: str | None = None) -> tuple[png.Raster, str]:
    """The picture in the PNG at `path` and the sha256 of the bytes it was decoded from, read
    ONCE so the two describe one file. With `sha256`, a file that no longer matches it is
    refused: it is not the frame its manifest describes."""
    try:
        data = path.read_bytes()
    except (OSError, ValueError) as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}") from None
    digest = hashlib.sha256(data).hexdigest()
    if sha256 is not None and digest != sha256:
        raise Invalid("bad_argument", f"{name}: {path} no longer matches the sha256 its manifest "
                      "names, so it is not the frame the manifest describes")
    try:
        return png.decode(data), digest
    except png.NotAPicture as e:
        raise Invalid("bad_argument", f"{name}: {path}: {e}") from None
