"""Which emulator a session runs, where that choice came from, and what the build says it is.

ONE LADDER, CLIMBED ONCE PER LAUNCH: the caller's `binary`, else the server's variable, else the
executable the PATH finds. The first rung that holds anything is the one taken, and a wrong value
there is refused rather than passed over: a caller who named a build and silently got another
would be measuring the wrong emulator. The reply says which rung it was, so the choice is never
made in silence. Both servers climb it; each names its product, its executable and its variable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scry_core import judges
from scry_core.reply_contract import Code, Invalid

ARGUMENT = "argument"
PATH_RUNG = "PATH"
VERSION_TIMEOUT_S = 5.0


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
            origin, found = ARGUMENT, shutil.which(str(judges.absolute("binary", binary)))
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


def version(binary: str, env: Mapping[str, str] | None = None) -> str | dict[str, Any]:
    """The first line `<binary> -version` prints, or why there is none. `env` is the environment
    the server launches the emulator with (None: the server's own): a build that does not know
    `-version` may start instead of answering, and must start as a real launch would.

    THE EXIT CODE IS NOT THE SIGNAL: a build may print its banner on stderr and exit non-zero
    for an informational option, so a version is the first non-blank line, stdout before
    stderr. What makes it unavailable is a spawn that failed, a timeout, or nothing printed. The
    bound is there because an option a build does not know may start the emulator instead. Its
    stdin is closed, so such a build cannot read the server's own protocol stream."""
    try:
        got = subprocess.run([binary, "-version"], capture_output=True, text=True,
                             errors="replace", check=False, timeout=VERSION_TIMEOUT_S,
                             stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return {"available": False,
                "why": f"`{binary} -version` did not return in {VERSION_TIMEOUT_S:g} s"}
    except OSError as exc:
        return {"available": False, "why": f"`{binary} -version` could not run: {exc}"}
    for line in (got.stdout + "\n" + got.stderr).splitlines():
        if line.strip():
            return line.strip()
    return {"available": False,
            "why": f"`{binary} -version` printed nothing (rc={got.returncode})"}


def facts(resolved: Resolved, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The three fields a launch answers about its binary, its version probed with `env`."""
    return {"binary": resolved.path, "binary_origin": resolved.origin,
            "version": version(resolved.path, env)}
