"""The demo runner against a real MCP server of the tests' own (`fixtures/demo/server.py`),
started over stdio by the real `mcp` library: each line of the output contract, its exit codes,
the README block and the normalisation."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from scry_core import demo as d
from scry_core import example, motion, png, verdict
from scry_core.verdict import EXIT_INVALID

SERVER = Path(__file__).resolve().parent / "fixtures" / "demo" / "server.py"
FIXTURE_AVI = SERVER.with_name("screen.avi")
#: What the fixture's recording holds: 72 frames at 60 a second.
FIXTURE_FRAMES, FIXTURE_MS = 72, 1200
needs_loop_programs = pytest.mark.skipif(
    any(shutil.which(name) is None for name in motion.PROGRAMS),
    reason="a loop is made by ffmpeg and img2webp on PATH")
README = (f"# A demo\n\n{d.MOTION_BEGIN}\nold motion\n{d.MOTION_END}\n\nBefore.\n\n"
          f"{d.BEGIN}\nold block\n{d.END}\n\nAfter.\n")


def _said(field: str) -> Any:
    return lambda reply, run: f"{field} {reply[field]}"


def _shot(tmp_path: Path) -> Path:
    return tmp_path / "out" / "shot.png"


def _demo(tmp_path: Path, steps: list[d.Step] | None = None, **kw: Any) -> d.Demo:
    readme = tmp_path / "demos" / "x" / "README.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    default = [
        d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
               ask="Start the machine with the value 7.", title="Start it",
               reads="The reply says where the machine stands.", shown=("value",)),
        d.Step("look", "read", {}, _said("value"), ask="Read the value back.",
               title="Read it back", reads="`value` is what the start set."),
        d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
               lambda reply, run: "a picture"),
        d.Step("end", "close", {}, lambda reply, run: "closed"),
    ]
    fields: dict[str, Any] = {
        "name": "x", "root": tmp_path, "server": [sys.executable, str(SERVER)],
        "readme": readme, "steps": default if steps is None else steps,
        "capture": lambda run: run.dir / "shot.png"}
    fields.update(kw)
    return d.Demo(**fields)


def _readme(demo: d.Demo) -> Path:
    """The demo's README, which every demo of these cases has."""
    assert demo.readme is not None
    return demo.readme


def _run(demo: d.Demo, tmp_path: Path, *argv: str) -> int:
    return d.main(demo, ["--transcript", str(tmp_path / "out" / "transcript.md"), *argv])


def _calls(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _norm(tmp_path: Path) -> str:
    return (tmp_path / "out" / "transcript-normalised.md").read_text()


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calls.log"
    monkeypatch.setenv("DEMO_LOG", str(path))
    return path


def test_every_step_ok_prints_one_line_each_and_the_tally(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_demo(tmp_path), tmp_path) == verdict.EXIT_PASS
    lines = capsys.readouterr().out.splitlines()
    assert lines[:5] == ["OK boot: value 7", "OK look: value 7", "OK shot: a picture",
                         "OK end: closed", "DEMO x: 4 steps, 4 OK"]
    assert lines[5] == f"transcript: {(tmp_path / 'out' / 'transcript.md').resolve()}"
    assert lines[6].startswith("normalised: ") and len(lines) == 7
    whole = (tmp_path / "out" / "transcript.md").read_text()
    assert "Also attached: image/png." in whole and '"pid": ' in whole
    assert [c["summary"] for c in _calls(log)] == ["started", "read", "picture", "closed"], \
        "a run that ended with close was closed again"


def test_a_run_that_does_not_end_with_close_is_closed(tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {}, _said("value"))]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_PASS
    assert [c["summary"] for c in _calls(log)] == ["started", "closed"]


def test_a_failed_step_is_rc_1_stops_the_run_and_still_cleans_up(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def wrong(reply: d.Reply, run: d.Run) -> str:
        raise d.StepFailed("the value was not 8")

    steps = [d.Step("boot", "start", {}, wrong), d.Step("look", "read", {}, _said("value"))]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == ["FAIL boot: the value was not 8", "DEMO x: 2 steps, 0 OK"]
    assert [c["summary"] for c in _calls(log)] == ["started", "closed"], "read ran, or no close"
    assert "Cleanup `close`:" in (tmp_path / "out" / "transcript.md").read_text()


@pytest.mark.parametrize(("tool", "args", "line", "reason"), [
    ("refuse", {}, "FAIL s: refuse answered 'INVALID': ", "refused on purpose"),
    ("boom", {}, "FAIL s: boom answered 'error': ", "Error executing tool boom"),
    ("start", {"value": "x"}, "FAIL s: start answered 'error': ", "value"),
])
def test_a_reply_that_is_not_ok_fails_with_its_reason(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str], tool: str,
        args: dict[str, Any], line: str, reason: str) -> None:
    steps = [d.Step("s", tool, args, lambda reply, run: "never asked")]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith(line) and reason in first[len(line):], first


def _raises_bare_assertion(reply: d.Reply, run: d.Run) -> str:
    raise AssertionError


@pytest.mark.parametrize(("check", "line"), [
    (lambda reply, run: reply["value"] == 7, "FAIL s: the check returned True, not a summary"),
    (lambda reply, run: reply["nothing"], "FAIL s: KeyError: 'nothing'"),
    (_raises_bare_assertion, "FAIL s: AssertionError"),
    (lambda reply, run: "two\nlines", "OK s: two lines"),
])
def test_a_check_gives_one_line_with_a_reason(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str], check: Any,
        line: str) -> None:
    _run(_demo(tmp_path, [d.Step("s", "start", {}, check)]), tmp_path)
    assert capsys.readouterr().out.splitlines()[0] == line


def test_zero_steps_is_invalid_and_starts_nothing(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_demo(tmp_path, []), tmp_path) == verdict.EXIT_INVALID
    assert capsys.readouterr().out.startswith("INVALID: the demo x declares zero steps")
    assert _calls(log) == []


def test_a_precheck_that_names_a_reason_is_invalid(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, precheck=lambda run: "no ROM: get it from https://example.org/x.zip")
    assert _run(demo, tmp_path) == verdict.EXIT_INVALID
    assert capsys.readouterr().out == "INVALID: no ROM: get it from https://example.org/x.zip\n"
    assert _calls(log) == []


def test_an_error_before_the_verdict_is_invalid_not_a_traceback(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, precheck=lambda run: run.replies["nothing"])
    assert _run(demo, tmp_path) == verdict.EXIT_INVALID
    assert capsys.readouterr().out == "INVALID: KeyError: 'nothing'\n"


@pytest.mark.parametrize("server", [["no-such-server"],
                                    [sys.executable, "-c", "import sys; sys.exit(3)"]])
def test_a_server_that_does_not_start_is_invalid_and_says_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], server: list[str]) -> None:
    demo = _demo(tmp_path, server=[s if s != "no-such-server" else str(tmp_path / s)
                                   for s in server])
    assert _run(demo, tmp_path) == verdict.EXIT_INVALID
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("INVALID: the server did not start (") and "TaskGroup" not in line, line


def test_a_server_that_dies_mid_run_fails_the_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    steps = [d.Step("boot", "start", {}, _said("value")),
             d.Step("die", "die", {}, lambda reply, run: "never")]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    assert "OK boot: value 7\nFAIL die: " in capsys.readouterr().out
    assert "Cleanup `close` failed: " in (tmp_path / "out" / "transcript.md").read_text()


