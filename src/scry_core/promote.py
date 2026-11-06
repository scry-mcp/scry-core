"""The session's draft and the promotion that writes it into the repository's store.

A `start`, a map's `add` and a `perform_export` keep what they learned, keyed by (kind, name);
`promote(dry_run)` reviews those against the store and `promote(entries)` writes the ones chosen,
creating `.scry/` only then. A candidate is complete only with what the reader of its kind
accepts, and a name the store already holds is an update, shown as its diff. A path a candidate
declares is written as `project_store`'s own placeholders; one that would leave them is refused
(`tracked`).
"""

from __future__ import annotations

import copy
import json
import os
import posixpath
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Required, TypedDict

from scry_core import fresh, project_store, prose, recording, screen_map
from scry_core.reply_contract import Invalid, When

KINDS = project_store.KINDS
STORE = project_store.STORE
#: What each kind's file name adds to its entry's name: a map is named by its application.
SUFFIXES = {"maps": screen_map.SUFFIX}
#: A path key whose one string holds several paths, and the separator between them.
LISTS = {"rompath": ";"}
#: How each kind is written: the indentation and whether its keys are sorted, the way the
#: reader's own writer writes it, so a promotion and an explicit save produce the same bytes.
WRITERS = {"start": (2, True), "maps": (1, False), "perform": (2, False)}
#: The lists whose items are identified by their `name`, and the changes one diff shows: a map
#: of many screens would otherwise fill a reply. Every other list is compared by index, because
#: a `perform` document's steps are a program and their order is part of it.
NAMED = frozenset({"screens", "controls"})
CHANGES_SHOWN = 20

#: What a tool's description fills from here (`scry_core.docs.filled`), in the words both
#: servers say it.
DOC_VALUES = {
    "PROMOTE": (
        "What this session learned, written into the repository's store (`.scry/`) only when\n"
        "approved. `start` keeps the recipe it ran, a map's `add` keeps the map, a\n"
        "`perform_export` keeps the script; each is complete only with what its reader accepts\n"
        "(the arguments a recipe cannot boot without, a map the map reader parses, a script\n"
        "with a check), and a reply that keeps one says `kept N (promote to review)`. The\n"
        "identity is (kind, name): an entry a call loaded (`start(profile=)`,\n"
        "`screen_map_write` `load`, `perform(path=)`) names what is learned next, and a name\n"
        "the store already holds is an update. `dry_run=true` lists every candidate with its\n"
        "file, its size and whether it is new or an update, an update with its diff; `entries`\n"
        "(`<kind>/<name>`) writes only those, `names` renames one as it is written, and only\n"
        "that approved call creates `.scry/`. `root` names the repository the store is in or\n"
        "becomes; without it the nearest `.scry/` above this server's directory or the draft's\n"
        "paths is used, and a promotion that finds none is refused. Every path is written as a\n"
        "`project_store` placeholder; one that would leave them is refused, since a tracked\n"
        "file carries no path of this machine. Reply: `store`, `candidates` (a review), `written`\n"
        "and `draft` (an approval), `total_bytes`, `store_bytes`; `close` names what was left\n"
        "unkept. Refused: nothing kept (`needs_call`); an entry the draft does not hold; two\n"
        "entries written to one file; a candidate the caps cannot hold; an entry that is there\n"
        "and cannot be read as JSON."),
}


class PromoteFields(TypedDict, total=False):
    """What `promote` answers: the store, a review's candidates, an approval's writes, and what
    the draft still holds."""

    candidates: Annotated[list[Any], When("a review")]
    written: Annotated[list[Any], When("an approval")]
    draft: Annotated[list[str], When("an approval")]
    total_bytes: Annotated[int, When("a review")]
    store: Required[str]
    store_bytes: Required[int]


@dataclass(frozen=True)
class Candidate:
    """One thing a session learned: what it is, the pair it is keyed by, the document a
    promotion writes and which of that document's keys hold paths."""

    kind: str
    name: str
    document: dict[str, Any]
    path_keys: tuple[str, ...] = ()


