"""Files the media layer creates: each one made new, never written over, and never left half
written. One rule for every writer, because a half file read back later is a wrong answer that
looks like a file, and a file written over is somebody else's evidence gone.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO

from scry_core.reply_contract import Code, Invalid


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


def replace(path: Path, data: bytes, what: str, named_by_caller: bool = True,
            new_mode: int | None = None) -> None:
    """`data` at `path`, over what is there, whole or not at all: written beside it, then renamed
    over it, so a reader never meets half a file and a write that fails, a cancel included,
    leaves the old one whole and nothing beside it. A file replaced keeps its mode; a new one
    takes `new_mode` when given, whatever the umask, else the umask's. A path that cannot take
    the new file is `bad_argument` when the caller named it, `host_failed` when the server chose
    it, as in `create`; a rename that fails once the file is written whole is the host's
    (`host_failed`: a full disk, a volume gone read-only)."""
    code: Code = "bad_argument" if named_by_caller else "host_failed"
    beside = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        try:
            if path.is_dir():
                raise Invalid(code, f"{what} {path} is a directory")
            create(beside, data, what, named_by_caller)
            try:
                os.chmod(beside, stat.S_IMODE(path.stat().st_mode))
            except FileNotFoundError:
                if new_mode is not None:
                    os.chmod(beside, new_mode)
        except OSError as e:
            raise Invalid(code, f"{what} {path} cannot be written: {e}") from None
        try:
            os.replace(beside, path)
        except OSError as e:
            raise Invalid("host_failed", f"{what} {path} could not be written: {e}") from None
    finally:
        beside.unlink(missing_ok=True)


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


def directory(dest: Path | None, folder: Path, name: Callable[[int], str],
              what: str) -> Path:
    """A directory made new for a piece of work: `dest` (a path the caller named and the
    server judged), or the first free `folder / name(n)` (`numbered_dir`)."""
    if dest is None:
        return numbered_dir(folder, name, what)
    try:
        dest.mkdir()
    except FileExistsError:
        raise Invalid("bad_argument", f"dest: {dest} is already there. This will not write into "
                      "it: name a directory that is not there yet") from None
    except OSError as e:
        raise Invalid("bad_argument", f"dest: {dest} cannot be created: {e}") from None
    return dest


@contextlib.contextmanager
def taken_back(where: Path) -> Iterator[None]:
    """The work that fills `where`, a directory `directory` just made: any exception, a refusal
    or a cancel alike, takes the whole directory away again, so no half piece of work is left
    where a caller or the next call would find it."""
    try:
        yield
    except BaseException:
        remove_dir(where)
        raise


def remove_dir(where: Path) -> None:
    """`where` and everything in it, gone: a directory made for work that produced nothing."""
    shutil.rmtree(where, ignore_errors=True)


def _fill(out: IO[bytes], path: Path, data: bytes, what: str) -> None:
    try:
        with out:
            out.write(data)
    except OSError as e:
        path.unlink(missing_ok=True)
        raise Invalid("host_failed", f"{what} {path} could not be written whole: {e}") from None
