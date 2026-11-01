"""`scry_core.window_words`: a window request as an emulator's command-line words."""

from __future__ import annotations

import sys

import pytest

from scry_core import window as w
from scry_core import window_words as words
from scry_core.reply_contract import Invalid

WINDOWED = w.WindowRequest(1, False, (2048, 0))
FULL = w.WindowRequest(1, True, (2048, 0))


def test_dosbox_x_positions_a_windowed_run_inside_its_display() -> None:
    assert words.dosbox_x(WINDOWED) == ["-set", "sdl display=1", "-set",
                                        "sdl windowposition=2088,40"]


def test_dosbox_x_fills_the_display_in_full_screen_and_sends_no_position() -> None:
    assert words.dosbox_x(FULL) == ["-set", "sdl display=1", "-fullscreen"]


@pytest.mark.parametrize(("resolution", "flags"), [
    (None, ["-window", "-nomaximize"]),
    ("640x480", ["-window", "-nomaximize", "-resolution", "640x480"]),
])
def test_mame_windows_the_run_on_the_asked_display(resolution: str | None,
                                                   flags: list[str]) -> None:
    assert words.mame(WINDOWED, resolution) == [*flags, "-screen0", "screen1"]


def test_mame_full_screen_drops_the_window_where_it_is_allowed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(words, "MAME_NO_FULLSCREEN_ON", ())
    assert words.mame(FULL) == ["-nowindow", "-screen0", "screen1"]


@pytest.mark.parametrize(("platform", "refused"), [("darwin", True), ("win32", True),
                                                    ("linux", False)])
def test_mame_full_screen_is_refused_on_the_platforms_where_nowindow_was_measured_not_to_fill_it(
        monkeypatch: pytest.MonkeyPatch, platform: str, refused: bool) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    if refused:
        with pytest.raises(Invalid) as e:
            words.mame(FULL)
        assert e.value.code == "bad_argument" and "-nowindow" in str(e.value)
    else:
        assert words.mame(FULL)[0] == "-nowindow"


def test_a_window_that_is_not_full_screen_is_never_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert words.mame(WINDOWED, None)
