"""`hook` -- the pre-commit of a repository that pins this package, held once here.

Run as `python -m scry_core.hook` from inside the repository, under its own `uv run`, so the
pinned package is the one that runs. It needs `jscpd` on the path and a tracked
`.jscpd-baseline.json`. Three checks, each about the tree as a whole; the linters and the suite
are the battery, run directly. Skipping is git's own `--no-verify`.

DUPLICATION: jscpd against the baseline, read through its JSON reporter, never its table. A run
that analysed no file is INVALID.

PROBE: `python -m scry_core.probe all --check`, which asks no model. A 1 is a refusal only when
it prints `REFUSED ...`, a 0 a pass only when it covered a server (`OK ...`).

PROSE: per tracked or untracked `*.py`, symlinks aside, the bytes of its comments and docstrings
over its bytes, against a quarter, or a sixth under `tests/`. A registered tool's docstring is
its description, held by the client's cap, so it is not counted. `[tool.scry-prose] exempt =
{ "<path>" = "<reason>" }` in `pyproject.toml` is for generated or vendored files only.

SEAMS: `PRECOMMIT_JSCPD` and `PRECOMMIT_PROBE` name programs to run in place of either.

EXIT: 0 clean; 1 new duplication, a probe refusal or a file over its ceiling; 2 usage, an
exemption with no reason or no file; 3 INVALID (it examined nothing, or could not finish).
"""

from __future__ import annotations

import argparse
import ast
import codecs
import io
import json
import os
import subprocess
import sys
import tempfile
import tokenize
import tomllib
from pathlib import Path

from scry_core.probe import CHECK_OK, CHECK_REFUSED
from scry_core.probe_checks import SERVERS_FILE, TASKS_DIR
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

BASELINE = ".jscpd-baseline.json"
PROBE_CHECK = ["-m", "scry_core.probe", "all", "--check", "--servers", str(SERVERS_FILE),
               "--tasks", str(TASKS_DIR)]


PROSE_CEILING = 0.25
PROSE_CEILING_TESTS = 1 / 6
EXIT_USAGE = 2


class Refused(Exception):
    """A verdict against the commit, with what to do about it."""


class Misconfigured(Exception):
    """The repository's configuration of a check is wrong, so the commit is not judged."""


