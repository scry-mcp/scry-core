"""The shape a picture is shown in: 4:3 for the whole frame, no pixel row or column dropped, and a
crop of the stretched frame that is the stretch of the crop."""

from __future__ import annotations

import pytest

from scry_core import aspect


@pytest.mark.parametrize(("size", "shown"), [
    ((320, 200), (320, 240)), ((1280, 800), (1280, 960)), ((640, 400), (640, 480)),
    ((320, 240), (320, 240)), ((640, 480), (640, 480)), ((256, 224), (299, 224)),
    ((4, 5), (7, 5)), ((8, 8), (11, 8)),
])
def test_a_whole_frame_is_shown_at_4_to_3_by_growing_its_short_side(
        size: tuple[int, int], shown: tuple[int, int]) -> None:
    assert aspect.shown(*size) == shown
    wide, high = aspect.shown(*size)
    assert abs(wide * 3 - high * 4) <= 2, "4:3 to within the rounding of one side"
    assert wide >= size[0] and high >= size[1], "no row or column of the machine is dropped"


@pytest.mark.parametrize(("whole", "wide", "start", "stop"), [
    (400, 480, 56, 344), (200, 240, 28, 172), (10, 12, 2, 8), (10, 12, 0, 10), (8, 13, 2, 8),
    (7, 7, 1, 5), (5, 12, 0, 1),
])
def test_a_crop_of_the_stretched_axis_is_the_stretch_of_the_crop(
        whole: int, wide: int, start: int, stop: int) -> None:
    shown = [i * whole // wide for i in range(wide)]
    assert aspect.axis(whole, wide, start, stop) == [v - start for v in shown
                                                     if start <= v < stop]


def test_the_card_s_two_pictures_are_shown_at_the_sizes_it_asks_for() -> None:
    """640 x 288 of a 640 x 400 game is 345.6 tall, and 1280 x 800 is 960."""
    assert len(aspect.axis(400, 480, 56, 344)) in (345, 346)
    assert len(aspect.axis(800, 960, 0, 800)) == 960


def test_every_source_pixel_is_shown_at_least_once_when_an_axis_grows() -> None:
    for whole, wide in ((200, 240), (5, 7), (3, 4)):
        assert set(aspect.axis(whole, wide, 0, whole)) == set(range(whole))
