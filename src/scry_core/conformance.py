"""The contracts a server runs against its own tools: subclass `SessionContract` (`start`,
`window`, `status`, `close`), `PromoteContract` (what a `start` keeps and `promote` writes) or
`KnowledgeContract` (what its dictionaries owe) in a test file and provide the `subject` fixture.
The rules are those every server's replies are held to, so a server that passes them answers a
caller as the others do."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

import pytest

from scry_core import session_block
from scry_core import window as w
from scry_core.knowledge import Base, Lock, SourceIndex, Support, check
from scry_core.project_store import STORE
from scry_core.window_stand_ins import hosts

Reply = dict[str, Any]


class Subject(Protocol):
    """A server on a booted fake, with no emulator behind it. `shows_fullscreen` is whether its
    emulator can show a full-screen window on this host; a server that cannot refuses it by name.
    `takes_fullscreen` is whether its `start` has the argument at all."""

    shows_fullscreen: bool
    takes_fullscreen: bool

    def start(self, **arguments: Any) -> Reply:
        """`start(shared, display, fullscreen, background)`; the fake's window opens as asked."""
        ...

    def window(self, front: bool = False) -> Reply: ...

    def close(self) -> Reply:
        """With no session: `status` ok, `closed` False, `ended_by` "none", the note and summary of
        `session_block`."""
        ...

    def status(self) -> Reply:
        """With no session: `status` ok, `session.alive` False, no `system`, the summary of
        `session_block`."""
        ...

    def asked(self) -> tuple[int, w.WindowRequest] | None:
        """The pid and window request of the live session, None without a window or a session."""
        ...

    def has_session(self) -> bool: ...


def _on(monkeypatch: pytest.MonkeyPatch, host: hosts.Obeying) -> None:
    monkeypatch.setattr(w, "host", lambda _platform="": host)


def _needs_fullscreen(subject: Subject) -> None:
    if not subject.takes_fullscreen:
        pytest.skip("this server's `start` has no `fullscreen` argument")


