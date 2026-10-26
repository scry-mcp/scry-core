"""Argument judges shared by the media layer; each refuses `bad_argument` naming the argument."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, TypeGuard

from scry_core import png
from scry_core.reply_contract import Invalid

Rect = tuple[int, int, int, int]

#: A JSON integer or a `0x` string, so the schema offers both and `number` decides.
NumberArg = int | str
HEX = re.compile(r"0[xX][0-9a-fA-F]+")


def number(name: str, value: object, bits: int, holder: str) -> int:
    """`value` as an integer or `0x` hex string, or the refusal naming `name`: empty or decimal
    text (bare digits read either way), a bool, a float, a sign before `0x`, or more than `bits`
    bits (`holder`'s width). A negative integer passes: the tool judges its own range."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise Invalid("bad_argument",
                      f"{name} is an integer or a `0x` hex string; got {value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise Invalid("bad_argument", f"{name} is empty: an integer or a `0x` hex string")
        if text[:2].lower() == "0x" and not HEX.fullmatch(text):
            raise Invalid("bad_argument", f"{name}={value!r} starts like hex and is not: `0x` "
                                          "is followed by hex digits")
        if not HEX.fullmatch(text):
            raise Invalid("bad_argument", f"{name}={value!r} is not an integer or a `0x` hex "
                                          "string: decimal text is refused, since bare digits "
                                          "read either way")
        value = int(text, 16)
    if value.bit_length() > bits:
        raise Invalid("bad_argument", f"{name} is wider than {bits} bits, the widest "
                                      f"number {holder} holds")
    return value


def hex_at_width(value: int, bits: int) -> str:
    """`value` as `0x` digits at `bits` width, rounded up to a whole digit."""
    return f"{value:#0{2 + (bits + 3) // 4}x}"


#: Hits a call lists (a scan's survivors): the most shown, and the default when none is named.
HITS_MAX, HITS_DEFAULT = 400, 40
#: A value scan's cells and its comparisons, compared unsigned; `!` is "not equal".
SCAN_CELL_BYTES = (1, 2, 4)
SCAN_OPERATORS = ("=", "!", ">", ">=", "<", "<=")


def whole(value: object, lo: int = 0, hi: int | None = None) -> TypeGuard[int]:
    """`value` is an int in `lo..hi`; a bool is not."""
    return (isinstance(value, int) and not isinstance(value, bool) and value >= lo
            and (hi is None or value <= hi))


def rect(name: str, value: object) -> Rect:
    """`value` as `[x, y, width, height]`, x and y at least 0, width and height at least 1."""
    if not (isinstance(value, list | tuple) and len(value) == 4
            and all(whole(v) for v in value[:2]) and all(whole(v, 1) for v in value[2:])):
        raise Invalid("bad_argument", f"{name}={value!r} is [x, y, width, height]: x and y at or "
                      "above zero, a width and a height above it")
    x, y, w, h = value
    return x, y, w, h


def shift(value: object) -> tuple[int, int]:
    """`value` as `[dx, dy]`, two integers of any sign."""
    if not (isinstance(value, list | tuple) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
        raise Invalid("bad_argument", f"shift={value!r} is [dx, dy], two whole numbers")
    return value[0], value[1]


def absolute(name: str, value: object, **fields: Any) -> Path:
    """The one judge of a path argument on both servers: an absolute path, or one led by `~`
    (expanded here, since no shell stands between client and argument), or the refusal; `fields`
    ride on it. A relative path would be judged in one directory and used in another."""
    if not isinstance(value, str):
        raise Invalid("bad_argument", f"{name}={value!r} is not a path", **fields)
    if not value:
        raise Invalid("bad_argument", f"{name} is empty: give an absolute path, or one starting "
                      "with `~`", **fields)
    if "\x00" in value:
        raise Invalid("bad_argument", f"{name}={value!r} holds a NUL, which no file name holds",
                      **fields)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as e:
        raise Invalid("bad_argument", f"{name}={value!r} holds a lone surrogate "
                      f"{value[e.start]!r}, which no file name holds", **fields) from None
    path = Path(value)
    if value.startswith("~"):
        try:
            path = path.expanduser()
        except RuntimeError:
            path = Path(value)
        if str(path).startswith("~"):
            raise Invalid("bad_argument", f"{name}={value!r} names a home directory this host "
                          "cannot find: write it out in full", **fields)
    if not path.is_absolute():
        raise Invalid("bad_argument", f"{name}={value!r} must be an absolute path or start with "
                      "`~`: a relative one would be judged in one directory and used in another",
                      **fields)
    return path


def writable_file(name: str, value: object, **fields: Any) -> Path:
    """A file a tool is about to write, which may exist: `absolute`, in an existing directory.
    An unreadable path is refused, never raised: before Python 3.14 `is_dir` raises on EACCES."""
    path = absolute(name, value, **fields)
    try:
        there = path.parent.is_dir()
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be looked at: {e}",
                      **fields) from None
    if not there:
        raise Invalid("bad_argument", f"{name}: {path.parent} is not a directory, so "
                      f"{path.name} has nowhere to go", **fields)
    return path


def fresh_file(name: str, value: object, **fields: Any) -> Path:
    """A file a tool is about to create: `writable_file`, with nothing there, a dangling link
    included (a writer would follow it)."""
    path = writable_file(name, value, **fields)
    try:
        taken = path.exists() or path.is_symlink()
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be looked at: {e}",
                      **fields) from None
    if taken:
        raise Invalid("bad_argument", f"{name}: {path} already exists. This will not overwrite "
                      "it: name a path that is not there yet", **fields)
    return path


