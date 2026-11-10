"""The name of a file a server writes: lowercase words joined by hyphens, one extension."""

from __future__ import annotations

import re
from pathlib import Path

from scry_core.reply_contract import Invalid

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+")
_OTHER = re.compile(r"[^a-z0-9]+")
_EXTENSION = re.compile(r"[a-z0-9]+")


def word(value: str, what: str) -> str:
    """An outside value as words of a name, or refused as the argument `what`."""
    words = _OTHER.sub("-", value.lower()).strip("-")
    if not words:
        raise _nameless(value, what)
    return words


def name(*words: str | int, extension: str) -> str:
    """A name a server makes up; outside the rule it is the builder's defect, so no refusal."""
    made = f"{'-'.join(str(w) for w in words)}.{extension}"
    if not NAME.fullmatch(made):
        raise ValueError(f"{made!r} is outside the rule of a server's file names "
                         f"({NAME.pattern})")
    return made


def caller_file(path: Path, what: str) -> Path:
    """A path the caller named, normalised in its last component only."""
    stem, dot, extension = path.name.rpartition(".")
    extension = extension.lower()
    if not dot or not _EXTENSION.fullmatch(extension):
        raise Invalid("bad_argument", f"{what}: {path.name!r} has no extension of letters and "
                      "digits after its last dot, and a file is written under a name that has "
                      "one: name it, as in `dump.bin`")
    try:
        return path.with_name(f"{word(stem, what)}.{extension}")
    except Invalid:
        raise _nameless(path.name, what) from None


def _nameless(value: str, what: str) -> Invalid:
    return Invalid("bad_argument", f"{what}: {value!r} holds no letter or digit of a file name "
                   "(a-z, 0-9), so it names no file")


def outside(folder: Path) -> list[Path]:
    """The files under `folder` named outside the rule, for a battery to hold what it wrote to.
    Directories are not judged; a walk that met no file judged nothing and raises."""
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"{folder} holds no file, so no name was judged")
    return [path for path in files if not NAME.fullmatch(path.name)]
