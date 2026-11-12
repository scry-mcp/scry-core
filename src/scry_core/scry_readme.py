"""`scry_readme` -- renders a repository's `.scry/README.md` from one template and its folder.

Run `uv run python -m scry_core.scry_readme [--check] [DIR]` from a scry-core checkout, DIR being
the repository (default: the current directory). The servers' approved `promote` renders the same
page. The page is always rendered whole, so a re-render is safe and brings a changed template to
every repository. What the folder cannot say for itself is in `.scry/about.json`
(`scry-about/1`): `purpose` and `server` (`mame` or `dosbox-x`) are required; `build` is
`{"command", "note"?}`; `notes` is a list of paragraphs; `files` gives one line per file of
`start/`, `maps/` and `perform/`, and must cover exactly the files there.

`--check` writes nothing and refuses a page that differs from its render.

EXIT: 0 written, unchanged or current; 1 `--check` found drift; 2 the manifest breaks its
format; 3 INVALID (no `.scry/` above DIR, no entry in it, or a page that cannot be read
or written).
"""
from __future__ import annotations

import argparse
import json
import re
import string
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scry_core import project_store
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

EXIT_USAGE = 2
ABOUT = "about.json"
README = "README.md"
FORMAT = "scry-about/1"
SERVERS = ("mame", "dosbox-x")
TEMPLATE = Path(__file__).with_name("scry_readme_template.md")
FIELDS = ("purpose", "build", "start", "files", "notes")
_STORE_PATHS = "https://github.com/scry-mcp/scry-core/blob/main/docs/store-paths.md"
_KEYS = {"format", "purpose", "server", "build", "notes", "files"}
_KINDS = (
    ("start", "Recipes", "A recipe is the arguments of `start`, so a session boots a program "
     "without composing them by hand."),
    ("maps", "Screen maps", "Each names a program's screens and where their controls are."),
    ("perform", "Sessions", "Each is a list of steps the `perform` tool replays."),
)


class Refused(Exception):
    """The manifest or the folder breaks the format; the message names the key or the file."""


def fields(template: str) -> set[str]:
    return set(re.findall(r"\$([a-z]+)", template))


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.splitlines()) != 1:
        raise Refused(f"{where} must be one non-empty line of text")
    return value.strip()


