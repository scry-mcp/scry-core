"""The bench a server's live tier runs on: files copied once from their source checkouts, each
pinned by its sha256 in the bench's manifest, so a live run reads no other repository.

    python -m scry_core.live_bench check --bench <bench>
    python -m scry_core.live_bench fill --bench <bench> --from some-project=/path/to/checkout ...
    python -m scry_core.live_bench fill ... --from some-project=... --record

The bench is named, never found: its manifest is `<bench>/bench.json` by contract, and each
server's live tier resolves its own bench, so a default resolved from where this package is
installed cannot read some other tree's bench in silence.

A copy and not the checkout: a session working in the checkout can change it under a run, while
the copy changes only when somebody fills it again.

`fill` copies the manifest's entries from the checkouts named by `--from <source_repo>=<path>`
and refuses a source whose bytes are not the pinned ones; `--record` writes the pins instead,
from the copies it just made, with each source's `HEAD`. An entry with a `capture` holds the
output of a program run once in its checkout (`capture` is its argv, run there with
`PYTHONDONTWRITEBYTECODE` set; `source_path` names that program in the reports).

Exit codes: 0 the bench matches (or was filled), 1 a file is missing or does not match, or a
source was refused, 2 a usage error, 3 INVALID (an empty manifest, a bench root that does not
exist, a manifest that is not one, a `--from` the manifest does not name or that is not a
directory, `--record` on a checkout with no `HEAD`, and anything else that stopped the action
before its verdict: 1 is a verdict about the bench, so an error never answers it).
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

#: The manifest's name inside its bench: the contract, so no caller names it.
MANIFEST = "bench.json"
KEYS = ("path", "sha256", "source_repo", "source_path", "source_commit")
CAPTURE_TIMEOUT_S = 600


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


def _relative(text: object, what: str) -> str:
    """`text` as a normalized relative path, refused when it could leave its directory."""
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
    """Whether `path` is `prefix` or inside it, by whole segments (`board` is not in `board2/x`)."""
    head = prefix.rstrip("/")
    return not head or path == head or path.startswith(head + "/")


def problems(at: Path, prefix: str = "") -> list[str]:
    """One line per entry under `prefix` (all when empty) absent from the bench or off its pin.

    `Invalid` when the bench root does not exist or nothing lies under `prefix`: neither
    examined a file, so neither may read as a match."""
    if not at.is_dir():
        raise Invalid(f"the bench does not exist: {at} is not a directory")
    manifest = at / MANIFEST
    entries = [e for e in load(manifest) if _under(e.path, prefix)]
    if not entries:
        raise Invalid(f"{manifest} names no file under {prefix!r}")
    lines = []
    for e in entries:
        here = at / e.path
        if not here.is_file():
            lines.append(f"MISSING {e.path}: not in the bench at {at}")
        elif (got := digest(here)) != e.sha256:
            lines.append(f"MISMATCH {e.path}: sha256 {got}, the manifest pins {e.sha256 or 'none'}")
    return lines


def check_command(at: Path) -> str:
    """The command that judges the bench at `at`."""
    return f"python -m scry_core.live_bench check --bench {at}"


def fill_remedy(at: Path) -> str:
    """The remedy sentence for a missing or moved file."""
    return (f"`{fill_command(at)}` copies them from a checkout that still matches the pin "
            "(`--record` re-pins one that moved)")


def fill_command(at: Path) -> str:
    """The command that copies a bench's files back from a checkout matching their pins."""
    return f"python -m scry_core.live_bench fill --bench {at} --from <source_repo>=<checkout>"


