"""The window placement helper, asked the way both servers ask it: real programs of each case's own,
run through `WINDOW_APP`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scry_core import placement
from scry_core.reply_contract import Invalid

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the helper doubles are POSIX scripts")


def _helper(where: Path, body: str) -> Path:
    """A helper that runs `body` as Python with the arguments it was given in `sys.argv`."""
    (where / "helper.py").write_text(body + "\n", encoding="utf-8")
    exe = where / "helper"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{where / "helper.py"}" "$@"\n')
    exe.chmod(0o755)
    return exe


def test_the_flags_are_the_helper_s_lines_one_token_each(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `-set` pair is one token with its space, so the answer is split on lines, never on
    whitespace; and the helper is asked for the app, `--shared` and the display."""
    exe = _helper(tmp_path, "import sys; print('-set'); print('sdl display=1'); "
                            "print(' '.join(sys.argv[1:]))")
    monkeypatch.setenv(placement.HELPER_VAR, str(exe))
    got = placement.ask("dosbox", True, "main")
    assert got.flags == ["-set", "sdl display=1", "dosbox --shared --display main"], got


def test_a_helper_that_prints_nothing_answers_no_flags(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host with one display has nowhere to choose: no flags is an answer, not a failure."""
    monkeypatch.setenv(placement.HELPER_VAR, str(_helper(tmp_path, "pass")))
    assert placement.ask("dosbox", True) == placement.Placed([])


@pytest.mark.parametrize(("case", "said"), [
    ("unset", "is not set"), ("absent", "not an executable file"),
    ("not executable", "not an executable file"),
    ("refuses", "answered exit code 1 and printed 'no such display'"),
    ("hangs", "did not answer within 0.3 s")])
def test_a_helper_that_cannot_answer_says_why(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, said: str) -> None:
    if case == "hangs":          # shortened only where it is the case: a busy host starts slowly
        monkeypatch.setattr(placement, "HELPER_TIMEOUT_S", 0.3)
    named = {"unset": "", "absent": str(tmp_path / "gone")}.get(case)
    if named is None:
        body = {"refuses": "import sys; sys.stderr.write('no such display'); sys.exit(1)",
                "hangs": "import time; time.sleep(5)", "not executable": "pass"}[case]
        exe = _helper(tmp_path, body)
        if case == "not executable":
            exe.chmod(0o644)
        named = str(exe)
    monkeypatch.setenv(placement.HELPER_VAR, named)
    got = placement.ask("mame", False)
    assert got.flags is None and said in got.why, got


def test_a_display_belongs_to_a_watched_run(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(Invalid, match="nobody watches"):
        placement.check_display(False, "main")
    placement.check_display(True, "main")
    monkeypatch.delenv(placement.SHARED_DISPLAY_VAR, raising=False)
    assert placement.shared_display(False, "main") == ""
    assert placement.shared_display(True, "") == "secondary"
    monkeypatch.setenv(placement.SHARED_DISPLAY_VAR, "main")
    assert placement.shared_display(True, "") == "main"
    assert placement.shared_display(True, "secondary") == "secondary"
    monkeypatch.setenv(placement.SHARED_DISPLAY_VAR, "left")
    with pytest.raises(Invalid, match="WINDOW_SHARED_DISPLAY='left'"):
        placement.shared_display(True, "")


def test_a_helper_the_system_cannot_run_says_so(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Executable by its bits and still no program: an interpreter that is not there."""
    exe = tmp_path / "helper"
    exe.write_text("#!/nonexistent/interpreter\n")
    exe.chmod(0o755)
    monkeypatch.setenv(placement.HELPER_VAR, str(exe))
    got = placement.ask("mame", False)
    assert got.flags is None and "could not be run" in got.why, got


def test_a_helper_that_prints_bytes_no_encoding_holds_is_answered_not_raised(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A helper's stray byte (a failing tool it calls, in another locale) is a word of its
    answer: the refusal reads it, and the server never dies of a decode."""
    exe = _helper(tmp_path, "import sys; sys.stderr.buffer.write(bytes([0xff, 0xfe])); "
                            "sys.exit(1)")
    monkeypatch.setenv(placement.HELPER_VAR, str(exe))
    got = placement.ask("dosbox", True)
    assert got.flags is None and "exit code 1" in got.why, got
