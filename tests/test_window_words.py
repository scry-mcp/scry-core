"""`scry_core.window_words`: a window request as an emulator's command-line words."""

from __future__ import annotations

import pytest

from scry_core import window as w
from scry_core import window_words as words

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


def test_mame_full_screen_is_the_words_alone_the_platform_rule_is_the_requests() -> None:
    assert words.mame(FULL) == ["-nowindow", "-screen0", "screen1"]


def _sized(size: tuple[int, int], scale: float = 1.0) -> w.WindowRequest:
    return w.WindowRequest(1, False, (2048, 0), size=size, scale=scale)


def test_dosbox_x_sends_a_stated_size_after_its_position() -> None:
    assert words.dosbox_x(_sized((1280, 960))) == [
        "-set", "sdl display=1", "-set", "sdl windowposition=2088,40", "-set",
        "sdl windowresolution=1280x960"]


def test_dosbox_x_on_a_scaled_windows_display_is_told_logical_pixels() -> None:
    assert words.dosbox_x(_sized((3840, 2880), 3.0))[-1] == "sdl windowresolution=1280x960"


def test_dosbox_x_never_sends_a_size_with_full_screen() -> None:
    assert "windowresolution" not in " ".join(words.dosbox_x(w.WindowRequest(
        1, True, (2048, 0), size=(1280, 960))))


def test_mame_resolution_follows_the_stated_size_and_keeps_nomaximize_on_macos() -> None:
    assert words.mame(_sized((744, 768)), platform="darwin") == [
        "-window", "-nomaximize", "-resolution", "744x768", "-screen0", "screen1"]


def test_mame_on_windows_drops_nomaximize_for_a_stated_size_which_it_would_ignore() -> None:
    assert words.mame(_sized((744, 768)), platform="win32") == [
        "-window", "-resolution", "744x768", "-screen0", "screen1"]


def test_mame_on_windows_keeps_nomaximize_when_no_size_was_stated() -> None:
    assert words.mame(WINDOWED, platform="win32")[:2] == ["-window", "-nomaximize"]


def test_a_stated_size_wins_over_a_resolution_a_server_passes_beside_it() -> None:
    assert "744x768" in words.mame(_sized((744, 768)), "640x480", platform="darwin")
