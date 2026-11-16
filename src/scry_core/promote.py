"""The session's draft and the promotion that writes it into the repository's store.

A `start`, a map's `add` and a `perform_export` keep what they learned, keyed by (project, kind,
name): each entry belongs, from the moment it is kept, to one project, and this module alone
decides which store it may be written to. `promote(dry_run)` reviews those against the store and
`promote(entries)` writes the ones chosen, creating `.scry/` only then, and with the server's
name also its `about.json` and README. Without `root` an entry is written only into its own
project's store, and one whose project has none is refused by name. A candidate is complete only
with what the reader of its kind accepts, and a name the store already holds is an update, shown
as its diff. A path a candidate declares is written as `project_store`'s own placeholders; a
review lists apart one that would leave them, and an approval refuses it (`tracked`).
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Required

from typing_extensions import TypedDict

from scry_core import (
    fresh,
    given,
    project_store,
    promote_paths,
    prose,
    recording,
    screen_map,
    scry_readme,
)
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
        "with a check), and a reply that keeps one says `kept N (promote to review)`, naming\n"
        "each repository of the draft with no store and the `root` it takes. An entry belongs\n"
        "to the repository it was learned in: the one whose store a call loaded it from, else\n"
        "the current `start`'s, its profile's or where its program runs, where the server can\n"
        "tell. The identity is\n"
        "(repository, kind, name): an entry a call loaded (`start(profile=)`,\n"
        "`screen_map_write` `load`, `perform(path=)`) names what is learned next, and a name\n"
        "the store already holds is an update, which keeps the keys a run owns as the\n"
        "store has them, and one that changes nothing is named in `unchanged`, not offered.\n"
        "`dry_run=true` lists every other candidate with its\n"
        "file, its size and whether it is new or an update, an update with its diff; `entries`\n"
        "(`<kind>/<name>`, the kind one of `start`, `maps`, `perform`) writes only those,\n"
        "`names` renames one as it is written, and only\n"
        "that approved call creates `.scry/`, and with the server's name also `about.json` and\n"
        "the rendered `README.md`; `dry_run`\n"
        "names those in `would_create`, the approval in `created`. Without `root` each entry\n"
        "goes only to its own repository's store, one store a call, and one whose repository\n"
        "has none is unwritable; `root` names the repository whose store a call writes every\n"
        "entry to, a candidate from another saying `from`. Every path is\n"
        "written as a `project_store` placeholder, since a tracked file carries no path of this\n"
        "machine; an approval of an entry a review calls unwritable is refused. Reply: `store`,\n"
        "`candidates` and `unchanged` (a review), `unwritable`, each entry with its reason\n"
        "(a review holding an entry it cannot write), `written` and `draft` (an approval),\n"
        "`would_create` and `created` (the store, `about.json`, `README.md` not yet there),\n"
        "`total_bytes`,\n"
        "`store_bytes`; `close` names what was left unkept, which stays in the draft until the\n"
        "server ends. Refused: nothing kept (`needs_call`); an entry the draft does not hold;\n"
        "without `root`, a call none of whose entries has a store, or entries of two stores; a\n"
        "name two repositories hold, unless `root` is one of them; two entries written to one\n"
        "file; a kind or a store past its cap."),
}


class PromoteFields(TypedDict, total=False):
    """What `promote` answers: the store, a review's candidates, an approval's writes, and what
    the draft still holds."""

    candidates: Annotated[list[Any], When("a review")]
    unchanged: Annotated[list[str], When("a review")]
    unwritable: Annotated[list[Any], When("a review holding an entry it cannot write")]
    written: Annotated[list[Any], When("an approval")]
    would_create: Annotated[list[str], When("a review", "not yet there")]
    created: Annotated[list[str], When("an approval", "not yet there")]
    draft: Annotated[list[str], When("an approval")]
    total_bytes: Annotated[int, When("a review")]
    store: Required[str]
    store_bytes: Required[int]


@dataclass(frozen=True)
class Candidate:
    """One thing a session learned: what it is, the pair it is keyed by, the document a
    promotion writes, which of that document's keys hold paths, and the project it belongs to
    ("" when nothing the session read says which)."""

    kind: str
    name: str
    document: dict[str, Any]
    path_keys: tuple[str, ...] = ()
    own: tuple[str, ...] = ()
    project: str = ""

    @property
    def entry(self) -> str:
        return f"{self.kind}/{self.name}"

    @property
    def key(self) -> tuple[str, str, str]:
        return self.project, self.kind, self.name


def _spelled(name: str) -> str:
    """`name` as `keep` spells it, so a stem written before the rule is still the entry read;
    one the rule cannot spell is kept as given, and `keep` refuses it."""
    try:
        return project_store.entry_name(name)
    except Invalid:
        return name


@dataclass
class Drafts:
    """What the session kept, for the server's life: one candidate per (project, kind, name);
    the entry each kind was last read from and the file it was read in, which keys what that read
    learns; and the project the session's current `start` runs in, which whatever is kept with no
    store file of its own belongs to."""

    kept: dict[tuple[str, str, str], Candidate] = field(default_factory=dict)
    loaded: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    started_in: str = ""

    def __len__(self) -> int:
        return len(self.kept)

    @contextmanager
    def starting(self, *, profile: str = "", anchor: str = "",
                 live: Callable[[], object] = lambda: None) -> Iterator[None]:
        """A `start` runs: `profile` names the store file it read, `anchor` where the server says
        its program lives, `live` the server's live session. What is kept from here on belongs to
        the profile's project, else the anchor's, and a script the last session replayed no
        longer names what is learned. A start that raises leaving no session of its own live
        leaves the draft as it was."""
        before, session = (dict(self.loaded), dict(self.sources), self.started_in), live()
        if profile:
            self.loaded_entry("start", project_store.entry_of(Path(profile), "start"),
                              source=profile)
        else:
            self.forget("start")
        self.forget("perform")
        self.started_in = project_store.project(profile if _in_store(profile) else anchor)
        try:
            yield
        except BaseException:
            if live() in (None, session):
                self.loaded, self.sources, self.started_in = before
            raise

    def loaded_entry(self, kind: str, name: str, source: str = "") -> None:
        """`kind` was read from the entry `name`, in the file `source`: what the session learns
        of it is that entry."""
        if kind in KINDS and name:
            self.loaded[kind] = _spelled(name)
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
        """`document` as the candidate (kind, name) of its project, replacing an earlier one
        there, and whether it entered; an incomplete act proposes nothing and leaves what was
        kept. `needs` names the keys a `start` recipe cannot do without; `own` the keys the run
        owns, which a candidate leaves out and an update therefore keeps as the store holds
        them."""
        if kind not in KINDS:
            raise Invalid("bad_argument", f"{kind!r} is not a kind: a store holds "
                          f"{', '.join(KINDS)}")
        name = project_store.entry_name(name)
        if not isinstance(document, dict):
            raise Invalid("bad_argument", f"the {kind} candidate {name!r} is a "
                          f"{type(document).__name__}, not a document")
        if not complete(kind, document, needs):
            return False
        held = Candidate(kind, name, document, tuple(path_keys), tuple(own),
                         self.project_of(kind, name))
        self.kept[held.key] = held
        return True

    def project_of(self, kind: str, name: str) -> str:
        """The project an entry kept now belongs to: the one whose store the session read it
        from, when it updates that entry, else the one the current `start` runs in."""
        source = self.sources.get(kind, "") if self.loaded.get(kind) == name else ""
        return project_store.project(source) if _in_store(source) else self.started_in

    def held(self, kind: str, name: str) -> list[Candidate]:
        """The candidates (kind, name) the draft holds, one per project that kept it."""
        return [candidate for _key, candidate in sorted(self.kept.items())
                if (candidate.kind, candidate.name) == (kind, name)]

    def entries(self) -> list[str]:
        """The draft's entries, `<kind>/<name>`, sorted; a name two projects hold is listed
        twice."""
        return sorted(candidate.entry for candidate in self.kept.values())


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


def unkept(drafts: Drafts, state: str = "") -> list[str]:
    """What `close` names: the entries left waiting for an approval, less any its own project's
    store already holds as it is. One with no store to compare, or one that cannot be reviewed,
    is named: the session has already closed, and this must not cost the reply."""
    left = []
    for candidate in drafts.kept.values():
        try:
            store_dir = own_store(candidate.project)
            same = store_dir is not None and _unchanged(
                planned_entry(candidate, store_dir, state, None)[3])
        except (Invalid, OSError):
            same = False
        if not same:
            left.append(candidate.entry)
    return sorted(left)


def only_the_run(names: frozenset[str] | None, run_own: frozenset[str]) -> bool:
    """Whether the caller gave `start` nothing but `run_own`; names it cannot tell: never."""
    return names is not None and names <= run_own


def keep_start(drafts: Drafts, params: Mapping[str, Any], *, guest: str,
               defaults: Mapping[str, Any], run_own: frozenset[str], needs: Collection[str],
               path_keys: Collection[str]) -> bool:
    """A start's recipe as a candidate, named by the profile it read, else by `guest`: what the
    call set away from `defaults`, outside `run_own`. A loaded profile run again with only
    `run_own` changed keeps nothing."""
    loaded = drafts.loaded_name("start")
    if not (name := loaded or guest):
        return False
    if loaded and only_the_run(given.names(), run_own):
        return False
    document: dict[str, Any] = {"format": project_store.FORMAT}
    document.update({key: value for key, value in params.items()
                     if key in defaults and key not in run_own and value != defaults[key]})
    return drafts.keep("start", name, document, needs=needs, path_keys=path_keys,
                       own=sorted(run_own))


def after_map(drafts: Drafts, maps: screen_map.Maps, method: str, reply: dict[str, Any], *,
              guest: str) -> dict[str, Any]:
    """`screen_map_write`'s reply: a `load` names the entry this session read, and an `add`
    keeps the map, named by that entry, else by `guest`."""
    if method == "load":
        drafts.loaded_entry("maps", str(reply.get("application", "")),
                            source=str(reply.get("path", "")))
    application = maps.session_application or guest
    if method != "add" or not application:
        return reply
    if drafts.keep("maps", application, maps.document(application)):
        return {**reply, "kept": kept_line(drafts)}
    return reply


def kept_line(drafts: Drafts) -> str:
    """The one line a reply that kept a candidate says, and for each project of the draft with no
    store, its entries and the `root` that would give them one."""
    homeless: dict[str, list[str]] = {}
    for candidate in drafts.kept.values():
        if not _has_store(candidate.project):
            homeless.setdefault(candidate.project, []).append(candidate.entry)
    said = [f"kept {len(drafts)} (promote to review)"]
    said += [f"{', '.join(sorted(entries))}: {_storeless(project)}: promote(dry_run=true, "
             f"root={project or '<the repository>'}) lists what an approval would create"
             for project, entries in sorted(homeless.items())]
    return "; ".join(said)


def store(root: str) -> Path:
    """The `.scry/` of the repository `root` names, which a promotion naming it writes into."""
    base = Path(os.path.expanduser(root))
    if not base.is_absolute():
        raise Invalid("bad_argument", f"root={root!r} is not absolute: name the repository, "
                      "absolute or `~`-led")
    if base.resolve().name == STORE:
        raise Invalid("bad_argument", f"root={base} names the store itself, not the "
                      "repository that holds it")
    if not base.is_dir():
        raise Invalid("bad_argument", f"root={base} is not a directory")
    return _checked(base / STORE)


def own_store(project: str) -> Path | None:
    """The store an entry of `project` is written to without `root`: the project's own `.scry/`,
    or None when it holds none. Never another project's."""
    if not project:
        return None
    store_dir = _checked(Path(project) / STORE)
    return store_dir if store_dir.is_dir() else None


