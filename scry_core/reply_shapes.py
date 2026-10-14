"""The pytest plugin that runs the shape guard (`reply_shapes_guard`), loaded by pytest through
the `pytest11` entry point wherever this package is installed.

THIN ON PURPOSE, AND NOT MEASURED. pytest imports an entry-point plugin before pytest-cov starts,
and pytest-cov documents that such a plugin cannot be measured. So this module defines the
hooks and nothing else, the ini option is declared here without importing the guard, and every
hook body imports the guard only once the session has begun, where coverage sees it: what runs
is measured, and only these few lines are left out of the measure, by name, in `pyproject.toml`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

#: The ini option a suite declares its anchors in, by module name.
ANCHORS_INI = "reply_shapes_anchors"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(ANCHORS_INI, type="args", default=[],
                  help="the modules whose reply anchors the shape guard wraps, by name")


def pytest_configure(config: pytest.Config) -> None:
    # `--help` and `--version` run no suite, so they need no declaration.
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
