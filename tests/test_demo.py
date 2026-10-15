"""The demo runner against a real MCP server of the tests' own (`fixtures/demo/server.py`),
started over stdio by the real `mcp` library: each line of the output contract, its exit codes,
the README block and the normalisation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client

from scry_core import demo as d

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


def _run(demo: d.Demo, tmp_path: Path, *argv: str) -> int:
    return d.main(demo, ["--transcript", str(tmp_path / "out" / "transcript.md"), *argv])


def _calls(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _norm(tmp_path: Path) -> str:
    return (tmp_path / "out" / "transcript.normalised.md").read_text()


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calls.log"
    monkeypatch.setenv("DEMO_LOG", str(path))
    return path


def test_every_step_ok_prints_one_line_each_and_the_tally(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(_demo(tmp_path), tmp_path) == d.EXIT_OK
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
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_OK
    assert [c["summary"] for c in _calls(log)] == ["started", "closed"]


def test_a_failed_step_is_rc_1_stops_the_run_and_still_cleans_up(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def wrong(reply: d.Reply, run: d.Run) -> str:
        raise d.StepFailed("the value was not 8")

    steps = [d.Step("boot", "start", {}, wrong), d.Step("look", "read", {}, _said("value"))]
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
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
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
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
    assert _run(_demo(tmp_path, []), tmp_path) == d.EXIT_INVALID
    assert capsys.readouterr().out.startswith("INVALID: the demo x declares zero steps")
    assert _calls(log) == []


def test_a_precheck_that_names_a_reason_is_invalid(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, precheck=lambda run: "no ROM: get it from https://example.org/x.zip")
    assert _run(demo, tmp_path) == d.EXIT_INVALID
    assert capsys.readouterr().out == "INVALID: no ROM: get it from https://example.org/x.zip\n"
    assert _calls(log) == []


def test_an_error_before_the_verdict_is_invalid_not_a_traceback(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, precheck=lambda run: run.replies["nothing"])
    assert _run(demo, tmp_path) == d.EXIT_INVALID
    assert capsys.readouterr().out == "INVALID: KeyError: 'nothing'\n"


@pytest.mark.parametrize("server", [["no-such-server"],
                                    [sys.executable, "-c", "import sys; sys.exit(3)"]])
def test_a_server_that_does_not_start_is_invalid_and_says_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], server: list[str]) -> None:
    demo = _demo(tmp_path, server=[s if s != "no-such-server" else str(tmp_path / s)
                                   for s in server])
    assert _run(demo, tmp_path) == d.EXIT_INVALID
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("INVALID: the server did not start (") and "TaskGroup" not in line, line


def test_a_server_that_dies_mid_run_fails_the_step(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    steps = [d.Step("boot", "start", {}, _said("value")),
             d.Step("die", "die", {}, lambda reply, run: "never")]
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
    assert "OK boot: value 7\nFAIL die: " in capsys.readouterr().out
    assert "Cleanup `close` failed: " in (tmp_path / "out" / "transcript.md").read_text()


def test_a_call_that_never_answers_fails_at_the_bound(
        tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(d, "CALL_TIMEOUT_S", 1)
    steps = [d.Step("nap", "sleep", {"seconds": 5}, lambda reply, run: "never")]
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
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
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
    stderr = (tmp_path / "out" / "server.stderr").resolve()
    assert capsys.readouterr().out.splitlines()[:3] == [
        "OK boot: value 7", "FAIL x: the session with the server ended in an error "
        f"(RuntimeError: the transport closed badly); its stderr is in {stderr}",
        "DEMO x: 1 steps, 1 OK"]


@pytest.mark.parametrize("argv", [["--bogus"], ["--update"], ["--rompath", "/x"], ["--shared"]])
def test_an_unknown_or_abbreviated_option_exits_2(tmp_path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        d.main(_demo(tmp_path), argv)
    assert exc.value.code == 2


def test_offered_options_reach_the_options_step_only_when_given(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, offers=frozenset({"rompath", "shared"}), steps=[
        d.Step("boot", "start", {"binary": "default"}, _said("binary"), options=True),
        d.Step("again", "start", {"binary": "default"}, _said("binary"))])
    assert _run(demo, tmp_path) == d.EXIT_OK
    assert _run(demo, tmp_path, "--binary", "/b") == d.EXIT_OK
    assert [c["binary"] for c in _calls(log) if c["summary"] == "started"] == [
        "default", "default", "/b", "default"]
    normalised = _norm(tmp_path)
    assert '"binary": "/b"' in normalised and '"rompath"' not in normalised
    assert _run(demo, tmp_path, "--rompath", "/r", "--shared") == d.EXIT_OK
    assert '"rompath": "/r",\n  "shared": true' in _norm(tmp_path)


def test_a_step_takes_only_the_options_it_names(tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, offers=frozenset({"shared"}), reads=frozenset({"shared"}), steps=[
        d.Step("boot", "start", lambda run: {"value": 9 if run.options.get("shared") else 7},
               _said("value"), options=frozenset({"binary"}))])
    assert _run(demo, tmp_path, "--binary", "/b", "--shared") == d.EXIT_OK
    (call,) = [c for c in _calls(log) if c["summary"] == "started"]
    assert (call["binary"], call["value"]) == ("/b", 9), call
    assert '"shared"' not in _norm(tmp_path).split("```json")[1], "an option it does not take"


def test_an_option_given_that_nothing_takes_is_invalid(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    demo = _demo(tmp_path, offers=frozenset({"shared"}), steps=[
        d.Step("boot", "start", {}, _said("value"), options=frozenset({"binary"}))])
    assert _run(demo, tmp_path, "--shared") == d.EXIT_INVALID
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
    assert _run(demo, tmp_path, "--binary", "/b") == d.EXIT_INVALID
    assert capsys.readouterr().out.startswith("INVALID: options ['binary'] were given")
    assert _calls(log) == []


def test_a_demo_cannot_offer_an_option_the_runner_does_not_know(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rompth"):
        d.main(_demo(tmp_path, offers=frozenset({"rompth"})), [])


def test_update_readme_rewrites_the_block_and_the_capture(
        tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path)
    assert _run(demo, tmp_path, "--update-readme") == d.EXIT_OK
    text = demo.readme.read_text()
    assert d.block_of(text) == _norm(tmp_path).strip("\n")
    assert text.startswith("# A demo\n\nBefore.\n\n") and text.endswith("\n\nAfter.\n")
    assert (demo.readme.parent / "screen.png").read_bytes() == _shot(tmp_path).read_bytes()
    normalised = tmp_path / "out" / "transcript.normalised.md"
    assert d.readme_drift(demo.readme, normalised) == ""
    normalised.write_text(normalised.read_text().replace("value 7", "value 8", 1))
    assert d.readme_drift(demo.readme, normalised).startswith("line 1: the README has ")


@pytest.mark.parametrize("readme", ["no markers\n", f"{d.BEGIN}\n{d.BEGIN}\n{d.END}\n",
                                    f"{d.BEGIN}\n{d.END}\n{d.END}\n", f"{d.END}\n{d.BEGIN}\n"])
def test_markers_not_there_once_are_invalid_and_write_nothing(
        tmp_path: Path, log: Path, readme: str) -> None:
    demo = _demo(tmp_path)
    demo.readme.write_text(readme)
    assert _run(demo, tmp_path, "--update-readme") == d.EXIT_INVALID
    assert demo.readme.read_text() == readme
    assert not (demo.readme.parent / "screen.png").exists()
    assert _calls(log) == [], "the server ran although the README could not take the block"


def test_a_failed_run_leaves_the_readme_as_it_was(tmp_path: Path, log: Path) -> None:
    demo = _demo(tmp_path, [d.Step("no", "refuse", {}, lambda reply, run: "")])
    assert _run(demo, tmp_path, "--update-readme") == d.EXIT_FAILED
    assert demo.readme.read_text() == README


def test_a_capture_this_run_did_not_write_leaves_the_readme_as_it_was(
        tmp_path: Path, log: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A picture an earlier run left at the capture's path is not this run's picture."""
    _shot(tmp_path).parent.mkdir(parents=True)
    _shot(tmp_path).write_bytes(b"an old picture")
    demo = _demo(tmp_path, [d.Step("boot", "start", {}, _said("value"))])
    assert _run(demo, tmp_path, "--update-readme") == d.EXIT_INVALID
    assert demo.readme.read_text() == README
    assert not (demo.readme.parent / "screen.png").exists()
    assert "INVALID: the capture" in capsys.readouterr().out