def _checked(store_dir: Path) -> Path:
    if store_dir.is_symlink():
        raise Invalid("bad_argument", f"{store_dir} is a link: a store is the repository's own, "
                      "and its caps cannot see through one")
    if store_dir.exists() and not store_dir.is_dir():
        raise Invalid("bad_argument", f"{store_dir} is there and is not a directory: a store "
                      "is one, and a promotion does not write through a file")
    return store_dir


def promote(drafts: Drafts, *, dry_run: bool = False,
            entries: Sequence[str] | None = None, names: Mapping[str, str] | None = None,
            root: str = "", state: str = "", environ: Mapping[str, str] | None = None,
            server: str = "") -> dict[str, Any]:
    """One gesture: `dry_run` reviews every candidate, `entries` approves some. `server`, the
    name of the server that promotes, sets up the store's `about.json` and README too; with
    none, entries are all a promotion touches."""
    if dry_run:
        if entries:
            raise Invalid("bad_argument", "dry_run reviews every candidate and entries approves "
                          "some: give one, not both")
        return review(drafts, root=root, state=state, environ=environ, server=server)
    if not entries:
        raise Invalid("bad_argument", "name the entries to write in `entries` "
                      "(`<kind>/<name>`), or review them with `dry_run=true`")
    return write(drafts, entries=entries, names=names, root=root, state=state, environ=environ,
                 server=server)


