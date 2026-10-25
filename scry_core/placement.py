"""Asks the host's placement helper (`WINDOW_APP`) where an emulator window goes."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scry_core.reply_contract import Invalid

HELPER_VAR = "WINDOW_APP"
DISPLAYS = ("main", "secondary")
SHARED_DISPLAY_VAR = "WINDOW_SHARED_DISPLAY"
DISPLAY_OPTIONS = ("", *DISPLAYS)
DISPLAY_ARGUMENT = ("Where a watched (`shared`) window opens: `main` or `secondary`; empty, the "
                    "display `WINDOW_SHARED_DISPLAY` names, else the secondary.")
# A hung helper would hold the server's one lock for ever.
HELPER_TIMEOUT_S = 15.0


def check_display(shared: bool, display: str) -> None:
    """Refuse a `display` on an unwatched run; the helper would only complain on a hidden stderr."""
    if display and not shared:
        raise Invalid("bad_argument",
            f"display={display!r} on a run nobody watches: such a run never obeys the display. "
            "Pass `shared=True` if somebody is going to watch, or drop it.")


def shared_display(shared: bool, display: str) -> str:
    """The display a shared start goes to: argument, else the variable, else secondary; "" if
    unshared."""
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
    """The helper's flags (empty on a one-display host), or None with `why` it gave none."""
    flags: list[str] | None
    why: str = ""


def ask(app: str, shared: bool, display: str = "") -> Placed:
    """The placement flags the helper prints for `app`, or why there are none.

    `is_file()` and `os.access`, not `exists()`: a dangling link or non-exec file raises an
    OSError that `check=False` misses. `X_OK` is always True on Windows; the `except` covers it."""
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
        # stdin closed: else the helper inherits the server's protocol stream.
        output = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                                check=False, timeout=HELPER_TIMEOUT_S,
                                stdin=subprocess.DEVNULL)
    except OSError as e:
        return Placed(None, f"the helper at {helper} could not be run: {e}")
    except subprocess.TimeoutExpired:
        return Placed(None, f"the helper at {helper} did not answer within "
                            f"{HELPER_TIMEOUT_S:g} s")
    if output.returncode != 0:
        # Its own words: without stderr a bad display reads as a missing program.
        said = output.stderr.strip() or output.stdout.strip() or "nothing"
        return Placed(None, f"the helper at {helper} answered exit code {output.returncode} and "
                            f"printed {said!r}")
    return Placed([line for line in output.stdout.splitlines() if line.strip()])
