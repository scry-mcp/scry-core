"""Where an emulator's window goes: one helper answers, both servers ask it the same way.

The helper is the host's, named by `WINDOW_APP` and never guessed: a path this package invented
(beside it, under the home) would read differently in every clone and point at somebody's private
configuration. Asked `<helper> <app> [--shared] [--display main|secondary]`, it prints the
emulator's placement flags one argv token per line; a WATCHED (shared) run goes to the display
named, else to the one the session exported in `WINDOW_SHARED_DISPLAY`, else to the secondary. A
host with one display may answer no flags at all, which is an answer and not a failure.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scry_core.reply_contract import Invalid

#: The variable that names the helper.
HELPER_VAR = "WINDOW_APP"
#: The two display NAMES the helper knows, spelled as it spells them, and the variable a session
#: exports with its answer to "main or secondary?", read when `display` is empty so the reply can
#: SAY which display a shared start went to.
DISPLAYS = ("main", "secondary")
SHARED_DISPLAY_VAR = "WINDOW_SHARED_DISPLAY"
#: What a `start`'s `display` takes: a display, or "" for not given; and its schema description.
DISPLAY_OPTIONS = ("", *DISPLAYS)
DISPLAY_ARGUMENT = ("Where a watched (`shared`) window opens: `main` or `secondary`; empty, the "
                    "display `WINDOW_SHARED_DISPLAY` names, else the secondary. The host's "
                    "placement helper (`WINDOW_APP`) places it; a run nobody watches takes none.")
#: How long the helper is given: it reads the display topology and prints flags, and one that
#: hangs would hold `start`, and the server's one lock, for ever.
HELPER_TIMEOUT_S = 15.0


def check_display(shared: bool, display: str) -> None:
    """A `display` belongs to a watched run: on any other nobody is looking at a display, so the
    helper would ignore it, out loud on a stderr no caller sees, and it is refused here."""
    if display and not shared:
        raise Invalid("bad_argument",
            f"display={display!r} on a run nobody watches: such a run never obeys the display. "
            "Pass `shared=True` if somebody is going to watch, or drop it.")


def shared_display(shared: bool, display: str) -> str:
    """Which display a shared start goes to, as its reply reports it: the argument, else the
    session's exported answer, else the helper's default (the secondary); "" for a run nobody
    watches. An unusable value in the environment is refused naming the variable, never passed
    on for the helper to reject on a stderr nobody sees."""
    if not shared:
        return ""
    if display:
        return display
    exported = os.environ.get(SHARED_DISPLAY_VAR, "")
    if exported and exported not in DISPLAYS:
        raise Invalid("bad_argument",
            f"{SHARED_DISPLAY_VAR}={exported!r} in this server's environment is not one of "
            f"{list(DISPLAYS)}; pass `display` explicitly or fix the variable")
    return exported or "secondary"


@dataclass(frozen=True)
class Placed:
    """The helper's answer: its flags (an empty list is an answer on a one-display host), or
    None with `why` it gave no answer."""
    flags: list[str] | None
    why: str = ""


def ask(app: str, shared: bool, display: str = "") -> Placed:
    """The placement flags the helper prints for `app`, or why there are none: unset, not an
    executable file, failed to run, timed out, or answered non-zero (in its own words).

    `is_file()` AND `os.access`, never `exists()`: what arrives can be a link a checkout did not
    materialise, or a short text file with no exec bit, and running either raises an OSError that
    `check=False` does not catch. `os.access(X_OK)` answers True for any file on Windows, so the
    `except` is the half that carries the case there."""
    named = os.environ.get(HELPER_VAR, "").strip()
    helper = Path(named)
    if not named:
        return Placed(None, f"{HELPER_VAR} is not set, so no helper says where the window "
                            f"goes; set it to the placement helper")
    if not (helper.is_file() and os.access(helper, os.X_OK)):
        return Placed(None, f"the placement helper {HELPER_VAR} names is not an executable "
                            f"file at {helper}")
    cmd = [str(helper), app] + (["--shared"] if shared else [])
    if display:
        cmd += ["--display", display]
    try:
        # STDIN CLOSED: the helper inherits the server's own protocol stream otherwise. Its
        # output is decoded leniently, so a stray byte is a word in its answer, never a crash.
        output = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                check=False, timeout=HELPER_TIMEOUT_S,
                                stdin=subprocess.DEVNULL)
    except OSError as e:
        return Placed(None, f"the helper at {helper} could not be run: {e}")
    except subprocess.TimeoutExpired:
        return Placed(None, f"the helper at {helper} did not answer within "
                            f"{HELPER_TIMEOUT_S:g} s")
    if output.returncode != 0:
        # THE HELPER'S OWN WORDS: without its stderr a bad display or a topology failure reads
        # as a missing program.
        said = output.stderr.strip() or output.stdout.strip() or "nothing"
        return Placed(None, f"the helper at {helper} answered exit code {output.returncode} and "
                            f"printed {said!r}")
    return Placed([line for line in output.stdout.splitlines() if line.strip()])
