"""`python -m scry_core.window_cli`: the shell-side twin of a watched `start`. The host is a double
that lists what it is told; the exit codes are the contract a launcher script reads."""

from __future__ import annotations

import os
import runpy
import signal
import sys
import time
from pathlib import Path

import pytest

from scry_core import window as w
from scry_core import window_cli as cli
from scry_core.reply_contract import Invalid

TWO = [w.Display(0, (0, 0, 2048, 1152)), w.Display(1, (2048, 0, 2048, 1152))]


class Desk:
    def __init__(self, displays: list[w.Display], listed: list[w.Seen] | None = None) -> None:
        self._displays, self.listed = displays, listed or []

    def displays(self) -> list[w.Display]:
        return self._displays

    def windows(self) -> list[w.Seen]:
        return self.listed

    def above(self, window: w.Seen) -> list[w.Seen]:
        return []


@pytest.fixture
def desk(monkeypatch: pytest.MonkeyPatch) -> Desk:
    fake = Desk(TWO)
    monkeypatch.setattr(cli, "host", lambda: fake)
    return fake


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    got = capsys.readouterr()
    return code, got.out, got.err


def test_displays_lists_each_index_with_its_bounds(desk: Desk,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "displays")
    assert code == 0
    assert out.splitlines() == ["display 0 bounds=0,0,2048x1152",
                                "display 1 bounds=2048,0,2048x1152"]