def expanded(value: str) -> str:
    """`value` with a leading `~` expanded as `absolute` does; anything else as given."""
    if not value.startswith("~"):
        return value
    try:
        return str(Path(value).expanduser())
    except RuntimeError:
        return value


def window(name: str, value: object) -> tuple[float, float] | None:
    """A span `[from_s, to_s]` of finite seconds at least 0, in order; None if absent."""
    if value is None:
        return None
    if not (isinstance(value, list | tuple) and len(value) == 2 and all(
            isinstance(t, int | float) and not isinstance(t, bool) and math.isfinite(t)
            and t >= 0 for t in value) and value[0] < value[1]):
        raise Invalid("bad_argument", f"{name}={value!r} is [from_s, to_s], finite seconds at or "
                      "above zero, the first before the second")
    return float(value[0]), float(value[1])


def existing_file(name: str, value: object, thing: str = "file", **fields: Any) -> Path:
    """`absolute`, and a regular file is there (`exists()` would take a directory); a path the
    filesystem will not look at is refused, never raised. `fields` ride on the refusal."""
    path = absolute(name, value, **fields)
    try:
        there = path.is_file()
    except (OSError, ValueError) as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be looked at: {e}",
                      **fields) from None
    if not there:
        raise Invalid("bad_argument", f"{name}: no {thing} at {path}", **fields)
    return path


def read_text(name: str, value: object, thing: str, **fields: Any) -> str:
    """A caller's text file, whole, as UTF-8; `utf-8-sig` drops a byte-order mark an editor
    put first, which would otherwise garble the first name."""
    path = existing_file(name, value, thing, **fields)
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as e:
        raise Invalid("bad_argument",
            f"{name}: {path} is not UTF-8 text: byte {e.start} "
            f"({e.object[e.start:e.start + 1]!r}) {e.reason}", **fields) from None
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}", **fields) from None


def picture_file(name: str, path: Path, sha256: str | None = None) -> tuple[png.Raster, str]:
    """The PNG picture at `path` and the sha256 of the bytes decoded, from one read. A file not
    matching `sha256` is refused."""
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


def file_facts(path: Path) -> dict[str, Any]:
    """`path`, `bytes` and `sha256` of a file a tool wrote, from one read."""
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
