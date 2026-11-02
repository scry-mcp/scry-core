"""`scry_core.window_size`: the size words of a window, the fit to a display's usable area and the
judgement of the size a host lists. Hosts are doubles: nothing here needs a desk or a scale-2
display, and the macOS and Windows cases differ only in the numbers they are given."""

from __future__ import annotations

import pytest

from scry_core import window as w
from scry_core import window_size as size
from scry_core.reply_contract import Invalid

MAC = w.Display(0, (0, 0, 2048, 1152), usable=(0, 30, 2048, 1122))
WIN = w.Display(0, (0, 0, 3840, 2160), usable=(0, 0, 3840, 2016), scale=3.0)


@pytest.mark.parametrize(("text", "parsed"), [("1280x960", (1280, 960)), ("640X480", (640, 480))])
def test_a_size_is_width_x_height_in_any_case(text: str, parsed: size.Size) -> None:
    assert size.parse(text) == parsed


@pytest.mark.parametrize("text", ["1280", "0x480", "640x0", "-3x4", "axb", "1x2x3", "",
                                  "640 x 480"])
def test_anything_else_is_refused_naming_the_format(text: str) -> None:
    with pytest.raises(Invalid) as e:
        size.parse(text)
    assert e.value.code == "bad_argument" and "WIDTHxHEIGHT" in str(e.value)


def test_a_size_that_fits_the_usable_area_is_kept_to_its_edge() -> None:
    size.refuse_unfit((2048, 1122), MAC)


@pytest.mark.parametrize("asked", [(2049, 1122), (2048, 1123)])
def test_a_size_beyond_the_usable_area_is_refused_naming_the_usable_size(
        asked: size.Size) -> None:
    with pytest.raises(Invalid) as e:
        size.refuse_unfit(asked, MAC)
    assert e.value.code == "bad_argument" and "2048x1122" in str(e.value)
    assert "display 0" in str(e.value)


def test_a_display_that_reports_no_usable_area_is_judged_by_its_bounds() -> None:
    bare = w.Display(1, (2048, 0, 1920, 1080))
    assert bare.work == (2048, 0, 1920, 1080)
    with pytest.raises(Invalid) as e:
        size.refuse_unfit((1921, 100), bare)
    assert "1920x1080" in str(e.value)


@pytest.mark.parametrize(("display", "platform", "native", "fitted"), [
    (MAC, "darwin", (320, 240), (1280, 960)),      # 6 across, 4 up: the title bar costs a row
    (WIN, "win32", (320, 240), (2240, 1680)),      # the frame grows with the scale
    (MAC, "darwin", (3000, 2000), (3000, 2000)),   # never below the emulator's own scale 1
])
def test_the_largest_whole_multiple_of_the_native_size_that_fits(
        display: w.Display, platform: str, native: size.Size, fitted: size.Size) -> None:
    assert size.integer_fit(native, display, platform) == fitted


@pytest.mark.parametrize(("display", "platform", "fitted"), [
    (MAC, "darwin", (1453, 1090)),
    (WIN, "win32", (2452, 1839)),
])
def test_the_largest_window_of_an_aspect_that_fits(
        display: w.Display, platform: str, fitted: size.Size) -> None:
    assert size.aspect_fit((4, 3), display, platform) == fitted


def test_a_platform_the_hosts_do_not_cover_has_no_frame_to_allow() -> None:
    with pytest.raises(Invalid) as e:
        size.integer_fit((320, 240), MAC, "linux")
    assert e.value.code == "host_failed" and "linux" in str(e.value)


def _seen(bounds: w.Rect, client: size.Size | None = None) -> w.Seen:
    return w.Seen(pid=1, number=1, bounds=bounds, onscreen=True, client=client)


def test_a_windows_client_area_is_compared_when_the_host_has_one() -> None:
    got = size.judge((3840, 2880), _seen((0, 0, 3888, 3057), client=(3840, 2880)), 3.0)
    assert got["matches"] is True and got["compared"] == "client"
    assert got["seen"] == {"width": 3840, "height": 2880}


def test_a_client_a_pixel_off_still_matches_within_the_stated_tolerance() -> None:
    got = size.judge((3840, 2880), _seen((0, 0, 3888, 3057), client=(3839, 2881)), 3.0)
    assert got["matches"] is True and got["tolerance_px"] == size.tolerance_px(3.0) >= 3


def test_a_window_of_another_size_does_not_match() -> None:
    got = size.judge((3840, 2880), _seen((0, 0, 1968, 1617), client=(1920, 1440)), 3.0)
    assert got["matches"] is False and got["asked"] == {"width": 3840, "height": 2880}


def test_macos_has_no_client_area_so_the_title_bar_is_allowed_on_the_height_only() -> None:
    ok = size.judge((1280, 960), _seen((0, 30, 1280, 992)), 1.0)
    assert ok["matches"] is True and ok["compared"] == "outer"
    for wrong in ((0, 30, 1280, 1000), (0, 30, 1290, 992), (0, 30, 1280, 950)):
        assert size.judge((1280, 960), _seen(wrong), 1.0)["matches"] is False


def test_an_emulator_that_fits_the_height_to_its_aspect_is_judged_on_the_width_alone() -> None:
    fitted = _seen((0, 0, 780, 661), client=(744, 558))
    assert size.judge((744, 768), fitted, 1.0, height_free=True)["matches"] is True
    assert size.judge((744, 768), fitted, 1.0)["matches"] is False
    narrow = _seen((0, 0, 400, 359), client=(384, 256))
    got = size.judge((744, 768), narrow, 1.0, height_free=True)
    assert got["matches"] is False and got["height_free"] is True
