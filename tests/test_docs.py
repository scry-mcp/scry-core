"""A description's placeholders, filled from the code at registration."""
from __future__ import annotations

import pytest

from scry_core import docs, picture, series


def test_every_placeholder_is_filled_from_the_values() -> None:
    assert docs.filled("t", "at most {MAX}, {PICTURE2}", {"MAX": "8", "PICTURE2": "p"}) \
        == "at most 8, p"


@pytest.mark.parametrize("left", ["{SCREEN_MAX}", "{X2}", "{A}"])
def test_one_left_unfilled_fails_naming_the_tool(left: str) -> None:
    with pytest.raises(TypeError, match=rf"t's docstring names \['\{{{left[1:-1]}\}}'\]"):
        docs.filled("t", f"up to {left}", {})


def test_braces_that_are_no_placeholder_stay_as_written() -> None:
    text = "a JSON `{}` or `{x}` or `{2X}`"
    assert docs.filled("t", text, {}) == text


def test_the_media_modules_export_their_values() -> None:
    assert picture.DOC_VALUES == {"PICTURE": picture.DESCRIBED, "PICTURE_ARGS": picture.ARGUMENTS}
    assert {"SERIES_MAX": str(series.SERIES_MAX)} == series.DOC_VALUES
