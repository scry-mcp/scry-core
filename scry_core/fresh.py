"""Files the media layer creates: each one made new, never written over, and never left half
written. One rule for every writer, because a half file read back later is a wrong answer that
looks like a file, and a file written over is somebody else's evidence gone.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import IO

from scry_core.reply_contract import Invalid


def create(path: Path, data: bytes, what: str, named_by_caller: bool = False) -> None:
    """`data` at `path`, created here: a file already there is refused (`bad_argument`, it is
    the caller's), and a write that fails part-way takes the file away again. A path that
    cannot be opened is `bad_argument` when the caller named it (its `dest`), `host_failed`
    when the server chose it. `what` names the file in the refusal."""
    try:
        out = path.open("xb")
    except FileExistsError:
        raise Invalid("bad_argument", f"{what} {path} is already there. This will not overwrite "
                      "it: name a path that is not there yet") from None
    except (OSError, ValueError) as e:
        raise Invalid("bad_argument" if named_by_caller else "host_failed",
                      f"{what} {path} cannot be created: {e}") from None
    _fill(out, path, data, what)


def numbered(folder: Path, name: Callable[[int], str], data: bytes, what: str) -> Path:
    """`data` at the first `folder / name(n)`, n from 1, that nobody has taken, `folder`
    created if it is not there. Taking a name is the exclusive create itself, so two writers at
    once take two names rather than one refusing the other."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Invalid("host_failed", f"{what}: {folder} cannot be created: {e}") from None
    number = 1
    while True:
        path = folder / name(number)
        try:
            out = path.open("xb")
        except FileExistsError:
            number += 1
            continue
        except OSError as e:
            raise Invalid("host_failed", f"{what} {path} cannot be created: {e}") from None
        _fill(out, path, data, what)
        return path


def numbered_dir(folder: Path, name: Callable[[int], str], what: str) -> Path:
    """A new directory at the first `folder / name(n)`, n from 1, that nobody has taken,
    `folder` created if it is not there: the mkdir itself takes the name."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Invalid("host_failed", f"{what}: {folder} cannot be created: {e}") from None
    number = 1
    while True:
        path = folder / name(number)
        try:
            path.mkdir()
            return path
        except FileExistsError:
            number += 1
        except OSError as e:
            raise Invalid("host_failed", f"{what} {path} cannot be created: {e}") from None


def _fill(out: IO[bytes], path: Path, data: bytes, what: str) -> None:
    try:
        with out:
            out.write(data)
    except OSError as e:
        path.unlink(missing_ok=True)
        raise Invalid("host_failed", f"{what} {path} could not be written whole: {e}") from None