def test_displays_exit_3_with_the_refusal_when_the_host_fails(
        desk: Desk, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    def failing() -> list[w.Display]:
        raise Invalid("host_failed", "this process already chose a DPI awareness")
    monkeypatch.setattr(desk, "displays", failing)
    code, out, err = run(capsys, "displays")
    assert (code, out) == (3, "")
    assert err.startswith("host_failed: this process already chose")


def test_displays_exit_3_when_the_host_reports_none(desk: Desk,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    desk._displays = []
    code, out, err = run(capsys, "displays")
    assert code == 3 and out == "" and "no display" in err


def test_words_prints_one_word_per_line_for_the_asked_display(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "words", "dosbox-x", "--display", "1")
    assert code == 0
    assert out.splitlines() == ["-set", "sdl display=1", "-set", "sdl windowposition=2088,40"]


def test_words_default_to_the_main_display(desk: Desk,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "words", "mame")
    assert code == 0 and out.splitlines()[-2:] == ["-screen0", "screen0"]


def test_words_refuse_a_display_the_host_lacks_naming_the_count(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "words", "mame", "--display", "5")
    assert code == 2 and out == "" and "5 does not exist" in err and "2 displays" in err


def test_words_refuse_full_screen_for_mame_by_name(desk: Desk, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    code, out, err = run(capsys, "words", "mame", "--fullscreen")
    assert code == 2 and out == "" and "-nowindow" in err


@pytest.mark.parametrize("argv", [["nothing"], [], ["words"], ["words", "mame", "--bogus"],
                                  ["words", "mame", "--display", "x"], ["proof"],
                                  ["proof", "abc"], ["words", "mame", "--display"]])
def test_an_unknown_command_or_option_exits_2_never_ignored(
        desk: Desk, capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == "" and err, (out, err)


def test_proof_prints_the_window_line_and_exits_0_on_the_asked_display(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk.listed = [w.Seen(pid=7, number=1, bounds=(2088, 40, 640, 512), onscreen=True)]
    code, out, _ = run(capsys, "proof", "7", "--display", "1", "--seconds", "1")
    assert code == 0
    assert out.strip() == "window: display=1 bounds=2088,40,640x512 onscreen=true"


def test_proof_exits_3_naming_what_was_seen_when_the_window_is_on_another_display(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk.listed = [w.Seen(pid=7, number=1, bounds=(40, 40, 640, 512), onscreen=True)]
    code, out, err = run(capsys, "proof", "7", "--display", "1", "--seconds", "0")
    assert code == 3 and out == "" and "window_not_visible" in err and "display 0" in err


def test_proof_exits_3_when_no_window_appears(desk: Desk,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "proof", "7", "--seconds", "0")
    assert code == 3 and out == "" and "window_not_visible" in err


def test_proof_of_full_screen_exits_3_when_the_window_does_not_fill_the_display(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk.listed = [w.Seen(pid=7, number=1, bounds=(40, 40, 640, 512), onscreen=True)]
    code, _, err = run(capsys, "proof", "7", "--fullscreen", "--seconds", "0")
    assert code == 3 and "does not fill" in err


@pytest.mark.parametrize("arguments, listed", [
    (("--seconds", "0"), []),
    (("--display", "1", "--seconds", "0"),
     [w.Seen(pid=7, number=1, bounds=(40, 40, 640, 512), onscreen=True)]),
    (("--fullscreen", "--seconds", "0"),
     [w.Seen(pid=7, number=1, bounds=(40, 40, 640, 512), onscreen=True)]),
], ids=["never-opened", "other-display", "does-not-fill"])
def test_a_refusal_at_a_shell_names_no_tool_of_a_server(
        desk: Desk, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...],
        listed: list[w.Seen]) -> None:
    desk.listed = listed
    code, _, err = run(capsys, "proof", "7", *arguments)
    assert code == 3 and "window_not_visible" in err
    assert not any(f"`{tool}`" in err for tool in ("status", "close", "resume", "window", "start"))
    assert "session" not in err


def test_proof_exits_4_when_the_host_has_no_display_to_prove_against(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk._displays = []
    code, out, err = run(capsys, "proof", "7", "--seconds", "0")
    assert code == 4 and out == "" and "could not prove" in err


def test_the_module_runs_as_a_program_and_exits_with_the_command_s_code(
        desk: Desk, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delitem(sys.modules, "scry_core.window_cli")
    monkeypatch.setattr("sys.argv", ["window_cli", "displays"])
    monkeypatch.setattr("scry_core.window.host", lambda: desk)
    with pytest.raises(SystemExit) as e:
        runpy.run_module("scry_core.window_cli", run_name="__main__")
    assert e.value.code == 0 and "display 0" in capsys.readouterr().out


def test_words_exit_3_like_displays_when_no_display_is_online(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    desk._displays = []
    code, out, err = run(capsys, "words", "mame")
    assert code == 3 and out == "" and "no display online" in err and "could not prove" not in err


def test_a_refusal_the_host_raises_during_proof_is_could_not_prove(
        desk: Desk, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def broken(*_a: object, **_k: object) -> w.WindowState:
        raise Invalid("host_failed", "the window list cannot be read")
    monkeypatch.setattr(cli, "prove", broken)
    code, out, err = run(capsys, "proof", "7")
    assert code == 4 and out == "" and "could not prove" in err


@pytest.mark.parametrize("argv", [["proof", "7", "--seconds", "nan"],
                                  ["proof", "7", "--seconds", "inf"],
                                  ["proof", "7", "--seconds", "-1"],
                                  ["words", "mame", "--disp", "1"],
                                  ["words", "mame", "--full"]])
def test_a_bound_that_never_ends_and_an_abbreviated_option_are_usage_errors(
        desk: Desk, capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == "" and err, (out, err)


def test_launch_starts_the_command_with_the_placement_words_and_prints_its_pid(
        desk: Desk, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    record = tmp_path / "argv.txt"
    code, out, err = run(capsys, "launch", "dosbox-x", "--display", "1", "--",
                         sys.executable, "-c",
                         "import sys,time;open(sys.argv[1],'w').write(chr(10).join(sys.argv[2:]));"
                         "time.sleep(30)", str(record))
    pid = int(out.removeprefix("pid: ").strip())
    try:
        assert code == 0 and err == ""
        deadline = time.monotonic() + 10
        while (not (record.exists() and record.read_text().endswith("2088,40"))
               and time.monotonic() < deadline):
            time.sleep(0.02)
        assert record.read_text().splitlines() == ["-set", "sdl display=1", "-set",
                                                   "sdl windowposition=2088,40"]
    finally:
        os.kill(pid, signal.SIGTERM)


def test_launch_refuses_a_display_the_host_lacks_and_starts_nothing(
        desk: Desk, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "launch", "mame", "--display", "5", "--", sys.executable)
    assert code == 2 and out == "" and "5 does not exist" in err


@pytest.mark.parametrize("argv", [["launch", "mame"], ["launch", "mame", "--"],
                                  ["launch", "mame", "--", "/no/such/program-anywhere"]])
def test_launch_without_a_command_or_with_one_that_does_not_start_exits_2(
        desk: Desk, capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    code, out, err = run(capsys, *argv)
    assert code == 2 and out == "" and err, (out, err)


def test_a_shell_run_is_never_halted_so_dosbox_x_full_screen_on_a_second_display_prints_words(
        desk: Desk, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    code, out, _ = run(capsys, "words", "dosbox-x", "--fullscreen", "--display", "1")
    assert code == 0 and out.splitlines() == ["-set", "sdl display=1", "-fullscreen"]