def _manifest(store: Path) -> dict[str, object]:
    path = store / ABOUT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise Refused(f"{path} is missing: it holds what the folder cannot say for itself, "
                      f"in `{FORMAT}`") from None
    except ValueError as exc:
        raise Refused(f"{path} is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise Refused(f"{path} must be a JSON object")
    if data.get("format") != FORMAT:
        raise Refused(f"{path}: format must be {FORMAT!r}")
    unknown = sorted(set(data) - _KEYS)
    if unknown:
        raise Refused(f"{path}: unknown key {', '.join(unknown)}")
    return data


def _entries(store: Path) -> list[str]:
    found: list[str] = []
    for kind in project_store.KINDS:
        suffix = project_store.SUFFIXES.get(kind, ".json")
        found += [f"{kind}/{p.name}" for p in sorted((store / kind).glob(f"*{suffix}"))
                  if p.is_file()]
    return found


def _server(value: object) -> str:
    if value not in SERVERS:
        raise Refused(f"server must be one of {', '.join(SERVERS)}, not {value!r}")
    return str(value)


def _build(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, dict):
        raise Refused("build must be an object with a `command` and an optional `note`")
    extra = sorted(set(value) - {"command", "note"})
    if extra:
        raise Refused(f"build: unknown key {', '.join(extra)}")
    command = _text(value.get("command"), "build.command")
    note = f" {_text(value['note'], 'build.note')}" if "note" in value else ""
    return f"## Build first\n\nThe recipes below need this built first.{note}\n\n    {command}"


def _files(entries: list[str], lines: Mapping[str, object], server: str) -> tuple[str, str]:
    missing = sorted(set(entries) - set(lines))
    ghosts = sorted(set(lines) - set(entries))
    if missing:
        raise Refused(f"{ABOUT} has no line for {', '.join(missing)}")
    if ghosts:
        raise Refused(f"{ABOUT} has a line for {', '.join(ghosts)}, which is not in the folder")
    said = {name: _text(lines[name], f"files[{name!r}]") for name in entries}
    start = ""
    if any(name.startswith("start/") for name in entries):
        start = (f"## How to start\n\nCall the `{server}` server's `start` tool with a recipe's "
                 'name: `start(profile="<name>")`. An argument in the same call wins over the '
                 "recipe's. A recipe's paths resolve against the directory holding `.scry/`, "
                 f"and what would be this machine's path is a [placeholder]({_STORE_PATHS}).")
    sections = []
    for kind, title, what in _KINDS:
        rows = []
        for name in (n for n in entries if n.startswith(f"{kind}/")):
            label = f"`{name}`"
            if kind == "start":
                label = f"`{project_store.entry_of(Path(name), kind)}` (`{name}`)"
            rows.append(f"- {label}: {said[name]}")
        if rows:
            sections.append(f"## {title}\n\n{what}\n\n" + "\n".join(rows))
    return start, "\n\n".join(sections)


def _render(data: Mapping[str, object], entries: list[str]) -> str:
    purpose = _text(data.get("purpose"), "purpose")
    server = _server(data.get("server"))
    lines = data.get("files")
    if not isinstance(lines, dict):
        raise Refused("files must map each file of start/, maps/ and perform/ to its line")
    notes = data.get("notes", [])
    if not isinstance(notes, list):
        raise Refused("notes must be a list of paragraphs")
    start, files = _files(entries, lines, server)
    values = {"purpose": purpose, "build": _build(data.get("build")), "start": start,
              "files": files,
              "notes": "\n\n".join(_text(n, "a note") for n in notes)}
    text = string.Template(TEMPLATE.read_text(encoding="utf-8")).substitute(values)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip("\n") + "\n"


def render(root: Path) -> str:
    store = root / project_store.STORE
    return _render(_manifest(store), _entries(store))


def derived_line(kind: str, name: str, document: object) -> str:
    """The `files` line an entry earns with no hand-written one, from the entry alone
    (docs/scry-readme.md says what each kind says)."""
    doc = document if isinstance(document, dict) else {}
    if kind == "start":
        for key in ("program", "system"):
            if value := _flat(doc.get(key)):
                return f"boots `{value}`."
        return "a run recipe."
    if kind == "maps":
        return f"the screens of {_flat(doc.get('application')) or name}."
    steps = doc.get("steps")
    if not isinstance(steps, list):
        return "a session."
    return f"replays {len(steps)} step{'' if len(steps) == 1 else 's'}."


@dataclass(frozen=True)
class Setup:
    """What an approved promotion leaves in the store besides its entries: `about` (None when
    the manifest already covers every file and stays as it is), the rendered `page`, and what
    did not exist before, as paths from the repository."""

    about: bytes | None
    page: bytes
    created: tuple[str, ...]


def scaffold(root: Path, server: str, entries: Mapping[str, object]) -> Setup:
    """`root`'s `.scry/about.json` and README as they stand once `entries` (each file of the
    store, `start/x.json`, with its document) are written. A manifest that exists keeps every
    line it has and gains one derived line per file it lacks; one that does not is made from
    `server`, with a line for every file the store will hold. Nothing is written."""
    store = root / project_store.STORE
    _server(server)
    for name in (ABOUT, README):
        if (store / name).exists() and not (store / name).is_file():
            raise Refused(f"{store / name} is not a file")
    if (store / ABOUT).exists():
        data = _manifest(store)
        held = data.get("files")
        lines = dict(held) if isinstance(held, dict) else held
    else:
        data = {"format": FORMAT,
                "purpose": f"What this repository declares for SCRY's `{server}` server.",
                "server": server}
        lines = {}
    names = sorted(set(_entries(store)) | set(entries))
    changed = False
    if isinstance(lines, dict):
        for name in names:
            if name not in lines:
                kind = name.partition("/")[0]
                document = entries[name] if name in entries else _read(store / name)
                lines[name] = derived_line(kind, project_store.entry_of(Path(name), kind),
                                           document)
                changed = True
        data = {**data, "files": lines}
    text = _render(data, names)
    created = tuple(path for path, absent in (
        (f"{project_store.STORE}/", not store.exists()),
        (f"{project_store.STORE}/{ABOUT}", not (store / ABOUT).exists()),
        (f"{project_store.STORE}/{README}", not (store / README).exists())) if absent)
    about = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return Setup(about if changed or not (store / ABOUT).exists() else None,
                 text.encode("utf-8"), created)


def _flat(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scry_core.scry_readme", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("directory", nargs="?", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = project_store.root([Path(args.directory).resolve()])
        if root is None:
            raise Invalid(f"no {project_store.STORE}/ at or above {args.directory}")
        if not _entries(root / project_store.STORE):
            raise Invalid(f"{root / project_store.STORE} holds no file under "
                          f"{', '.join(project_store.KINDS)}: nothing to render")
        text = render(root)
    except Refused as exc:
        print(f"scry_readme: REFUSED: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Invalid as exc:
        print(f"scry_readme: INVALID: {exc}", file=sys.stderr)
        return EXIT_INVALID
    page = root / project_store.STORE / README
    try:
        current = page.read_text(encoding="utf-8") if page.is_file() else None
        if args.check:
            if current == text:
                print(f"OK {page}")
                return EXIT_PASS
            print(f"DRIFT {page}: differs from its render; run without --check",
                  file=sys.stderr)
            return EXIT_FAIL
        if current == text:
            print(f"unchanged {page}")
        else:
            page.write_bytes(text.encode("utf-8"))
            print(f"wrote {page}")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"scry_readme: INVALID: {page} could not be read or written: {exc}",
              file=sys.stderr)
        return EXIT_INVALID
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