def review(drafts: Drafts, *, root: str = "", state: str = "",
           environ: Mapping[str, str] | None = None, server: str = "") -> dict[str, Any]:
    """Each candidate that would change the store as it would be written: its target, its size,
    and for an update what changes; the others are named, and so is what an approval would
    create beside them. Nothing is written or made."""
    named = store(root) if root else None
    if not drafts:
        raise Invalid("needs_call", "nothing is kept: a `start`, a map's `add` and a "
                      "`perform_export` keep what they learn, and a complete one is a recipe "
                      "of what it boots with, a map its reader parses or a script with a check")
    every = sorted(drafts.kept.values(), key=lambda held: (held.entry, held.project))
    chosen, unwritable = _one_per_name(every, named)
    store_dir, placed = _placed(chosen, named, unwritable)
    planned = []
    for candidate in placed:
        try:
            planned.append(planned_entry(candidate, store_dir, state, environ))
        except Invalid as exc:
            unwritable.append({"entry": candidate.entry, "reason": str(exc)})
    changed = [entry for entry in planned if not _unchanged(entry[3])]
    setup = _setup(planned, store_dir, server)
    extra = _setup_files(store_dir, setup)
    _within(planned, store_dir, extra)
    reply: dict[str, Any] = {
        "store": str(store_dir), "candidates": [item for *_, item in changed],
        "unchanged": [str(item["entry"]) for *_, item in planned if _unchanged(item)],
        "total_bytes": sum(len(data) for _, _, data, _ in changed),
        "store_bytes": _store_bytes(store_dir, planned, extra)}
    if unwritable:
        reply["unwritable"] = sorted(unwritable, key=lambda item: str(item["entry"]))
    if setup and setup.created:
        reply["would_create"] = list(setup.created)
    return reply


