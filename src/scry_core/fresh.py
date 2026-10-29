"""New files for the media layer: never overwritten unasked, never left half written."""

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
    """`data` at a new `path`; an existing file is `bad_argument`, a failed write removes it.
    An unopenable path is `bad_argument` if the caller named it, else `host_failed`."""
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
    """`data` over `path`, whole or not at all: written beside it, then renamed over.
    A replaced file keeps its mode; a new one takes `new_mode` if given, else the umask's.
    Refusal codes as in `create`; a failed rename is always `host_failed`."""
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
    """`data` at the first free `folder / name(n)`, n from 1; the exclusive create takes the
    name."""
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
    """A new directory at the first free `folder / name(n)`, n from 1; the mkdir takes the name."""
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
    """A new directory: `dest` if the caller named one, else `numbered_dir`."""
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
    """Removes `where` on any exception, a cancel included, so no half-filled directory stays."""
    try:
        yield
    except BaseException:
        remove_dir(where)
        raise


def remove_dir(where: Path) -> None:
    """Remove `where` and its contents."""
    shutil.rmtree(where, ignore_errors=True)


def _fill(out: IO[bytes], path: Path, data: bytes, what: str) -> None:
    try:
        with out:
            out.write(data)
    except OSError as e:
        path.unlink(missing_ok=True)
        raise Invalid("host_failed", f"{what} {path} could not be written whole: {e}") from None
