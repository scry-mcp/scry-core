"""The session's draft and the promotion that writes it into the repository's store.

A `start`, a map's `add` and a `perform_export` keep what they learned, keyed by (kind, name);
`promote(dry_run)` reviews those against the store and `promote(entries)` writes the ones chosen,
creating `.scry/` only then. A candidate is complete only with what the reader of its kind
accepts, and a name the store already holds is an update, shown as its diff. A path a candidate
declares is written as `project_store`'s own placeholders; a review lists apart one that would
leave them, and an approval refuses it (`tracked`).
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Required

from typing_extensions import TypedDict

from scry_core import fresh, project_store, promote_paths, prose, recording, screen_map
from scry_core.promote_diff import difference
from scry_core.promote_paths import LISTS, Places
from scry_core.reply_contract import Invalid, When

KINDS = project_store.KINDS
STORE = project_store.STORE
#: How each kind is written: the indentation and whether its keys are sorted, the way the
#: reader's own writer writes it, so a promotion and an explicit save produce the same bytes.
WRITERS = {"start": (2, True), "maps": (1, False), "perform": (2, False)}

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
        "the store already holds is an update, which keeps the keys a run owns as the\n"
        "store has them, and one that changes nothing is named in `unchanged`, not offered.\n"
        "`dry_run=true` lists every other candidate with its\n"
        "file, its size and whether it is new or an update, an update with its diff; `entries`\n"
        "(`<kind>/<name>`, the kind one of `start`, `maps`, `perform`) writes only those,\n"
        "`names` renames one as it is written, and only\n"
        "that approved call creates `.scry/`. `root` names the repository the store is in or\n"
        "becomes; without it the first `.scry/` found walking up from the file a loaded recipe\n"
        "came from, the draft's paths, then this server's directory, is used, and a promotion\n"
        "that finds none is refused. Every path is\n"
        "written as a `project_store` placeholder, since a tracked file carries no path of this\n"
        "machine; an approval of an entry a review calls unwritable is refused. Reply: `store`,\n"
        "`candidates` and `unchanged` (a review), `unwritable`, each entry with its reason\n"
        "(a review holding an entry it cannot write), `written` and `draft` (an approval),\n"
        "`total_bytes`,\n"
        "`store_bytes`; `close` names what was left unkept, which stays in the draft until the\n"
        "server ends. Refused: nothing kept (`needs_call`); an entry the draft does not hold; two\n"
        "entries written to one file; a kind or a store past its cap."),
}


class PromoteFields(TypedDict, total=False):
    """What `promote` answers: the store, a review's candidates, an approval's writes, and what
    the draft still holds."""

    candidates: Annotated[list[Any], When("a review")]
    unchanged: Annotated[list[str], When("a review")]
    unwritable: Annotated[list[Any], When("a review holding an entry it cannot write")]
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
    own: tuple[str, ...] = ()


@dataclass
class Drafts:
    """What the session kept, for the server's life: one candidate per (kind, name), and the
    name of the file each kind was last read from, which keys what that read learns, and where
    that file is, which says whose store it belongs to."""

    kept: dict[tuple[str, str], Candidate] = field(default_factory=dict)
    loaded: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.kept)

    def loaded_entry(self, kind: str, name: str, source: str = "") -> None:
        """`kind` was read from the entry `name`, in the file `source`: what the session learns
        of it is that entry."""
        if kind in KINDS and name:
            self.loaded[kind] = name
            self.sources[kind] = source

    def loaded_name(self, kind: str) -> str:
        """The entry `kind` was last read from, or "" when it was read from none."""
        return self.loaded.get(kind, "")

    def forget(self, kind: str) -> None:
        """`kind` is being learned from no entry now: what comes next names its own."""
        self.loaded.pop(kind, None)
        self.sources.pop(kind, None)

    def keep(self, kind: str, name: str, document: dict[str, Any], *,
             needs: Collection[str] = (), path_keys: Collection[str] = (),
             own: Collection[str] = ()) -> bool:
        """`document` as the candidate (kind, name), replacing an earlier one, and whether it
        entered; an incomplete act proposes nothing and leaves what was kept. `needs` names the
        keys a `start` recipe cannot do without; `own` the keys the run owns, which a candidate
        leaves out and an update therefore keeps as the store holds them."""
        if kind not in KINDS:
            raise Invalid("bad_argument", f"{kind!r} is not a kind: a store holds "
                          f"{', '.join(KINDS)}")
        name = project_store.entry_name(name)
        if not isinstance(document, dict):
            raise Invalid("bad_argument", f"the {kind} candidate {name!r} is a "
                          f"{type(document).__name__}, not a document")
        if not complete(kind, document, needs):
            return False
        self.kept[kind, name] = Candidate(kind, name, document, tuple(path_keys), tuple(own))
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


def unkept(drafts: Drafts, starting: Callable[[], Iterable[str | Path]],
           state: str = "") -> list[str]:
    """What `close` names: the entries left waiting for an approval, less any the store already
    holds as they are. With no store to compare, or one that cannot be reviewed, all of them:
    the session has already closed, and this must not cost the reply."""
    if not drafts:
        return []
    try:
        same = review(drafts, starting=starting(), state=state)["unchanged"]
    except (Invalid, OSError):
        same = []
    return [entry for entry in drafts.entries() if entry not in same]


def only_the_run(names: frozenset[str] | None, run_own: frozenset[str]) -> bool:
    """Whether the caller gave `start` nothing but `run_own`; names it cannot tell: never."""
    return names is not None and names <= run_own


def starting(drafts: Drafts, paths: Callable[[Mapping[str, Any]], Iterable[str]]) -> list[str]:
    """Where the store is looked for: the files this session loaded, the paths `paths` reads from
    each recipe the draft holds, then this process's directory."""
    starts = [source for source in drafts.sources.values() if source]
    for candidate in drafts.kept.values():
        block = (candidate.document if candidate.kind == "start"
                 else candidate.document.get("start"))
        if candidate.kind != "maps" and isinstance(block, Mapping):
            starts += [os.path.expanduser(part.strip()) for part in paths(block)
                       if project_store.absolute(part.strip())]
    return [*starts, os.getcwd()]


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
    if store_dir.is_symlink():
        raise Invalid("bad_argument", f"{store_dir} is a link: a store is the repository's own, "
                      "and its caps cannot see through one")
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
    """Each candidate that would change the store as it would be written: its target, its size,
    and for an update what changes; the others are named. Nothing is written or made."""
    store_dir = store(starting, root)
    if not drafts:
        raise Invalid("needs_call", "nothing is kept: a `start`, a map's `add` and a "
                      "`perform_export` keep what they learn, and a complete one is a recipe "
                      "of what it boots with, a map its reader parses or a script with a check")
    planned = []
    unwritable = []
    for (kind, name), candidate in sorted(drafts.kept.items()):
        try:
            planned.append(planned_entry(candidate, store_dir, state, environ))
        except Invalid as exc:
            unwritable.append({"entry": f"{kind}/{name}", "reason": str(exc)})
    _within(planned, store_dir)
    changed = [entry for entry in planned if not _unchanged(entry[3])]
    reply: dict[str, Any] = {
        "store": str(store_dir), "candidates": [item for *_, item in changed],
        "unchanged": [str(item["entry"]) for *_, item in planned if _unchanged(item)],
        "total_bytes": sum(len(data) for _, _, data, _ in changed),
        "store_bytes": _store_bytes(store_dir, planned)}
    if unwritable:
        reply["unwritable"] = unwritable
    return reply


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
    targets = [str(target).casefold() for _candidate, target, _data, _item in planned]
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
    named = project_store.entry_name(name or candidate.name)
    document = tracked(candidate, store_dir.parent, state, environ)
    if candidate.kind == "maps":
        document["application"] = named
        screen_map.parse(document, f"the candidate {entry or f'{candidate.kind}/{named}'}")
    target = store_dir / candidate.kind / project_store.file_name(candidate.kind, named)
    if target.is_symlink():
        raise Invalid("bad_argument", f"{target} is a link: a store entry is a file the "
                      "repository holds, and a promotion never replaces a link")
    if target.is_dir():
        raise Invalid("bad_argument", f"{target} is a directory: a store entry is a file")
    change = "update" if target.is_file() else "new"
    old = _existing(target) if change == "update" else None
    if isinstance(old, dict):
        _keep_spelling(candidate, document, old, store_dir.parent, state, environ)
        document.update({key: old[key] for key in candidate.own
                         if key in old and key not in document})
    data = serialised(candidate.kind, document)
    shown = entry or f"{candidate.kind}/{candidate.name}"
    if candidate.kind == "start" and len(data) > project_store.PROFILE_BYTES_MAX:
        raise Invalid("bad_argument", f"{shown} is {len(data)} bytes, past the "
                      f"{project_store.PROFILE_BYTES_MAX} a start profile holds: a profile "
                      "is start's arguments, and anything larger is data")
    item: dict[str, Any] = {
        "entry": shown, "kind": candidate.kind,
        "name": named,
        "file": f"{STORE}/{candidate.kind}/{project_store.file_name(candidate.kind, named)}",
        "bytes": len(data), "change": change}
    if change == "update":
        item["diff"] = difference(old, document)
    return candidate, target, data, item


