"""The argument judges the media layer shares: whole numbers, rectangles, shifts, paths and the
picture a path names. Each refuses `bad_argument` in a sentence naming the argument, so a server
tool and a file tool reject one mistake in one voice.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, TypeGuard

from scry_core import png
from scry_core.reply_contract import Invalid

Rect = tuple[int, int, int, int]

#: The annotation of a number a caller may also spell in hex: a JSON integer or a `0x` string,
#: so the schema a client reads offers both and `number` decides.
NumberArg = int | str
#: A hex spelling of a number: `0x` and its digits, whatever their case.
HEX = re.compile(r"0[xX][0-9a-fA-F]+")


def number(name: str, value: object, bits: int, holder: str) -> int:
    """`value` as the integer it is or spells in hex (`0x`), or the refusal naming `name`:
    empty text, decimal text (bare digits read either way), a bool, a float, a sign written
    before `0x`, and anything wider than `bits`, the widest number `holder` holds. A negative
    integer is an integer: the tool's own range is judged after this, on the integer."""
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
    """`value` as a reply shows a value the machine holds, written the way `number` takes it
    back: `0x` and its digits at the holder's width, a width that is not a multiple of four
    rounded up to the next whole digit, since a value cannot be shown in a fraction of one."""
    return f"{value:#0{2 + (bits + 3) // 4}x}"


#: A list of hits a call answers (a value scan's survivors): the most it shows, and how many when
#: the caller names none; what a server shows past the most is its own to say.
HITS_MAX, HITS_DEFAULT = 400, 40


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


def absolute(name: str, value: object, **fields: Any) -> Path:
    """THE ONE JUDGE OF A PATH ARGUMENT, on both servers: a string naming an absolute path, or
    one led by `~`, expanded here as the shell would (`~` is what a person types, and no shell
    stands between a client and this argument), or the refusal naming `name`; `fields` ride on
    it. A relative path is refused because it would be judged in one directory and used in
    another (the server's, the emulator's); a NUL and a lone surrogate because no file name can
    hold either."""
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
    """A file a tool is about to write, which may be there: `absolute`, and its directory is
    one, or the refusal naming `name`. A path the filesystem will not look at is refused the
    same way, never raised: before Python 3.14 `exists` and `is_dir` raise on EACCES."""
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
    """A file a tool is about to create: `writable_file`, and nothing at it yet, a link that
    points nowhere included (it is something there, and a writer would follow it)."""
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
    """`value` with a leading `~` expanded as `absolute` expands it, for a server that hands the
    text on (to an emulator's command line, or a list it splits); anything else, a `~user` this
    host cannot find included, as given, for `absolute` to judge."""
    if not value.startswith("~"):
        return value
    try:
        return str(Path(value).expanduser())
    except RuntimeError:
        return value


def window(name: str, value: object) -> tuple[float, float] | None:
    """A span of seconds `[from_s, to_s]`: two finite numbers at or above zero, the first before
    the second; None for none given."""
    if value is None:
        return None
    if not (isinstance(value, list | tuple) and len(value) == 2 and all(
            isinstance(t, int | float) and not isinstance(t, bool) and math.isfinite(t)
            and t >= 0 for t in value) and value[0] < value[1]):
        raise Invalid("bad_argument", f"{name}={value!r} is [from_s, to_s], finite seconds at or "
                      "above zero, the first before the second")
    return float(value[0]), float(value[1])


def existing_file(name: str, value: object) -> Path:
    """`absolute`, and a file is there. A path the filesystem will not look at is refused the
    same way, never raised, as in `writable_file`."""
    path = absolute(name, value)
    try:
        there = path.is_file()
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be looked at: {e}") from None
    if not there:
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


def file_facts(path: Path) -> dict[str, Any]:
    """A file a tool wrote, as every reply names one: `path`, `bytes` and `sha256`, the size and
    the hash taken off ONE read of the file."""
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
