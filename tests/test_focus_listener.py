"""`scry_core.focus_listener`: what was heard and the stretch it covers, the lines a listener
prints, a `Listener` against listeners of the test's own, the build, and the host's listener."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scry_core import focus_listener as fl

DEADLINE_S = 5.0
LISTENING = "1000\tLISTENING\tiTerm2\t5"
#: What a killed process returns: Windows has no signal to name.
KILLED = 1 if sys.platform == "win32" else -9
#: What opening a directory as a file raises: Windows answers that it may not.
NOT_A_FILE = PermissionError if sys.platform == "win32" else IsADirectoryError


def until(true: Callable[[], object], what: str) -> None:
    deadline = time.monotonic() + DEADLINE_S
    while not true():
        assert time.monotonic() < deadline, what
        time.sleep(0.001)


def no_listener(_folder: Path) -> str:
    return "this test has no listener"


def fake_listener(*lines: str, then: str = "sys.stdin.read()") -> Any:
    """A listener of the test's own: it prints `lines`, then runs `then` (by default it waits
    for its stdin to end, as the real one does)."""
    code = f"import os, sys, time\nfor l in {lines!r}: print(l, flush=True)\n{then}\n"
    return lambda _folder: [sys.executable, "-c", code]


def gated_listener(gate: Path, line: str) -> Any:
    """One that says it listens, prints `line` once `gate` exists, then waits for its stdin."""
    return fake_listener(LISTENING, then=(
        f"while not os.path.exists({str(gate)!r}): time.sleep(0.001)\n"
        f"print({line!r}, flush=True)\nsys.stdin.read()"))


@pytest.mark.parametrize(("heard", "window", "says"), [
    (fl.Heard(error="built with swiftc"), (0, 3000), "built with swiftc"),
    (fl.Heard(), (0, 3000), "never said it was listening"),
    (fl.Heard(since_ms=1), (0, 3000), "began at 1, after the window opened at 0"),
    (fl.Heard(since_ms=0, until_ms=2999), (0, 3000), "ended at 2999, before the window closed"),
    (fl.Heard(since_ms=0, until_ms=3000), (0, 3000), ""),
    (fl.Heard(since_ms=0), (0, 3000), ""),
    (fl.Heard(since_ms=5, until_ms=9), (5, 9), ""),
])
def test_a_stretch_is_heard_whole_or_says_why_not(
        heard: fl.Heard, window: tuple[int, int], says: str) -> None:
    why = heard.unheard(*window)
    assert says in why and bool(why) == bool(says)


def test_who_was_in_front_is_the_last_to_come_there_and_nobody_where_nothing_listened() -> None:
    first = fl.Activation(1000, "iTerm2", 5)
    heard = fl.Heard((fl.Activation(1100, "dosbox-x", 77), fl.Activation(1120, "Finder", None)),
                     since_ms=1000, until_ms=2000, front=first)
    assert [heard.front_at(ms) and heard.front_at(ms).app  # type: ignore[union-attr]
            for ms in (999, 1000, 1099, 1100, 1119, 1120, 2000, 2001)] == [
        None, "iTerm2", "iTerm2", "dosbox-x", "dosbox-x", "Finder", "Finder", None]
    assert fl.Heard(since_ms=0).front_at(5) is None
    assert fl.Heard(error="no swiftc", front=first).front_at(1500) is None


@pytest.mark.parametrize(("line", "read"), [
    ("1000\tLISTENING\tiTerm2\t5\n", (True, fl.Activation(1000, "iTerm2", 5))),
    ("1100\tdosbox-x\t77\n", (False, fl.Activation(1100, "dosbox-x", 77))),
    ("1100\tdosbox-x\t77", (False, fl.Activation(1100, "dosbox-x", 77))),
    ("1120\t\t-1\n", (False, fl.Activation(1120, "", None))),
    ("12\tLISTENING\t5\n", (False, fl.Activation(12, "LISTENING", 5))),
    ("12\tLISTENING\tLISTENING\t5\n", (True, fl.Activation(12, "LISTENING", 5))),
])
def test_a_listener_line_is_read_as_listening_or_as_an_activation(
        line: str, read: tuple[bool, fl.Activation]) -> None:
    assert fl.parse(line) == read


@pytest.mark.parametrize("line", [
    "", "\n", "hello", "12\tdosbox-x", "12\tdosbox-x\tpid", "\tLISTENING", "12\tLISTENING",
    "x\tdosbox-x\t7", "-1\tdosbox-x\t7", "12\ta\tb\t7", "12\tLISTENING\tiTerm2\tpid",
    "12\tdosbox-x\t--5", "²\tdosbox-x\t7", "12\tdosbox-x\t²", "12\tdosbox-x\t7\t",
])
def test_a_line_in_neither_shape_is_no_reading(line: str) -> None:
    assert fl.parse(line) is None


def test_an_activation_is_written_as_it_was_heard() -> None:
    assert fl.Activation(1100, "dosbox-x", 77).line() == "1100\tdosbox-x\t77"
    assert fl.Activation(1120, "Finder").line() == "1120\tFinder\t"


def test_a_listener_hears_each_activation_as_it_is_printed_and_writes_it(tmp_path: Path) -> None:
    record = tmp_path / "heard.tsv"
    listener = fl.Listener(record, fake_listener(LISTENING, "1100\tdosbox-x\t77",
                                                 "1120\tFinder\t-1"))
    assert listener.returncode is None
    with listener:
        until(lambda: len(listener.heard.activations) >= 2, "two activations were printed")
        during = listener.heard
        assert listener.returncode is None
    assert during == fl.Heard((fl.Activation(1100, "dosbox-x", 77),
                               fl.Activation(1120, "Finder", None)), since_ms=1000,
                              front=fl.Activation(1000, "iTerm2", 5))
    after = listener.heard
    assert after.until_ms is not None and after.unheard(1000, after.until_ms) == ""
    assert record.read_text() == "1100\tdosbox-x\t77\n1120\tFinder\t\n"
    assert listener.returncode == 0


def test_no_listener_is_said_and_nothing_is_written(tmp_path: Path) -> None:
    with fl.Listener(tmp_path / "heard.tsv", no_listener) as listener:
        pass
    assert listener.heard == fl.Heard(error="this test has no listener")
    assert not listener.record.exists() and listener.returncode is None


def test_a_listener_that_cannot_be_started_is_said_not_raised(tmp_path: Path) -> None:
    with fl.Listener(tmp_path / "heard.tsv",
                     lambda _folder: [str(tmp_path / "no-such-listener")]) as listener:
        pass
    assert "the listener did not start" in listener.heard.error


def test_a_listener_that_ends_early_stopped_listening_then(tmp_path: Path) -> None:
    with fl.Listener(tmp_path / "heard.tsv", fake_listener(LISTENING, then="")) as listener:
        until(lambda: listener.heard.until_ms is not None, "the listener ended")
        ended = listener.heard.until_ms
        time.sleep(0.01)
    assert listener.heard.until_ms == ended and ended is not None
    assert "ended at" in listener.heard.unheard(1000, ended + 1)


def test_a_line_of_another_shape_is_said_and_the_hearing_goes_on(tmp_path: Path) -> None:
    with fl.Listener(tmp_path / "heard.tsv", fake_listener(
            LISTENING, "12\tdosbox-x\t--5", "1100\tdosbox-x\t77", then="")) as listener:
        until(lambda: listener.heard.until_ms is not None, "the listener ended")
    heard = listener.heard
    assert "no shape it has" in heard.error and repr("12\tdosbox-x\t--5\n") in heard.error
    assert heard.activations == (fl.Activation(1100, "dosbox-x", 77),)


def test_a_listener_that_never_says_it_listens_is_waited_for_and_then_left_unheard(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fl, "LISTEN_WAIT_S", 0.05)
    monkeypatch.setattr(fl, "STOP_WAIT_S", 0.05)
    began = time.monotonic()
    with fl.Listener(tmp_path / "heard.tsv", fake_listener(then="time.sleep(60)")) as listener:
        waited = time.monotonic() - began
        assert listener.heard.unheard(0, 1) == "the listener never said it was listening"
    assert waited >= 0.05
    assert listener.returncode == KILLED


def test_a_wait_that_is_interrupted_ends_the_listener_it_started(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listener = fl.Listener(tmp_path / "heard.tsv", fake_listener(LISTENING))

    def interrupted(_timeout: float) -> bool:
        raise KeyboardInterrupt
    monkeypatch.setattr(listener._listening, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        listener.__enter__()
    assert listener.returncode == 0


def test_a_record_that_cannot_be_opened_refuses_before_the_run(tmp_path: Path) -> None:
    listener = fl.Listener(tmp_path / "heard.tsv", fake_listener(LISTENING))
    listener.record.mkdir()
    with pytest.raises(NOT_A_FILE):
        listener.__enter__()
    assert listener.returncode is None


@pytest.mark.parametrize(("own", "raised"), [(None, ValueError), (RuntimeError, RuntimeError)])
def test_a_record_that_cannot_be_written_says_so_at_the_end_unless_the_run_failed_itself(
        tmp_path: Path, own: type[Exception] | None, raised: type[Exception]) -> None:
    gate = tmp_path / "gate"
    listener = fl.Listener(tmp_path / "heard.tsv", gated_listener(gate, "1100\tdosbox-x\t77"))
    with pytest.raises(raised), listener:
        assert listener._out is not None
        listener._out.close()
        gate.touch()
        until(lambda: listener.heard.until_ms is not None, "the hearing stopped")
        if own is not None:
            raise own("the run's own failure")
    assert listener.heard.activations == (fl.Activation(1100, "dosbox-x", 77),)


def test_off_macos_nothing_listens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fl, "_MACOS", False)
    assert "macOS only" in str(fl.host(tmp_path))


@pytest.mark.parametrize(("compiler", "run", "want"), [
    (None, None, "which this host does not have"),
    ("/usr/bin/swiftc", OSError("no exec"), "did not build focus_listener.swift: no exec"),
    ("/usr/bin/swiftc", subprocess.TimeoutExpired("swiftc", 300), "did not build"),
    ("/usr/bin/swiftc", (1, "error: no such module"), "error: no such module"),
    ("/usr/bin/swiftc", (1, ""), "did not build focus_listener.swift: 1"),
    ("/usr/bin/swiftc", (0, ""), None),
])
def test_the_host_listener_is_built_beside_the_record_or_says_why_not(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, compiler: str | None, run: Any,
        want: str | None) -> None:
    monkeypatch.setattr(fl, "_MACOS", True)
    monkeypatch.setattr(shutil, "which", lambda name: compiler)
    asked: list[list[str]] = []

    def fake(argv: list[str], **_kw: object) -> object:
        asked.append(argv)
        if isinstance(run, Exception):
            raise run
        return subprocess.CompletedProcess(argv, run[0], "", run[1])
    monkeypatch.setattr(subprocess, "run", fake)
    made = fl.host(tmp_path)
    if want is None:
        assert made == [str(tmp_path / fl.NAME)] and len(fl.NAME) <= 16
        assert asked == [["/usr/bin/swiftc", "-O", "-warnings-as-errors", str(fl.SOURCE), "-o",
                          made[0]]]
        assert fl.SOURCE.is_file()
    else:
        assert isinstance(made, str) and want in made


@pytest.mark.skipif(sys.platform != "darwin", reason="the listener is macOS's")
@pytest.mark.skipif(shutil.which("swiftc") is None, reason="the listener is built with swiftc")
def test_the_host_listener_says_who_is_in_front_and_ends_with_its_run(tmp_path: Path) -> None:
    before = int(time.time() * 1000)
    with fl.Listener(tmp_path / "heard.tsv") as listener:
        heard = listener.heard
    assert heard.error == "" and heard.since_ms is not None and heard.since_ms >= before, heard
    assert heard.front is not None and heard.front.epoch_ms == heard.since_ms
    assert listener.returncode == 0
