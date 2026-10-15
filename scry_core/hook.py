"""`hook` -- the pre-commit of a repository that pins this package, held once here.

Run as `python -m scry_core.hook` from inside the repository, under its own `uv run`, so the
pinned package is the one that runs: each repository's `.githooks/pre-commit.sh` is that one
line, so the decision lives here and only the invocation is copied. It needs `jscpd` on the path,
a tracked `.jscpd-baseline.json`, and the probe laid out as `probe_checks` reads it.

IT RUNS TWO CHECKS, the ones whose answer is about the tree as a whole and that nobody would
otherwise run: new duplication, and a probe task set that no longer fits the MCP servers. The
linters and the suite are the battery, run directly. Skipping is git's own `--no-verify`.

THE DUPLICATION is jscpd's, against the tracked `.jscpd-baseline.json`, read through its JSON
reporter: the console table is aligned columns a reader scans, and a number picked out of it by
position cannot say which metric it landed on. A run that analysed no file is INVALID, since jscpd
exits 0 having lexed nothing when pointed at a language it cannot read.

THE PROBE is `python -m scry_core.probe all --check` on the repository's servers file and tasks,
the check alone, which asks no model: free, offline, the same answer every time. A 1 is a refusal
only when the check prints one (`REFUSED ...`), since a probe that died on import exits 1 too; a 0
is a pass only when it covered a server (`OK ...`).

THE SEAMS: `PRECOMMIT_JSCPD` and `PRECOMMIT_PROBE` name programs to run in place of `jscpd` and of
the probe's check, which is how this module's own suite hands each one that fails on demand.

EXIT: 0 clean; 1 new duplication or a probe refusal; 2 usage; 3 INVALID (it examined nothing, or
could not finish). INVALID is never folded into green.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scry_core.probe import CHECK_OK, CHECK_REFUSED
from scry_core.probe_checks import SERVERS_FILE, TASKS_DIR

EXIT_CLEAN, EXIT_BLOCKED, EXIT_INVALID = 0, 1, 3
BASELINE = ".jscpd-baseline.json"
PROBE_CHECK = ["-m", "scry_core.probe", "all", "--check", "--servers", str(SERVERS_FILE),
               "--tasks", str(TASKS_DIR)]


class Invalid(Exception):
    """The hook could not reach a verdict: nothing here is a pass or a block."""


class Blocked(Exception):
    """A verdict against the commit, with what to do about it."""


def _run(argv: list[str], what: str) -> tuple[int, str]:
    """`argv`'s exit code and its stdout and stderr together, or `Invalid` naming `what` when it
    cannot be started."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", check=False)
    except OSError as e:
        raise Invalid(f"{what} could not be run ({argv[0]}): {e}") from None
    return done.returncode, done.stdout + done.stderr


def duplication(scratch: Path) -> str:
    """The duplication check's line for a clean tree; `Blocked` on new clones, `Invalid` when it
    examined nothing or wrote no report."""
    if not Path(BASELINE).is_file():
        raise Invalid(f"{BASELINE} is missing, so there is nothing to judge NEW duplication "
                      "against. It is tracked; restore it, or create one with:\n"
                      f"    jscpd . --baseline {BASELINE} --update-baseline")
    jscpd = os.environ.get("PRECOMMIT_JSCPD") or "jscpd"
    rc, said = _run([jscpd, ".", "--baseline", BASELINE, "--fail-on-new-clones",
                     "--reporters", "json", "--output", str(scratch)], "jscpd")
    report = scratch / "jscpd-report.json"
    if not report.is_file():
        raise Invalid(f"jscpd wrote no report (rc={rc}):\n{said}")
    try:
        total = json.loads(report.read_text(encoding="utf-8"))["statistics"]["total"]
        sources, new = int(total.get("sources", 0)), int(total.get("newClones", 0))
        lines = total.get("duplicatedLines", "?")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Invalid(f"the jscpd report could not be read: {type(e).__name__}: {e}") from None
    if sources == 0:
        raise Invalid("jscpd analysed 0 files, so this is not a verdict")
    if rc != 0 and new == 0:
        raise Invalid(f"jscpd exited {rc} and its report counts no new clone:\n{said}")
    if new > 0:
        # jscpd keys a clone by its content, so one that shrank under an edit reads as new.
        raise Blocked(
            f"{said}\n{new} new clone(s) over a baseline of accepted duplication, in {sources} "
            f"files, {lines} duplicated lines (rc={rc}).\n"
            "A clone that shrank or split under your edit is counted as new even when the "
            "duplication went DOWN. Compare the duplicated lines with HEAD's first:\n"
            "    d=$(mktemp -d); git archive HEAD | tar -x -C \"$d\"\n"
            "    (cd \"$d\" && jscpd . --reporters json --output r)  # statistics.total"
            ".duplicatedLines\n"
            "Consolidate it, or accept it deliberately with:\n"
            f"    jscpd . --baseline {BASELINE} --update-baseline\n"
            "and say in the commit message WHY that site stays duplicated.")
    return f"   {sources} files, no new duplication"


def probe_fit() -> str:
    """The probe check's own lines for a covered task set; `Blocked` on a refusal it names,
    `Invalid` on anything else."""
    seam = os.environ.get("PRECOMMIT_PROBE")
    rc, said = _run([seam] if seam else [sys.executable, *PROBE_CHECK], "the probe check")
    lines = said.splitlines()
    if rc == 0:
        if not any(line.startswith(CHECK_OK) for line in lines):
            raise Invalid(f"the probe check examined no server, so this is not a verdict:\n{said}")
        return "\n".join(f"   {line}" for line in lines)
    if rc == 1:
        if not any(line.startswith(CHECK_REFUSED) for line in lines):
            raise Invalid(f"the probe check exited 1 naming no refusal:\n{said}")
        raise Blocked(
            f"{said}\na probe task is missing or wrong (above). Fix it in "
            f"{TASKS_DIR}/<server>.json and run the free check again, through the same `uv run` "
            "as this hook, from the repository root: python -m scry_core.probe <server> --check "
            f"--servers {SERVERS_FILE} --tasks {TASKS_DIR}\n"
            "The same command with `--runs 3` in place of `--check` drives the model and costs a "
            "run: it is only for a task added for a new or changed tool.")
    raise Invalid(f"the probe check exited {rc}:\n{said}")


def _root() -> Path:
    try:
        done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                              text=True, errors="replace", check=False)
    except OSError as e:
        raise Invalid(f"git could not be run: {e}") from None
    if done.returncode != 0:
        raise Invalid(f"git does not say where the repository root is (rc={done.returncode}): "
                      f"{done.stderr.strip()}")
    return Path(done.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m scry_core.hook", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            allow_abbrev=False).parse_args(argv)
    try:
        os.chdir(_root())
        with tempfile.TemporaryDirectory(prefix="scry-hook-") as scratch:
            print("== jscpd (new duplication against the baseline)")
            print(duplication(Path(scratch)))
        print("== mcp_probe (the probe's tasks still fit the MCP servers)")
        print(probe_fit())
    except Blocked as e:
        print(f"pre-commit: BLOCKED -- {e}", file=sys.stderr)
        return EXIT_BLOCKED
    except Invalid as e:
        print(f"pre-commit: INVALID -- {e}", file=sys.stderr)
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- anything else stopped it before a verdict
        print(f"pre-commit: INVALID -- the hook stopped before its verdict: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