def _run(argv: list[str], what: str, root: Path, seam: str) -> tuple[int, str]:
    """`argv`'s exit code and its stdout and stderr together, run at the repository's `root`, or
    `Invalid` naming `what`, and where the program was looked for, when it cannot be started:
    the value of the variable `seam` when it is set, else the program on PATH."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", check=False,
                              cwd=root)
    except OSError as e:
        found = (f"it is {seam}'s value" if os.environ.get(seam)
                 else f"it is looked for on PATH (or named by {seam})")
        raise Invalid(f"{what} could not be run ({argv[0]}): {e}; {found}") from None
    return done.returncode, done.stdout + done.stderr


def duplication(root: Path, scratch: Path) -> str:
    """The duplication check's line for a clean tree; `Refused` on new clones, `Invalid` when it
    examined nothing or wrote no report."""
    if not (root / BASELINE).is_file():
        raise Invalid(f"{BASELINE} is missing, so there is nothing to judge NEW duplication "
                      "against. It is tracked; restore it, or create one with:\n"
                      f"    jscpd . --baseline {BASELINE} --update-baseline")
    jscpd = os.environ.get("PRECOMMIT_JSCPD") or "jscpd"
    rc, said = _run([jscpd, ".", "--baseline", BASELINE, "--fail-on-new-clones",
                     "--reporters", "json", "--output", str(scratch)], "jscpd", root,
                    "PRECOMMIT_JSCPD")
    report = scratch / "jscpd-report.json"
    if not report.is_file():
        raise Invalid(f"jscpd wrote no report (rc={rc}):\n{said}")
    try:
        total = json.loads(report.read_text(encoding="utf-8"))["statistics"]["total"]
        sources, new = int(total.get("sources", 0)), int(total.get("newClones", 0))
        # THE NEW CLONES' LINES, which jscpd counts apart from the baseline's beside them: the
        # whole tree's `duplicatedLines` is what the advice below compares with HEAD's.
        lines = total.get("newDuplicatedLines", "?")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Invalid(f"the jscpd report could not be read: {type(e).__name__}: {e}") from None
    if sources == 0:
        raise Invalid("jscpd analysed 0 files, so this is not a verdict")
    if rc != 0 and new == 0:
        raise Invalid(f"jscpd exited {rc} and its report counts no new clone:\n{said}")
    if new > 0:
        # jscpd keys a clone by its content, so one that shrank under an edit reads as new.
        raise Refused(
            f"{said}\n{new} new clone(s), {lines} new duplicated lines, over a baseline of "
            f"accepted duplication, in {sources} files (rc={rc}).\n"
            "A clone that shrank or split under your edit is counted as new even when the "
            "duplication went DOWN. Compare the duplicated lines with HEAD's first, from the "
            "repository's root:\n"
            "    d=$(mktemp -d); git archive HEAD | tar -x -C \"$d\"\n"
            "    (cd \"$d\" && jscpd . --reporters json --output r)  # statistics.total"
            ".duplicatedLines\n"
            "Consolidate it, or accept it deliberately with:\n"
            f"    jscpd . --baseline {BASELINE} --update-baseline\n"
            "and say in the commit message WHY that site stays duplicated.")
    return f"   {sources} files, no new duplication"


def probe_fit(root: Path) -> str:
    """The probe check's own lines for a covered task set; `Refused` on a refusal it names,
    `Invalid` on anything else."""
    seam = os.environ.get("PRECOMMIT_PROBE")
    rc, said = _run([seam] if seam else [sys.executable, *PROBE_CHECK], "the probe check", root,
                    "PRECOMMIT_PROBE")
    lines = said.splitlines()
    if rc == 0:
        if not any(line.startswith(CHECK_OK) for line in lines):
            raise Invalid(f"the probe check examined no server, so this is not a verdict:\n{said}")
        return "\n".join(f"   {line}" for line in lines)
    if rc == 1:
        if not any(line.startswith(CHECK_REFUSED) for line in lines):
            raise Invalid(f"the probe check exited 1 naming no refusal:\n{said}")
        raise Refused(
            f"{said}\na probe task is missing or wrong (above). Fix it in "
            f"{TASKS_DIR}/<server>.json and run the free check again, through the same `uv run` "
            "as this hook, from the repository root: python -m scry_core.probe <server> --check "
            f"--servers {SERVERS_FILE} --tasks {TASKS_DIR}\n"
            "The same command with `--runs 3` in place of `--check` drives the model and costs a "
            "run: it is only for a task added for a new or changed tool.")
    raise Invalid(f"the probe check exited {rc}:\n{said}")


def _is_tool(decorator: ast.expr) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    f = decorator.func
    return (isinstance(f, ast.Name) and f.id == "tool") or (
        isinstance(f, ast.Attribute) and f.attr == "tool")


def prose_bytes(source: bytes) -> int:
    """The bytes of `source`'s comment tokens and docstrings, a registered tool's left out."""
    # ast's columns on line 1 do not count a BOM, so the line offsets must not either
    source = source.removeprefix(codecs.BOM_UTF8)
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    n = sum(len(t.string.encode()) for t in tokenize.tokenize(io.BytesIO(source).readline)
            if t.type == tokenize.COMMENT)
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not isinstance(node, ast.Module) and any(map(_is_tool, node.decorator_list)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str) and first.end_lineno is not None \
                and first.end_col_offset is not None:
            # ast's columns are UTF-8 byte offsets, so the span is counted in bytes directly.
            n += (starts[first.end_lineno - 1] + first.end_col_offset
                  - starts[first.lineno - 1] - first.col_offset)
    return n


def _exemptions(root: Path) -> dict[str, str]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise Misconfigured(f"pyproject.toml does not parse: {e}") from None
    try:
        table = doc.get("tool", {}).get("scry-prose", {}).get("exempt", {})
    except AttributeError:
        raise Misconfigured("[tool.scry-prose] is not a table under [tool]") from None
    if not isinstance(table, dict):
        raise Misconfigured("[tool.scry-prose] exempt is not a table of path = reason")
    for rel, why in table.items():
        if not isinstance(why, str) or not why.strip():
            raise Misconfigured(f"{rel} is exempted with no reason")
        if not (root / rel).is_file():
            raise Misconfigured(f"{rel} is exempted but does not exist")
    return table


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", *args], capture_output=True, check=False, cwd=cwd)
    except OSError as e:
        raise Invalid(f"git could not be run: {e}") from None


def _python_files(root: Path) -> list[str]:
    listed: set[str] = set()
    for extra in ([], ["--others", "--exclude-standard"]):
        done = _git(["ls-files", "-z", *extra], root)
        if done.returncode != 0:
            raise Invalid(f"git ls-files failed (rc={done.returncode}): "
                          f"{done.stderr.decode(errors='replace').strip()}")
        listed.update(done.stdout.decode(errors="surrogateescape").split("\0"))
    return sorted(rel for rel in listed if rel.endswith(".py") and not (root / rel).is_symlink()
                  and (root / rel).is_file())


def prose(root: Path) -> str:
    """The prose check's line for a tree within its ceilings; `Refused` naming each file over."""
    exempt = _exemptions(root)
    judged, over = 0, []
    for rel in _python_files(root):
        if rel in exempt:
            continue
        source = (root / rel).read_bytes()
        try:
            share = prose_bytes(source) / len(source) if source else 0.0
        except (SyntaxError, ValueError, tokenize.TokenError) as e:
            raise Invalid(f"{rel} could not be read: {type(e).__name__}: {e}") from None
        ceiling = PROSE_CEILING_TESTS if rel.startswith("tests/") else PROSE_CEILING
        judged += 1
        if share > ceiling:
            over.append(f"{rel}: prose {share:.1%} of {len(source)} bytes, ceiling {ceiling:.1%}")
    if judged == 0:
        raise Invalid("prose examined 0 files, so this is not a verdict")
    if over:
        raise Refused("\n".join(over))
    return f"prose: {judged} files within the ceiling"