def write(drafts: Drafts, *, entries: Sequence[str], names: Mapping[str, str] | None = None,
          root: str = "", state: str = "", environ: Mapping[str, str] | None = None,
          server: str = "") -> dict[str, Any]:
    """The entries chosen, each written to its own file in the store, then the store's
    `about.json` and README, and what the draft still holds. Only this call creates `.scry/`
    and its kind directories."""
    named = store(root) if root else None
    unknown = sorted(set(names or {}) - set(entries))
    if unknown:
        raise Invalid("bad_argument", f"names names {_listed(unknown)}, which entries does not: "
                      "a name is given for an entry written by this call")
    chosen: list[tuple[str, Candidate]] = []
    for entry in entries:
        kind, name = _split(entry)
        if any(given == entry for given, _ in chosen):
            raise Invalid("bad_argument", f"entry {entry!r} is named twice")
        held = drafts.held(kind, name)
        if not held:
            raise Invalid("bad_argument", f"entry {entry!r} is not in the draft: it holds "
                          f"{', '.join(drafts.entries()) or 'nothing'}")
        candidate, why = _one_of(held, named)
        if candidate is None:
            raise Invalid("bad_argument", f"entry {entry!r} is {why}")
        chosen.append((entry, candidate))
    apart: list[dict[str, Any]] = []
    store_dir, _ = _placed([candidate for _entry, candidate in chosen], named, apart)
    if apart:
        raise Invalid("bad_argument", "; ".join(f"{item['entry']} cannot be written: "
                                                f"{item['reason']}" for item in apart))
    planned = [planned_entry(candidate, store_dir, state, environ, entry=entry,
                             name=(names or {}).get(entry, candidate.name))
               for entry, candidate in chosen]
    targets = [str(target).casefold() for _candidate, target, _data, _item in planned]
    repeated = sorted({target for target in targets if targets.count(target) > 1})
    if repeated:
        raise Invalid("bad_argument", f"{_listed(repeated)} would be written twice: `names` "
                      "leaves each entry in its own file")
    setup = _setup(planned, store_dir, server)
    extra = _setup_files(store_dir, setup)
    _within(planned, store_dir, extra)
    written: list[tuple[Candidate, Path, bytes, dict[str, Any]]] = []
    done: list[str] = []
    jobs: list[tuple[str, Path, bytes, tuple[Candidate, Path, bytes, dict[str, Any]] | None]] = [
        (str(each[3]["entry"]), each[1], each[2], each) for each in planned]
    jobs += [(path.name, path, text, None) for path, text in extra]
    for label, target, data, job in jobs:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            fresh.replace(target, data, "the store file")
        except (OSError, Invalid) as exc:
            _dropped(drafts, written)
            raise Invalid("host_failed", f"{label} could not be written ({exc}); "
                          f"written before it: {', '.join(done) or 'none'}") from None
        done.append(label)
        if job is not None:
            written.append(job)
    _dropped(drafts, written)
    reply = {"store": str(store_dir), "written": [item for *_, item in written],
             "draft": drafts.entries(), "store_bytes": _store_bytes(store_dir, [])}
    if setup and setup.created:
        reply["created"] = list(setup.created)
    return reply


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
    if candidate.project and not _same(candidate.project, store_dir.parent):
        item["from"] = candidate.project
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


