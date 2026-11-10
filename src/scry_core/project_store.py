"""The store a repository declares for its own program (`.scry/`): where it is, and what a
`start` profile says.

    .scry/start/<name>.json                   a run recipe: `start`'s arguments
    .scry/maps/<application>-screen-map.json  a screen map (`scry-screen-map/1`)
    .scry/perform/<name>.json                 a `perform` document

A profile is `{"format": "scry-start/1", ...}` whose keys are `start`'s own arguments, which the
reading server hands in with the pre-gate that judges them, and whose paths resolve against one
base: the directory that holds `.scry/`, never the file's own. `${root}`, `${home}`, `${state}`
and `${env:NAME}` stand for what a tracked file must not carry, and an unset one is refused by
name. The caller's own argument wins over the profile's (`precedence`); `applied` is the one call
a server makes."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from scry_core import file_names
from scry_core.reply_contract import Invalid

STORE = ".scry"
KINDS = ("start", "maps", "perform")
#: What a kind's file name adds to its entry's name.
SUFFIXES = {"maps": "-screen-map.json"}
FORMAT = "scry-start/1"

#: A profile of `start`'s arguments is a few hundred bytes; past this it is not arguments but
#: data, which does not belong in a repository's profile.
PROFILE_BYTES_MAX = 64 * 1024
#: Entries one kind directory may hold, and the whole store's bytes: `promote` reads both.
ENTRIES_MAX = 200
STORE_BYTES_MAX = 4 * 1024 * 1024

_PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
_DRIVE = re.compile(r"[A-Za-z]:[\\/]")


def root(starting: Iterable[str | Path]) -> Path | None:
    """The nearest directory at or above a starting point that holds `.scry/`, the starting
    points tried in order; None when none does."""
    for start in starting:
        for above in _above(Path(start)):
            if (above / STORE).is_dir():
                return above
    return None


def locate(starting: Iterable[str | Path], name: str, kind: str = "start") -> Path:
    """The entry `name` of `kind` found by walking up from each starting point in order, or the
    refusal naming the directories searched."""
    name = entry_name(name)
    if kind not in KINDS:
        raise Invalid("bad_argument", f"a store holds {', '.join(KINDS)}; {kind!r} is not one")
    starts = list(starting)
    if not starts:
        raise Invalid("bad_argument", f"no directory to search for the {kind} named {name!r}: "
                      "give the working directory, or the directory a program is named from")
    searched: list[Path] = []
    seen: set[Path] = set()
    for start in starts:
        for above in _above(Path(start)):
            if above in seen:
                continue
            seen.add(above)
            searched.append(above)
            found = above / STORE / kind / file_name(kind, name)
            if found.is_file():
                return found
    raise Invalid("bad_argument", f"no {STORE}/{kind}/{file_name(kind, name)} above "
                  f"{_listed(starts)}: searched {_listed(searched)}")


def read(entry: Path, keys: Collection[str], path_keys: Collection[str] = (), *,
         state: str = "", environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """A profile's `start` arguments, each path resolved against the store's root. `keys` is what
    the reading server takes and `path_keys` which of them hold paths; `state` is the session's
    scratch, refused by name where the file uses `${state}` and there is none."""
    where = f"the profile {entry}"
    base = _base(entry, where)
    raw = _json(entry, where)
    declared = raw.get("format")
    if declared is None:
        raise Invalid("bad_argument", f"{where} declares no `format`: a start profile is "
                      f'{{"format": "{FORMAT}", ...}}')
    if declared != FORMAT:
        raise Invalid("bad_argument", f"{where} is format {declared!r}, which this reader does "
                      f"not know: it reads {FORMAT!r}")
    values = {key: value for key, value in raw.items() if key != "format"}
    extra = sorted(set(values) - set(keys))
    if extra:
        raise Invalid("bad_argument", f"{where} sets {_listed(extra)}, which a start profile does "
                      "not take: its keys are the arguments the reading server hands in")
    env = os.environ if environ is None else environ
    resolved = {key: _texts(value, base, state, env, where) for key, value in values.items()}
    return {key: _paths(value, base) if key in path_keys else value
            for key, value in resolved.items()}


def precedence(values: Mapping[str, object],
               given: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    """The call's arguments: the caller's `given` over the profile's `values`, and the names the
    profile supplied, sorted."""
    return {**values, **given}, sorted(set(values) - set(given))


@dataclass(frozen=True)
class Applied:
    """What a profile filled in one call, and the file it was read from."""

    name: str
    file: Path
    supplied: list[str]
    arguments: dict[str, object]

    def shown(self) -> dict[str, object]:
        """The reply's `profile` block."""
        return {"name": self.name, "file": str(self.file), "supplied": self.supplied}


def applied(profile: str, *, starting: Iterable[str | Path], keys: Collection[str],
            path_keys: Collection[str], given: Collection[str],
            arguments: Mapping[str, object], state: str = "",
            environ: Mapping[str, str] | None = None) -> Applied:
    """`arguments` with the profile `profile` names (or paths) filling only the names `given`
    does not carry; `keys` and `path_keys` are what the reading server hands in."""
    entry = Path(os.path.expanduser(profile)) if absolute(profile) else locate(starting, profile)
    values = read(entry, keys, path_keys, state=state, environ=environ)
    fill = {name: value for name, value in values.items() if name not in set(given)}
    call, _ = precedence(arguments, fill)
    return Applied(profile, entry, sorted(fill), call)