def _root() -> Path:
    done = _git(["rev-parse", "--show-toplevel"])
    if done.returncode != 0:
        raise Invalid(f"git does not say where the repository root is (rc={done.returncode}): "
                      f"{done.stderr.decode(errors='replace').strip()}")
    return Path(done.stdout.decode(errors="surrogateescape").strip())


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m scry_core.hook", description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            allow_abbrev=False).parse_args(argv)
    try:
        root = _root()
        with tempfile.TemporaryDirectory(prefix="scry-hook-") as scratch:
            print("== jscpd (new duplication against the baseline)")
            print(duplication(root, Path(scratch)))
        print("== mcp_probe (the probe's tasks still fit the MCP servers)")
        print(probe_fit(root))
        print("== prose (comments and docstrings within their ceiling)")
        print(prose(root))
    except Refused as e:
        print(f"pre-commit: REFUSED: {e}", file=sys.stderr)
        return EXIT_FAIL
    except Misconfigured as e:
        print(f"pre-commit: USAGE: {e}", file=sys.stderr)
        return EXIT_USAGE
    except Invalid as e:
        print(f"pre-commit: INVALID: {e}", file=sys.stderr)
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- anything else stopped it before a verdict
        print(f"pre-commit: INVALID: the hook stopped before its verdict: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_INVALID
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
