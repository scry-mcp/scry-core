from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from scry_core.reply_contract import Invalid

_KINDS = ((stat.S_ISDIR, "a directory"), (stat.S_ISFIFO, "a FIFO"), (stat.S_ISSOCK, "a socket"),
          (stat.S_ISCHR, "a character device"), (stat.S_ISBLK, "a block device"))


STATE_NAME_MAX = 64
#: A state's name becomes a file name, and on MAME one console parameter: no leading `-`, which
#: a command line reads as an option.
STATE_NAME = re.compile(rf"[A-Za-z0-9_][A-Za-z0-9_-]{{0,{STATE_NAME_MAX - 1}}}")


def check_state_name(name: object, becomes: str) -> str:
    """`name` when it is a state name, else the refusal; `becomes` says what it turns into."""
    if not isinstance(name, str) or not STATE_NAME.fullmatch(name):
        raise Invalid("bad_argument",
            f"a state name is letters, digits, `_` and `-`, never starting with `-`, "
            f"at most {STATE_NAME_MAX} of them; got {name!r}. It becomes {becomes}")
    return name


#: Windows' `readlink` puts this on an absolute target.
_LONG_PATH = "\\\\?\\"


def _target(path: Path) -> str:
    return os.readlink(path).removeprefix(_LONG_PATH)


def not_a_state(path: Path) -> str | None:
    """Why the state file at `path` holds no state, else None (a regular file, or nothing there)."""
    # `Path`'s own checks raise PermissionError on some interpreters for an unsearchable target
    linked = os.path.islink(path)
    try:
        if not os.path.exists(path):
            return (f"the file is a link to {_target(path)}, and no file is reached through "
                    "it" if linked else None)
        mode = os.stat(path).st_mode
        target = _target(path) if linked else ""
    except FileNotFoundError:
        return None      # gone since it was looked for: nothing is there
    if stat.S_ISREG(mode):
        return None
    kind = next((name for test, name in _KINDS if test(mode)), "not a regular file")
    there = f"a link to {target}, which is {kind}" if linked else kind
    return f"the file is {there}, not a state"


def refused_load(name: str, path: Path, why: str) -> Invalid:
    """The refusal for a name `not_a_state` judged, shared by both servers."""
    return Invalid("unknown_ref",
                   f"no state named {name!r} to load: at {path} {why}, and "
                   "`state_write(method=\"save\")` refuses the name while it is there")
