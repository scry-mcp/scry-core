"""The `private_run` plugin: a battery that asks for it gets a home and a temp folder of its own,
and fails when it leaves a file in that home."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

#: Every suite with this package installed declares the shape guard's anchors.
SUITE = '[tool.pytest.ini_options]\nreply_shapes_anchors = ["scry_core.reply_contract"]\n'
ASKED = SUITE + "private_run = true\n"


def test_a_file_left_in_the_home_fails_the_run_and_is_named(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(ASKED)
    pytester.makepyfile("""
        from pathlib import Path

        def test_leaves_a_file():
            (Path.home() / ".local" / "state" / "tool").mkdir(parents=True)
            (Path.home() / ".local" / "state" / "tool" / "left.log").write_text("x")
    """)
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*left in the run's home*left.log*"])


def test_the_run_has_a_home_and_a_temp_folder_of_its_own_and_gives_them_back(
        pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(ASKED)
    pytester.makepyfile("""
        import os, tempfile
        from pathlib import Path

        def test_where(tmp_path_factory):
            base = tmp_path_factory.getbasetemp()
            assert Path.home().is_relative_to(base), Path.home()
            assert Path(os.environ["XDG_STATE_HOME"]).is_relative_to(Path.home())
            own = Path(tempfile.gettempdir())
            assert own.name.startswith("run-") and os.environ["TMPDIR"] == str(own), own
            assert Path(tempfile.mkdtemp()).parent == own
            Path("where").write_text(str(own))
    """)
    home, temp = Path.home(), tempfile.gettempdir()
    pytester.runpytest().assert_outcomes(passed=1)
    assert (Path.home(), tempfile.gettempdir()) == (home, temp), "the run gave them back"
    assert not Path((pytester.path / "where").read_text()).exists(), "its temp folder is gone"


def test_a_directory_alone_is_no_file_left(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(ASKED)
    pytester.makepyfile("""
        from pathlib import Path

        def test_makes_a_folder():
            (Path.home() / ".cache" / "tool").mkdir(parents=True)
    """)
    pytester.runpytest().assert_outcomes(passed=1)


def test_a_suite_that_does_not_ask_keeps_its_home(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(SUITE)
    pytester.makepyfile(f"""
        import os

        def test_home_is_the_callers():
            assert os.environ["HOME"] == {os.environ["HOME"]!r}
    """)
    pytester.runpytest().assert_outcomes(passed=1)


def test_a_suite_that_deselects_its_live_cases_is_private(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(ASKED + 'markers = ["live: needs the real emulator"]\n'
                               "addopts = \"-m 'not live'\"\n")
    pytester.makepyfile(f"""
        import os, pytest

        @pytest.mark.live
        def test_needs_the_bench():
            raise AssertionError("deselected")

        def test_home_is_the_runs():
            assert os.environ["HOME"] != {os.environ["HOME"]!r}
    """)
    pytester.runpytest().assert_outcomes(passed=1, deselected=1)


def test_a_live_run_stands_aside(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml(ASKED + 'markers = ["live: needs the real emulator"]\n')
    pytester.makepyfile(f"""
        import os, pytest

        @pytest.mark.live
        def test_home_is_the_callers():
            assert os.environ["HOME"] == {os.environ["HOME"]!r}
    """)
    pytester.runpytest("-m", "live").assert_outcomes(passed=1)
    # A live case selected without its marker being named is as live.
    pytester.runpytest().assert_outcomes(passed=1)
