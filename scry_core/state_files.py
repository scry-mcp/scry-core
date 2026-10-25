from __future__ import annotations

import os
import stat
from pathlib import Path

from scry_core.reply_contract import Invalid

_KINDS = ((stat.S_ISDIR, "a directory"), (stat.S_ISFIFO, "a FIFO"), (stat.S_ISSOCK, "a socket"),
          (stat.S_ISCHR, "a character device"), (stat.S_ISBLK, "a block device"))


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
