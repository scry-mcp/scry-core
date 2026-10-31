"""The window tier a server inherits by installing scry-core: the marker, the fixture and the
decorator come from the plugin and the stand-ins package, with no copy in the server's tests."""

from __future__ import annotations

import pytest

SUITE = """
from scry_core.window_stand_ins import on_the_desk


@on_the_desk
def test_on_the_desk(behind_a_fullscreen_app):
    raise AssertionError("the desk is not for this run")


def test_ordinary():
    pass
"""

QUIET = ("-p", "no:cacheprovider", "--no-cov")


@pytest.fixture(autouse=True)
def _own_suite(pytester: pytest.Pytester) -> None:
    """The shape guard refuses a suite declaring no anchors; these suites reply to nothing."""
    pytester.makepyprojecttoml('[tool.pytest.ini_options]\n'
                               'reply_shapes_anchors = ["scry_core.reply_contract"]\n')


def test_the_marker_is_registered_with_what_it_moves(pytester: pytest.Pytester) -> None:
    out = pytester.runpytest("--markers", "-p", "no:cacheprovider").stdout.str()
    assert "@pytest.mark.window:" in out and "owner's Space" in out


def test_the_fixture_comes_from_the_plugin(pytester: pytest.Pytester) -> None:
    out = pytester.runpytest("--fixtures", "-p", "no:cacheprovider").stdout.str()
    assert "behind_a_fullscreen_app" in out


def test_a_default_style_run_leaves_the_tier_out_and_a_window_run_selects_it(
        pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRY_FOCUS_CONTROL", raising=False)
    pytester.makepyfile(SUITE)
    pytester.runpytest("-m", "not window", *QUIET).assert_outcomes(passed=1, deselected=1)
    selected = pytester.runpytest("-m", "window", "-rs", *QUIET)
    selected.assert_outcomes(skipped=1, deselected=1)
    assert "SCRY_FOCUS_CONTROL" in selected.stdout.str() or "macOS" in selected.stdout.str()