def after_close(drafts: Drafts, reply: dict[str, Any], *, state: str = "") -> dict[str, Any]:
    """`close` names what the session left waiting for an approval."""
    if draft := unkept(drafts, state):
        reply["draft"] = draft
    return reply


def promote_line(args: Mapping[str, Any], reply: Mapping[str, Any]) -> str:
    """`promote`'s summary line: what a review lists, or what an approval wrote."""
    if "written" in reply:
        line = (f"promote: {prose.counted(len(reply['written']), 'entry', 'entries')} written "
                f"to {reply['store']}, "
                f"{prose.counted(len(reply['draft']), 'entry', 'entries')} still kept")
        return f"{line}; created {', '.join(reply['created'])}" if reply.get("created") else line
    line = f"promote: {prose.counted(len(reply['candidates']), 'candidate')} in {reply['store']}"
    if unwritable := reply.get("unwritable"):
        line += f", {prose.counted(len(unwritable), 'entry', 'entries')} cannot be written"
    if would := reply.get("would_create"):
        line += f"; would create {', '.join(would)}"
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


def _setup(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
           store_dir: Path, server: str) -> scry_readme.Setup | None:
    """What the store gets beside `planned`: its `about.json` and README, or None when no server
    asked for them or nothing is planned."""
    if not server or not planned:
        return None
    files = {f"{item['kind']}/{project_store.file_name(str(item['kind']), str(item['name']))}":
             json.loads(data) for _candidate, _target, data, item in planned}
    try:
        return scry_readme.scaffold(store_dir.parent, server, files)
    except scry_readme.Refused as exc:
        raise Invalid("bad_argument", f"{exc}: a promotion renders the store's README from "
                      "its about.json, so fix or remove it") from None


def _setup_files(store_dir: Path, setup: scry_readme.Setup | None) -> list[tuple[Path, bytes]]:
    """The files `setup` writes, in the order it writes them."""
    if setup is None:
        return []
    return [*([(store_dir / scry_readme.ABOUT, setup.about)] if setup.about is not None else []),
            (store_dir / scry_readme.README, setup.page)]


def _within(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
            store_dir: Path, extra: Sequence[tuple[Path, bytes]] = ()) -> None:
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
    total = _store_bytes(store_dir, planned, extra)
    if total > project_store.STORE_BYTES_MAX:
        raise Invalid("bad_argument", f"{_entries(planned)} would leave {store_dir} at {total} "
                      f"bytes, past the {project_store.STORE_BYTES_MAX} a store holds: promote "
                      "what belongs to the program, not what a run produced")


def _store_bytes(store_dir: Path, planned: Sequence[tuple[Candidate, Path, bytes,
                                                          dict[str, Any]]],
                 extra: Sequence[tuple[Path, bytes]] = ()) -> int:
    """The store's bytes with `planned` and `extra` written: every file it holds now, minus
    what each promotion replaces, plus what it writes."""
    targets = {target for _candidate, target, _data, _item in planned} | {
        path for path, _data in extra}
    kept = sum(path.stat().st_size for path in store_dir.rglob("*")
               if path.is_file() and path not in targets)
    return (kept + sum(len(data) for _candidate, _target, data, _item in planned)
            + sum(len(data) for _path, data in extra))