class SessionContract:
    @pytest.fixture(autouse=True)
    def _desk(self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> Any:
        monkeypatch.setattr(w, "WAIT_S", 0.0)
        _on(monkeypatch, hosts.Obeying(subject.asked))
        yield
        subject.close()

    @pytest.mark.parametrize("asked", [{}, {"display": 1}, {"fullscreen": False}])
    def test_a_watched_start_proves_the_window_on_the_asked_display(
            self, subject: Subject, asked: dict[str, Any]) -> None:
        if "fullscreen" in asked:
            _needs_fullscreen(subject)
        got = subject.start(shared=True, **asked)
        assert got["status"] == "ok", got
        window = got["window"]
        assert window["display"] == asked.get("display", 0) and window["onscreen"] is True, window
        assert window["fullscreen"] is bool(asked.get("fullscreen")), window

    def test_a_full_screen_start_fills_the_asked_display_or_is_refused_by_name(
            self, subject: Subject) -> None:
        _needs_fullscreen(subject)
        got = subject.start(shared=True, display=1, fullscreen=True)
        if subject.shows_fullscreen:
            assert got["status"] == "ok", got
            assert got["window"]["display"] == 1 and got["window"]["fullscreen"] is True, got
        else:
            assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
            assert "fullscreen" in got["message"] and not subject.has_session(), got

    def test_a_window_that_appears_late_is_proved_within_the_bound(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(w, "WAIT_S", 5.0)
        monkeypatch.setattr(w, "POLL_S", 0.001)
        _on(monkeypatch, hosts.Late(subject.asked, after=3))
        got = subject.start(shared=True)
        assert got["status"] == "ok" and got["window"]["onscreen"] is True, got

    def test_window_reads_the_main_window_when_the_pid_lists_a_small_one_first(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        _on(monkeypatch, hosts.WithAuxiliary(subject.asked))
        subject.start(shared=True, display=1)
        got = subject.window()
        wanted = subject.asked()
        assert wanted is not None
        assert got["window"]["bounds"]["width"] == (wanted[1].size or hosts.SIZE)[0], got
        assert got["window"]["display"] == 1, got

    def test_an_unwatched_start_opens_no_window_and_window_is_no_channel(
            self, subject: Subject) -> None:
        got = subject.start()
        assert got["status"] == "ok" and "window" not in got, got
        refused = subject.window()
        assert refused["status"] == "INVALID" and refused["code"] == "no_channel", refused
        assert "shared=true" in refused["message"], refused

    @pytest.mark.parametrize("asked", [{"display": 0}, {"fullscreen": True},
                                       {"display": 1, "fullscreen": False}])
    def test_the_window_arguments_without_shared_are_refused_not_ignored(
            self, subject: Subject, asked: dict[str, Any]) -> None:
        if "fullscreen" in asked:
            _needs_fullscreen(subject)
        got = subject.start(**asked)
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
        assert "shared=true" in got["message"], got

    def test_a_display_past_the_host_s_count_is_refused_naming_the_count(
            self, subject: Subject) -> None:
        got = subject.start(shared=True, display=5)
        assert got["status"] == "INVALID" and got["code"] == "bad_argument", got
        assert "2 displays (0 to 1)" in got["message"], got
        assert not subject.has_session()

    def test_window_with_no_session_is_no_session(self, subject: Subject) -> None:
        got = subject.window()
        assert got["status"] == "INVALID" and got["code"] == "no_session", got

    def test_close_with_no_session_says_so_and_changes_nothing(self, subject: Subject) -> None:
        got = subject.close()
        assert got["status"] == "ok" and got["closed"] is False and got["ended_by"] == "none", got
        assert got["note"] == session_block.NO_SESSION_CLOSE_NOTE, got
        assert got["summary"] == session_block.NO_SESSION_CLOSE, got
        assert not subject.has_session()

    def test_status_with_a_session_says_it_is_alive(self, subject: Subject) -> None:
        subject.start()
        got = subject.status()
        assert got["status"] == "ok" and got["session"]["alive"] is True, got

    def test_status_with_no_session_says_so(self, subject: Subject) -> None:
        got = subject.status()
        assert got["status"] == "ok" and got["summary"] == session_block.NO_SESSION_STATUS, got
        assert got["session"]["alive"] is False and "system" not in got, got

    def test_a_window_the_emulator_never_opened_refuses_the_start_and_leaves_the_session_to_close(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        _on(monkeypatch, hosts.Absent(subject.asked))
        got = subject.start(shared=True)
        assert got["status"] == "INVALID" and got["code"] == "window_not_visible", got
        assert subject.has_session(), "the caller closes it, as the message says"

    def test_window_answers_where_the_window_is_and_with_front_brings_it_forward(
            self, subject: Subject) -> None:
        subject.start(shared=True, display=1)
        got = subject.window()
        assert got["status"] == "ok" and got["window"]["display"] == 1, got
        forward = subject.window(front=True)
        assert forward["status"] == "ok" and forward["window"]["front"] is True, forward

    def test_window_answers_a_window_the_owner_dragged_to_another_display(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        subject.start(shared=True, display=0)
        _on(monkeypatch, hosts.Dragged(subject.asked))
        got = subject.window()
        assert got["status"] == "ok" and got["window"]["display"] == 1, got

    def test_window_front_activates_a_covered_window_and_without_front_only_reports_it(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        covered = hosts.Covered(subject.asked)
        _on(monkeypatch, covered)
        subject.start(shared=True, display=1)
        covered.activations = 0
        seen = subject.window()
        assert seen["window"]["onscreen"] is False and covered.activations == 0, seen
        forward = subject.window(front=True)
        assert forward["window"]["onscreen"] is True and covered.activations == 1, forward

    def test_window_front_on_a_background_session_names_the_background_launch(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        _on(monkeypatch, hosts.Stuck(subject.asked))
        subject.start(shared=True, background=True)
        got = subject.window(front=True)
        assert got["status"] == "INVALID" and got["code"] == "window_not_visible", got
        assert "background=true" in got["message"] and "background=false" in got["message"], got

    def test_window_front_on_a_foreground_session_never_blames_the_background(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        """THE CONTROL: the same stuck window, a session that was not launched behind."""
        _on(monkeypatch, hosts.Stuck(subject.asked))
        subject.start(shared=True, background=False)
        got = subject.window(front=True)
        assert got["code"] == "window_not_visible" and "background" not in got["message"], got

    def test_a_fullscreen_that_does_not_fill_the_display_is_refused_not_reported(
            self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> None:
        if not subject.shows_fullscreen:
            pytest.skip("this emulator refuses full screen here: the rule above is its proof")
        _on(monkeypatch, hosts.Bordered(subject.asked))
        got = subject.start(shared=True, fullscreen=True)
        assert got["status"] == "INVALID" and got["code"] == "window_not_visible", got
        assert got["seen"]["fullscreen"] is False and "fullscreen" in got["message"], got


class Promoter(Protocol):
    """A server's promotion over a launch that runs no emulator, with an empty draft: what its
    `start` keeps, and its `promote` and `close` tools."""

    def start(self, project: Path, name: str) -> Reply:
        """`start` of the program `name` whose files sit in `project`, as a session working there
        calls it. A server that tells a program's project only by the profile it read starts
        from one it writes into the project's store, when there is one, with an argument the
        profile lacks so the recipe is kept. The reply carries `kept`."""
        ...

    def promote(self, **arguments: Any) -> Reply: ...

    def close(self) -> Reply: ...


class Places:
    """Under the home, as on a machine: a store's repository (`game`), a repository with none
    (`bare`), a second store's (`other`), and the server's own directory, which holds a store
    too: the documented install runs every server in its own clone."""

    def __init__(self, base: Path) -> None:
        self.game, self.bare, self.other, self.server = (
            base / "game", base / "bare", base / "other", base / "server")
        for store in (self.game, self.other, self.server):
            (store / STORE).mkdir(parents=True)
        (self.bare / ".git").mkdir(parents=True)

    def stored(self, place: Path) -> dict[str, bytes]:
        """The entries `place`'s store holds, `<kind>/<file>` to its bytes."""
        store = place / STORE
        return {path.relative_to(store).as_posix(): path.read_bytes()
                for path in sorted(store.rglob("*")) if path.is_file() and path.parent != store}


class PromoteContract:
    """Without `root` an entry is written only into its own project's store: one whose project
    has none is refused by name and told to pass `root`, and the server's own directory never
    lends its store."""

    @pytest.fixture
    def places(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Places:
        for home in ("HOME", "USERPROFILE"):
            monkeypatch.setenv(home, str(tmp_path))
        places = Places(tmp_path)
        monkeypatch.chdir(places.server)
        return places

    @pytest.fixture(autouse=True)
    def _closed(self, subject: Promoter) -> Any:
        yield
        subject.close()

    def test_without_root_an_entry_is_never_written_outside_its_own_project_s_store(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.game, "alpha")
        _started(subject, places.bare, "beta")
        review = subject.promote(dry_run=True)
        assert review["status"] == "ok" and review["store"] == str(places.game / STORE), review
        assert [c["entry"] for c in review["candidates"]] == ["start/alpha"], review
        assert [(u["entry"], "root=" in u["reason"]) for u in review["unwritable"]] == [
            ("start/beta", True)], review
        before = places.stored(places.game)
        refused = subject.promote(entries=["start/alpha", "start/beta"])
        assert refused["status"] == "INVALID" and "start/beta" in refused["message"], refused
        assert places.stored(places.game) == before, "a refused approval wrote"
        assert subject.promote(entries=["start/alpha"])["status"] == "ok"
        after = places.stored(places.game)
        assert list(after) == ["start/alpha.json"] and after != before, after
        assert not (places.bare / STORE).exists() and places.stored(places.server) == {}

    def test_the_kept_line_names_an_entry_with_no_store_and_the_root_it_takes(
            self, subject: Promoter, places: Places) -> None:
        assert "root=" not in _started(subject, places.game, "alpha")
        kept = _started(subject, places.bare, "beta")
        assert "start/beta" in kept and "root=" in kept, kept

    def test_the_server_s_own_directory_never_lends_its_store(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.bare, "beta")
        refused = subject.promote(entries=["start/beta"])
        assert refused["status"] == "INVALID" and "root=" in refused["message"], refused
        assert places.stored(places.server) == {}

    def test_with_root_an_entry_is_written_into_that_repository_s_store(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.bare, "beta")
        written = subject.promote(entries=["start/beta"], root=str(places.bare))
        assert written["status"] == "ok" and written["created"], written
        assert list(places.stored(places.bare)) == ["start/beta.json"]

    def test_entries_of_two_stores_are_written_each_into_its_own_one_call_at_a_time(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.game, "alpha")
        _started(subject, places.other, "gamma")
        before = places.stored(places.game), places.stored(places.other)
        both = subject.promote(entries=["start/alpha", "start/gamma"])
        assert both["status"] == "INVALID", both
        assert (places.stored(places.game), places.stored(places.other)) == before
        for entry in ("start/alpha", "start/gamma"):
            assert subject.promote(entries=[entry])["status"] == "ok"
        after = places.stored(places.game), places.stored(places.other)
        assert [list(each) for each in after] == [["start/alpha.json"], ["start/gamma.json"]]
        assert after[0] != before[0] and after[1] != before[1], after

    def test_a_name_two_projects_hold_is_written_only_where_root_names(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.game, "dos")
        _started(subject, places.other, "dos")
        before = places.stored(places.game), places.stored(places.other)
        refused = subject.promote(entries=["start/dos"])
        assert refused["status"] == "INVALID" and "root" in refused["message"], refused
        assert (places.stored(places.game), places.stored(places.other)) == before
        assert subject.promote(entries=["start/dos"], root=str(places.game))["status"] == "ok"
        assert places.stored(places.game) != before[0]
        assert places.stored(places.other) == before[1]

    def test_close_names_what_the_session_left_waiting(
            self, subject: Promoter, places: Places) -> None:
        _started(subject, places.bare, "beta")
        assert subject.close().get("draft") == ["start/beta"]


def _started(subject: Promoter, project: Path, name: str) -> str:
    """`start` of `name` in `project`, then `close`, and the `kept` line the start gave."""
    got = subject.start(project, name)
    assert got["status"] == "ok" and "kept" in got, got
    subject.close()
    return str(got["kept"])


class KnowledgeSubject(Protocol):
    """A server's knowledge base: what it declares, its loaded dictionaries (`fts5=False` forces
    the index of our own), the committed index of the sources they cite, the committed lock of its
    checked entries, and the scopes its code depends on (the keys of its cpu tables, the cpus its
    demos run)."""

    def support(self) -> Support: ...

    def base(self, fts5: bool | None = None) -> Base: ...

    def sources(self) -> SourceIndex: ...

    def lock(self) -> Lock: ...

    def code_scopes(self) -> Iterable[str]: ...


def _none(faults: list[str]) -> None:
    assert not faults, "\n".join(faults)


class KnowledgeContract:
    """What a server's dictionaries owe, one case per rule, each naming the file to write or the
    entry to fix. A checked entry's text is held by its digest: it fails when the text changes
    without a new check."""

    def test_the_check_examined_something(self, subject: KnowledgeSubject) -> None:
        base, support = subject.base(), subject.support()
        assert support.scopes, "INVALID: no dictionary was examined: nothing here says what " \
            "this server supports"
        assert len(base) and base.dictionaries, "INVALID: the server's base holds no entry"
        assert subject.sources().rows, "INVALID: the source index holds no row, so no entry " \
            "was held to a source"

    def test_the_declaration_is_well_formed(self, subject: KnowledgeSubject) -> None:
        _none(subject.support().faults())

    def test_every_declared_scope_device_and_chip_has_the_dictionaries_it_owes(
            self, subject: KnowledgeSubject) -> None:
        _none(check.owed_dictionaries(subject.base(), subject.support()))

    def test_every_dictionary_is_of_a_declared_scope_and_the_code_names_no_other(
            self, subject: KnowledgeSubject) -> None:
        _none(check.undeclared(subject.base(), subject.support(), subject.code_scopes()))

    def test_every_dictionary_file_parses(self, subject: KnowledgeSubject) -> None:
        _none(subject.base().file_faults)

    def test_every_entry_is_whole_and_ids_are_unique(self, subject: KnowledgeSubject) -> None:
        base = subject.base()
        _none([*base.entry_faults, *base.load_faults])

    def test_every_entry_agrees_with_the_source_index(self, subject: KnowledgeSubject) -> None:
        _none(check.against_sources(subject.base(), subject.sources()))

    def test_every_key_of_the_list_a_dictionary_covers_is_named_or_left_out(
            self, subject: KnowledgeSubject) -> None:
        _none(check.covered(subject.base(), subject.sources()))

    def test_every_relation_resolves(self, subject: KnowledgeSubject) -> None:
        _none(check.relations(subject.base()))

    def test_two_sources_agree_or_the_entry_says_how_they_differ(
            self, subject: KnowledgeSubject) -> None:
        _none(check.both_sources(subject.base(), subject.sources()))

    def test_no_alias_is_another_entry_s_name(self, subject: KnowledgeSubject) -> None:
        _none(check.names_unique(subject.base()))

    def test_the_database_holds_what_the_files_hold(self, subject: KnowledgeSubject) -> None:
        _none(check.held(subject.base()))

    def test_the_fallback_answers_as_fts5_does(self, subject: KnowledgeSubject) -> None:
        if not subject.base().uses_fts5:
            pytest.skip("this host's SQLite has no FTS5, so the fallback is the only path")
        _none(check.fallback_differs(subject.base))

    def test_a_checked_entry_is_never_reworded(self, subject: KnowledgeSubject) -> None:
        _none(check.reworded(subject.base()))

    def test_every_checked_entry_is_locked_and_stays_as_it_was_locked(
            self, subject: KnowledgeSubject) -> None:
        _none(check.locked(subject.base(), subject.lock()))