@dataclass
class Drafts:
    """What the session kept, for the server's life: one candidate per (kind, name), and the
    name of the file each kind was last read from, which keys what that read learns."""

    kept: dict[tuple[str, str], Candidate] = field(default_factory=dict)
    loaded: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.kept)

    def loaded_entry(self, kind: str, name: str) -> None:
        """`kind` was read from the entry `name`: what the session learns of it is that entry."""
        if kind in KINDS and name:
            self.loaded[kind] = name

    def loaded_name(self, kind: str) -> str:
        """The entry `kind` was last read from, or "" when it was read from none."""
        return self.loaded.get(kind, "")

    def forget(self, kind: str) -> None:
        """`kind` is being learned from no entry now: what comes next names its own."""
        self.loaded.pop(kind, None)

    def keep(self, kind: str, name: str, document: dict[str, Any], *,
             needs: Collection[str] = (), path_keys: Collection[str] = ()) -> bool:
        """`document` as the candidate (kind, name), replacing an earlier one, and whether it
        entered; an incomplete act proposes nothing and leaves what was kept. `needs` names the
        keys a `start` recipe cannot do without."""
        if kind not in KINDS:
            raise Invalid("bad_argument", f"{kind!r} is not a kind: a store holds "
                          f"{', '.join(KINDS)}")
        project_store.entry_name(name)
        if not isinstance(document, dict):
            raise Invalid("bad_argument", f"the {kind} candidate {name!r} is a "
                          f"{type(document).__name__}, not a document")
        if not complete(kind, document, needs):
            return False
        self.kept[kind, name] = Candidate(kind, name, document, tuple(path_keys))
        return True

    def entries(self) -> list[str]:
        """The draft's entries, `<kind>/<name>`, sorted."""
        return sorted(f"{kind}/{name}" for kind, name in self.kept)


def complete(kind: str, document: Mapping[str, Any], needs: Collection[str]) -> bool:
    """Whether `document` is a candidate worth proposing: a recipe of what it cannot boot
    without, a map document with a screen, a script with a check."""
    if kind == "start":
        return document.get("format") == project_store.FORMAT and all(
            _carries(document.get(name)) for name in needs)
    if kind == "maps":
        screens = document.get("screens")
        return (document.get("format") == screen_map.FORMAT and isinstance(screens, list)
                and bool(screens))
    steps = document.get("steps")
    return isinstance(steps, list) and any(
        isinstance(step, dict) and step.get("recorded") for step in steps)


def unkept(drafts: Drafts) -> list[str]:
    """What `close` names: every entry the session left waiting for an approval."""
    return drafts.entries()


def kept_line(drafts: Drafts) -> str:
    """The one line a reply that kept a candidate says."""
    return f"kept {len(drafts)} (promote to review)"


def store(starting: Iterable[str | Path], root: str = "") -> Path:
    """The `.scry/` a promotion writes: `root` names the repository that holds it, else the
    nearest one above `starting`."""
    if root:
        base = Path(os.path.expanduser(root))
        if not base.is_absolute():
            raise Invalid("bad_argument", f"root={root!r} is not absolute: name the repository, "
                          "absolute or `~`-led")
        if base.name == STORE:
            raise Invalid("bad_argument", f"root={base} names the store itself, not the "
                          "repository that holds it")
        if not base.is_dir():
            raise Invalid("bad_argument", f"root={base} is not a directory")
    else:
        found = project_store.root(starting)
        if found is None:
            raise Invalid("bad_argument", f"no {STORE}/ above {_listed(starting)}: pass "
                          f"root=<the repository>, and an approved promotion creates it there")
        base = found
    store_dir = base / STORE
    if store_dir.exists() and not store_dir.is_dir():
        raise Invalid("bad_argument", f"{store_dir} is there and is not a directory: a store "
                      "is one, and a promotion does not write through a file")
    return store_dir