def test_a_volatile_key_is_hidden_and_a_shown_value_is_not(tmp_path: Path, log: Path) -> None:
    assert _run(_demo(tmp_path), tmp_path) == d.EXIT_OK
    whole = (tmp_path / "out" / "transcript.md").read_text()
    norm = _norm(tmp_path)
    assert '"pid": "<volatile>"' in norm and '"pid": "<volatile>"' not in whole
    assert norm.count('"value": 7') == 3, "a shown value was normalised away (one argument, " \
        "two replies)"
    assert '"where": "."' in norm and str(tmp_path) not in norm
    assert '"dest": "./out/shot.png"' in norm, "a Path argument was not sent as its text"


def test_a_demo_declares_its_own_volatile_keys_and_its_arguments_keep_theirs(
        tmp_path: Path, log: Path) -> None:
    assert _run(_demo(tmp_path, volatile={"value": "the test says so"}), tmp_path) == d.EXIT_OK
    norm = _norm(tmp_path)
    assert '"value": "<volatile>"' in norm, "the reply's value was shown"
    assert '"value": 7' in norm, "the demo's own argument was hidden"


def test_a_host_argument_is_hidden_and_the_demos_own_are_not(tmp_path: Path, log: Path) -> None:
    steps = [d.Step("boot", "start", {"value": 7, "binary": "-set sdl display=1"},
                    _said("value"))]
    # The fixture's `start` echoes `binary` in its reply, so the demo declares that key too.
    demo = _demo(tmp_path, steps, host_args={"binary": "where this host puts a window"},
                 volatile={"binary": "the reply echoes the host's argument"})
    assert _run(demo, tmp_path) == d.EXIT_OK
    norm = _norm(tmp_path)
    assert "display=1" not in norm, "a host value reached the normalised transcript"
    assert '"binary": "<host>"' in norm.split("```json")[1], "the call did not hide it"
    assert '"value": 7' in norm, "the demo's own argument was hidden"
    assert "display=1" in (tmp_path / "out" / "transcript.md").read_text()
    n = d.Normaliser(Path("/r"), Path("/h"), {}, {"binary": "x"})
    assert n.arguments({"a": [{"binary": "p"}], "binary": "q", "c": "/r/f"}) == {
        "a": [{"binary": "<host>"}], "binary": "<host>", "c": "./f"}


