"""The window contract a server runs against its own `start` and `window`: subclass
`WindowContract` in a test file and provide the `subject` fixture. The rules are those every
server's replies are held to, so a server that passes them answers a caller as the others do."""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from scry_core import window as w
from scry_core.window_stand_ins import hosts

Reply = dict[str, Any]


class Subject(Protocol):
    """A server on a booted fake, with no emulator behind it. `shows_fullscreen` is whether its
    emulator can show a full-screen window on this host; a server that cannot refuses it by name."""

    shows_fullscreen: bool

    def start(self, **arguments: Any) -> Reply:
        """`start(shared, display, fullscreen, background)`; the fake's window opens as asked."""
        ...

    def window(self, front: bool = False) -> Reply: ...

    def close(self) -> None: ...

    def asked(self) -> tuple[int, w.WindowRequest] | None:
        """The pid and window request of the live session, None without a window or a session."""
        ...

    def has_session(self) -> bool: ...


def _on(monkeypatch: pytest.MonkeyPatch, host: hosts.Obeying) -> None:
    monkeypatch.setattr(w, "host", lambda _platform="": host)


class WindowContract:
    @pytest.fixture(autouse=True)
    def _desk(self, subject: Subject, monkeypatch: pytest.MonkeyPatch) -> Any:
        monkeypatch.setattr(w, "WAIT_S", 0.0)
        _on(monkeypatch, hosts.Obeying(subject.asked))
        yield
        subject.close()

    @pytest.mark.parametrize("asked", [{}, {"display": 1}, {"fullscreen": False}])
    def test_a_watched_start_proves_the_window_on_the_asked_display(
            self, subject: Subject, asked: dict[str, Any]) -> None:
        got = subject.start(shared=True, **asked)
        assert got["status"] == "ok", got
        window = got["window"]
        assert window["display"] == asked.get("display", 0) and window["onscreen"] is True, window
        assert window["fullscreen"] is bool(asked.get("fullscreen")), window

    def test_a_full_screen_start_fills_the_asked_display_or_is_refused_by_name(
            self, subject: Subject) -> None:
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
        assert got["window"]["bounds"]["width"] == hosts.SIZE[0], got
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
