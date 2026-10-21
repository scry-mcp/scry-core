"""What sits under a saved state's name and holds no state, judged by what the path resolves to
before anything opens it: a link through which no file is reached, and anything that is not a
regular file (a directory, a link to one, a FIFO, whose open would block the call for good). The
name is taken all the same, and a save refuses it, so a listing shows it with each of the state's
readings unavailable, saying what is there, rather than failing the whole listing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from scry_core.reply_contract import Invalid

_KINDS = ((stat.S_ISDIR, "a directory"), (stat.S_ISFIFO, "a FIFO"), (stat.S_ISSOCK, "a socket"),
          (stat.S_ISCHR, "a character device"), (stat.S_ISBLK, "a block device"))


#: Windows' long-path prefix, which its `readlink` puts on an absolute target.
_LONG_PATH = "\\\\?\\"


def _target(path: Path) -> str:
    """Where the link at `path` points, as a path a reader types (`_LONG_PATH` dropped)."""
    return os.readlink(path).removeprefix(_LONG_PATH)


def not_a_state(path: Path) -> str | None:
    """Why the state file at `path` holds no state, else None (a regular file, or nothing there,
    a name that went away while it was looked at included)."""
    # `os.path` here, not `Path`'s: on some supported interpreters the latter raises
    # `PermissionError` for a target in a directory this process may not search, and no file is
    # reached through such a link either
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
    """`state_load`'s refusal of a name `not_a_state` judged, said the same on both servers."""
    return Invalid("unknown_ref",
                   f"no state named {name!r} to load: at {path} {why}, and `state_save` refuses "
                   "the name while it is there")
