"""A path as a tracked store file may hold it: under the store's placeholders or refused."""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import project_store
from scry_core.reply_contract import Invalid

#: The arguments of a `perform` step that name a file; any other string may be text to type.
STEP_PATHS = frozenset({"path", "dest"})


def same_on_host(first: str, second: str) -> bool:
    """Whether this host's filesystem says the two spellings are one directory."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


@dataclass(frozen=True)
class Places:
    """What a path may be written against, and who says two spellings are one directory."""

    base: Path
    state: str
    environ: Mapping[str, str]
    same_directory: Callable[[str, str], bool] = same_on_host


def steps(value: Any, places: Places, where: str, key: str = "") -> Any:
    """`value` with every absolute path one of the store's placeholders covers written as it,
    which is what a step's argument can be rewritten without guessing what it means."""
    if isinstance(value, str):
        if value.lstrip().startswith("~") and key not in STEP_PATHS:
            return value
        return _one(value, places, where, step=True)
    if isinstance(value, list):
        return [steps(item, places, where, key) for item in value]
    if isinstance(value, dict):
        return {name: steps(item, places, where, name) for name, item in value.items()}
    return value


def placeholders(value: Any, places: Places, where: str, separator: str) -> Any:
    if isinstance(value, str):
        parts = value.split(separator) if separator else [value]
        return separator.join(_one(part, places, where, step=False) for part in parts)
    if isinstance(value, list):
        return [placeholders(item, places, where, separator) for item in value]
    if isinstance(value, dict):
        return {key: placeholders(item, places, where, separator) for key, item in value.items()}
    raise Invalid("bad_argument", f"{where} is a {type(value).__name__}, not a path or a table "
                  "of them")


def _one(part: str, places: Places, where: str, *, step: bool) -> str:
    """`part` as a placeholder path: a declared key's value must resolve under the root, the
    home, the state or a variable, and a step's absolute path is rewritten when one covers it."""
    normal = _slashed(part.strip())
    if not normal:
        return part
    if normal.startswith("~"):
        if normal == "~":
            return "${home}"
        if normal.startswith("~/"):
            inside = _norm(normal[2:])
            if inside == ".." or inside.startswith("../"):
                raise Invalid("bad_argument", f"{where} names {part!r}, which climbs out of the "
                              "home: a tracked file carries no path of this machine")
            return "${home}/" + inside
        if "/" in normal:
            raise Invalid("bad_argument", f"{where} names {part!r}, a `~user` path this store "
                          "cannot express: write `${home}` or a path inside the repository")
        return part             # a file whose name begins with a tilde, which is relative
    if project_store.absolute(normal):
        target = _norm(normal)
    elif step:
        return part             # a step's argument that is no path to begin with
    else:
        target = _norm(_slashed(str(places.base)).rstrip("/") + "/" + normal)
    for placeholder, value in _options(places):
        if _under(target, value, places.same_directory):
            return placeholder + target[len(value):]
    environ = places.environ
    for var in sorted(environ, key=lambda name: (-len(environ[name]), name)):
        if not _names_a_root(environ[var]) and _under(target, environ[var],
                                                      places.same_directory):
            return f"${{env:{var}}}" + target[len(_norm(_slashed(environ[var]))):]
    if step:
        return part
    raise Invalid("bad_argument", f"{where} names {part!r}, which is not under the repository "
                  f"({places.base}), the home, the session's state or a variable of the server's "
                  "environment: a tracked file carries no path of this machine")


def _options(places: Places) -> list[tuple[str, str]]:
    options = [("${root}", _norm(_slashed(str(places.base)))),
               ("${home}", _norm(_slashed(str(Path.home()))))]
    if places.state:
        options.append(("${state}", _norm(_slashed(places.state))))
    return sorted(options, key=lambda option: -len(option[1]))


def _under(target: str, value: str, same_directory: Callable[[str, str], bool]) -> bool:
    base = _norm(_slashed(value))
    if target == base or target.startswith(base.rstrip("/") + "/"):
        return True
    head = target[:len(base)]
    return (head.lower() == base.lower() and target[len(base):len(base) + 1] in ("", "/")
            and _alike(head, base, same_directory))


def _alike(first: str, second: str, same_directory: Callable[[str, str], bool]) -> bool:
    """Whether two spellings that differ only in case name one directory: a drive path is read
    as Windows reads it, any other is asked of `same_directory`."""
    return re.match(r"^[A-Za-z]:/", first) is not None or same_directory(first, second)


def _names_a_root(value: str) -> bool:
    """Whether `value` is a filesystem root, which would cover every path of the machine."""
    return re.fullmatch(r"(?:[A-Za-z]:)?", value.replace("\\", "/").rstrip("/")) is not None


def _norm(text: str) -> str:
    return posixpath.normpath(text)


def _slashed(text: str) -> str:
    """`text` with this host's separator as `/`; on a POSIX host a backslash is a name's own."""
    return text.replace(os.sep, "/") if os.sep != "/" else text
