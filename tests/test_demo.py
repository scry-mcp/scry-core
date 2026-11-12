"""The demo runner against a real MCP server of the tests' own (`fixtures/demo/server.py`),
started over stdio by the real `mcp` library: each line of the output contract, its exit codes,
the README block and the normalisation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.client import Client

from scry_core import demo as d
from scry_core import png, verdict
from scry_core.verdict import EXIT_INVALID

SERVER = Path(__file__).resolve().parent / "fixtures" / "demo" / "server.py"
README = f"# A demo\n\nBefore.\n\n{d.BEGIN}\nold block\n{d.END}\n\nAfter.\n"


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
        d.Step("boot", "start", {"value": 7}, _said("value"), options=True),
        d.Step("look", "read", {}, _said("value")),
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
    assert d.block_of(text) == _norm(tmp_path).strip("\n")
    assert text.startswith("# A demo\n\nBefore.\n\n") and text.endswith("\n\nAfter.\n")
    assert (_readme(demo).parent / "screen.png").read_bytes() == _shot(tmp_path).read_bytes()
    normalised = tmp_path / "out" / "transcript-normalised.md"
    assert d.readme_drift(_readme(demo), normalised) == ""
    normalised.write_text(normalised.read_text().replace("value 7", "value 8", 1))
    assert d.readme_drift(_readme(demo), normalised).startswith("line 1: the README has ")


def _loop_demo(tmp_path: Path) -> d.Demo:
    return _demo(tmp_path, loop=d.Loop("shot"))


def test_a_loop_is_recorded_right_after_the_step_it_follows(
        tmp_path: Path, log: Path) -> None:
    assert _run(_loop_demo(tmp_path), tmp_path) == verdict.EXIT_PASS
    assert [c["summary"] for c in _calls(log)][-3:] == ["picture", "record: 240 frames",
                                                        "closed"]
    assert (tmp_path / "out" / "loop.avi").is_file(), "the run wrote no loop"
    normalised = _norm(tmp_path)
    assert "**4. `record`**" in normalised and "**5. `close`**" in normalised, normalised
    assert "./out/loop.avi" in normalised, "the loop's path was not the run's"
    assert '"frame_before": "<volatile>"' in normalised, \
        "where the recording began is the host's and must not be compared"
    assert '"frames": 240' in normalised, "the frames asked are the demo's own"


def test_update_readme_converts_the_loop_beside_the_capture(
        tmp_path: Path, log: Path) -> None:
    demo = _loop_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    loop = _readme(demo).with_name(d.LOOP_MP4)
    assert loop.is_file(), "the loop was not converted"
    assert 0 < loop.stat().st_size <= d.LOOP_BUDGET_BYTES, loop.stat().st_size
    assert loop.read_bytes()[4:8] == b"ftyp", "not an MP4"


def test_a_loop_past_its_budget_is_invalid_naming_its_file_and_bytes(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    demo = _loop_demo(tmp_path)
    committed = _readme(demo).with_name(d.LOOP_MP4)
    committed.write_bytes(b"the loop in the repository")
    monkeypatch.setattr(d, "LOOP_BUDGET_BYTES", 10)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    said = capsys.readouterr().out
    assert f"INVALID: the loop {committed} is " in said and " bytes, past the 10-byte budget" \
        in said, said
    assert _readme(demo).read_text() == README, "the README was written over a refused loop"
    assert committed.read_bytes() == b"the loop in the repository", \
        "a refused conversion replaced the committed loop"


def test_a_run_that_cannot_write_its_readmes_leaves_the_committed_loop_as_it_was(
        tmp_path: Path, log: Path) -> None:
    front = _front(tmp_path)

    def vanish(reply: d.Reply, run: d.Run) -> str:
        front.write_text("# no markers now\n")
        return "markers gone"

    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
                    shown=START_SHOWN),
             d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"}, vanish)]
    demo = _demo(tmp_path, steps, front=front, loop=d.Loop("shot"))
    committed = _readme(demo).with_name(d.LOOP_MP4)
    committed.write_bytes(b"the loop in the repository")
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert committed.read_bytes() == b"the loop in the repository"


def test_a_loop_is_converted_from_a_tiny_avi_within_the_budget(tmp_path: Path) -> None:
    run, demos = tmp_path / "run", tmp_path / "demos"
    run.mkdir()
    demos.mkdir()
    avi = run / d.LOOP_AVI
    avi.write_bytes((Path(__file__).resolve().parent / "fixtures" / "demo"
                     / "screen.avi").read_bytes())
    data = d._convert_loop(avi, demos / d.LOOP_MP4)
    assert data[4:8] == b"ftyp" and 0 < len(data) <= d.LOOP_BUDGET_BYTES, len(data)
    assert not (demos / d.LOOP_MP4).exists(), "the conversion wrote the committed path itself"
    assert not (run / d.LOOP_MP4).exists(), "the staged conversion was left in the run"


def test_the_conversion_is_the_command_the_plan_decided(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H.264 to a muted MP4 at most three seconds long, trimmed by time, startable early."""
    run = tmp_path / "run"
    run.mkdir()
    avi = run / d.LOOP_AVI
    avi.write_bytes(b"an avi")
    seen: list[list[str]] = []

    def fake(argv: list[str], **_: Any) -> SimpleNamespace:
        seen.append(argv)
        Path(argv[-1]).write_bytes(b"an mp4")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake)
    assert d._convert_loop(avi, tmp_path / d.LOOP_MP4) == b"an mp4"
    (argv,) = seen
    assert Path(argv[0]).name == "ffmpeg" and argv[1:] == [
        "-y", "-i", str(avi), "-t", str(d.LOOP_SECONDS), "-an", "-c:v", "libx264", "-pix_fmt",
        "yuv420p", "-crf", "30", "-preset", "slow", "-movflags", "+faststart",
        str(run / d.LOOP_MP4)]