def test_the_normaliser_matches_whole_path_prefixes_only() -> None:
    n = d.Normaliser(Path("/Users/m/repo"), Path("/Users/m"), d.VOLATILE)
    got = n.reply({"a": ["/Users/m/repo/x", "/Users/m/y", 3, ("/Users/m",)],
                   "/Users/m/k": {"pid": 9, "b": "/Users/mx/f /Users/m/repo-notes/a"},
                   "c": "at /Users/m: here"})
    assert got == {"a": ["./x", "~/y", 3, ["~"]],
                   "~/k": {"pid": "<volatile>", "b": "/Users/mx/f ~/repo-notes/a"},
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
    assert _run(_demo(tmp_path, steps), tmp_path) == d.EXIT_FAILED
    assert capsys.readouterr().out.startswith(
        "OK doc: n 3\nFAIL list: plain answered None: no reason given")
    assert d._document("[1, 2]") == {"value": [1, 2]}
    assert d._document("not json") == {"text": "not json"}


def test_first_difference_names_the_line() -> None:
    assert d.first_difference("a\nb", "a\nb") == ""
    assert d.first_difference("a\nb", "a\nc") == "line 2: the README has 'b', the run has 'c'"
    assert d.first_difference("a", "a\nb") == "line 2: the README has 1, the run 2"