def tracked(candidate: Candidate, base: Path, state: str = "",
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The candidate's document as a tracked file may hold it. A key `path_keys` names is
    resolved and must stay under the root, the home, the state or a variable; a `perform`
    document's `start` block the same, and its steps' absolute paths are rewritten where one of
    those covers them, since a step's argument is the tool's and only a path can be."""
    document = copy.deepcopy(candidate.document)
    places = _places(base, state, environ)
    if candidate.kind == "start":
        _rewrite(document, candidate, places)
    elif candidate.kind == "perform":
        start = document.get("start")
        if isinstance(start, dict):
            _rewrite(start, candidate, places)
        steps = document.get("steps")
        if isinstance(steps, list):
            document["steps"] = promote_paths.steps(
                steps, places, f"the candidate perform/{candidate.name}'s steps")
    return document


def serialised(kind: str, document: Mapping[str, Any]) -> bytes:
    """`document` as its kind is written on disk."""
    indent, sorted_keys = WRITERS[kind]
    return (json.dumps(document, indent=indent, sort_keys=sorted_keys) + "\n").encode()


def after_export(drafts: Drafts, reply: dict[str, Any],
                 path_keys: Collection[str]) -> dict[str, Any]:
    """The document an export wrote is a candidate, named by the entry this session replayed or
    by the file it wrote."""
    path = str(reply.get("path") or "")
    name = drafts.loaded_name("perform") or Path(path).stem
    document = recording.read_document(path)
    try:
        kept = drafts.keep("perform", name, document, path_keys=path_keys)
    except Invalid:             # a file whose name is no entry's is written and not proposed
        kept = False
    return {**reply, "kept": kept_line(drafts)} if kept else reply


def after_close(drafts: Drafts, reply: dict[str, Any], *,
                starting: Callable[[], Iterable[str | Path]], state: str = "") -> dict[str, Any]:
    """`close` names what the session left waiting for an approval."""
    if draft := unkept(drafts, starting, state):
        reply["draft"] = draft
    return reply


def promote_line(args: Mapping[str, Any], reply: Mapping[str, Any]) -> str:
    """`promote`'s summary line: what a review lists, or what an approval wrote."""
    if "written" in reply:
        return (f"promote: {prose.counted(len(reply['written']), 'entry', 'entries')} written "
                f"to {reply['store']}, "
                f"{prose.counted(len(reply['draft']), 'entry', 'entries')} still kept")
    line = f"promote: {prose.counted(len(reply['candidates']), 'candidate')} in {reply['store']}"
    if unwritable := reply.get("unwritable"):
        line += f", {prose.counted(len(unwritable), 'entry', 'entries')} cannot be written"
    return line


def _relative(value: Any, separator: str) -> bool:
    """Whether a stored value is relative spellings only: an absolute one is this machine's."""
    parts = value.split(separator) if separator and isinstance(value, str) else [value]
    return all(isinstance(part, str) and not project_store.absolute(part.strip())
               for part in parts)


def _places(base: Path, state: str, environ: Mapping[str, str] | None) -> Places:
    return Places(base, state, os.environ if environ is None else environ)


def _rewrite(document: dict[str, Any], candidate: Candidate, places: Places) -> None:
    for key in candidate.path_keys:
        if key in document:
            where = f"the candidate {candidate.kind}/{candidate.name}'s `{key}`"
            document[key] = promote_paths.placeholders(document[key], places, where,
                                                       LISTS.get(key, ""))


def _keep_spelling(candidate: Candidate, document: dict[str, Any], old: dict[str, Any],
                   base: Path, state: str, environ: Mapping[str, str] | None) -> None:
    """Leave as the store has it each path that resolves to what `document` now says: an
    equivalent spelling is the author's, and neither a change nor something to rewrite."""
    places = _places(base, state, environ)
    new: Any = document
    held: Any = old
    if candidate.kind == "perform":
        new, held = document.get("start"), old.get("start")
    if candidate.kind == "maps" or not isinstance(new, dict) or not isinstance(held, dict):
        return
    for key in set(candidate.path_keys) & new.keys() & held.keys():
        if not _relative(held[key], LISTS.get(key, "")):
            continue
        try:
            resolved = promote_paths.placeholders(held[key], places, f"the stored `{key}`",
                                                  LISTS.get(key, ""))
        except Invalid:
            continue
        if resolved == new[key]:
            new[key] = held[key]


def _unchanged(item: Mapping[str, Any]) -> bool:
    """An update whose document equals the entry it replaces: nothing was learned."""
    diff = item.get("diff")
    return item["change"] == "update" and isinstance(diff, dict) and not any(
        diff.get(key) for key in ("added", "removed", "changed"))


def _within(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
            store_dir: Path) -> None:
    """Refuse a promotion the store's caps cannot hold, naming the entries that would exceed."""
    by_kind: dict[str, set[str]] = {}
    for _candidate, _target, _data, item in planned:
        by_kind.setdefault(str(item["kind"]), set()).add(str(item["name"]))
    for kind, names in sorted(by_kind.items()):
        if (store_dir / kind).is_symlink():
            raise Invalid("bad_argument", f"{store_dir / kind} is a link: a kind directory is "
                          "the repository's own, and the store's caps cannot see through one")
        present = {project_store.entry_of(path, kind)
                   for path in (store_dir / kind).glob("*.json")}
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
    return kind, project_store.entry_name(name)


def _listed(values: Iterable[Any]) -> str:
    return ", ".join(str(value) for value in values) or "this process's directory"


def _carries(value: Any) -> bool:
    return value not in ("", None) and value != []