def test_the_loop_s_check_judges_the_reply_and_not_only_a_file_that_happens_to_be_there(
        tmp_path: Path) -> None:
    check = d._loop_step(d.Loop("shot")).check
    run = d.Run(dir=tmp_path)
    stale = tmp_path / "loop.avi"
    stale.write_bytes(b"an earlier run's recording")
    with pytest.raises(d.StepFailed, match="names no `path`"):
        check(d.Reply({"status": "ok"}), run)
    with pytest.raises(d.StepFailed, match="did not both begin and end"):
        check(d.Reply({"status": "ok", "began": False, "ended": False, "path": str(stale)}), run)
    ended = {"status": "ok", "began": True, "ended": True, "path": str(stale)}
    with pytest.raises(d.StepFailed, match="names no `avi_frames`"):
        check(d.Reply(ended), run)
    stale.unlink()
    with pytest.raises(d.StepFailed, match="was not written by this call"):
        check(d.Reply({**ended, "avi_frames": 240}), run)


def test_an_earlier_run_s_loop_is_not_left_for_this_run(
        tmp_path: Path, log: Path) -> None:
    stale = tmp_path / "out" / "loop.avi"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"an earlier run's recording")
    demo = _demo(tmp_path, steps=[d.Step("no", "refuse", {}, lambda reply, run: "")],
                 loop=d.Loop("no"))
    assert _run(demo, tmp_path) == verdict.EXIT_FAIL
    assert not stale.exists(), "an earlier run's loop was left for this run"


def test_a_loop_whose_avi_this_run_did_not_write_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(verdict.Invalid, match="wrote no loop.avi"):
        d._convert_loop(tmp_path / "loop.avi", tmp_path / "loop.mp4")


def test_a_loop_with_no_ffmpeg_on_the_path_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    avi = tmp_path / "loop.avi"
    avi.write_bytes(b"RIFF")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(verdict.Invalid, match="ffmpeg is not on PATH"):
        d._convert_loop(avi, tmp_path / "loop.mp4")


def test_a_loop_ffmpeg_cannot_read_is_invalid_with_its_own_words(
        tmp_path: Path) -> None:
    avi, mp4 = tmp_path / "loop.avi", tmp_path / "loop.mp4"
    avi.write_bytes(b"not an AVI at all")
    with pytest.raises(verdict.Invalid, match="ffmpeg refused to convert"):
        d._convert_loop(avi, mp4)
    assert not mp4.exists()