@dataclass(frozen=True)
class Bench:
    """A server's bench at the `root` its live tier resolved.

    Answers are cached per `Bench`: a run asks the same question for every cell of a board, and
    the answer changes only by filling the bench, which is a new run."""

    root: Path
    _reasons: dict[str, str] = field(default_factory=dict, init=False, repr=False,
                                     compare=False)

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST

    def missing(self, prefix: str) -> str:
        """Why the files under `prefix` cannot be used (a board is BLOCKED with it), or empty."""
        if prefix not in self._reasons:
            self._reasons[prefix] = self._why(prefix)
        return self._reasons[prefix]

    def _why(self, prefix: str) -> str:
        if self.root.is_dir() and not self.manifest.is_file():
            # `fill` copies what the manifest names, so it cannot make the manifest itself.
            return (f"bench manifest ABSENT: {self.manifest} pins every copy and is kept only in "
                    f"the bench; restore it there, then `{check_command(self.root)}`")
        try:
            found = problems(self.root, prefix)
        except (Invalid, OSError) as e:
            # Nothing was examined, so no copy can be the remedy.
            return f"bench unusable: {e}"
        if not found:
            return ""
        more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
        return (f"bench {found[0]}{more}; `{check_command(self.root)}` lists them all, and "
                + fill_remedy(self.root))

    @functools.cached_property
    def pinned(self) -> frozenset[str]:
        """Every path the manifest pins."""
        return frozenset(e.path for e in load(self.manifest))


def _check(at: Path) -> int:
    found = problems(at)
    for line in found:
        print(line)
    pinned = len(load(at / MANIFEST))
    if not found:
        print(f"OK {at}: {pinned} files match the manifest")
        return EXIT_PASS
    print(f"FAIL {at}: {len(found)} of {pinned} files do not match the manifest; "
          + fill_remedy(at))
    return EXIT_FAIL


def _head(checkout: Path) -> str:
    done = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Invalid(f"{checkout}: git rev-parse HEAD answered rc={done.returncode}: "
                      f"{done.stderr.strip()}")
    return done.stdout.strip()


def _take(e: Entry, checkout: Path, into: Path) -> str:
    """Write the source of `e` to `into`; the reason it could not be, or empty."""
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


def _fill(at: Path, sources: dict[str, Path], record: bool) -> int:
    manifest = at / MANIFEST
    entries = load(manifest)
    known = {e.source_repo for e in entries}
    for name, checkout in sources.items():
        if name not in known:
            raise Invalid(f"--from {name}: {manifest} names no file from it "
                          f"(it names {', '.join(sorted(known))})")
        if not checkout.is_dir():
            raise Invalid(f"--from {name}={checkout}: not a directory")
    heads = {name: _head(checkout) for name, checkout in sources.items()} if record else {}
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
                why = (f"the checkout's sha256 {got}, the manifest pins {e.sha256 or 'none'}: "
                       "`--record` pins the checkout's instead")
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
    unverified = ", not verified (name their source with --from)" if others else ""
    print(f"fill {at}: {copied} copied, {kept} already in place, {refused} refused, "
          f"{others} from sources not named{unverified}{recorded}")
    return EXIT_FAIL if refused else EXIT_PASS


def _source(text: str) -> tuple[str, Path]:
    name, sep, path = text.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"{text!r} is not <source_repo>=<checkout>")
    return name, Path(path).expanduser()


def _bench(text: str) -> Path:
    return Path(text).expanduser().absolute()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scry_core.live_bench",
                                description=__doc__.split("\n\n")[0], allow_abbrev=False)
    sub = p.add_subparsers(dest="action", required=True, metavar="{check,fill}")
    check = sub.add_parser("check", help="verify the bench against its manifest",
                           allow_abbrev=False)
    fill = sub.add_parser("fill", help="copy the manifest's files from their checkouts",
                          allow_abbrev=False)
    for action in (check, fill):
        action.add_argument("--bench", required=True, type=_bench,
                            help=f"the bench's directory; its manifest is <bench>/{MANIFEST}")
    fill.add_argument("--from", dest="sources", required=True, action="append", type=_source,
                      metavar="SOURCE_REPO=CHECKOUT",
                      help="a checkout the manifest's entries of SOURCE_REPO are copied from")
    fill.add_argument("--record", action="store_true",
                      help="write the pins from the fresh copies instead of refusing a change")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.action == "fill":
        names = [name for name, _ in args.sources]
        if twice := sorted({n for n in names if names.count(n) > 1}):
            p.error(f"--from names {', '.join(twice)} twice")
    try:
        if args.action == "check":
            return _check(args.bench)
        return _fill(args.bench, dict(args.sources), args.record)
    except Invalid as e:
        print(f"INVALID: {e}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 -- anything else stopped it before a verdict
        print(f"INVALID: {args.action} stopped before its verdict, so nothing here is one: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
    return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
