"""Which emulator a session runs, where that choice came from, and what the build says it is.

ONE LADDER, CLIMBED ONCE PER LAUNCH: the caller's `binary`, else the server's variable, else the
executable the PATH finds. The first rung that holds anything is the one taken, and a wrong value
there is refused rather than passed over: a caller who named a build and silently got another
would be measuring the wrong emulator. The reply says which rung it was, so the choice is never
made in silence. Both servers climb it; each names its product, its executable and its variable.
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
#: The most of each of `-version`'s two streams read, and of the line kept: a version is one
#: line, and a build that starts instead can print without end.
VERSION_READ_MAX = 4096


@dataclass(frozen=True)
class Resolved:
    path: str
    origin: str


@dataclass(frozen=True)
class Ladder:
    """One server's ladder: `product` as a refusal names it, the `executable` the PATH rung
    looks for, and the `variable` of the middle rung."""
    product: str
    executable: str
    variable: str

    def resolve(self, binary: str) -> Resolved:
        """The absolute executable the ladder lands on. A relative value is `bad_argument`
        naming its argument or the variable. One naming no executable file is refused naming
        what all three rungs held and why the one taken is no executable: `bad_argument` when
        the caller's own `binary` was the rung, `host_failed` when the host's variable or PATH
        was, since that is the host's to fix."""
        held = os.environ.get(self.variable, "")
        on_path = shutil.which(self.executable)
        # The variable is held to the argument's rule: a relative path would resolve against
        # the server's working directory, which is nobody's project.
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
        # THE PATH `which` APPROVED, unchanged: `abspath` collapses `..` by spelling, so through
        # a symlinked directory it would name another file. A relative PATH entry is joined, not
        # normalised, for the same reason.
        return Resolved(found if os.path.isabs(found) else os.path.join(os.getcwd(), found),
                        origin)


def why_not(path: str) -> str:
    """Why a named path is no executable file, in the words its owner looks for: a file that is
    there without its exec bit is not missing."""
    if not os.path.exists(path):        # a dangling link included: nothing there to run
        return "no such file"
    if os.path.isdir(path):
        return "a directory"
    return "not executable"


def version(binary: str, env: Mapping[str, str] | None = None,
            seconds: float = VERSION_TIMEOUT_S) -> str | dict[str, Any]:
    """The first line `<binary> -version` prints, or why there is none. `env` is the environment
    the server launches the emulator with (None: the server's own): a build that does not know
    `-version` may start instead of answering, and must start as a real launch would. `seconds`
    is the bound, never longer than the launch's own.

    THE EXIT CODE IS NOT THE SIGNAL: a build may print its banner on stderr and exit non-zero
    for an informational option, so a version is the first non-blank line, stdout before
    stderr. What makes it unavailable is a spawn that failed, a timeout, or nothing printed.
    Such a build may also start the emulator, so the probe is its own process group, ended
    whole when the bound runs out (a wrapper that does not `exec` leaves the emulator as its
    child), its output goes to files read no further than `VERSION_READ_MAX`, and its stdin is
    closed, so it cannot read the server's own protocol stream."""
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
    return subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env,
                            start_new_session=True)


def _end_group(proc: subprocess.Popen[bytes], ran_out: bool) -> None:
    """End the probe's group, whatever is left of it, and reap the probe. On Windows the tree is
    followed by parent pid with no start time, so it is ended only while the probe still runs:
    a pid freed by its exit can be another program's."""
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
    """The three fields a launch answers about its binary, its version probed with `env` within
    `seconds`."""
    return {"binary": resolved.path, "binary_origin": resolved.origin,
            "version": version(resolved.path, env, seconds)}
