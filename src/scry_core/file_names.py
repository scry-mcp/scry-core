"""The name of a file a server writes: lowercase words joined by hyphens, one extension."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from scry_core.reply_contract import Invalid

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.[a-z0-9]+")
_OTHER = re.compile(r"[^a-z0-9]+")
_EXTENSION = re.compile(r"[a-z0-9]+")
#: The most `word` takes from an outside value; a caller's whole file name is the host's to bound.
WORD_MAX = 64


def word(value: str, what: str) -> str:
    """An outside value as words of a name, or refused as the argument `what`."""
    words = _words(value)
    if not words:
        raise _nameless(value, what)
    if len(words) > WORD_MAX:
        raise Invalid("bad_argument", f"{what}: {value[:WORD_MAX]!r}... makes a name of "
                      f"{len(words)} characters, and a file name takes at most {WORD_MAX} from "
                      "it: shorten it")
    return words


def stamp(when: dt.datetime) -> str:
    """The UTC instant `when` (aware) as one word, to the microsecond."""
    return when.astimezone(dt.UTC).strftime("%Y%m%dt%H%M%S%fz")


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
    words = _words(stem)
    if not words:
        raise _nameless(path.name, what)
    return path.with_name(f"{words}.{extension}")


def _words(value: str) -> str:
    return _OTHER.sub("-", value.lower()).strip("-")


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
