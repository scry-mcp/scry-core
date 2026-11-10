"""Pytest plugin (`pytest11`): a suite that sets `private_run = true` runs with a home and a
temp folder of its own, and fails when it leaves a file in that home. A run with a case marked
`live` among those it selected stands aside: a live case reads the real home.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator

import pytest

KEY = "private_run"
HOME_VARS = ("HOME", "USERPROFILE")
XDG_HOMES = {"XDG_STATE_HOME": ".local/state", "XDG_CACHE_HOME": ".cache",
             "XDG_CONFIG_HOME": ".config", "XDG_DATA_HOME": ".local/share"}
TEMP_VARS = ("TMPDIR", "TEMP", "TMP")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(KEY, "run with a home and a temp folder of the run's own, and fail on a file "
                       "left in that home", type="bool", default=False)


def _selects_live(session: pytest.Session) -> bool:
    return any(item.get_closest_marker("live") for item in session.items)


@pytest.fixture(scope="session", autouse=True)
def private_run(request: pytest.FixtureRequest,
                tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    config = request.config
    if not config.getini(KEY) or _selects_live(request.session):
        yield
        return
    home = tmp_path_factory.mktemp("home")
    # Directly in the temp folder: a Unix socket is bound under it and its path has few bytes.
    temp = tempfile.mkdtemp(prefix="run-")
    try:
        with pytest.MonkeyPatch.context() as patch:
            for name in HOME_VARS:
                patch.setenv(name, str(home))
            for name, under in XDG_HOMES.items():
                patch.setenv(name, str(home / under))
            for name in TEMP_VARS:
                patch.setenv(name, temp)
            patch.setattr(tempfile, "tempdir", temp)
            yield
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    left = sorted(str(p.relative_to(home)) for p in home.rglob("*") if not p.is_dir())
    found = [f"{len(left)} file(s) left in the run's home, {home}: " + ", ".join(left)] * bool(left)
    if os.path.exists(temp):
        found.append(f"the run's temp folder could not be removed: {temp}")
    if found:
        pytest.fail("; ".join(found), pytrace=False)