def _entries(planned: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]],
             kind: str = "") -> str:
    return ", ".join(str(item["entry"]) for _candidate, _target, _data, item in planned
                     if not kind or item["kind"] == kind)


def _dropped(drafts: Drafts,
             written: Sequence[tuple[Candidate, Path, bytes, dict[str, Any]]]) -> None:
    """The draft entries whose file landed: a promotion is done for them and for none other."""
    for candidate, _target, _data, _item in written:
        drafts.kept.pop(candidate.key, None)


def _placed(candidates: Sequence[Candidate], named: Path | None,
            apart: list[dict[str, Any]]) -> tuple[Path, list[Candidate]]:
    """The one store a call writes and what goes there, the rest added to `apart` with the
    reason. With `named` (a `root`'s store) every candidate goes there. Without it each goes to
    its own project's store, and only one store is written: entries of two are refused, naming
    both."""
    if named is not None:
        return named, list(candidates)
    stores: dict[Path, list[Candidate]] = {}
    for candidate in candidates:
        try:
            own = own_store(candidate.project)
        except (Invalid, OSError) as exc:
            apart.append({"entry": candidate.entry, "reason": str(exc)})
            continue
        if own is None:
            apart.append({"entry": candidate.entry, "reason": (
                f"{_storeless(candidate.project)}: pass root="
                f"{candidate.project or '<the repository>'}, and an approved promotion creates "
                f"its {STORE}/ there")})
        else:
            stores.setdefault(own, []).append(candidate)
    if len(stores) > 1:
        raise Invalid("bad_argument", "; ".join(
            f"{', '.join(one.entry for one in held)} go to {own}" for own, held in stores.items())
            + ": a promotion writes one store, so review one with its repository in `root`, or "
            "approve one store's entries in `entries`")
    if not stores:
        raise Invalid("bad_argument", "no store to write into without `root`: " + "; ".join(
            f"{item['entry']}: {item['reason']}" for item in apart))
    [(own, held)] = stores.items()
    return own, held


def _one_per_name(candidates: Sequence[Candidate], named: Path | None
                  ) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """`candidates` with each name once, as `_one_of` chooses it, the rest set apart."""
    placed: list[Candidate] = []
    apart: list[dict[str, Any]] = []
    for candidate in candidates:
        chosen, why = _one_of([one for one in candidates if one.entry == candidate.entry], named)
        if chosen is candidate:
            placed.append(candidate)
        else:
            apart.append({"entry": candidate.entry, "reason": why or (
                f"the one kept in {candidate.project or 'no repository'}: "
                f"{named.parent if named else ''} holds its own {candidate.entry}, which this "
                "call writes")})
    return placed, apart


def _one_of(held: Sequence[Candidate], named: Path | None) -> tuple[Candidate | None, str]:
    """Which of `held`, the candidates of one name, a call writes: the only one, or the one of
    `named`'s repository; else none, and why."""
    if len(held) == 1:
        return held[0], ""
    ours = [one for one in held if named is not None and _same(one.project, named.parent)]
    if len(ours) == 1:
        return ours[0], ""
    return None, (f"kept in {_listed(_repositories(held))}: name the one to write with its "
                  "repository in `root`")


def _repositories(candidates: Iterable[Candidate]) -> list[str]:
    return [candidate.project or "no repository" for candidate in candidates]


def _same(project: str, base: Path) -> bool:
    """Whether `project` is the directory `base`, by its spelling or by what the host says."""
    return bool(project) and (os.path.normpath(project) == os.path.normpath(base)
                              or promote_paths.same_on_host(project, str(base)))


def _has_store(project: str) -> bool:
    """Whether `project` holds the store `own_store` writes to; one it cannot judge answers yes,
    so a reply that kept a candidate never claims what it could not read."""
    try:
        return own_store(project) is not None
    except (Invalid, OSError):
        return True


def _in_store(path: str) -> bool:
    """Whether the file `path` lies in a store, the one place a file says whose an entry is."""
    return bool(path) and STORE in Path(path).parts


def _storeless(project: str) -> str:
    """Why an entry of `project` has no store to be written to without `root`."""
    if not project:
        return "nothing this session read names its repository"
    return f"no {STORE}/ in {project}, the repository it was kept in"


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
    return ", ".join(str(value) for value in values)


def _carries(value: Any) -> bool:
    return value not in ("", None) and value != []
