"""The views by pen both servers draw: the isolated grey, the runs of unused pens, an isolation's
count and box, the pixel view's crop."""
from __future__ import annotations

from scry_core import pens


def test_an_isolated_view_draws_the_set_in_its_hue_and_the_rest_grey_in_a_band() -> None:
    assert pens.isolated((10, 20, 30), True) == pens.ISOLATE_COLOUR
    assert pens.isolated((0, 0, 0), False) == (pens.GREY_LOW,) * 3
    assert pens.isolated((255, 255, 255), False) == (pens.GREY_HIGH,) * 3


def test_unused_pens_are_said_as_runs() -> None:
    assert pens.runs([]) == []
    assert pens.runs([0, 1, 2, 5, 7, 8]) == ["0x0-0x2", "0x5", "0x7-0x8"]


def test_an_isolation_counts_its_pixels_and_boxes_them_in_screen_coordinates() -> None:
    # a 3x2 window at (10, 20): pens 1 at (11, 20) and (12, 21)
    got = pens.isolation([0, 1, 0, 0, 0, 1], 3, 10, 20, {1})
    assert got == {"pixels": 2, "bbox": [11, 20, 12, 21], "pens": [1],
                   "isolate_color": "#ff00ff"}
    none = pens.isolation([0, 0], 2, 0, 0, {9})
    assert none["pixels"] == 0 and none["bbox"]["available"] is False


def test_the_pixel_crop_stays_inside_the_screen() -> None:
    assert pens.pixel_crop(0, 0, 320, 200) == [0, 0, 48, 48]
    assert pens.pixel_crop(319, 199, 320, 200) == [272, 152, 48, 48]
    assert pens.pixel_crop(5, 5, 20, 10) == [0, 0, 20, 10]