def test_stale_ignores_a_loop_s_bytes_and_names_one_that_is_not_committed(
        tmp_path: Path, log: Path) -> None:
    demo = _loop_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert d.stale(demo, tmp_path / "out") == []
    loop = _readme(demo).with_name(d.LOOP_MP4)
    loop.write_bytes(loop.read_bytes() + b"another host's encoder")
    assert d.stale(demo, tmp_path / "out") == [], "a recording was compared byte for byte"
    readme = _readme(demo)
    readme.write_text(readme.read_text().replace("value 7", "value 9", 1))
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and found[0].startswith("x's README: line "), found
    readme.write_text(readme.read_text().replace("value 9", "value 7", 1))
    loop.unlink()
    assert d.stale(demo, tmp_path / "out") == [f"x's {d.LOOP_MP4} is not committed"]
    (readme.parent / "screen.png").unlink()
    assert d.stale(demo, tmp_path / "out") == ["x's screen.png is not this run's capture",
                                               f"x's {d.LOOP_MP4} is not committed"]


def test_a_loop_that_follows_no_step_is_refused_before_a_call(
        tmp_path: Path, log: Path) -> None:
    with pytest.raises(ValueError, match="which is no step of it"):
        d.main(_demo(tmp_path, loop=d.Loop("nope")), ["--transcript",
                                                     str(tmp_path / "t.md")])
    assert _calls(log) == []


def _highlighted(tmp_path: Path) -> d.Demo:
    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
                    highlight="The boot call says where the machine stands."),
             d.Step("look", "read", {}, _said("value")),
             d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
                    lambda reply, run: "a picture", highlight="One call, one picture."),
             d.Step("end", "close", {}, lambda reply, run: "closed")]
    return _demo(tmp_path, steps)


