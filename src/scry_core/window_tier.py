"""Pytest plugin (`pytest11`): the `window` marker and the `behind_a_fullscreen_app` fixture.

Unmeasured like `reply_shapes`; the fixture's body is `window_stand_ins`, imported late.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from scry_core.window_host import MacHost

MARKER = "window: opens stand-in windows and may switch the owner's Space; run with `-m window`"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", MARKER)


@pytest.fixture
def behind_a_fullscreen_app(tmp_path: Path) -> Iterator[tuple[int, MacHost]]:
    from scry_core import window_stand_ins

    yield from window_stand_ins.behind_a_fullscreen_app(tmp_path)
