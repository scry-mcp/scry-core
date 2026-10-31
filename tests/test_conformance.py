"""`scry_core.conformance`: the window contract every server runs against its own `start` and
`window`. A server with no emulator behind it passes; one that breaks a rule is told which."""

from __future__ import annotations

from pathlib import Path

import pytest
from null_server import NullServer

from scry_core import conformance

QUIET = ("-p", "no:cacheprovider", "--no-cov", "-rf")

SUITE = """
import pytest
from null_server import {server}
from scry_core import conformance


class TestWindowContract(conformance.WindowContract):
    @pytest.fixture
    def subject(self):
        return {server}()
"""


class TestNullServer(conformance.WindowContract):
    @pytest.fixture
    def subject(self) -> NullServer:
        return NullServer()


@pytest.fixture(autouse=True)
def _own_suite(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.pytest.ini_options]\n'
                               'reply_shapes_anchors = ["scry_core.reply_contract"]\n')
    pytester.syspathinsert(Path(__file__).parent)


def _failed(server: str, pytester: pytest.Pytester) -> tuple[set[str], int]:
    pytester.makepyfile(SUITE.format(server=server))
    run = pytester.runpytest(*QUIET)
    failed = {line.split("::")[-1].split("[")[0].split(" ")[0]
              for line in run.stdout.str().splitlines() if line.startswith("FAILED")}
    assert run.parseoutcomes().get("errors", 0) == 0, run.stdout.str()
    return failed, run.parseoutcomes().get("passed", 0)


def test_the_null_server_run_examines_something() -> None:
    assert [n for n in dir(conformance.WindowContract) if n.startswith("test_")]


def test_a_server_that_follows_every_rule_passes(pytester: pytest.Pytester) -> None:
    failed, passed = _failed("NullServer", pytester)
    assert failed == set() and passed > 0


def test_a_server_with_no_window_tool_fails_the_rules_that_call_it(
        pytester: pytest.Pytester) -> None:
    failed, passed = _failed("WithoutWindowTool", pytester)
    assert failed >= {"test_window_answers_where_the_window_is_and_with_front_brings_it_forward",
                      "test_an_unwatched_start_opens_no_window_and_window_is_no_channel"}
    assert passed > 0, "a server that only lacks `window` still passes the rest"


def test_a_server_that_ignores_display_unwatched_is_told_so(pytester: pytest.Pytester) -> None:
    failed, passed = _failed("IgnoresDisplayUnwatched", pytester)
    assert failed == {"test_the_window_arguments_without_shared_are_refused_not_ignored"}
    assert passed > 0


@pytest.mark.parametrize(("server", "rule"), [
    ("AlwaysBehind", "test_window_front_on_a_foreground_session_never_blames_the_background"),
    ("SkipsProve", "test_a_window_the_emulator_never_opened_refuses_the_start_and_leaves_the_"
                   "session_to_close"),
    ("SkipsProve", "test_a_fullscreen_that_does_not_fill_the_display_is_refused_not_reported"),
    ("CachesStartBlock", "test_window_answers_a_window_the_owner_dragged_to_another_display"),
])
def test_each_broken_server_is_caught_by_the_rule_that_names_its_defect(
        pytester: pytest.Pytester, server: str, rule: str) -> None:
    failed, passed = _failed(server, pytester)
    assert rule in failed and passed > 0, failed