def promote(drafts: Drafts, *, dry_run: bool = False,
            entries: Sequence[str] | None = None, names: Mapping[str, str] | None = None,
            root: str = "", starting: Iterable[str | Path] = (), state: str = "",
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """One gesture: `dry_run` reviews every candidate, `entries` approves some."""
    if dry_run:
        if entries:
            raise Invalid("bad_argument", "dry_run reviews every candidate and entries approves "
                          "some: give one, not both")
        return review(drafts, starting=starting, root=root, state=state, environ=environ)
    if not entries:
        raise Invalid("bad_argument", "name the entries to write in `entries` "
                      "(`<kind>/<name>`), or review them with `dry_run=true`")
    return write(drafts, entries=entries, names=names, starting=starting, root=root,
                 state=state, environ=environ)


def review(drafts: Drafts, *, starting: Iterable[str | Path] = (), root: str = "",
           state: str = "", environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Every candidate as it would be written: its target, its size, and for an update what
    changes. Nothing is written and no directory is made."""
    store_dir = store(starting, root)
    if not drafts:
        raise Invalid("needs_call", "nothing is kept: a `start`, a map's `add` and a "
                      "`perform_export` keep what they learn, and a complete one is a recipe "
                      "of what it boots with, a map its reader parses or a script with a check")
    planned = [planned_entry(candidate, store_dir, state, environ)
               for _, candidate in sorted(drafts.kept.items())]
    _within(planned, store_dir)
    return {"store": str(store_dir), "candidates": [item for *_, item in planned],
            "total_bytes": sum(len(data) for _, _, data, _ in planned),
            "store_bytes": _store_bytes(store_dir, planned)}


def write(drafts: Drafts, *, entries: Sequence[str], names: Mapping[str, str] | None = None,
          starting: Iterable[str | Path] = (), root: str = "", state: str = "",
          environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The entries chosen, each written to its own file in the store, and what the draft still
    holds. Only this call creates `.scry/` and its kind directories."""
    store_dir = store(starting, root)
    unknown = sorted(set(names or {}) - set(entries))
    if unknown:
        raise Invalid("bad_argument", f"names names {_listed(unknown)}, which entries does not: "
                      "a name is given for an entry written by this call")
    chosen: list[tuple[str, Candidate]] = []
    for entry in entries:
        key = _split(entry)
        if any(named == entry for named, _ in chosen):
            raise Invalid("bad_argument", f"entry {entry!r} is named twice")
        candidate = drafts.kept.get(key)
        if candidate is None:
            raise Invalid("bad_argument", f"entry {entry!r} is not in the draft: it holds "
                          f"{', '.join(drafts.entries()) or 'nothing'}")
        chosen.append((entry, candidate))
    planned = [planned_entry(candidate, store_dir, state, environ, entry=entry,
                             name=(names or {}).get(entry, candidate.name))
               for entry, candidate in chosen]
    targets = [str(target) for _candidate, target, _data, _item in planned]
    repeated = sorted({target for target in targets if targets.count(target) > 1})
    if repeated:
        raise Invalid("bad_argument", f"{_listed(repeated)} would be written twice: `names` "
                      "leaves each entry in its own file")
    _within(planned, store_dir)
    written: list[tuple[Candidate, Path, bytes, dict[str, Any]]] = []
    for candidate, target, data, item in planned:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fresh.replace(target, data, "the store entry")
        except (OSError, Invalid) as exc:
            _dropped(drafts, written)
            raise Invalid("host_failed", f"{item['entry']} could not be written ({exc}); "
                          f"written before it: {_entries(written) or 'none'}") from None
        written.append((candidate, target, data, item))
    _dropped(drafts, written)
    return {"store": str(store_dir), "written": [item for *_, item in written],
            "draft": drafts.entries(), "store_bytes": _store_bytes(store_dir, [])}


def planned_entry(candidate: Candidate, store_dir: Path, state: str,
                  environ: Mapping[str, str] | None, *, entry: str = "",
                  name: str = "") -> tuple[Candidate, Path, bytes, dict[str, Any]]:
    """`candidate` as it would be written: its document with every path expressed for a tracked
    file, the bytes it makes, its target, and the reply's item. A map is judged by its own
    reader here, under the name it is written as."""
    named = name or candidate.name
    project_store.entry_name(named)
    document = tracked(candidate, store_dir.parent, state, environ)
    if candidate.kind == "maps":
        document["application"] = named
        screen_map.parse(document, f"the candidate {entry or f'{candidate.kind}/{named}'}")
    data = serialised(candidate.kind, document)
    target = store_dir / candidate.kind / file_name(candidate.kind, named)
    if target.is_symlink():
        raise Invalid("bad_argument", f"{target} is a link: a store entry is a file the "
                      "repository holds, and a promotion never replaces a link")
    if target.is_dir():
        raise Invalid("bad_argument", f"{target} is a directory: a store entry is a file")
    change = "update" if target.is_file() else "new"
    item: dict[str, Any] = {
        "entry": entry or f"{candidate.kind}/{candidate.name}", "kind": candidate.kind,
        "name": named, "file": f"{STORE}/{candidate.kind}/{file_name(candidate.kind, named)}",
        "bytes": len(data), "change": change}
    if change == "update":
        item["diff"] = difference(_existing(target), document)
    return candidate, target, data, item


def tracked(candidate: Candidate, base: Path, state: str = "",
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The candidate's document as a tracked file may hold it. A key `path_keys` names is
    resolved and must stay under the root, the home, the state or a variable; a `perform`
    document's `start` block the same, and its steps' absolute paths are rewritten where one of
    those covers them, since a step's argument is the tool's and only a path can be."""
    document = copy.deepcopy(candidate.document)
    env = os.environ if environ is None else environ
    if candidate.kind == "start":
        _rewrite(document, candidate.path_keys, base, state, env, candidate)
    elif candidate.kind == "perform":
        start = document.get("start")
        if isinstance(start, dict):
            _rewrite(start, candidate.path_keys, base, state, env, candidate)
        steps = document.get("steps")
        if isinstance(steps, list):
            document["steps"] = _steps(steps, base, state, env, candidate)
    return document


def file_name(kind: str, name: str) -> str:
    """The file an entry of `kind` named `name` is written to."""
    return f"{name}{SUFFIXES.get(kind, '.json')}"


def serialised(kind: str, document: Mapping[str, Any]) -> bytes:
    """`document` as its kind is written on disk."""
    indent, sorted_keys = WRITERS[kind]
    return (json.dumps(document, indent=indent, sort_keys=sorted_keys) + "\n").encode()


def difference(old: Any, new: Any) -> dict[str, Any]:
    """What an update changes: the paths it adds, removes and changes, with both values. A map's
    screens and its controls are changed whole by name, and a reordering of them is a change; a
    `perform` document's steps are compared by index, because their order is the program."""
    added: list[str] = []
    removed: list[str] = []
    changed: list[dict[str, Any]] = []
    _walk("", old, new, added, removed, changed)
    shown = {"added": added, "removed": removed, "changed": changed[:CHANGES_SHOWN]}
    if len(changed) > CHANGES_SHOWN:
        shown["changed_total"] = len(changed)
    return shown


def after_export(drafts: Drafts, reply: dict[str, Any],
                 path_keys: Collection[str]) -> dict[str, Any]:
    """The document an export wrote is a candidate, named by the entry this session replayed or
    by the file it wrote."""
    path = str(reply.get("path") or "")
    name = drafts.loaded_name("perform") or Path(path).stem
    document = recording.read_document(path)
    if drafts.keep("perform", name, document, path_keys=path_keys):
        return {**reply, "kept": kept_line(drafts)}
    return reply


def after_close(drafts: Drafts, reply: dict[str, Any]) -> dict[str, Any]:
    """`close` names what the session left waiting for an approval."""
    if draft := unkept(drafts):
        reply["draft"] = draft
    return reply


def promote_line(args: Mapping[str, Any], reply: Mapping[str, Any]) -> str:
    """`promote`'s summary line: what a review lists, or what an approval wrote."""
    if "written" in reply:
        return (f"promote: {prose.counted(len(reply['written']), 'entry', 'entries')} written "
                f"to {reply['store']}, "
                f"{prose.counted(len(reply['draft']), 'entry', 'entries')} still kept")
    return f"promote: {prose.counted(len(reply['candidates']), 'candidate')} in {reply['store']}"


def _walk(path: str, old: Any, new: Any, added: list[str], removed: list[str],
          changed: list[dict[str, Any]]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        removed.extend(_join(path, key) for key in sorted(old.keys() - new.keys()))
        added.extend(_join(path, key) for key in sorted(new.keys() - old.keys()))
        for key in sorted(old.keys() & new.keys()):
            _walk(_join(path, key), old[key], new[key], added, removed, changed)
        return
    if isinstance(old, list) and isinstance(new, list):
        if _key(path) in NAMED and _named(old) and _named(new):
            before = {item["name"]: item for item in old}
            after = {item["name"]: item for item in new}
            removed.extend(_join(path, name) for name in sorted(before.keys() - after.keys()))
            added.extend(_join(path, name) for name in sorted(after.keys() - before.keys()))
            for name in sorted(before.keys() & after.keys()):
                if before[name] != after[name]:
                    changed.append({"path": _join(path, name), "was": before[name],
                                    "now": after[name]})
            order_old = [item["name"] for item in old]
            order_new = [item["name"] for item in new]
            if order_old != order_new and sorted(order_old) == sorted(order_new):
                changed.append({"path": f"{path}[order]", "was": order_old, "now": order_new})
            return
        if all(isinstance(item, dict) for item in (*old, *new)):
            for i in range(min(len(old), len(new))):
                _walk(f"{path}[{i}]", old[i], new[i], added, removed, changed)
            added.extend(f"{path}[{i}]" for i in range(len(old), len(new)))
            removed.extend(f"{path}[{i}]" for i in range(len(new), len(old)))
            return
        if old != new:
            changed.append({"path": path, "was": old, "now": new})
        return
    if old != new:
        changed.append({"path": path, "was": old, "now": new})


def _named(items: list[Any]) -> bool:
    """Whether `items` is a list of objects each named: the unit a diff changes whole."""
    names = [item.get("name") for item in items if isinstance(item, dict)]
    if len(names) != len(items) or not all(isinstance(name, str) and name for name in names):
        return False
    return len(set(names)) == len(names)


def _rewrite(document: dict[str, Any], keys: Collection[str], base: Path, state: str,
             environ: Mapping[str, str], candidate: Candidate) -> None:
    for key in keys:
        if key in document:
            where = f"the candidate {candidate.kind}/{candidate.name}'s `{key}`"
            document[key] = _placeholders(document[key], base, state, environ, where,
                                          LISTS.get(key, ""), step=False)


def _steps(value: Any, base: Path, state: str, environ: Mapping[str, str],
           candidate: Candidate) -> Any:
    """`value` with every absolute path one of the store's placeholders covers written as it,
    which is what a step's argument can be rewritten without guessing what it means."""
    where = f"the candidate perform/{candidate.name}'s steps"
    if isinstance(value, str):
        return _one(value, base, state, environ, where, step=True)
    if isinstance(value, list):
        return [_steps(item, base, state, environ, candidate) for item in value]
    if isinstance(value, dict):
        return {key: _steps(item, base, state, environ, candidate)
                for key, item in value.items()}
    return value


def _placeholders(value: Any, base: Path, state: str, environ: Mapping[str, str], where: str,
                  separator: str, *, step: bool) -> Any:
    if isinstance(value, str):
        parts = value.split(separator) if separator else [value]
        return separator.join(_one(part, base, state, environ, where, step=step)
                              for part in parts)
    if isinstance(value, list):
        return [_placeholders(item, base, state, environ, where, separator, step=step)
                for item in value]
    if isinstance(value, dict):
        return {key: _placeholders(item, base, state, environ, where, separator, step=step)
                for key, item in value.items()}
    raise Invalid("bad_argument", f"{where} is a {type(value).__name__}, not a path or a table "
                  "of them")


def _one(part: str, base: Path, state: str, environ: Mapping[str, str], where: str, *,
         step: bool) -> str:
    """`part` as a placeholder path: a declared key's value must resolve under the root, the
    home, the state or a variable, and a step's absolute path is rewritten when one covers it."""
    normal = _slashed(part.strip())
    if not normal:
        return part
    if normal.startswith("~"):
        if normal == "~":
            return "${home}"
        if normal.startswith("~/"):
            return "${home}" + normal[1:]
        if "/" in normal:
            if step:
                return part
            raise Invalid("bad_argument", f"{where} names {part!r}, a `~user` path this store "
                          "cannot express: write `${home}` or a path inside the repository")
        return part             # a file whose name begins with a tilde, which is relative
    if project_store.absolute(normal):
        target = _norm(normal)
    elif step:
        return part             # a step's argument that is no path to begin with
    else:
        target = _norm(_slashed(str(base)).rstrip("/") + "/" + normal)
    for placeholder, value in _options(base, state):
        if _under(target, value):
            return placeholder + target[len(value):]
    for var in sorted(environ, key=lambda name: (-len(environ[name]), name)):
        if _under(target, environ[var]):
            return f"${{env:{var}}}" + target[len(_norm(_slashed(environ[var]))):]
    if step:
        return part
    raise Invalid("bad_argument", f"{where} names {part!r}, which is not under the repository "
                  f"({base}), the home, the session's state or a variable of the server's "
                  "environment: a tracked file carries no path of this machine")


def _options(base: Path, state: str) -> list[tuple[str, str]]:
    options = [("${root}", _norm(_slashed(str(base)))),
               ("${home}", _norm(_slashed(str(Path.home()))))]
    if state:
        options.append(("${state}", _norm(_slashed(state))))
    return sorted(options, key=lambda option: -len(option[1]))


def _under(target: str, value: str) -> bool:
    base = _norm(_slashed(value))
    return bool(base) and (target == base or target.startswith(base.rstrip("/") + "/"))


def _norm(text: str) -> str:
    return posixpath.normpath(text)


def _slashed(text: str) -> str:
    """`text` with this host's separator as `/`; on a POSIX host a backslash is a name's own."""
    return text.replace(os.sep, "/") if os.sep != "/" else text


def _within(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
            store_dir: Path) -> None:
    """Refuse a promotion the store's caps cannot hold, naming the entries that would exceed."""
    for candidate, _target, data, item in planned:
        if candidate.kind == "start" and len(data) > project_store.PROFILE_BYTES_MAX:
            raise Invalid("bad_argument", f"{item['entry']} is {len(data)} bytes, past the "
                          f"{project_store.PROFILE_BYTES_MAX} a start profile holds: a profile "
                          "is start's arguments, and anything larger is data")
    by_kind: dict[str, set[str]] = {}
    for _candidate, _target, _data, item in planned:
        by_kind.setdefault(str(item["kind"]), set()).add(str(item["name"]))
    for kind, names in sorted(by_kind.items()):
        present = {_stem(path, kind) for path in (store_dir / kind).glob("*.json")}
        if len(present | names) > project_store.ENTRIES_MAX:
            raise Invalid("bad_argument", f"{STORE}/{kind}/ would hold "
                          f"{len(present | names)} entries after {_entries(planned, kind)}, "
                          f"past the {project_store.ENTRIES_MAX} a kind directory holds")
    total = _store_bytes(store_dir, planned)
    if total > project_store.STORE_BYTES_MAX:
        raise Invalid("bad_argument", f"{_entries(planned)} would leave {store_dir} at {total} "
                      f"bytes, past the {project_store.STORE_BYTES_MAX} a store holds: promote "
                      "what belongs to the program, not what a run produced")


def _store_bytes(store_dir: Path, planned: Sequence[tuple[Candidate, Path, bytes,
                                                          dict[str, Any]]]) -> int:
    """The store's bytes with `planned` written: every file it holds now, minus what each
    promotion replaces, plus what it writes."""
    targets = {target for _candidate, target, _data, _item in planned}
    kept = sum(path.stat().st_size for path in store_dir.rglob("*")
               if path.is_file() and path not in targets)
    return kept + sum(len(data) for _candidate, _target, data, _item in planned)


def _entries(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
             kind: str = "") -> str:
    return ", ".join(str(item["entry"]) for _candidate, _target, _data, item in planned
                     if not kind or item["kind"] == kind)


def _dropped(drafts: Drafts,
             written: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]]) -> None:
    """The draft entries whose file landed: a promotion is done for them and for none other."""
    for candidate, _target, _data, _item in written:
        drafts.kept.pop((candidate.kind, candidate.name), None)


def _existing(target: Path) -> Any:
    """The entry an update replaces, as JSON, or the refusal: an entry this promotion cannot
    diff is one it does not overwrite."""
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Invalid("bad_argument", f"{target} is there and could not be read as JSON "
                      f"({exc}): the promotion does not overwrite an entry it cannot diff; "
                      "fix or remove it") from None


def _split(entry: str) -> tuple[str, str]:
    kind, sep, name = entry.partition("/")
    if not sep or kind not in KINDS:
        raise Invalid("bad_argument", f"entry={entry!r} is `<kind>/<name>`, a kind of "
                      f"{', '.join(KINDS)}")
    project_store.entry_name(name)
    return kind, name


def _stem(path: Path, kind: str) -> str:
    """The entry name a file of `kind` holds."""
    suffix = SUFFIXES.get(kind, ".json")
    return path.name[:-len(suffix)] if path.name.endswith(suffix) else path.name


def _key(path: str) -> str:
    """The document key a diff path ends in, its indices cut."""
    return path.rsplit(".", 1)[-1].split("[", 1)[0]


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _listed(values: Iterable[Any]) -> str:
    return ", ".join(str(value) for value in values) or "this process's directory"


def _carries(value: Any) -> bool:
    return value not in ("", None) and value != []
