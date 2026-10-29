"""Pytest plugin (`pytest11` entry point) that runs the shape guard.

Thin and unmeasured on purpose: pytest-cov cannot measure an entry-point plugin, so hook bodies
import the guard late, where coverage sees it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

ANCHORS_INI = "reply_shapes_anchors"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(ANCHORS_INI, type="args", default=[],
                  help="the modules whose reply anchors the shape guard wraps, by name")


def pytest_configure(config: pytest.Config) -> None:
    if config.option.help or config.option.version:
        return
    from scry_core import reply_shapes_guard

    reply_shapes_guard.declared(config)


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    from scry_core import reply_shapes_guard

    if line := reply_shapes_guard.summary_line(config):
        terminalreporter.write_line(line)


@pytest.fixture(scope="session", autouse=True)
def one_word_one_shape(request: pytest.FixtureRequest) -> Iterator[None]:
    from scry_core import reply_shapes_guard

    yield from reply_shapes_guard.one_word_one_shape(request.config)