def test_a_call_that_never_answers_fails_at_the_bound(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(d, "CALL_TIMEOUT_S", 1)
    steps = [d.Step("nap", "sleep", {"seconds": 5}, lambda reply, run: "never")]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    assert capsys.readouterr().out.startswith("FAIL nap: ")


def test_a_session_that_ends_in_an_error_after_its_steps_fails(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    real_exit = Client.__aexit__

    async def broken_exit(self: Any, *exc: Any) -> None:
        await real_exit(self, *exc)
        raise RuntimeError("the transport closed badly")

    monkeypatch.setattr(Client, "__aexit__", broken_exit)
    steps = [d.Step("boot", "start", {}, _said("value"))]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    stderr = (tmp_path / "out" / "server.stderr").resolve()
    assert capsys.readouterr().out.splitlines()[:3] == [
        "OK boot: value 7", "FAIL x: the session with the server ended in an error "
        f"(RuntimeError: the transport closed badly); its stderr is in {stderr}",
        "DEMO x: 1 step, 1 OK"]


@pytest.mark.parametrize("argv", [["--bogus"], ["--update"], ["--rompath", "/x"], ["--shared"],
                                  ["--cwd", "/x"]])
def test_an_unknown_or_abbreviated_option_exits_2(tmp_path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        d.main(_demo(tmp_path), argv)
    assert exc.value.code == 2


def test_offered_options_reach_the_options_step_only_when_given(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, offers=frozenset({"cwd", "rompath", "shared"}), steps=[
        d.Step("boot", "start", {"binary": "default"}, _said("binary"), options=True),
        d.Step("again", "start", {"binary": "default"}, _said("binary"))])
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    assert _run(demo, tmp_path, "--binary", "/b") == verdict.EXIT_PASS
    assert [c["binary"] for c in _calls(log) if c["summary"] == "started"] == [
        "default", "default", "/b", "default"]
    normalised = _norm(tmp_path)
    assert '"binary": "/b"' in normalised and '"rompath"' not in normalised
    assert _run(demo, tmp_path, "--rompath", "/r", "--shared") == verdict.EXIT_PASS
    assert '"rompath": "/r",\n  "shared": true' in _norm(tmp_path)
    assert _run(demo, tmp_path, "--cwd", "/c") == verdict.EXIT_PASS
    assert '"cwd": "/c"' in _norm(tmp_path)


def test_the_display_the_run_opens_on_reaches_the_options_step(tmp_path: Path,
                                                               log: Path) -> None:
    demo = _demo(tmp_path, offers=frozenset({"shared", "display"}),
                 steps=[d.Step("boot", "start", {}, _said("value"), options=True)])
    assert _run(demo, tmp_path, "--shared", "--display", "1") == verdict.EXIT_PASS
    (call,) = [c for c in _calls(log) if c["summary"] == "started"]
    assert (call["shared"], call["display"]) == (True, 1), call
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    call = [c for c in _calls(log) if c["summary"] == "started"][-1]
    assert "display" not in call, "an option left out is absent"


def test_the_window_a_demo_asks_for_is_watched_behind_and_on_its_display(tmp_path: Path) -> None:
    assert d.window_args(d.Run(dir=tmp_path)) == {"shared": True, "background": True, "display": 0}
    named = d.Run(dir=tmp_path, options={"display": 1})
    assert d.window_args(named)["display"] == 1


def test_a_step_takes_only_the_options_it_names(tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, offers=frozenset({"shared"}), reads=frozenset({"shared"}), steps=[
        d.Step("boot", "start", lambda run: {"value": 9 if run.options.get("shared") else 7},
               _said("value"), options=frozenset({"binary"}))])
    assert _run(demo, tmp_path, "--binary", "/b", "--shared") == verdict.EXIT_PASS
    (call,) = [c for c in _calls(log) if c["summary"] == "started"]
    assert (call["binary"], call["value"]) == ("/b", 9), call
    assert '"shared"' not in _norm(tmp_path).split("```json")[1], "an option it does not take"


def test_an_option_given_that_nothing_takes_is_invalid(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, offers=frozenset({"shared"}), steps=[
        d.Step("boot", "start", {}, _said("value"), options=frozenset({"binary"}))])
    assert _run(demo, tmp_path, "--shared") == verdict.EXIT_INVALID
    assert capsys.readouterr().out.startswith("INVALID: options ['shared'] were given")
    assert _calls(log) == []


@pytest.mark.parametrize(("options", "reads"), [
    (frozenset({"binay"}), frozenset()), ("binary", frozenset()), (True, frozenset({"rompth"}))])
def test_a_demo_naming_an_option_the_runner_does_not_know_is_refused(
        tmp_path: Path, options: Any, reads: frozenset[str]) -> None:
    demo = _demo(tmp_path, reads=reads, steps=[d.Step("boot", "start", {}, _said("value"),
                                                      options=options)])
    with pytest.raises(ValueError):
        d.main(demo, [])


def test_options_given_with_no_step_to_take_them_are_invalid(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, steps=[d.Step("boot", "start", {}, _said("value"))])
    assert _run(demo, tmp_path, "--binary", "/b") == verdict.EXIT_INVALID
    assert capsys.readouterr().out.startswith("INVALID: options ['binary'] were given")
    assert _calls(log) == []


def test_a_demo_cannot_offer_an_option_the_runner_does_not_know(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rompth"):
        d.main(_demo(tmp_path, offers=frozenset({"rompth"})), [])


def test_update_readme_rewrites_the_block_and_the_capture(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    text = _readme(demo).read_text()
    examples = tmp_path / "out" / "transcript-examples.md"
    assert d.block_of(text) == examples.read_text().strip("\n")
    assert text.startswith("# A demo\n\n") and text.endswith("\n\nAfter.\n")
    assert "old motion" in text, "a demo with no moment had its motion block rewritten"
    assert (_readme(demo).parent / "screen.png").read_bytes() == _shot(tmp_path).read_bytes()
    assert d.readme_drift(_readme(demo), examples) == ""
    examples.write_text(examples.read_text().replace("Start it", "Stop it", 1))
    assert d.readme_drift(_readme(demo), examples).startswith("line 1: the README has ")


def _film(name: str = "film") -> d.Step:
    return d.recording(name, FIXTURE_FRAMES)


def _moment_demo(tmp_path: Path, **kw: Any) -> d.Demo:
    """The default demo with a recording after its picture, shown as its one moment."""
    steps = [
        d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
               ask="Start the machine with the value 7.", title="Start it",
               reads="The reply says where the machine stands.", shown=("value",)),
        d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
               lambda reply, run: "a picture", ask="Take a picture of the screen.",
               title="Take a picture", reads="`path` is the file the picture went to."),
        _film(),
        d.Step("end", "close", {}, lambda reply, run: "closed"),
    ]
    fields: dict[str, Any] = {"moments": (d.Moment("shot", "film", "The pattern moves."),),
                              "alt": "A test pattern moving"}
    fields.update(kw)
    return _demo(tmp_path, steps, **fields)


def test_a_recording_a_moment_shows_is_a_call_of_the_demo_s_own(
        tmp_path: Path, log: Path) -> None:
    assert _run(_moment_demo(tmp_path), tmp_path) == verdict.EXIT_PASS
    assert [c["summary"] for c in _calls(log)][-3:] == [
        "picture", f"record: {FIXTURE_FRAMES} frames", "closed"]
    assert (tmp_path / "out" / "film.avi").is_file(), "the run wrote no recording"
    normalised = _norm(tmp_path)
    assert "**3. `record`**" in normalised and "**4. `close`**" in normalised, normalised
    assert "./out/film.avi" in normalised, "the recording's path was not the run's"
    assert '"frame_before": "<volatile>"' in normalised, \
        "where the recording began is the host's and must not be compared"
    assert f'"frames": {FIXTURE_FRAMES}' in normalised, "the frames asked are the demo's own"
    block = (tmp_path / "out" / "transcript-motion.md").read_text()
    assert block == ('<p align="center"><picture><source media="(prefers-reduced-motion: '
                     'reduce)" srcset="screen.png"><img src="loop.webp" alt="A test pattern '
                     'moving"></picture></p>\n\n1. The pattern moves.\n\n'
                     f"<!-- moments-ms: {FIXTURE_MS} -->\n")


def test_a_recording_a_bound_or_a_stop_cut_is_a_failed_step(tmp_path: Path) -> None:
    check = d.recorded(FIXTURE_FRAMES)
    film = tmp_path / "film.avi"
    film.write_bytes(b"the recording")
    for ended in ("TIMEOUT", "OTHER_STOP"):
        reply = d.Reply({"status": "ok", "verdict": ended, "path": str(film),
                         "avi_frames": 1, "began": True, "ended": True})
        with pytest.raises(d.StepFailed, match=f"ended '{ended}'"):
            check(reply, d.Run(dir=tmp_path))


def test_a_recording_s_check_judges_the_reply_and_not_only_a_file_that_happens_to_be_there(
        tmp_path: Path) -> None:
    check = d.recorded(FIXTURE_FRAMES, lambda reply, run: "the game plays on")
    run = d.Run(dir=tmp_path)
    stale = tmp_path / "film.avi"
    stale.write_bytes(b"an earlier run's recording")
    with pytest.raises(d.StepFailed, match="names no `path`"):
        check(d.Reply({"status": "ok"}), run)
    with pytest.raises(d.StepFailed, match="did not both begin and end"):
        check(d.Reply({"status": "ok", "began": False, "ended": False, "path": str(stale)}), run)
    ended = {"status": "ok", "began": True, "ended": True, "verdict": "ELAPSED",
             "path": str(stale)}
    with pytest.raises(d.StepFailed, match="names no `avi_frames`"):
        check(d.Reply(ended), run)
    assert check(d.Reply({**ended, "avi_frames": 240}), run) == "the game plays on"
    stale.unlink()
    with pytest.raises(d.StepFailed, match="was not written by this call"):
        check(d.Reply({**ended, "avi_frames": 240}), run)


def test_an_earlier_run_s_recording_is_not_left_for_this_run(tmp_path: Path, log: Path) -> None:
    """`record` writes only a file that is not there yet, so the step clears its own."""
    stale = tmp_path / "out" / "film.avi"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"an earlier run's recording")
    assert _run(_moment_demo(tmp_path), tmp_path) == verdict.EXIT_PASS
    assert stale.read_bytes() == FIXTURE_AVI.read_bytes(), "an earlier run's recording was kept"


@needs_loop_programs
def test_update_readme_makes_the_loop_beside_the_capture_and_writes_the_motion_block(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _moment_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    loop = _readme(demo).with_name(motion.LOOP_NAME)
    data = loop.read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP" and b"ANIM" in data[:64], data[:64]
    assert 0 < len(data) <= motion.BUDGET_BYTES, len(data)
    text = _readme(demo).read_text()
    assert d.block_of(text, d.MOTION_BEGIN, d.MOTION_END) == (
        tmp_path / "out" / "transcript-motion.md").read_text().strip("\n")
    assert "old motion" not in text and "1. The pattern moves." in text
    assert f"{loop} rewritten: {len(data)} bytes, lossless, 1.2 s in 1 moment" \
        in capsys.readouterr().out


@needs_loop_programs
def test_a_loop_past_its_budget_is_invalid_naming_its_bytes(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    demo = _moment_demo(tmp_path)
    committed = _readme(demo).with_name(motion.LOOP_NAME)
    committed.write_bytes(b"the loop in the repository")
    monkeypatch.setattr(motion, "BUDGET_BYTES", 10)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    said = capsys.readouterr().out
    assert "INVALID: the loop is " in said and "bytes lossless and " in said \
        and "bytes lossy, past the 10-byte budget" in said, said
    assert _readme(demo).read_text() == README, "the README was written over a refused loop"
    assert committed.read_bytes() == b"the loop in the repository", \
        "a refused loop replaced the committed one"


def test_a_run_that_cannot_write_its_readmes_leaves_the_committed_loop_as_it_was(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "ffmpeg", "img2webp": "img2webp"})
    front = _front(tmp_path)

    def vanish(reply: d.Reply, run: d.Run) -> str:
        front.write_text("# no markers now\n")
        return "markers gone"

    demo = _moment_demo(tmp_path, front=front)
    demo = d.Demo(**{**demo.__dict__, "steps": [
        *demo.steps[:-1], d.Step("end", "close", {}, vanish)]})
    committed = _readme(demo).with_name(motion.LOOP_NAME)
    committed.write_bytes(b"the loop in the repository")
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert committed.read_bytes() == b"the loop in the repository"
    assert _readme(demo).read_text() == README


def test_a_loop_with_a_program_missing_is_invalid_by_name_and_runs_nothing(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/bin/ffmpeg" if name == "ffmpeg" else None)
    assert _run(_moment_demo(tmp_path), tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert "INVALID: img2webp is not on PATH, and a demo's loop.webp is made with ffmpeg and " \
        "img2webp" in capsys.readouterr().out
    assert _calls(log) == [], "the server ran for a loop that could not be made"
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(verdict.Invalid, match="ffmpeg and img2webp are not on PATH"):
        motion.programs()


def test_a_readme_without_its_motion_markers_is_invalid_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _moment_demo(tmp_path)
    bare = f"# A demo\n\n{d.BEGIN}\nold block\n{d.END}\n"
    _readme(demo).write_text(bare)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _readme(demo).read_text() == bare and _calls(log) == []


@needs_loop_programs
def test_stale_ignores_a_loop_s_bytes_and_names_what_departs_from_the_run(
        tmp_path: Path, log: Path) -> None:
    demo = _moment_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert d.stale(demo, tmp_path / "out") == []
    loop = _readme(demo).with_name(motion.LOOP_NAME)
    loop.write_bytes(loop.read_bytes() + b"another host's encoder")
    assert d.stale(demo, tmp_path / "out") == [], "a recording was compared byte for byte"
    readme = _readme(demo)
    readme.write_text(readme.read_text().replace("The pattern moves.", "It moves.", 1))
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and found[0].startswith("x's motion block: line 3: "), found
    readme.write_text(readme.read_text().replace("It moves.", "The pattern moves.", 1))
    loop.unlink()
    assert d.stale(demo, tmp_path / "out") == [f"x's {motion.LOOP_NAME} is not committed"]
    (readme.parent / "screen.png").unlink()
    assert d.stale(demo, tmp_path / "out") == ["x's screen.png is not this run's capture",
                                               f"x's {motion.LOOP_NAME} is not committed"]


@needs_loop_programs
def test_a_loop_that_cuts_its_frames_cuts_the_still_beside_it_and_stale_holds_it(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A capture twice the size of 2 x 1 frames whose loop keeps the right pixel: the still is
    that pixel's 2 x 2 block, and it stays this run's capture for `stale`."""
    big = png.encode(png.enlarged(png.Raster(2, 1, bytes((1, 2, 3, 4, 5, 6))), 2))

    def drawn(run: d.Run) -> dict[str, Any]:
        (run.dir / "big.png").write_bytes(big)
        return {}

    demo = _moment_demo(tmp_path, capture=lambda run: run.dir / "big.png")
    demo = d.Demo(**{**demo.__dict__, "steps": [
        *demo.steps[:-1], d.Step("end", "close", drawn, lambda reply, run: "closed")]})
    built = motion.build
    monkeypatch.setattr(motion, "build", lambda cuts, work: dataclasses.replace(
        built(cuts, work), kept=motion.Box(1, 0, 1, 1, (2, 1))))
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    still = _readme(demo).with_name("screen.png")
    assert png.decode(still.read_bytes()) == png.Raster(2, 2, bytes((4, 5, 6)) * 4)
    assert d.stale(demo, tmp_path / "out") == []
    still.write_bytes(png.encode(png.Raster(2, 2, bytes((7, 7, 7)) * 4)))
    assert d.stale(demo, tmp_path / "out") == ["x's screen.png is not this run's capture"]


@needs_loop_programs
def test_a_still_that_cannot_be_cut_as_its_loop_leaves_every_file_as_it_was(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    big = png.encode(png.Raster(4, 2, bytes(range(24))))

    def drawn(run: d.Run) -> dict[str, Any]:
        (run.dir / "big.png").write_bytes(big)
        return {}

    demo = _moment_demo(tmp_path, capture=lambda run: run.dir / "big.png")
    demo = d.Demo(**{**demo.__dict__, "steps": [
        *demo.steps[:-1], d.Step("end", "close", drawn, lambda reply, run: "closed")]})
    built = motion.build
    monkeypatch.setattr(motion, "build", lambda cuts, work: dataclasses.replace(
        built(cuts, work), kept=motion.Box(0, 0, 2, 1, (3, 1))))
    before = _readme(demo).read_text()
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _readme(demo).read_text() == before
    assert not (_readme(demo).parent / "screen.png").exists()
    assert not (_readme(demo).parent / d.FULL_NAME).exists()
    assert not (_readme(demo).parent / motion.LOOP_NAME).exists()


@pytest.mark.parametrize(("moments", "kw", "why"), [
    ((d.Moment("shot", "nope", "It moves."),), {}, r"names \['nope'\], which is no step"),
    ((d.Moment("boot", "film", "It moves."),), {}, "is a recording, so it shows what followed"),
    ((d.Moment("boot", "shot", "It moves."),), {}, "and the demo's `video`"),
    ((d.Moment("shot", "boot", "It moves."),), {"video": lambda run: run.dir},
     "needs 'boot' after 'shot'"),
    ((d.Moment("shot", "film", "It moves. Twice."),), {}, "its caption is one sentence"),
    ((d.Moment("shot", "film", ""),), {}, "its caption is one sentence"),
    ((d.Moment("shot", "film", "It moves.", skip=-1),), {}, "neither is negative"),
    ((d.Moment("shot", "film", "It moves."),), {"alt": " "}, "does not say what moves"),
    ((d.Moment("shot", "film", "It moves."),) * 4, {}, "a loop shows at most 3"),
])
def test_a_moment_the_demo_s_steps_cannot_give_is_refused_before_a_call(
        tmp_path: Path, log: Path, moments: tuple[d.Moment, ...], kw: dict[str, Any],
        why: str) -> None:
    with pytest.raises(ValueError, match=why):
        d.main(_moment_demo(tmp_path, moments=moments, **kw),
               ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


@pytest.mark.parametrize(("step", "demo"), [
    ({"value": "varies here"}, {}), ({}, {"value": "the host's"}), ({}, {})])
def test_an_example_that_shows_a_field_its_run_hides_is_refused_before_a_call(
        tmp_path: Path, log: Path, step: dict[str, str], demo: dict[str, str]) -> None:
    """A page would print `<volatile>` where it promised a value; `pid` is hidden in every demo."""
    shown = ("value",) if step or demo else ("pid",)
    steps = [d.Step("boot", "start", {}, _said("value"), ask="Start it.", title="Start",
                    reads="It starts.", shown=shown, volatile=step)]
    hidden = shown[0]
    with pytest.raises(ValueError, match=rf"step boot: its example shows \['{hidden}'\], which "
                                         "the transcript hides"):
        d.main(_demo(tmp_path, steps, volatile=demo), ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


@pytest.mark.parametrize("shown", [("width", "sha256"), ("bytes",)])
def test_an_example_that_shows_a_written_pictures_digest_fails_its_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str],
        shown: tuple[str, ...]) -> None:
    """A written picture's size and digest are hidden by the reply's shape, which no declaration
    names: the page would print `<volatile>` where it promised a value."""
    steps = [d.Step("boot", "start", {}, _said("value")),
             d.Step("shot", "snap", lambda run: {"dest": run.dir / "s.png"},
                    lambda reply, run: "a picture", ask="Take a picture.", title="Shoot",
                    reads="It writes the picture.", shown=shown),
             d.Step("end", "close", {}, lambda reply, run: "closed")]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    said = capsys.readouterr().out
    assert f"FAIL shot: the example shows {sorted(set(shown) - {'width'})}, which the " \
           "transcript hides in a written picture" in said, said


def test_a_lead_that_answers_with_a_written_pictures_digest_fails_its_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    front = tmp_path / "README.md"
    front.write_text(LEAD_FRONT.format(begin=d.lead_begin("x"), end=d.lead_end("x")),
                     encoding="utf-8")
    steps = [d.Step("boot", "start", {}, _said("value")),
             d.Step("shot", "snap", lambda run: {"dest": run.dir / "s.png"},
                    lambda reply, run: "a picture"),
             _film(), d.Step("end", "close", {}, lambda reply, run: "closed")]
    lead = d.Lead(front=front, step="shot", ask="Take one.", caption="A picture taken.",
                  answer=("sha256",))
    demo = _demo(tmp_path, steps, lead=lead, alt="A test pattern moving",
                 moments=(d.Moment("shot", "film", "The pattern moves."),))
    assert _run(demo, tmp_path) == verdict.EXIT_FAIL
    said = capsys.readouterr().out
    assert "FAIL shot: the example shows ['sha256'], which the transcript hides in a written " \
           "picture" in said, said


def test_two_steps_of_one_name_are_refused_before_a_call(tmp_path: Path, log: Path) -> None:
    steps = [d.Step("look", "read", {}, _said("value")), d.Step("look", "read", {}, _said("value"))]
    with pytest.raises(ValueError, match=r"names \['look'\] more than once"):
        d.main(_demo(tmp_path, steps), ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []
    d.declared(_demo(tmp_path))


def _replies(**frames: Any) -> dict[str, d.Reply]:
    return {name: d.Reply({"status": "ok", **body}) for name, body in frames.items()}


def _session_video(tmp_path: Path) -> Path:
    """A session's own video in two files, as a change of video mode leaves it."""
    folder = tmp_path / "capture"
    folder.mkdir()
    for name in ("x_000.avi", "x_001.avi"):
        (folder / name).write_bytes(FIXTURE_AVI.read_bytes())
    return folder


def test_a_moment_between_two_steps_is_cut_from_the_session_s_video_by_the_replies_frames(
        tmp_path: Path) -> None:
    """The video's last frame is the last one a reply counted: 144 frames ending at frame 150,
    so the stretch after frame 100 begins at the video's frame 94, the second file's 22."""
    folder = _session_video(tmp_path)
    demo = _moment_demo(tmp_path, video=lambda run: folder, moments=(
        d.Moment("boot", "shot", "It moves."),
        d.Moment("boot", "shot", "It moves on.", skip=6, frames=20)))
    run = d.Run(dir=tmp_path, replies=_replies(
        boot={"frame": 100}, shot={"ran": [{"reply": {"frame": 110}}, {"reply": {"frame": 130}}]},
        film={"note": "counts none"}, end={"frame": 150}))
    assert d.cuts(demo, run) == [motion.Cut(folder / "x_001.avi", 22, 30),
                                 motion.Cut(folder / "x_001.avi", 28, 20)]
    still = d.Demo(**{**demo.__dict__, "moments": (d.Moment("shot", "end", "It moves."),)})
    assert d.cuts(still, d.Run(dir=tmp_path, replies=_replies(
        boot={"frame": 100}, shot={"read": "a step that moved nothing"}, film={"frame": 150},
        end={"note": "nor this one"}))) == [motion.Cut(folder / "x_001.avi", 22, 50)], \
        "a step that counts no frame stands at the last one counted before it"


@pytest.mark.parametrize(("frames", "why"), [
    ({"boot": {"frame": 60}, "shot": {"frame": 100}, "end": {"frame": 150}},
     "which no one file of"),
    ({"boot": {}, "shot": {"frame": 100}, "end": {"frame": 150}},
     "no reply up to step 'boot' counts a `frame`"),
    ({"boot": {"frame": 100}, "shot": {"frame": 130}, "end": {"note": "moved, uncounted"}},
     "the session's video holds 144 frames and the last reply to count one counts frame 130"),
    ({"boot": {"frame": True}, "shot": {"frame": 100}}, "no reply up to step 'boot' counts a"),
])
def test_a_moment_the_session_s_video_does_not_hold_is_invalid(
        tmp_path: Path, frames: dict[str, Any], why: str) -> None:
    folder = _session_video(tmp_path)
    demo = _moment_demo(tmp_path, video=lambda run: folder,
                        moments=(d.Moment("boot", "shot", "It moves."),))
    with pytest.raises(verdict.Invalid, match=why):
        d.cuts(demo, d.Run(dir=tmp_path, replies=_replies(**frames)))
    empty = tmp_path / "none"
    empty.mkdir()
    with pytest.raises(verdict.Invalid, match="the session wrote no video"):
        d.cuts(d.Demo(**{**demo.__dict__, "video": lambda run: empty}),
               d.Run(dir=tmp_path, replies=_replies(**frames)))


def test_a_moment_between_two_steps_of_a_demo_with_no_video_is_invalid(tmp_path: Path) -> None:
    demo = _moment_demo(tmp_path, moments=(d.Moment("boot", "shot", "It moves."),))
    with pytest.raises(verdict.Invalid, match="the demo x names no `video` for its moments"):
        d.cuts(demo, d.Run(dir=tmp_path, replies=_replies(boot={"frame": 1}, shot={"frame": 2})))


def test_a_moment_longer_than_its_stretch_is_invalid_and_one_with_a_skip_ends_with_it(
        tmp_path: Path) -> None:
    folder = _session_video(tmp_path)
    replies = _replies(boot={"frame": 100}, shot={"frame": 130}, end={"frame": 150})
    long = _moment_demo(tmp_path, video=lambda run: folder,
                        moments=(d.Moment("boot", "shot", "It moves.", skip=6, frames=40),))
    with pytest.raises(verdict.Invalid, match="shows frames 6 to 45 of a stretch of 30"):
        d.cuts(long, d.Run(dir=tmp_path, replies=replies))
    whole = d.Demo(**{**long.__dict__, "moments": (d.Moment("boot", "shot", "It moves.", skip=6),)})
    assert d.cuts(whole, d.Run(dir=tmp_path, replies=replies)) == [
        motion.Cut(folder / "x_001.avi", 28, 24)]
    film = {"film": {"path": str(FIXTURE_AVI), "avi_frames": FIXTURE_FRAMES}}
    skipped = _moment_demo(tmp_path, moments=(d.Moment("shot", "film", "It moves.", skip=10),))
    assert d.cuts(skipped, d.Run(dir=tmp_path, replies=_replies(**film))) == [
        motion.Cut(FIXTURE_AVI, 10, FIXTURE_FRAMES - 10)]
    past = _moment_demo(tmp_path, moments=(d.Moment("shot", "film", "It moves.", skip=10,
                                                    frames=FIXTURE_FRAMES),))
    with pytest.raises(verdict.Invalid, match="shows frames 10 to 81 of a stretch of 72"):
        d.cuts(past, d.Run(dir=tmp_path, replies=_replies(**film)))


def test_the_motion_block_s_alt_is_written_as_an_attribute(tmp_path: Path) -> None:
    demo = _moment_demo(tmp_path, alt='A "ball" & a <paddle>')
    block = d.motion_block(demo, [1000])
    assert 'alt="A &quot;ball&quot; &amp; a &lt;paddle&gt;"></picture>' in block
    picture, _, rest = block.partition("\n")
    assert picture.startswith('<p align="center"><picture><source media="(prefers-reduced-motion:'
                              ' reduce)" srcset="screen.png"><img src="loop.webp" ') \
        and picture.endswith("</picture></p>"), "the picture is not centred on its own line"
    assert rest.startswith("\n1. The pattern moves.\n"), "the moments are not under the picture"


def test_a_recording_is_given_the_seconds_a_slow_host_needs() -> None:
    args = _film().args
    assert callable(args)
    assert args(d.Run(dir=Path("out")))["seconds"] == d.RECORD_SECONDS == 300


def test_a_moment_that_skips_its_whole_stretch_is_invalid(tmp_path: Path) -> None:
    demo = _moment_demo(tmp_path, moments=(d.Moment("shot", "film", "It moves.", skip=72),))
    run = d.Run(dir=tmp_path, replies=_replies(film={"path": str(FIXTURE_AVI),
                                                     "avi_frames": FIXTURE_FRAMES}))
    with pytest.raises(verdict.Invalid, match="skips 72 frames of a stretch of 72"):
        d.cuts(demo, run)


def test_the_block_carries_the_steps_to_try_each_in_the_one_shape(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    block = d.block_of(_readme(demo).read_text())
    first, second = block.split("### 2. ")
    assert first.startswith("### 1. Start it\n\nAsk:\n\n> Start the machine with the value 7.\n\n"
                            "Call:\n\n```text\nstart(value=7)\n```\n\n"), first
    fields = len(_calls(log)[0])
    assert f'Reply, 1 of {fields} fields:\n\n```json\n{{\n  "value": 7\n}}\n```\n\n' \
        "The reply says where the machine stands.\n\n" \
        "<details><summary>The whole reply</summary>" in first, first
    assert '"pid": "<volatile>"' in first, "the whole reply is the normalised one"
    assert second.startswith("Read it back\n\nAsk:\n\n> Read the value back.\n\n") \
        and '"summary": "read"' in second, second
    assert "picture(" not in block and "close(" not in block, "only the steps with an ask"
    assert (_readme(demo).parent / d.FULL_NAME).read_text() == _norm(tmp_path)
    assert _norm(tmp_path).startswith(
        "Every call of the run with its reply, in order: 4 calls. `<volatile>` stands for a "
        "value that changes from run to run, and `<host>` for one this host decides.\n\n"
        "**1. `start`**: OK boot: value 7")


@pytest.mark.parametrize(("asks", "said"), [(0, "0 steps"), (1, "1 step"), (5, "5 steps")])
def test_a_readme_offers_two_to_four_steps_to_try_or_nothing_runs(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str], asks: int,
        said: str) -> None:
    steps = [d.Step(f"look {n}", "read", {}, _said("value"), ask="Read the value.",
                    title="Read it", reads="It is the value.") if n < asks else
             d.Step(f"look {n}", "read", {}, _said("value")) for n in range(5)]
    assert _run(_demo(tmp_path, steps), tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert f"INVALID: the demo x marks {said} with an `ask`, and a README offers 2 to 4 to " \
        "try" in capsys.readouterr().out
    assert _calls(log) == []


def test_stale_reads_the_committed_whole_run(tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert d.stale(demo, tmp_path / "out") == []
    whole = _readme(demo).parent / d.FULL_NAME
    whole.write_text(whole.read_text().replace("value 7", "value 8", 1))
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and found[0].startswith(f"x's {d.FULL_NAME}: line "), found
    whole.unlink()
    assert d.stale(demo, tmp_path / "out") == [f"x's {d.FULL_NAME} is not committed"]


def test_stale_names_what_a_run_did_not_write_and_does_not_raise(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    (tmp_path / "out" / "transcript-examples.md").unlink()
    (tmp_path / "out" / "transcript-normalised.md").unlink()
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and "wrote no" in found[0] \
        and "transcript-examples.md" in found[0], found


@pytest.mark.parametrize(("fields", "why"), [
    ({"ask": "word " * 26, "reads": "It reads."}, "`ask` is 26 words, and an ask is 1 to 25"),
    ({"ask": "", "reads": "It reads."}, "`ask` is 0 words"),
    ({"ask": "Read it.", "reads": ""}, "`reads` is 0 words"),
    ({"ask": "Read it.", "reads": "One. Two. Three."}, "`reads` is 3 words in 3 sentences"),
    ({"ask": "Read it.", "reads": "word " * 41}, "`reads` is 41 words in 1 sentences"),
    ({"title": "A title and nothing to ask"}, "`ask` is 0 words"),
    ({"ask": "Read it.", "reads": "It reads."}, "an example carries a `title`"),
])
def test_an_example_past_its_limits_is_refused_before_a_call(
        tmp_path: Path, log: Path, fields: dict[str, str], why: str) -> None:
    demo = _demo(tmp_path, [d.Step("boot", "start", {}, _said("value"),
                                   ask=fields.get("ask", ""), title=fields.get("title", ""),
                                   reads=fields.get("reads", ""))])
    with pytest.raises(ValueError, match=f"step boot: {why}"):
        d.main(demo, ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


@pytest.mark.parametrize("readme", ["no markers\n", f"{d.BEGIN}\n{d.BEGIN}\n{d.END}\n",
                                    f"{d.BEGIN}\n{d.END}\n{d.END}\n", f"{d.END}\n{d.BEGIN}\n"])
def test_markers_not_there_once_are_invalid_and_write_nothing(
        tmp_path: Path, log: Path, readme: str) -> None:
    demo = _demo(tmp_path)
    _readme(demo).write_text(readme)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _readme(demo).read_text() == readme
    assert not (_readme(demo).parent / "screen.png").exists()
    assert _calls(log) == [], "the server ran although the README could not take the block"


def test_a_failed_run_leaves_the_readme_as_it_was(tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, [*_demo(tmp_path).steps[:2],
                            d.Step("no", "refuse", {}, lambda reply, run: "")])
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_FAIL
    assert _readme(demo).read_text() == README


def test_a_capture_this_run_did_not_write_leaves_the_readme_as_it_was(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A picture an earlier run left at the capture's path is not this run's picture."""
    _shot(tmp_path).parent.mkdir(parents=True)
    _shot(tmp_path).write_bytes(b"an old picture")
    demo = _demo(tmp_path, [*_demo(tmp_path).steps[:2]])
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _readme(demo).read_text() == README
    assert not (_readme(demo).parent / "screen.png").exists()
    assert "INVALID: the capture" in capsys.readouterr().out


def test_a_volatile_key_is_hidden_and_a_shown_value_is_not(tmp_path: Path, log: Path) -> None:
    assert _run(_demo(tmp_path), tmp_path) == verdict.EXIT_PASS
    whole = (tmp_path / "out" / "transcript.md").read_text()
    norm = _norm(tmp_path)
    assert '"pid": "<volatile>"' in norm and '"pid": "<volatile>"' not in whole
    assert norm.count('"value": 7') == 3, "a shown value was normalised away (one argument, " \
        "two replies)"
    assert '"where": "."' in norm and str(tmp_path) not in norm
    dest = json.dumps("./out/shot.png")
    assert f'"dest": {dest}' in norm, "a Path argument was not sent as its text"


def test_a_demo_declares_its_own_volatile_keys_and_its_arguments_keep_theirs(
        tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True),
             d.Step("look", "read", {}, _said("value"))]
    demo = _demo(tmp_path, steps, volatile={"value": "the test says so"})
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    norm = _norm(tmp_path)
    assert '"value": "<volatile>"' in norm, "the reply's value was shown"
    assert '"value": 7' in norm, "the demo's own argument was hidden"


def test_a_step_hides_its_own_volatile_keys_and_no_other_step_does(
        tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {}, _said("value"), volatile={"value": "varies here"}),
             d.Step("look", "read", {}, _said("value"))]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_PASS
    boot, look = _norm(tmp_path).split("**2. ")
    assert '"value": "<volatile>"' in boot and '"value": 7' not in boot.split("```json")[2]
    assert '"pid": "<volatile>"' in boot, "the step's keys replaced the module's list"
    assert '"value": 7' in look, "a step's volatile key was hidden in another step"
    with pytest.raises(ValueError, match="not a mapping"):
        d.main(_demo(tmp_path, [d.Step("s", "start", {}, _said("value"),
                                       volatile={"value"})]), [])  # type: ignore[arg-type]


def test_a_key_a_reply_carries_only_sometimes_is_dropped_whether_it_came_or_not(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Where a host-timed stop lands is the host's, and a server says so in `note` only there."""
    def normalised(optional: dict[str, str], note: str) -> str:
        monkeypatch.setenv("DEMO_NOTE", note)
        steps = [d.Step("boot", "start", {}, _said("value")),
                 d.Step("look", "read", {}, _said("value"), optional=optional)]
        assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_PASS
        return _norm(tmp_path)

    landed = "the stop landed in the BIOS idle handler"
    optional = {"note": "the host decides where the stop lands"}
    came = normalised(optional, landed)
    assert landed in (tmp_path / "out" / "transcript.md").read_text(), "the run never sent it"
    assert came == normalised(optional, "") and '"note"' not in came
    assert normalised({}, landed) != normalised({}, ""), "the control could not tell them apart"
    for bad, why in (({"note"}, "not a mapping"), ({"value": "x"}, "shows it")):
        with pytest.raises(ValueError, match=why):
            d.main(_demo(tmp_path, [d.Step("s", "start", {}, _said("value"), shown=("value",),
                                           optional=bad)]), [])  # type: ignore[arg-type]


def test_a_host_argument_is_hidden_and_the_demos_own_are_not(tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {"value": 7, "binary": "-set sdl display=1"},
                    _said("value"))]
    # The fixture's `start` echoes `binary` in its reply, so the demo declares that key too.
    demo = _demo(tmp_path, steps, host_args={"binary": "where this host puts a window"},
                 volatile={"binary": "the reply echoes the host's argument"})
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    norm = _norm(tmp_path)
    assert "display=1" not in norm, "a host value reached the normalised transcript"
    assert '"binary": "<host>"' in norm.split("```json")[1], "the call did not hide it"
    assert '"value": 7' in norm, "the demo's own argument was hidden"
    assert "display=1" in (tmp_path / "out" / "transcript.md").read_text()
    n = d.Normaliser(tmp_path / "r", tmp_path / "h", {}, {"binary": "x"})
    assert n.arguments({"a": [{"binary": "p"}], "binary": "q", "c": str(tmp_path / "r" / "f")}) \
        == {"a": [{"binary": "<host>"}], "binary": "<host>", "c": "./f"}


def test_the_normaliser_matches_whole_path_prefixes_only() -> None:
    m, sep = str(Path(Path.cwd().anchor, "Users", "m")), os.sep
    n = d.Normaliser(Path(m, "repo"), Path(m), d.VOLATILE)
    got = n.reply({"a": [f"{m}{sep}repo{sep}x", f"{m}{sep}y", 3, (m,)],
                   f"{m}{sep}k": {"pid": 9, "b": f"{m}x{sep}f {m}{sep}repo-notes{sep}a"},
                   "c": f"at {m}: here"})
    assert got == {"a": ["./x", "~/y", 3, ["~"]],
                   "~/k": {"pid": "<volatile>", "b": f"{m}x{sep}f ~/repo-notes/a"},
                   "c": "at ~: here"}
    assert d.Normaliser(Path("/"), Path("/"), {}).text("/a/b") == "/a/b"


def test_a_reply_is_a_mapping() -> None:
    reply = d.Reply({"a": 1})
    assert "a" in reply and "b" not in reply and dict(reply) == {"a": 1} and len(reply) == 1


def test_a_text_only_reply_is_still_read(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A reply with no structured document is read from its text: a JSON document as itself,
    anything else wrapped, and a wrapped one carries no `ok` status."""
    steps = [d.Step("doc", "plain", {"text": '{"status": "ok", "n": 3}'},
                    lambda reply, run: f"n {reply['n']}"),
             d.Step("list", "plain", {"text": "[1, 2]"}, lambda reply, run: "never")]
    assert _run(_demo(tmp_path, steps), tmp_path) == verdict.EXIT_FAIL
    assert capsys.readouterr().out.startswith(
        "OK doc: n 3\nFAIL list: plain answered None: no reason given")
    assert d._document("[1, 2]") == {"value": [1, 2]}
    assert d._document("not json") == {"text": "not json"}


def test_first_difference_names_the_line() -> None:
    assert d.first_difference("a\nb", "a\nb") == ""
    assert d.first_difference("a\nb", "a\nc") == "line 2: the README has 'b', the run has 'c'"
    assert d.first_difference("a", "a\nb") == "line 2: the README has 1, the run 2"


START_SHOWN = ("value", "binary", "where")
FRONT = "# The server\n\nWhy.\n\n{begin}\nold flow\n{end}\n\nMore why.\n"


def _front(tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(FRONT.format(begin=d.flow_begin("x"), end=d.flow_end("x")), encoding="utf-8")
    return path


def _shown_demo(tmp_path: Path) -> d.Demo:
    return _demo(tmp_path, front=_front(tmp_path))


def test_update_readme_writes_the_shown_steps_into_the_front_door_between_its_prose(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert demo.front is not None
    text = demo.front.read_text()
    assert text.startswith("# The server\n\nWhy.\n\n") and text.endswith("\n\nMore why.\n"), text
    flow = text[text.index(d.flow_begin("x")):text.index(d.flow_end("x"))]
    assert "```text\nread()\n```" in flow and '"value": 7' in flow, flow
    assert "#### 1. Start it\n" in flow and "> Read the value back." in flow, flow
    assert "picture(" not in flow and "close(" not in flow, "only the steps with an ask"
    assert "The whole reply" not in flow, "the front door carries no whole reply"
    assert d.flow_drift(demo.front, "x", tmp_path / "out" / "transcript-flow.md") == ""


def test_a_flow_that_departs_from_the_run_is_drift_naming_the_line(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert demo.front is not None
    demo.front.write_text(demo.front.read_text().replace('"value": 7', '"value": 8'))
    assert d.flow_drift(demo.front, "x", tmp_path / "out" / "transcript-flow.md").startswith(
        "line ")


def test_a_front_door_without_its_flow_markers_is_invalid_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert demo.front is not None
    demo.front.write_text("# The server\n")
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert demo.front.read_text() == "# The server\n" and _calls(log) == []


LEAD_FRONT = "# The server\n\n**What it does.**\n\n{begin}\nold lead\n{end}\n\n## Install\n"


def _lead_demo(tmp_path: Path, **kw: Any) -> d.Demo:
    """The demo with a moment, opening its repository's README with its loop and its `shot`."""
    front = tmp_path / "README.md"
    front.write_text(LEAD_FRONT.format(begin=d.lead_begin("x"), end=d.lead_end("x")),
                     encoding="utf-8")
    fields: dict[str, Any] = {"front": front, "step": "boot",
                              "ask": "Start the machine with `value` 7 & tell me <where>.",
                              "caption": "A pattern, moved by `record`.",
                              "answer": ("value", "summary")}
    fields.update(kw)
    return _moment_demo(tmp_path, lead=d.Lead(**fields))


@needs_loop_programs
def test_update_readme_opens_the_front_door_with_the_loop_and_one_exchange_of_the_run(
        tmp_path: Path, log: Path) -> None:
    demo = _lead_demo(tmp_path)
    assert demo.lead is not None
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    text = demo.lead.front.read_text()
    assert text.startswith("# The server\n\n**What it does.**\n\n") \
        and text.endswith("\n\n## Install\n"), text
    block = d.block_of(text, d.lead_begin("x"), d.lead_end("x"))
    assert block == (tmp_path / "out" / "transcript-lead.md").read_text().strip("\n")
    assert block.splitlines() == [
        '<p align="center"><a href="demos/x/"><picture><source media="(prefers-reduced-motion: '
        'reduce)" srcset="demos/x/screen.png"><img src="demos/x/loop.webp" alt="A test pattern '
        'moving"></picture></a></p>',
        '<p align="center"><em>A pattern, moved by <code>record</code>.</em></p>',
        "",
        '<table align="center">',
        '<tr><th align="left">You ask</th><td>Start the machine with <code>value</code> 7 &amp; '
        "tell me &lt;where&gt;.</td></tr>",
        '<tr><th align="left">Your client calls</th><td><code>start(value=7)</code></td></tr>',
        '<tr><th align="left">SCRY answers</th><td><code>{"value": 7, "summary": "started"}'
        "</code></td></tr>",
        "</table>"], block
    assert d.stale(demo, tmp_path / "out") == []
    learning = _lead_demo(tmp_path, learns=True)
    assert _run(learning, tmp_path, "--update-readme") == verdict.EXIT_PASS
    rows = d.block_of(demo.lead.front.read_text(), d.lead_begin("x"), d.lead_end("x"))
    assert rows.splitlines()[-2:] == [
        '<tr><th align="left">Your client learns</th><td>value 7</td></tr>', "</table>"], \
        "the check's own reading of the reply is not the last row"
    demo.lead.front.write_text(text.replace('"value": 7,', '"value": 8,'))
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and found[0].startswith("the README's x lead: line 7: "), found


#: A lead's declaration that cannot be given, with what its refusal says.
LEAD_REFUSED: list[tuple[dict[str, Any], str]] = [
    ({"step": "nope"}, "its lead names the step 'nope', which is no step of it"),
    ({"answer": ("pid",)}, r"its lead answers with \['pid'\], which the transcript hides"),
    ({"answer": ()}, "its lead's `answer` is \\(\\), not a tuple of the reply's field names"),
    ({"caption": "It moves. Twice."}, "its lead's caption is one sentence of at most 25 words"),
    ({"caption": " "}, "its lead's caption is one sentence"),
    ({"ask": "word " * 26}, "its lead's `ask` is 26 words, and an ask is 1 to 25"),
    ({"ask": " "}, "its lead's `ask` is 0 words, and an ask is 1 to 25"),
    ({"answer": "summary"}, "its lead's `answer` is 'summary', not a tuple of the reply's"),
    ({"moments": ()}, "opens a README with its loop, and it declares no moment"),
    ({"readme": None}, "opens a README with its loop, and it declares no moment or no page"),
]


@pytest.mark.parametrize(("kw", "why"), LEAD_REFUSED)
def test_a_lead_the_demo_cannot_give_is_refused_before_a_call(
        tmp_path: Path, log: Path, kw: dict[str, Any], why: str) -> None:
    of_the_demo: dict[str, Any] = {key: kw.pop(key) for key in ("moments", "readme")
                                   if key in kw}
    demo = _lead_demo(tmp_path, **kw)
    fields: dict[str, Any] = {**demo.__dict__, **of_the_demo}
    demo = d.Demo(**fields)
    with pytest.raises(ValueError, match=why):
        d.main(demo, ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


@pytest.mark.parametrize("where", ["step.volatile", "step.optional", "demo.volatile"])
def test_a_lead_answer_hidden_or_dropped_anywhere_is_refused_before_a_call(
        tmp_path: Path, log: Path, where: str) -> None:
    demo = _lead_demo(tmp_path, answer=("value",))
    reason = {"value": "it differs between runs"}
    boot = d.Step(**{**demo.steps[0].__dict__, "shown": ("summary",)})
    if where == "demo.volatile":
        demo = d.Demo(**{**demo.__dict__, "steps": [boot, *demo.steps[1:]], "volatile": reason})
    else:
        boot = d.Step(**{**boot.__dict__, where.split(".")[1]: reason})
        demo = d.Demo(**{**demo.__dict__, "steps": [boot, *demo.steps[1:]]})
    with pytest.raises(ValueError, match=r"its lead answers with \['value'\], which the "
                                         "transcript hides as the host's or drops"):
        d.main(demo, ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


def test_a_lead_that_opens_the_demo_s_own_page_is_refused_before_a_call(
        tmp_path: Path, log: Path) -> None:
    page = tmp_path / "demos" / "x" / "README.md"
    with pytest.raises(ValueError, match="its lead opens the demo's own page"):
        d.main(_lead_demo(tmp_path, front=page), ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


@needs_loop_programs
def test_a_flow_and_a_lead_in_one_readme_are_both_written(tmp_path: Path, log: Path) -> None:
    front = tmp_path / "README.md"
    demo = _lead_demo(tmp_path)
    front.write_text(f"# The server\n\n{d.lead_begin('x')}\nold lead\n{d.lead_end('x')}\n\n"
                     f"Between.\n\n{d.flow_begin('x')}\nold flow\n{d.flow_end('x')}\n\nAfter.\n")
    demo = d.Demo(**{**demo.__dict__, "front": front})
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    text = front.read_text()
    assert "old lead" not in text and "old flow" not in text, text
    assert '<table align="center">' in d.block_of(text, d.lead_begin("x"), d.lead_end("x"))
    assert "#### 1. Start it" in d.block_of(text, d.flow_begin("x"), d.flow_end("x"))
    assert "\n\nBetween.\n\n" in text and text.endswith("\n\nAfter.\n"), text
    assert d.stale(demo, tmp_path / "out") == []
    (tmp_path / "out" / "transcript-lead.md").unlink()
    assert d.stale(demo, tmp_path / "out") == [
        f"x: the run in {tmp_path / 'out'} wrote no transcript-lead.md"]


def test_a_lead_answer_is_judged_as_the_readme_spells_it(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A path under the repository reads `/path/to/<name>/...` in a README: an answer too long
    as this host spells it and short enough as the page does is an answer."""
    root = str(tmp_path.resolve())
    name = "b" * (example.COLUMNS - len(f"/path/to/{tmp_path.name}/"))
    binary = f"{root}/{name}"
    spelt = f"/path/to/{tmp_path.name}/{name}"
    assert len(binary) > example.COLUMNS == len(spelt), "the case needs a root this long"
    demo = _lead_demo(tmp_path, answer=("binary",))
    steps = [d.Step("boot", "start", {"value": 7, "binary": binary}, _said("value"),
                    ask="Start the machine.", title="Start it",
                    reads="The reply says where it stands."), *demo.steps[1:]]
    demo = d.Demo(**{**demo.__dict__, "steps": steps})
    assert _run(demo, tmp_path) == verdict.EXIT_PASS, capsys.readouterr().out
    assert f"<code>{spelt}</code>" in (tmp_path / "out" / "transcript-lead.md").read_text()


def test_the_exchange_s_call_is_one_line_with_its_long_values_cut(
        tmp_path: Path, log: Path) -> None:
    """Whole, this call takes two lines, which a page's example may; a README's exchange gives
    it one."""
    start = {"value": 7, "binary": "b" * 70, "shared": True, "display": 1}
    assert len(example.call_text("start", start).splitlines()) == 2
    demo = _lead_demo(tmp_path, answer=("value",))
    steps = [d.Step("boot", "start", start, _said("value"), ask="Start the machine.",
                    title="Start it", reads="The reply says where it stands."), *demo.steps[1:]]
    demo = d.Demo(**{**demo.__dict__, "steps": steps})
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    ends = d.LEAD_STRING_ENDS
    cut = f'start(value=7, binary="{"b" * ends}…{"b" * ends}", shared=true, display=1)'
    assert f"<td><code>{cut}</code></td>" in (tmp_path / "out" / "transcript-lead.md").read_text()
    assert ends < example.CALL_STRING_ENDS, "a phone wraps a call only between its arguments"
    fits = {"value": 7, "binary": "b" * 30}
    assert "…" not in example.call_text("start", fits, lines=1), "whole, it fits a line"
    steps = [d.Step("boot", "start", fits, _said("value"), ask="Start the machine.",
                    title="Start it", reads="The reply says where it stands."), *demo.steps[1:]]
    assert _run(d.Demo(**{**demo.__dict__, "steps": steps}), tmp_path) == verdict.EXIT_PASS
    assert f'<code>start(value=7, binary="{"b" * ends}…{"b" * ends}")</code>' in \
        (tmp_path / "out" / "transcript-lead.md").read_text(), "a phone cannot hold it whole"


def test_a_lead_outside_the_folder_its_readme_opens_is_refused_before_a_call(
        tmp_path: Path, log: Path) -> None:
    elsewhere = tmp_path / "other" / "README.md"
    elsewhere.parent.mkdir()
    elsewhere.write_text("# Another repository\n")
    with pytest.raises(ValueError, match="its lead opens .*README.md, and the demo's own page "
                                         "is not under that folder"):
        d.main(_lead_demo(tmp_path, front=elsewhere), ["--transcript", str(tmp_path / "t.md")])
    assert _calls(log) == []


def test_a_front_door_without_its_lead_markers_is_invalid_and_runs_nothing(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "ffmpeg", "img2webp": "img2webp"})
    demo = _lead_demo(tmp_path)
    assert demo.lead is not None
    demo.lead.front.write_text("# The server\n")
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert demo.lead.front.read_text() == "# The server\n" and _calls(log) == []


@pytest.mark.parametrize(("answer", "why"), [
    (("gone",), r"FAIL boot: the exchange answers with \['gone'\], which the reply does not"),
    (("where", "binary"), "FAIL boot: the exchange's answer is .* characters on its one line"),
])
def test_a_lead_answer_the_reply_cannot_give_on_one_line_fails_the_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str], answer: tuple[str, ...],
        why: str) -> None:
    import re
    demo = _lead_demo(tmp_path, answer=answer)
    steps = [d.Step("boot", "start", {"value": 7, "binary": "b" * 120}, _said("value"),
                    ask="Start the machine.", title="Start it",
                    reads="The reply says where it stands."), *demo.steps[1:]]
    demo = d.Demo(**{**demo.__dict__, "steps": steps})
    assert _run(demo, tmp_path) == verdict.EXIT_FAIL
    said = capsys.readouterr().out
    assert re.search(why, said)
    assert "DEMO x: 4 steps, 0 OK" in said and "ended in an error" not in said, \
        f"the failed step did not end the run as a failed step does: {said}"
    assert "**1. `start`**: FAIL boot: " in (tmp_path / "out" / "transcript.md").read_text()
    assert not (tmp_path / "out" / "transcript-lead.md").exists(), "a failed step is no exchange"


def _flow_of(tmp_path: Path, start: dict[str, Any]) -> str:
    """The flow a run writes when its `start` step, with `start` as its arguments, is shown."""
    demo = _demo(tmp_path, _asked(start, START_SHOWN), front=_front(tmp_path))
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    return (tmp_path / "out" / "transcript-flow.md").read_text()


def _asked(start: dict[str, Any], shown: tuple[str, ...]) -> list[d.Step]:
    """Two steps to try: a `start` whose excerpt shows `shown`, and a picture."""
    return [d.Step("boot", "start", start, _said("value"), options=True, shown=shown,
                   ask="Start the machine.", title="Start it",
                   reads="The reply says where it stands."),
            d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
                   lambda reply, run: "a picture", ask="Take a picture.", title="Take a picture",
                   reads="`path` is the file the picture went to.")]


def test_a_long_reply_is_shown_in_the_flow_abridged(tmp_path: Path, log: Path) -> None:
    flow = _flow_of(tmp_path, {"value": 7, "binary": "x" * 1000})
    call, reply = flow.split("Reply, 3 of ", 1)
    assert " ... (1000 characters)" in reply and "x" * 61 not in reply, flow
    assert f'binary="{"x" * 16}{example.ELIDED}{"x" * 16}"' in call, "a call's long value is cut"
    assert all(len(line) <= example.COLUMNS for line in flow.splitlines()), flow


def test_a_front_door_with_no_step_shown_is_a_declaration_error_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, [d.Step("boot", "start", {}, _said("value"))], front=_front(tmp_path))
    with pytest.raises(ValueError, match="no step carries an `ask` to show there"):
        _run(demo, tmp_path, "--update-readme")
    assert _calls(log) == [], "the server ran for a front door it could not fill"


def test_update_readme_on_a_demo_with_no_readme_is_invalid_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, readme=None)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _calls(log) == []


def test_a_step_that_names_its_fields_shows_only_those_in_that_order(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, _asked({"value": 7}, ("value", "summary")), front=_front(tmp_path))
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    flow = (tmp_path / "out" / "transcript-flow.md").read_text()
    assert '```json\n{\n  "value": 7,\n  "summary": "started"\n}\n```' in flow, flow
    assert '```json\n{\n  "summary": "picture"\n}\n```' in flow, "no field named shows the summary"


def test_a_field_the_front_door_shows_and_the_reply_lacks_fails_the_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, _asked({"value": 7}, ("value", "gone")), front=_front(tmp_path))
    assert _run(demo, tmp_path) == verdict.EXIT_FAIL
    assert "FAIL boot: the excerpt shows ['gone'], which the reply does not carry" \
        in capsys.readouterr().out


def test_a_shown_step_s_flow_is_the_normalised_reply(tmp_path: Path, log: Path) -> None:
    flow = _flow_of(tmp_path, {"value": 7})
    assert f'"where": "/path/to/{tmp_path.name}"' in flow and str(tmp_path) not in flow, flow


def test_a_front_door_whose_markers_go_mid_run_leaves_both_readmes_as_they_were(
        tmp_path: Path, log: Path) -> None:
    front = _front(tmp_path)

    def vanish(reply: d.Reply, run: d.Run) -> str:
        front.write_text("# no markers now\n")
        return "markers gone"

    boot, shot = _asked({"value": 7}, START_SHOWN)
    demo = _demo(tmp_path, [boot, d.Step(shot.name, shot.tool, shot.args, vanish, ask=shot.ask,
                                         title=shot.title, reads=shot.reads)], front=front)
    before = _readme(demo).read_text()
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _readme(demo).read_text() == before
    assert not (_readme(demo).parent / "screen.png").exists()


def test_a_run_that_writes_no_flow_leaves_no_earlier_flow_behind(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path) == verdict.EXIT_PASS
    failing = _demo(tmp_path, [d.Step("no", "refuse", {}, lambda reply, run: "")],
                    front=_front(tmp_path))
    failing = d.Demo(**{**failing.__dict__, "steps": [
        d.Step("no", "refuse", {}, lambda reply, run: "", shown=("status",),
               ask="Ask for a refusal.", title="Be refused", reads="It refuses.")]})
    _run(failing, tmp_path)
    assert not (tmp_path / "out" / "transcript-flow.md").exists()


def test_stale_names_each_way_a_demo_s_committed_files_depart_from_a_run(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    run_dir = tmp_path / "out"
    assert d.stale(demo, run_dir) == []
    assert demo.front is not None and demo.readme is not None
    demo.front.write_text(demo.front.read_text().replace('"value": 7', '"value": 8'))
    (demo.readme.parent / "screen.png").write_bytes(b"other")
    found = d.stale(demo, run_dir)
    assert len(found) == 2 and found[0].startswith("the front door's x flow: line "), found
    assert found[1] == "x's screen.png is not this run's capture", found
    readme = demo.readme
    readme.write_text(readme.read_text().replace('"value": 7', '"value": 9', 1))
    assert d.stale(demo, run_dir)[0].startswith("x's README: line "), d.stale(demo, run_dir)
    bare = d.Demo(**{**demo.__dict__, "readme": None, "front": None,
                     "steps": [d.Step("boot", "start", {}, _said("value"))]})
    assert d.stale(bare, run_dir) == []


def test_stale_takes_a_picture_compressed_another_way_as_this_run_s_capture(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert demo.readme is not None and demo.capture is not None
    committed = demo.readme.parent / "screen.png"
    raster = png.Raster(4, 2, bytes([0, 1, 2, 3, 3, 2, 1, 0]), ((0, 0, 0), (9, 9, 9), (7, 0, 0),
                                                               (0, 7, 0)))
    usual = png.encode(raster)
    demo.capture(d.Run(dir=tmp_path / "out")).write_bytes(usual)
    level = png.ZLIB_LEVEL
    try:
        png.ZLIB_LEVEL = 0  # another host's zlib: the same pixels in other bytes
        other = png.encode(raster)
    finally:
        png.ZLIB_LEVEL = level
    assert other != usual
    committed.write_bytes(other)
    assert d.stale(demo, tmp_path / "out") == []
    flipped = bytes([raster.pixels[0] ^ 1]) + raster.pixels[1:]
    committed.write_bytes(png.encode(png.Raster(raster.width, raster.height, flipped,
                                                raster.palette)))
    assert d.stale(demo, tmp_path / "out") == ["x's screen.png is not this run's capture"]


def test_a_picture_s_size_and_digest_are_hidden_and_other_bytes_are_not(tmp_path: Path) -> None:
    norm = d.Normaliser(tmp_path, Path("/home/nobody-here"), {})
    shown = norm.reply({"image": {"path": "/x/shot.png", "bytes": 10, "sha256": "ab"},
                        "state": {"path": "/x/s.sav", "bytes": 10, "sha256": "ab"}})
    assert shown["image"] == {"path": "/x/shot.png", "bytes": d.VOLATILE_MARK,
                              "sha256": d.VOLATILE_MARK}
    assert shown["state"] == {"path": "/x/s.sav", "bytes": 10, "sha256": "ab"}


def test_a_mark_begins_a_path_and_its_text_is_taken_as_written(tmp_path: Path) -> None:
    norm = d.Normaliser(tmp_path, Path("/home/nobody-here"), {},
                        marks={"/tmp/bench": "C:\\d\\1", "/tmp/s9/": "$TMPDIR"})
    assert norm.text("/var/tmp/bench/a") == "/var/tmp/bench/a"
    assert norm.text("/tmp/bench/a") == "C:\\d\\1/a"
    assert norm.text("/tmp/s9/b") == "$TMPDIR/b"


def test_load_answers_the_demo_a_file_declares_without_running_it(tmp_path: Path) -> None:
    file = tmp_path / "demos" / "y" / "demo.py"
    file.parent.mkdir(parents=True)
    file.write_text("from pathlib import Path\nfrom scry_core.demo import Demo\n"
                    "DEMO = Demo(name='y', root=Path('.'), server=['true'], steps=[])\n")
    assert d.load(file).name == "y"
    file.write_text("DEMO = 3\n")
    with pytest.raises(TypeError, match="not a Demo"):
        d.load(file)
    with pytest.raises(TypeError, match="cannot be imported"):
        d.load(tmp_path / "demo.txt")


def test_a_flow_spells_the_repository_as_an_absolute_placeholder(
        tmp_path: Path, log: Path) -> None:
    flow = _flow_of(tmp_path, {"value": 7, "binary": str(tmp_path / "bin" / "x")})
    placed = json.dumps(f"/path/to/{tmp_path.name}/bin/x")
    assert placed in flow and json.dumps("./bin/x") not in flow, flow


@pytest.mark.parametrize("shown", ["value", True, ("value", 3)])
def test_a_shown_that_is_not_a_tuple_of_field_names_is_refused_before_a_call(
        tmp_path: Path, shown: object) -> None:
    with pytest.raises(ValueError, match="`shown` is"):
        d.main(_demo(tmp_path, [d.Step("s", "start", {}, _said("value"),
                                       shown=shown)]), [])  # type: ignore[arg-type]


def test_a_windows_path_under_the_root_is_spelt_with_forward_slashes() -> None:
    """A block regenerated on Windows reads as the one regenerated on macOS."""
    norm = d.Normaliser(root=Path(r"C:\Users\ann\Code\scry"), home=Path(r"C:\Users\ann"),
                           volatile={})
    assert norm.text(r"path=C:\Users\ann\Code\scry\demos\bricks\bricks.sym, ok") == (
        "path=./demos/bricks/bricks.sym, ok")
    assert norm.text(r"C:\Users\ann\notes.txt") == "~/notes.txt"
    assert norm.text(r"C:\Users\annette\x") == r"C:\Users\annette\x", (
        "a longer name is not under it")


def test_two_paths_joined_by_a_colon_are_each_spelt_from_the_root() -> None:
    m, sep = str(Path(Path.cwd().anchor, "Users", "m")), os.sep
    norm = d.Normaliser(root=Path(m, "proj"), home=Path(m), volatile={})
    assert norm.text(f"{m}{sep}a:{m}{sep}b") == "~/a:~/b"
    assert norm.text(f"x={m}{sep}proj{sep}c&{m}{sep}d|{m}{sep}e") == "x=./c&~/d|~/e"


@pytest.mark.parametrize("option", ["--cwd", "--binary", "--rompath"])
def test_an_option_that_names_a_path_is_refused_empty(
        tmp_path: Path, log: Path, option: str, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, offers=frozenset({"cwd", "rompath"}))
    code = d.main(demo, ["--transcript", str(tmp_path / "t.md"), option, ""])
    assert code == EXIT_INVALID, code
    assert f"{option} names a path" in capsys.readouterr().out


def test_expect_passes_a_true_claim_and_fails_a_false_one_with_its_reason() -> None:
    d.expect(True, "never read")
    with pytest.raises(d.StepFailed, match="the value was not 8"):
        d.expect(False, "the value was not 8")
