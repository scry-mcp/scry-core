"""The bench a server's live tier runs on: files copied once from their source checkouts, each
pinned by its sha256 in the server's tracked manifest, so a live run reads no other repository.

    python -m scry_core.live_bench check --server mame --manifest tests/live/bench.json
    python -m scry_core.live_bench fill --server mame --manifest tests/live/bench.json \
        --from tch-blitter=/path/to/checkout ...
    python -m scry_core.live_bench fill ... --from tch-blitter=... --record

THE MANIFEST IS NAMED, NEVER FOUND: this module belongs to no server's tree, and a default
resolved from where it happens to be installed would read some other tree's manifest in silence.

WHY A COPY AND NOT THE CHECKOUT ITSELF: a tier that drives another project's working tree
measures whatever that tree holds today, and a session working there can change it under the
run (a symbol file rewritten, a binary rebuilt, a declaration cleared). The copy changes only
when somebody fills it again, and the hash says whether it is still the copy that was pinned.

`fill` copies the manifest's entries from the checkouts named by `--from <source_repo>=<path>`
and refuses a source whose bytes are not the ones pinned; `--record` writes the pins instead,
from the copies it just made, with each source's `HEAD`. An entry with a `capture` holds the
output of a program run once in its checkout (`capture` is its argv, `source_path` the program),
which is how a known answer is taken from a real run without the tier running it again. A
capture runs with `PYTHONDONTWRITEBYTECODE` set, so its checkout gains no `__pycache__`.

Exit codes: 0 the bench matches (or was filled), 1 a file is missing or does not match, or a
source was refused, 2 a usage error, 3 INVALID (an empty manifest, a bench root that does not
exist, a manifest that is not one, a `--from` the manifest does not name or that is not a
directory, `--record` on a checkout with no `HEAD`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INVALID = 0, 1, 2, 3

# One root per server, each overridable by its own variable.
ROOT_VARS = {"mame": "MAME_LIVE_BENCH", "dosbox-x": "DOSBOX_X_LIVE_BENCH"}
KEYS = ("path", "sha256", "source_repo", "source_path", "source_commit")
CAPTURE_TIMEOUT_S = 600


class Invalid(Exception):
    """Nothing was examined: no verdict about the bench."""


@dataclass(frozen=True)
class Entry:
    path: str
    sha256: str
    source_repo: str
    source_path: str
    source_commit: str
    capture: tuple[str, ...] | None = None

    def as_json(self) -> dict[str, object]:
        doc: dict[str, object] = {k: getattr(self, k) for k in KEYS}
        if self.capture is not None:
            doc["capture"] = list(self.capture)
        return doc


def root(server: str) -> Path:
    """The bench of `server`: its variable when set, else `~/.local/share/scry-bench/<server>`."""
    held = os.environ.get(ROOT_VARS[server], "")
    if held:
        return Path(held).expanduser().absolute()
    return Path.home() / ".local" / "share" / "scry-bench" / server


def _relative(text: object, what: str) -> str:
    """`text` as a path inside the bench or a checkout, in one spelling (`a/./b` is `a/b`),
    refused when it could leave it."""
    path = Path(text) if isinstance(text, str) else None
    if path is None or not path.parts or path.is_absolute() or ".." in path.parts:
        raise Invalid(f"{what} {text!r} is not a relative path inside its directory")
    return path.as_posix()


def _entry(doc: object, where: str) -> Entry:
    if not isinstance(doc, dict) or not set(KEYS) <= set(doc) or set(doc) - {*KEYS, "capture"}:
        raise Invalid(f"{where}: an entry carries exactly {', '.join(KEYS)} and an optional "
                      f"capture, not {sorted(doc) if isinstance(doc, dict) else doc!r}")
    if not all(isinstance(doc[k], str) for k in KEYS):
        raise Invalid(f"{where}: every field of an entry is a string")
    capture = doc.get("capture")
    if capture is not None and (not isinstance(capture, list) or not capture
                                or not all(isinstance(a, str) for a in capture)):
        raise Invalid(f"{where}: capture is an argv, a non-empty list of strings")
    return Entry(_relative(doc["path"], "path"), doc["sha256"], doc["source_repo"],
                 _relative(doc["source_path"], "source_path"), doc["source_commit"],
                 tuple(capture) if capture is not None else None)


def load(path: Path) -> list[Entry]:
    """The manifest at `path`, refused (`Invalid`) when it names no file or is not one."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Invalid(f"{path} is not a manifest: {e}") from e
    if not isinstance(doc, list):
        raise Invalid(f"{path} is not a list of entries")
    entries = [_entry(d, f"{path} entry {i}") for i, d in enumerate(doc)]
    if not entries:
        raise Invalid(f"{path} names no file, so there is nothing to examine")
    paths = [e.path for e in entries]
    if len(set(paths)) != len(paths):
        raise Invalid(f"{path} names a path twice")
    return entries