def test_a_highlighted_demo_s_block_carries_its_highlights_and_links_the_whole_run(
        tmp_path: Path, log: Path) -> None:
    demo = _highlighted(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    block = d.block_of(_readme(demo).read_text())
    assert "The boot call says where the machine stands." in block
    assert "One call, one picture." in block
    assert "**1. `start`**" in block and "**3. `picture`**" in block
    assert "**2. `read`**" not in block and "**4. `close`**" not in block
    assert f"[{d.FULL_NAME}]({d.FULL_NAME})" in block and "4 calls" in block
    assert (_readme(demo).parent / d.FULL_NAME).read_text() == _norm(tmp_path)


def test_a_demo_with_no_highlight_keeps_the_whole_run_in_its_block(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert not (_readme(demo).parent / d.FULL_NAME).exists()


def test_stale_reads_the_committed_whole_run_of_a_highlighted_demo(
        tmp_path: Path, log: Path) -> None:
    demo = _highlighted(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert d.stale(demo, tmp_path / "out") == []
    whole = _readme(demo).parent / d.FULL_NAME
    whole.write_text(whole.read_text().replace("value 7", "value 8", 1))
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and found[0].startswith(f"x's {d.FULL_NAME}: line "), found
    whole.unlink()
    assert d.stale(demo, tmp_path / "out") == [f"x's {d.FULL_NAME} is not committed"]


def test_stale_flags_a_whole_run_left_by_a_demo_that_lost_its_highlights(
        tmp_path: Path, log: Path) -> None:
    demo = _highlighted(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    plain = d.Demo(**{**demo.__dict__, "steps": [
        d.Step(s.name, s.tool, s.args, s.check, options=s.options) for s in demo.steps]})
    found = d.stale(plain, tmp_path / "out")
    assert any(f"x's {d.FULL_NAME} is committed" in line for line in found), found


def test_stale_names_what_a_run_did_not_write_and_does_not_raise(
        tmp_path: Path, log: Path) -> None:
    demo = _highlighted(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    (tmp_path / "out" / "transcript-story.md").unlink()
    (tmp_path / "out" / "transcript-normalised.md").unlink()
    found = d.stale(demo, tmp_path / "out")
    assert len(found) == 1 and "wrote no" in found[0] and "transcript-story.md" in found[0], found


def test_a_step_highlight_that_is_no_text_is_refused(tmp_path: Path) -> None:
    demo = _demo(tmp_path, [d.Step("boot", "start", {}, _said("value"), highlight=3)])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"step boot: `highlight` is 3"):
        d.main(demo, ["--transcript", str(tmp_path / "t.md")])


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
    demo = _demo(tmp_path, [d.Step("no", "refuse", {}, lambda reply, run: "")])
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_FAIL
    assert _readme(demo).read_text() == README


def test_a_capture_this_run_did_not_write_leaves_the_readme_as_it_was(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A picture an earlier run left at the capture's path is not this run's picture."""
    _shot(tmp_path).parent.mkdir(parents=True)
    _shot(tmp_path).write_bytes(b"an old picture")
    demo = _demo(tmp_path, [d.Step("boot", "start", {}, _said("value"))])
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
    demo = _demo(tmp_path, volatile={"value": "the test says so"})
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


START_SHOWN = ("value", "binary", "pid", "where")
FRONT = "# The server\n\nWhy.\n\n{begin}\nold flow\n{end}\n\nMore why.\n"


def _front(tmp_path: Path) -> Path:
    path = tmp_path / "README.md"
    path.write_text(FRONT.format(begin=d.flow_begin("x"), end=d.flow_end("x")), encoding="utf-8")
    return path


def _shown_demo(tmp_path: Path) -> d.Demo:
    steps = [
        d.Step("boot", "start", {"value": 7}, _said("value"), options=True),
        d.Step("look", "read", {}, _said("value"), shown=("value",)),
        d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
               lambda reply, run: "a picture"),
        d.Step("end", "close", {}, lambda reply, run: "closed"),
    ]
    return _demo(tmp_path, steps, front=_front(tmp_path))


def test_update_readme_writes_the_shown_steps_into_the_front_door_between_its_prose(
        tmp_path: Path, log: Path) -> None:
    demo = _shown_demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    assert demo.front is not None
    text = demo.front.read_text()
    assert text.startswith("# The server\n\nWhy.\n\n") and text.endswith("\n\nMore why.\n"), text
    flow = text[text.index(d.flow_begin("x")):text.index(d.flow_end("x"))]
    assert "read()\n-> {" in flow and '"value": 7' in flow, flow
    assert "start(" not in flow and "picture(" not in flow, "only the shown steps"
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


def test_a_long_value_in_a_flow_is_abridged_to_its_shape() -> None:
    shown = d.abridged({"rows": list(range(20)), "text": "x" * 1000, "n": 3})
    assert shown["rows"][-1] == f"... {20 - d.ABRIDGED_ITEMS} more"
    assert shown["text"].endswith(" ... (1000 characters)") and shown["n"] == 3


def _flow_of(tmp_path: Path, start: dict[str, Any]) -> str:
    """The flow a run writes when its `start` step, with `start` as its arguments, is shown."""
    steps = [d.Step("boot", "start", start, _said("value"), options=True, shown=START_SHOWN),
             d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
                    lambda reply, run: "a picture")]
    demo = _demo(tmp_path, steps, front=_front(tmp_path))
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    return (tmp_path / "out" / "transcript-flow.md").read_text()


def test_a_long_reply_is_shown_in_the_flow_abridged(tmp_path: Path, log: Path) -> None:
    flow = _flow_of(tmp_path, {"value": 7, "binary": "x" * 1000})
    reply = flow.split("\n-> ", 1)[1]
    assert " ... (1000 characters)" in reply and "x" * 1000 not in reply, flow
    assert f'binary="{"x" * 1000}"' in flow, "the call is what a reader types: kept whole"


def test_a_front_door_with_no_step_shown_is_a_declaration_error_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, front=_front(tmp_path))
    with pytest.raises(ValueError, match="shows no step"):
        _run(demo, tmp_path, "--update-readme")
    assert _calls(log) == [], "the server ran for a front door it could not fill"


def test_update_readme_on_a_demo_with_no_readme_is_invalid_and_runs_nothing(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, readme=None)
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_INVALID
    assert _calls(log) == []


def test_a_step_that_names_its_fields_shows_only_those_in_that_order(
        tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
                    shown=("value", "summary")),
             d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"},
                    lambda reply, run: "a picture")]
    demo = _demo(tmp_path, steps, front=_front(tmp_path))
    assert _run(demo, tmp_path, "--update-readme") == verdict.EXIT_PASS
    flow = (tmp_path / "out" / "transcript-flow.md").read_text()
    assert '-> {\n  "value": 7,\n  "summary": "started"\n}' in flow, flow


def test_a_field_the_front_door_shows_and_the_reply_lacks_fails_the_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True,
                    shown=("value", "gone"))]
    demo = _demo(tmp_path, steps, front=_front(tmp_path))
    assert _run(demo, tmp_path) == verdict.EXIT_FAIL
    assert "FAIL boot: the front door shows ['gone'], which the reply does not carry" \
        in capsys.readouterr().out


def test_a_shown_step_s_flow_is_the_normalised_reply(tmp_path: Path, log: Path) -> None:
    flow = _flow_of(tmp_path, {"value": 7})
    assert '"pid": "<volatile>"' in flow and str(tmp_path) not in flow, flow


def test_a_step_shown_with_no_front_door_is_a_declaration_error(tmp_path: Path) -> None:
    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True, shown=START_SHOWN)]
    with pytest.raises(ValueError, match="no front door"):
        _run(_demo(tmp_path, steps), tmp_path)


def test_a_front_door_whose_markers_go_mid_run_leaves_both_readmes_as_they_were(
        tmp_path: Path, log: Path) -> None:
    front = _front(tmp_path)

    def vanish(reply: d.Reply, run: d.Run) -> str:
        front.write_text("# no markers now\n")
        return "markers gone"

    steps = [d.Step("boot", "start", {"value": 7}, _said("value"), options=True, shown=START_SHOWN),
             d.Step("shot", "picture", lambda run: {"dest": run.dir / "shot.png"}, vanish)]
    demo = _demo(tmp_path, steps, front=front)
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
        d.Step("no", "refuse", {}, lambda reply, run: "", shown=("status",))]})
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
    readme.write_text(readme.read_text().replace("value 7", "value 9", 1))
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


def test_a_small_flat_object_inside_a_reply_is_one_line_and_the_reply_itself_is_not() -> None:
    """A control is a name, a rect and a point: one row, not eight; the top level stays a
    column so the reply reads as fields."""
    block = d.fenced({"matched": True, "controls": [
        {"name": "pict", "rect": [103, 0, 33, 11], "centre": [119, 5]}]})
    assert '{"name": "pict", "rect": [103, 0, 33, 11], "centre": [119, 5]}' in block, block
    assert block.startswith('```json\n{\n  "matched": true,'), block
    wide = {"controls": [{"name": "x" * 90, "rect": [1, 2, 3, 4]}]}
    assert '"name": "' + "x" * 90 + '",\n' in d.fenced(wide), "a long one stays a column"
    assert json.loads(d.fenced(wide).removeprefix("```json\n").removesuffix("\n```")) == wide


def test_a_list_of_scalars_is_one_line_in_a_transcript_block() -> None:
    """A rect or a pixel pair is one thought, not four lines: the README's size is its cost."""
    block = d.fenced({"size": [640, 480], "controls": [{"name": "pict", "rect": [103, 0, 33, 11]}],
                      "names": ["a", "b"], "none": [], "mixed": [1, [2, 3]]})
    assert '"size": [640, 480],' in block, block
    assert '"rect": [103, 0, 33, 11]' in block, block
    assert '"names": ["a", "b"]' in block and '"none": []' in block, block
    assert '"mixed": [\n' in block, block
    assert json.loads(block.removeprefix("```json\n").removesuffix("\n```")) == {
        "size": [640, 480], "controls": [{"name": "pict", "rect": [103, 0, 33, 11]}],
        "names": ["a", "b"], "none": [], "mixed": [1, [2, 3]]}


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