def demanded(arguments: Mapping[str, object], names: Iterable[str], *, tool: str) -> None:
    """Refuse the arguments of `names` a call leaves empty, naming them."""
    empty = [name for name in names if arguments.get(name) in ("", None)]
    if empty:
        raise Invalid("bad_argument", f"{tool} needs {_listed(empty)}: neither the call nor a "
                      f"profile gave it. Pass it, or name a {STORE}/start profile")


def entry_name(name: str) -> str:
    """The name a store entry is written and read under: a plain file stem, refused by name
    otherwise, as `file_names.word` spells it."""
    if (not name or "/" in name or "\\" in name or "\x00" in name or name in (".", "..")
            or name.endswith(".json")):
        raise Invalid("bad_argument", f"{name!r} is not an entry name: a plain file stem, with "
                      "no directory part and no extension, which the store adds")
    return file_names.word(name, "entry")


def file_name(kind: str, name: str) -> str:
    return f"{name}{SUFFIXES.get(kind, '.json')}"


def entry_of(path: Path, kind: str) -> str:
    suffix = SUFFIXES.get(kind, ".json")
    return path.name[:-len(suffix)] if path.name.endswith(suffix) else path.name


def _above(start: Path) -> Iterator[Path]:
    """`start` and its ancestors, up to the root the host has."""
    here = start
    while True:
        yield here
        parent = here.parent
        if parent == here:
            return
        here = parent


def _listed(paths: Iterable[str | Path]) -> str:
    return ", ".join(str(path) for path in paths)


def _base(entry: Path, where: str) -> Path:
    """The directory that holds the `.scry/` the entry lives in, or the refusal: a profile in no
    store has no base, and its own directory is never one."""
    parts = entry.parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == STORE:
            return Path(*parts[:i])
    raise Invalid("bad_argument", f"{where} is in no {STORE}/ directory, so its paths have no "
                  f"base: a profile lives in {STORE}/start/")


def _json(entry: Path, where: str) -> dict[str, object]:
    """The file as a JSON object, never past the cap and never as a bare exception."""
    try:
        with entry.open("rb") as handle:
            data = handle.read(PROFILE_BYTES_MAX + 1)
    except OSError as exc:
        raise Invalid("bad_argument", f"{where} could not be read: {exc}") from None
    if len(data) > PROFILE_BYTES_MAX:
        raise Invalid("bad_argument", f"{where} is past {PROFILE_BYTES_MAX} bytes, the most a "
                      "profile holds: a profile of start's arguments is a few hundred bytes, "
                      "and anything larger is data, which does not belong in one")
    try:
        raw = json.loads(data)
    except ValueError as exc:
        raise Invalid("bad_argument", f"{where} could not be read as JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise Invalid("bad_argument", f"{where} is a {type(raw).__name__}, not a JSON object of "
                      "start's arguments")
    return {str(key): value for key, value in raw.items()}


def _texts(value: object, base: Path, state: str, environ: Mapping[str, str],
           where: str) -> object:
    """`value` with every string's placeholders resolved, lists and objects walked."""
    if isinstance(value, str):
        return _text(value, base, state, environ, where)
    if isinstance(value, list):
        return [_texts(item, base, state, environ, where) for item in value]
    if isinstance(value, dict):
        return {key: _texts(item, base, state, environ, where) for key, item in value.items()}
    return value


def _text(text: str, base: Path, state: str, environ: Mapping[str, str], where: str) -> str:
    found = list(_PLACEHOLDER.finditer(text))
    if text.count("${") != len(found):
        raise Invalid("bad_argument", f"{where}: {text!r} opens a `${{` with no closing brace: "
                      "a placeholder is written `${name}`")

    def one(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "root":
            return str(base)
        if name == "home":
            return str(Path.home())
        if name == "state":
            if not state:
                raise Invalid("bad_argument", f"{where} uses `${{state}}`, the session's "
                              "scratch directory, and this read has none")
            return state
        if name.startswith("env:"):
            var = name[4:]
            if not var:
                raise Invalid("bad_argument", f"{where} uses `${{env:}}`, which names no variable")
            if var not in environ:
                raise Invalid("bad_argument", f"{where} uses `${{env:{var}}}`, and {var} is not "
                              "set in the server's environment")
            return environ[var]
        raise Invalid("bad_argument", f"{where} uses `${{{name}}}`, which is no placeholder: the "
                      "store resolves `${root}`, `${home}`, `${state}` and `${env:NAME}`")

    return _PLACEHOLDER.sub(one, text)


def _paths(value: object, base: Path) -> object:
    """`value`'s paths: a relative one resolves against the base, a list of them each, anything
    else as it came."""
    if isinstance(value, str):
        return value if absolute(value) else os.path.join(str(base), value)
    if isinstance(value, list):
        return [_paths(item, base) for item in value]
    if isinstance(value, dict):
        return {key: _paths(item, base) for key, item in value.items()}
    return value


def absolute(value: str) -> bool:
    """Whether `value` is a path of its own on either host, read as a string: a POSIX root, a
    Windows drive, a rooted or UNC path, or `~`, which a server's own path judge expands."""
    return value.startswith(("/", "\\", "~")) or _DRIVE.match(value) is not None