def digest(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _under(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` or lies inside it, by whole path segments: `lineup` is not a
    prefix of `lineup2/x`."""
    head = prefix.rstrip("/")
    return not head or path == head or path.startswith(head + "/")


def problems(server: str, manifest: Path, prefix: str = "") -> list[str]:
    """One line per entry under `prefix` (a directory or one file of the bench, every entry when
    empty) that is absent from the bench or does not match its pin.

    `Invalid` when the bench root does not exist or nothing lies under `prefix`: neither
    examined a file, so neither may read as a match."""
    entries = [e for e in load(manifest) if _under(e.path, prefix)]
    if not entries:
        raise Invalid(f"the manifest of {server} names no file under {prefix!r}")
    at = root(server)
    if not at.is_dir():
        raise Invalid(f"the bench of {server} does not exist: {at} is not a directory")
    lines = []
    for e in entries:
        here = at / e.path
        if not here.is_file():
            lines.append(f"MISSING {e.path}: not in the bench at {at}")
        elif (got := digest(here)) != e.sha256:
            lines.append(f"MISMATCH {e.path}: sha256 {got}, the manifest pins {e.sha256 or 'none'}")
    return lines


def missing(server: str, manifest: Path, prefix: str) -> str:
    """Why the files under `prefix` cannot be used, naming the first file and the remedy, or
    empty when every one matches its pin: the reason a live board is BLOCKED with."""
    try:
        found = problems(server, manifest, prefix)
    except (Invalid, OSError) as e:
        found = [str(e)]
    if not found:
        return ""
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return (f"bench {found[0]}{more}; run `python -m scry_core.live_bench check --server "
            f"{server} --manifest {manifest}`, then `fill` from the source checkouts")


def _check(server: str, manifest: Path) -> int:
    found = problems(server, manifest)
    for line in found:
        print(line)
    if not found:
        print(f"OK {server}: {len(load(manifest))} files match the manifest")
    return EXIT_FAILED if found else EXIT_OK


def _head(checkout: Path) -> str:
    done = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Invalid(f"{checkout}: git rev-parse HEAD answered rc={done.returncode}: "
                      f"{done.stderr.strip()}")
    return done.stdout.strip()


def _take(e: Entry, checkout: Path, into: Path) -> str:
    """The source of `e` written to `into`, answering why not when it could not be."""
    if e.capture is not None:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            done = subprocess.run(list(e.capture), cwd=checkout, capture_output=True, env=env,
                                  timeout=CAPTURE_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"its capture could not run: {exc}"
        if done.returncode != 0 or not done.stdout:
            return (f"its capture answered rc={done.returncode} with {len(done.stdout)} bytes: "
                    f"{done.stderr[-300:].decode(errors='replace').strip()}")
        into.write_bytes(done.stdout)
        return ""
    src = checkout / e.source_path
    if not src.is_file():
        return f"{src} is not a file"
    try:
        shutil.copyfile(src, into)
        shutil.copymode(src, into)
    except OSError as exc:
        return f"it could not be copied: {exc}"
    return ""


def _fill(server: str, manifest: Path, sources: dict[str, Path], record: bool) -> int:
    entries = load(manifest)
    known = {e.source_repo for e in entries}
    for name, checkout in sources.items():
        if name not in known:
            raise Invalid(f"--from {name}: the manifest of {server} names no file from it "
                          f"(it names {', '.join(sorted(known))})")
        if not checkout.is_dir():
            raise Invalid(f"--from {name}={checkout}: not a directory")
    heads = {name: _head(checkout) for name, checkout in sources.items()} if record else {}
    at = root(server)
    copied = kept = refused = 0
    out: list[Entry] = []
    for e in entries:
        if e.source_repo not in sources:
            out.append(e)
            continue
        dest = at / e.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            why = _take(e, sources[e.source_repo], tmp)
            got = "" if why else digest(tmp)
            if not why and not record and got != e.sha256:
                why = f"sha256 {got}, the manifest pins {e.sha256 or 'none'}"
            if why:
                print(f"REFUSED {e.path}: {e.source_repo}:{e.source_path}: {why}")
                refused += 1
                out.append(e)
                continue
            if dest.is_file() and digest(dest) == got:
                kept += 1
            else:
                os.replace(tmp, dest)
                print(f"copied {e.path} <- {e.source_repo}:{e.source_path}")
                copied += 1
            out.append(Entry(e.path, got, e.source_repo, e.source_path,
                             heads.get(e.source_repo, e.source_commit), e.capture))
        finally:
            tmp.unlink(missing_ok=True)
    others = len(entries) - copied - kept - refused
    if record and not refused:
        manifest.write_text(
            json.dumps([e.as_json() for e in out], indent=2) + "\n", encoding="utf-8")
    recorded = ("" if not record else "; manifest recorded" if not refused else
                "; manifest NOT recorded, so the copies made now are off their old pins")
    print(f"fill {server}: {copied} copied, {kept} already in place, {refused} refused, "
          f"{others} from sources not named{recorded}")
    return EXIT_FAILED if refused else EXIT_OK


def _source(text: str) -> tuple[str, Path]:
    name, sep, path = text.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"{text!r} is not <source_repo>=<checkout>")
    return name, Path(path).expanduser()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scry_core.live_bench",
                                description=__doc__.split("\n\n")[0], allow_abbrev=False)
    sub = p.add_subparsers(dest="action", required=True, metavar="{check,fill}")
    check = sub.add_parser("check", help="verify the bench against the manifest",
                           allow_abbrev=False)
    check.add_argument("--server", required=True, choices=sorted(ROOT_VARS))
    check.add_argument("--manifest", required=True, type=Path,
                       help="the server's tracked manifest (its tests/live/bench.json)")
    fill = sub.add_parser("fill", help="copy the manifest's files from their checkouts",
                          allow_abbrev=False)
    fill.add_argument("--server", required=True, choices=sorted(ROOT_VARS))
    fill.add_argument("--manifest", required=True, type=Path,
                      help="the server's tracked manifest (its tests/live/bench.json)")
    fill.add_argument("--from", dest="sources", required=True, action="append", type=_source,
                      metavar="SOURCE_REPO=CHECKOUT",
                      help="a checkout the manifest's entries of SOURCE_REPO are copied from")
    fill.add_argument("--record", action="store_true",
                      help="write the pins from the fresh copies instead of refusing a change")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.action == "check":
            return _check(args.server, args.manifest)
        sources = dict(args.sources)
        if len(sources) != len(args.sources):
            p.error("--from names one source twice")
        return _fill(args.server, args.manifest, sources, args.record)
    except Invalid as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
