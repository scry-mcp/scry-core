"""The binary ladder: the caller's `binary`, else the server's variable, else the PATH.

The first rung holding anything is taken, and a wrong value there is refused, never passed over.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import IO, Any

from scry_core import judges
from scry_core.reply_contract import Code, Invalid

ARGUMENT = "argument"
PATH_RUNG = "PATH"
VERSION_TIMEOUT_S = 5.0
#: Cap per `-version` stream: a build that starts instead can print without end.
VERSION_READ_MAX = 4096


@dataclass(frozen=True)
class Resolved:
    path: str
    origin: str


@dataclass(frozen=True)
class Ladder:
    """One server's ladder."""
    product: str
    executable: str
    variable: str

    def resolve(self, binary: str) -> Resolved:
        """The absolute executable the ladder lands on.

        Refusal is `bad_argument` when the caller's `binary` was the rung, else `host_failed`."""
        held = os.environ.get(self.variable, "")
        on_path = shutil.which(self.executable)
        # The variable gets the argument's rule: a relative path would resolve against the
        # server's working directory.
        if binary:
            try:
                given = judges.absolute("binary", binary)
            except Invalid as e:
                raise Invalid(e.code, f"{e}; or leave `binary` empty, and the ladder climbs to "
                              f"{self.variable}, then the PATH's `{self.executable}`",
                              **e.fields) from None
            origin, found = ARGUMENT, shutil.which(str(given))
        elif held:
            origin, found = self.variable, shutil.which(str(judges.absolute(self.variable,
                                                                             held)))
        else:
            origin, found = PATH_RUNG, on_path
        if found is None:
            named = f"{binary} ({why_not(binary)})" if origin == ARGUMENT else binary or "nothing"
            variable = (f"{held} ({why_not(held)})" if origin == self.variable
                        else held or "nothing")
            answerable: Code = "bad_argument" if origin == ARGUMENT else "host_failed"
            raise Invalid(answerable,
                f"no {self.product} binary resolves from the {origin} rung: the argument "
                f"`binary` held {named}, {self.variable} held {variable}, and the PATH holds "
                f"{on_path or f'no `{self.executable}`'}. The first rung holding a value is the "
                f"one taken, and it has to name an executable file")
        # `abspath` collapses `..` by spelling and through a symlinked directory would name
        # another file, so a relative PATH entry is joined, not normalised.
        return Resolved(found if os.path.isabs(found) else os.path.join(os.getcwd(), found),
                        origin)


def why_not(path: str) -> str:
    """Why a named path is no executable file."""
    if not os.path.exists(path):        # a dangling link included: nothing there to run
        return "no such file"
    if os.path.isdir(path):
        return "a directory"
    return "not executable"


def version(binary: str, env: Mapping[str, str] | None = None,
            seconds: float = VERSION_TIMEOUT_S) -> str | dict[str, Any]:
    """The first line `<binary> -version` prints, or why there is none.

    The exit code is no signal (a banner may go to stderr with rc!=0). The probe runs in its own
    process group, ended whole at the bound, with stdin closed so it cannot read the server's
    protocol stream."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = _spawn([binary, "-version"], out, err, env)
        except OSError as exc:
            return {"available": False, "why": f"`{binary} -version` could not run: {exc}"}
        try:
            rc = proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return {"available": False,
                    "why": f"`{binary} -version` did not return in {seconds:g} s"}
        finally:
            _end_group(proc, ran_out=proc.returncode is None)
        said = b"\n".join(_head(f) for f in (out, err)).decode("utf-8", "replace")
    for line in said.splitlines():
        if line.strip():
            return line.strip()[:VERSION_READ_MAX]
    return {"available": False, "why": f"`{binary} -version` printed nothing (rc={rc})"}


def _spawn(argv: list[str], out: IO[bytes], err: IO[bytes],
           env: Mapping[str, str] | None) -> subprocess.Popen[bytes]:
    """The probe in a process group of its own, so ending it ends whatever the build started."""
    if sys.platform == "win32":
        return subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:  # an `else`, so mypy skips this branch on win32 instead of calling it unreachable
        return subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True)


def _end_group(proc: subprocess.Popen[bytes], ran_out: bool) -> None:
    """End the probe's group and reap it. On Windows the tree is followed by parent pid, so it
    is ended only while the probe still runs: a freed pid can be another program's."""
    if sys.platform == "win32":
        if ran_out:
            with contextlib.suppress(subprocess.TimeoutExpired):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, check=False, timeout=VERSION_TIMEOUT_S)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=VERSION_TIMEOUT_S)


def _head(file: IO[bytes]) -> bytes:
    file.seek(0)
    return file.read(VERSION_READ_MAX)


def facts(resolved: Resolved, env: Mapping[str, str] | None = None,
          seconds: float = VERSION_TIMEOUT_S) -> dict[str, Any]:
    """The three fields a launch answers about its binary."""
    return {"binary": resolved.path, "binary_origin": resolved.origin,
            "version": version(resolved.path, env, seconds)}
