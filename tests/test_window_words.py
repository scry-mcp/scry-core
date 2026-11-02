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


@pytest.mark.parametrize(("origin", "position"), [
    ((-2048, 0), "-2008,40"),
    ((0, -1152), "40,-1112"),
    ((-2048, -1152), "-2008,-1112"),
])
def test_dosbox_x_keeps_the_sign_of_a_display_left_of_or_above_the_main_one(
        origin: tuple[int, int], position: str) -> None:
    asked = w.WindowRequest(1, False, origin)
    assert words.dosbox_x(asked)[-1] == f"sdl windowposition={position}"


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


def _sized(size: tuple[int, int], scale: float = 1.0,
           height_free: bool = False) -> w.WindowRequest:
    return w.WindowRequest(1, False, (2048, 0), size=size, scale=scale, height_free=height_free)


def test_dosbox_x_sends_a_stated_size_after_its_position() -> None:
    assert words.dosbox_x(_sized((1280, 960)), "darwin") == [
        "-set", "sdl display=1", "-set", "sdl windowposition=2088,40", "-set",
        "sdl windowresolution=1280x960"]


@pytest.mark.parametrize(("size", "scale", "platform", "sent"), [
    ((3840, 2880), 3.0, "win32", "1280x960"),      # DOSBox-X stops being DPI aware from 200 %
    ((2500, 1250), 2.5, "win32", "1000x500"),
    ((1920, 1440), 1.5, "win32", "1920x1440"),     # below 200 % it stays aware: real pixels
    ((1280, 960), 1.0, "win32", "1280x960"),
    ((1280, 960), 2.0, "darwin", "1280x960"),      # high DPI is off on macOS: points
])
def test_dosbox_x_is_told_the_unit_it_reads_on_the_platform_and_scale(
        size: tuple[int, int], scale: float, platform: str, sent: str) -> None:
    assert words.dosbox_x(_sized(size, scale), platform)[-1] == f"sdl windowresolution={sent}"


@pytest.mark.parametrize(("scale", "dpi_aware", "sent"), [
    (2.0, True, "1280x960"), (3.0, True, "1280x960"),      # asked aware: real pixels at any scale
    (1.5, False, "853x640"), (2.0, False, "640x480"),      # unaware: logical pixels at any scale
    (1.0, False, "1280x960"),
    (2.0, None, "640x480"), (1.5, None, "1280x960"),       # auto: unaware from 200 % only
])
def test_dosbox_x_reads_the_unit_from_the_conf_s_dpi_awareness_on_windows(
        scale: float, dpi_aware: bool | None, sent: str) -> None:
    asked = w.WindowRequest(1, False, (2048, 0), size=(1280, 960), scale=scale,
                            dpi_aware=dpi_aware)
    assert words.dosbox_x(asked, "win32")[-1] == f"sdl windowresolution={sent}"


@pytest.mark.parametrize(("scale", "system", "dpi_aware", "sent"), [
    (2.0, 1.0, None, "1280x960"),     # the primary display decides `auto`, not the asked one
    (1.5, 2.0, None, "853x640"),      # primary at 200 %: unaware, and the asked display scales it
    (1.0, 2.0, None, "1280x960"),
    (2.0, 1.0, False, "640x480"),     # an explicit setting ignores the primary display
])
def test_dosbox_x_reads_auto_off_the_primary_display_s_scale(
        scale: float, system: float, dpi_aware: bool | None, sent: str) -> None:
    asked = w.WindowRequest(1, False, (2048, 0), size=(1280, 960), scale=scale,
                            system_scale=system, dpi_aware=dpi_aware)
    assert words.dosbox_x(asked, "win32")[-1] == f"sdl windowresolution={sent}"


@pytest.mark.parametrize(("scale", "dpi_aware", "position"), [
    (3.0, True, "120,120"),           # real pixels: the margin grows with the scale
    (1.5, None, "60,60"),             # auto below 200 % is aware too
    (3.0, None, "40,40"),             # unaware: logical pixels, the margin as it is
    (3.0, False, "40,40"),
    (1.0, True, "40,40"),
])
def test_dosbox_x_keeps_its_title_bar_on_the_display_when_it_reads_real_pixels(
        scale: float, dpi_aware: bool | None, position: str) -> None:
    asked = w.WindowRequest(0, False, (0, 0), scale=scale, dpi_aware=dpi_aware)
    assert f"sdl windowposition={position}" in words.dosbox_x(asked, "win32")


def test_dpi_awareness_changes_nothing_on_macos() -> None:
    asked = w.WindowRequest(1, False, (2048, 0), size=(1280, 960), scale=2.0, dpi_aware=False)
    assert words.dosbox_x(asked, "darwin")[-1] == "sdl windowresolution=1280x960"


def test_dosbox_x_never_sends_a_size_with_full_screen() -> None:
    assert "windowresolution" not in " ".join(words.dosbox_x(w.WindowRequest(
        1, True, (2048, 0), size=(1280, 960))))


def test_mame_resolution_follows_the_stated_size_and_keeps_nomaximize_when_honoured() -> None:
    assert words.mame(_sized((744, 768))) == [
        "-window", "-nomaximize", "-resolution", "744x768", "-screen0", "screen1"]


def test_mame_drops_nomaximize_for_a_stated_size_when_the_request_says_the_height_is_free() -> None:
    assert words.mame(_sized((744, 768), height_free=True)) == [
        "-window", "-resolution", "744x768", "-screen0", "screen1"]


def test_mame_keeps_nomaximize_when_no_size_was_stated() -> None:
    assert words.mame(w.WindowRequest(1, False, (2048, 0), height_free=True))[:2] == [
        "-window", "-nomaximize"]


def test_a_stated_size_wins_over_a_resolution_a_server_passes_beside_it() -> None:
    assert "744x768" in words.mame(_sized((744, 768)), "640x480")
