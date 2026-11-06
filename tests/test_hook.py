"""`scry_core.hook`, run in process inside a repository of the test's own, every case through its
seams: the outcomes that matter cannot be produced by asking the real jscpd nicely (a tool that
examined nothing, one that found new duplication, one that wrote no report at all). The clean run
is the CONTROL: without it, a hook that blocked everything would satisfy every red."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scry_core import hook, host_program, verdict
from scry_core.probe_checks import SERVERS_FILE, TASKS_DIR

_program = host_program.write


#: A report jscpd's JSON reporter wrote on a real tree, the template every fake report is cut from.
REPORT = Path(__file__).resolve().parent / "fixtures" / "hook" / "jscpd-report.json"
#: What the hook must ask of jscpd: the fake refuses a call missing any of them.
FLAGS = ("--baseline", "--fail-on-new-clones", "--reporters")


def _jscpd(at: Path, sources: int, new: int, rc: int, report: bool = True) -> Path:
    """A jscpd that writes the real report with this case's `sources`, `newClones` and the
    duplicated lines (the tree's and the new clones') into the `--output` it is given, after
    checking it was asked for the baseline, new clones and the JSON reporter."""
    write = ("doc = json.loads(pathlib.Path(sys.argv[0] + '.json').read_text())\n"
             f"doc['statistics']['total'].update(sources={sources}, newClones={new}, "
             "duplicatedLines=640, newDuplicatedLines=48)\n"
             "pathlib.Path(out, 'jscpd-report.json').write_text(json.dumps(doc))\n"
             ) if report else ""
    Path(f"{at}.json").write_text(REPORT.read_text())
    return _program(at, "import json, os, pathlib, sys\n"
                        f"if not all(f in sys.argv for f in {FLAGS!r}) or 'json' not in sys.argv:\n"
                        "    sys.exit(97)\n"
                        "out = sys.argv[sys.argv.index('--output') + 1]\n"
                        "pathlib.Path(sys.argv[0] + '.cwd').write_text(os.getcwd())\n"
                        "pathlib.Path(out).mkdir(parents=True, exist_ok=True)\n" + write +
                        f"print('fake jscpd: sources={sources} newClones={new}')\nsys.exit({rc})\n")


def _probe(at: Path, printed: str, rc: int) -> Path:
    return _program(at, f"import sys\nprint({printed!r})\nsys.exit({rc})\n")


def _mypy(at: Path, printed: str, rc: int) -> Path:
    """A mypy that prints `printed` and exits `rc`, once it was asked for win32 strictly."""
    return _program(at, "import sys\n"
                        f"if sys.argv[1:] != {hook.WIN32_ARGS!r}:\n    sys.exit(97)\n"
                        f"print({printed!r})\nsys.exit({rc})\n")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository holding a baseline, entered from a subdirectory, with both seams set to
    a clean answer: each case below moves one of them."""
    at = tmp_path / "repo"
    (at / "sub").mkdir(parents=True)
    for var in [v for v in os.environ if v.startswith("GIT_")]:
        monkeypatch.delenv(var)
    subprocess.run(["git", "init", "-q", str(at)], check=True)
    (at / hook.BASELINE).write_text("{}")
    (at / "clean.py").write_text("x = 1\n")
    jscpd = _jscpd(tmp_path / "jscpd", 3, 0, 0)
    probe = _probe(tmp_path / "probe", "OK mame: 4 tasks cover 2 tools", 0)
    mypy = _mypy(tmp_path / "mypy", "Success: no issues found in 1 source file", 0)
    monkeypatch.setenv("PRECOMMIT_JSCPD", str(jscpd))
    monkeypatch.setenv("PRECOMMIT_PROBE", str(probe))
    monkeypatch.setenv("PRECOMMIT_MYPY", str(mypy))
    monkeypatch.chdir(at / "sub")
    return tmp_path


def _hook(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = hook.main([])
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_a_clean_run_passes_from_anywhere_in_the_repository(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said
    assert "3 files, no new duplication" in said and "OK mame: 4 tasks cover 2 tools" in said
    assert "win32: 1 files clean on win32" in said, said
    ran_in = Path((repo / "jscpd.cwd").read_text()).resolve()
    assert ran_in == (repo / "repo").resolve(), "jscpd ran outside the repository's root"


def test_new_duplication_blocks_naming_the_count_the_total_and_the_remedies(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _jscpd(repo / "jscpd", 3, 3, 1)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL
    for words in ("pre-commit: REFUSED: ", "3 new clone", "48 new duplicated lines",
                  "shrank or split", "from the repository's root", "--update-baseline"):
        assert words in said, words


@pytest.mark.parametrize(("sources", "report", "said"), [
    (0, True, "analysed 0 files, so this is not a verdict"),
    (3, False, "jscpd wrote no report (rc=0)"),
])
def test_a_duplication_check_that_examined_nothing_is_invalid_even_at_exit_0(
        repo: Path, capsys: pytest.CaptureFixture[str], sources: int, report: bool,
        said: str) -> None:
    _jscpd(repo / "jscpd", sources, 0, 0, report=report)
    rc, out = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and said in out, out


def test_a_report_that_cannot_be_read_is_invalid(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _program(repo / "jscpd", "import pathlib, sys\nout = sys.argv[sys.argv.index('--output') + 1]\n"
                             "pathlib.Path(out, 'jscpd-report.json').write_text('{}')\n")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "the jscpd report could not be read: KeyError" in said


def test_a_missing_baseline_names_the_file_and_not_the_tool(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "repo" / hook.BASELINE).unlink()
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and f"{hook.BASELINE} is missing" in said


def test_a_jscpd_that_cannot_be_run_is_invalid(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRECOMMIT_JSCPD", str(repo / "absent"))
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "jscpd could not be run" in said
    assert "it is PRECOMMIT_JSCPD's value" in said, said


def test_an_uncovered_tool_blocks_naming_the_hole_and_how_to_measure_after(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _probe(repo / "probe", "REFUSED no task on mame frame_grab", 1)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and "no task on mame frame_grab" in said
    assert ("from the repository root: python -m scry_core.probe <server> --check "
            f"--servers {SERVERS_FILE} --tasks {TASKS_DIR}") in said
    assert "only for a task added for a new or changed tool" in said, (
        "a typo in a task file is fixed with the free check, never sent to a paid model run")


@pytest.mark.parametrize(("printed", "rc", "said"), [
    ("ModuleNotFoundError: No module named mame_args", 1, "exited 1 naming no refusal"),
    ("INVALID mcp_probe/tasks/mame.json: bad JSON", 3, "the probe check exited 3"),
    ("probe: error: unrecognized arguments", 2, "the probe check exited 2"),
    ("", 0, "examined no server, so this is not a verdict"),
])
def test_a_probe_check_that_did_not_judge_is_invalid(
        repo: Path, capsys: pytest.CaptureFixture[str], printed: str, rc: int,
        said: str) -> None:
    _probe(repo / "probe", printed, rc)
    code, out = _hook(capsys)
    assert code == verdict.EXIT_INVALID and said in out, out
    assert "Fix it in" not in out and "--runs 3" not in out, "a broken check got the task remedy"


def test_outside_a_repository_it_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "git does not say where the repository root is" in said


def test_anything_else_that_stops_it_is_invalid_and_never_a_traceback(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_root: Path, _scratch: Path) -> str:
        raise KeyError("boom")

    monkeypatch.setattr(hook, "duplication", broken)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "stopped before its verdict: KeyError" in said
    assert "Traceback" not in said


def test_a_repository_with_no_server_skips_the_probe_and_reaches_the_steps_after(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A repository that holds no MCP server says so and is judged by the steps after it; the
    two steps that answer about the tree as a whole must still run."""
    monkeypatch.delenv("PRECOMMIT_PROBE", raising=False)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said
    assert f"skipped: no {SERVERS_FILE}" in said
    assert "prose: 1 files within the ceiling" in said, said
    assert "win32: 1 files clean on win32" in said, said


def test_a_seam_still_runs_where_the_repository_names_no_server(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`PRECOMMIT_PROBE` is a program the repository names, not a by-product of a file it
    holds: the clean run's own seam is what answers here."""
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS and "OK mame: 4 tasks cover 2 tools" in said, said
    assert "skipped" not in said, said


def test_an_unknown_option_is_usage() -> None:
    with pytest.raises(SystemExit) as exc:
        hook.main(["--fast"])
    assert exc.value.code == 2


def test_a_jscpd_that_fails_with_no_new_clone_is_invalid_and_not_a_block(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _jscpd(repo / "jscpd", 3, 0, 2)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID
    assert "jscpd exited 2 and its report counts no new clone" in said


def test_new_clones_block_even_when_jscpd_exits_0(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _jscpd(repo / "jscpd", 3, 2, 0)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and "2 new clones" in said


def test_a_git_that_cannot_be_run_is_invalid(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(repo / "empty"))
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "git could not be run" in said



TOY_SERVERS = '''
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def read(ref: str) -> None:
    raise AssertionError("the probe reads a tool, never calls it")


async def _listed() -> list[object]:
    return [SimpleNamespace(name="read", description="Read the bytes at a place.",
                            input_schema={"properties": {"ref": {}}})]


toy = ModuleType("toy")
toy.read = read
toy.mcp = SimpleNamespace(instructions="A toy server.", list_tools=_listed)


def load() -> dict[str, ModuleType]:
    return {"toy": toy}
'''
TOY_TASKS = ('{"tasks": [{"id": "T1", "prompt": "Read at PlayerX.", "tool": "read", '
             '"args": {"ref": "PlayerX"}}, {"id": "T2", "prompt": "Format the disk.", '
             '"expect": "CANNOT", "about": "read"}]}')


def test_the_real_probe_check_passes_a_repository_whose_tasks_cover_its_server(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The real path, end to end: the hook runs the probe module on the repository's own servers
    file and reads the line `--check` prints, with no fake standing in for either."""
    (repo / "repo" / "mcp_probe" / "tasks").mkdir(parents=True)
    (repo / "repo" / "mcp_probe" / "servers.py").write_text(TOY_SERVERS)
    (repo / "repo" / "mcp_probe" / "tasks" / "toy.json").write_text(TOY_TASKS)
    monkeypatch.delenv("PRECOMMIT_PROBE")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said
    assert "OK toy: 2 tasks cover 1 tools" in said


def test_a_jscpd_absent_from_path_is_invalid_saying_where_it_was_looked_for(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRECOMMIT_JSCPD", raising=False)
    git = shutil.which("git")
    assert git is not None
    # GIT'S OWN DIRECTORY, never a link to git elsewhere: on Windows git.exe loads DLLs from the
    # directory it sits in. A host whose git and jscpd share that directory cannot run this case.
    monkeypatch.setenv("PATH", str(Path(git).parent))
    if shutil.which("jscpd") is not None:
        pytest.skip("jscpd sits in git's own directory on this host, so no PATH holds one alone")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID, said
    assert "it is looked for on PATH (or named by PRECOMMIT_JSCPD)" in said, said


#: 100 bytes, 40 of them a comment.
FORTY = "#" * 40 + "\n" + "x = " + "1" * 54 + "\n"
#: 100 bytes, 20 of them a comment: over a test file's sixth, under a source file's quarter.
TWENTY = "#" * 20 + "\n" + "x = " + "1" * 74 + "\n"


def _plant(repo: Path, rel: str, text: str) -> None:
    (repo / "repo" / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / "repo" / rel).write_bytes(text.encode())    # its bytes counted, never CRLF


def _exempt(repo: Path, table: str) -> None:
    (repo / "repo" / "pyproject.toml").write_text(f"[tool.scry-prose]\nexempt = {table}\n")


def test_a_clean_tree_says_how_many_files_it_judged(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS and "prose: 1 files within the ceiling" in said, said


def test_a_source_file_over_a_quarter_blocks_with_its_one_line(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "over.py", FORTY)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL
    assert "over.py: prose 40.0% of 100 bytes, ceiling 25.0%" in said, said
    assert "clean.py" not in said


def test_a_test_file_is_judged_at_a_sixth(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "twenty.py", TWENTY)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said
    _plant(repo, "tests/test_twenty.py", TWENTY)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL
    assert "tests/test_twenty.py: prose 20.0% of 100 bytes, ceiling 16.7%" in said, said
    assert "twenty.py: prose" not in said.replace("tests/test_twenty.py", "")


@pytest.mark.parametrize("decorator", ["@server.tool(\"Read\")", "@tool(\"Read\")"])
def test_a_registered_tools_docstring_is_its_description_and_not_prose(
        repo: Path, capsys: pytest.CaptureFixture[str], decorator: str) -> None:
    body = f'{decorator}\ndef read() -> None:\n    """{"a" * 200}"""\n'
    _plant(repo, "tools.py", body)
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said
    _plant(repo, "tools.py", body.replace(decorator, "@other(\"Read\")"))
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and "tools.py: prose" in said, said


def test_comments_and_every_kind_of_docstring_count_exactly() -> None:
    source = ('"""ab"""\n# cd\nclass K:\n    "é"\n    def f(self):\n        """g"""\n'
              '        async def h():\n            "i"\n        return "not a docstring"\n')
    expected = [b'"""ab"""', b"# cd", '"é"'.encode(), b'"""g"""', b'"i"']
    assert hook.prose_bytes(source.encode()) == sum(map(len, expected))


def test_a_bom_and_non_ascii_text_are_counted_in_the_file_s_own_bytes() -> None:
    source = '\ufeff"""a\nb"""\nx = "\u00e9\u00e9"  # \u00e9\ndef f():\n    """c\n    \u00e9"""\n'
    expected = [b'"""a\nb"""', "# \u00e9".encode(), '"""c\n    \u00e9"""'.encode()]
    assert hook.prose_bytes(source.encode()) == sum(map(len, expected))


def test_a_file_exactly_at_its_ceiling_passes(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "quarter.py", "#" * 25 + "\n" + "x = " + "1" * 69 + "\n")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS, said


def test_an_exempted_file_is_not_judged(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "over.py", FORTY)
    _exempt(repo, '{ "over.py" = "generated by the font compiler" }')
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS and "prose: 1 files within the ceiling" in said, said


@pytest.mark.parametrize(("table", "said"), [
    ('{ "over.py" = "" }', "over.py is exempted with no reason"),
    ('{ "over.py" = "  " }', "over.py is exempted with no reason"),
    ('{ "gone.py" = "generated" }', "gone.py is exempted but does not exist"),
    ('{ "over.py" = 3 }', "over.py is exempted with no reason"),
    ('"over.py"', "[tool.scry-prose] exempt is not a table"),
])
def test_an_exemption_with_no_reason_or_a_stale_path_is_usage(
        repo: Path, capsys: pytest.CaptureFixture[str], table: str, said: str) -> None:
    _plant(repo, "over.py", FORTY)
    _exempt(repo, table)
    rc, out = _hook(capsys)
    assert rc == hook.EXIT_USAGE and said in out, out


@pytest.mark.parametrize("text", ["tool = 3\n", "[tool]\nscry-prose = \"x\"\n"])
def test_a_pyproject_whose_tool_table_has_the_wrong_shape_is_usage(
        repo: Path, capsys: pytest.CaptureFixture[str], text: str) -> None:
    (repo / "repo" / "pyproject.toml").write_text(text)
    rc, said = _hook(capsys)
    assert rc == hook.EXIT_USAGE and "[tool.scry-prose]" in said, said



def test_a_pyproject_that_does_not_parse_is_usage(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "repo" / "pyproject.toml").write_text("[tool.scry-prose\n")
    rc, said = _hook(capsys)
    assert rc == hook.EXIT_USAGE and "pyproject.toml does not parse" in said, said


def test_no_python_file_is_invalid(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "repo" / "clean.py").unlink()
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "prose examined 0 files" in said, said


def test_every_file_exempted_is_zero_examined(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _exempt(repo, '{ "clean.py" = "vendored" }')
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "prose examined 0 files" in said, said


def test_tracked_untracked_and_ignored_files_and_symlinks(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    at = repo / "repo"
    _plant(repo, "tracked.py", FORTY)
    subprocess.run(["git", "-C", str(at), "add", "tracked.py"], check=True)
    _plant(repo, "ignored.py", FORTY)
    (at / ".gitignore").write_text("ignored.py\n")
    (repo / "outside.py").write_text(FORTY)
    (at / "link.py").symlink_to(repo / "outside.py")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and "tracked.py: prose" in said, said
    assert "ignored.py" not in said and "link.py" not in said


def test_a_file_that_does_not_parse_is_invalid_naming_it(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "broken.py", "def (:\n")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "broken.py could not be read" in said, said


@pytest.mark.parametrize(("printed", "rc"), [
    ("No module named mypy", 1), ("", 0), ("Success: no issues found in 0 source files", 0),
    ("usage: mypy [-h]\nmypy: error: unrecognized arguments", 2)])
def test_a_win32_check_that_did_not_judge_is_invalid(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
        printed: str, rc: int) -> None:
    monkeypatch.setenv("PRECOMMIT_MYPY", str(_mypy(repo / "mypy", printed, rc)))
    got, said = _hook(capsys)
    assert got == verdict.EXIT_INVALID and f"mypy on win32 exited {rc} without a verdict" in said


def test_a_type_error_on_win32_blocks_naming_it_and_the_command(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    error = 'p.py:2: error: Module has no attribute "tcgetattr"  [attr-defined]'
    monkeypatch.setenv("PRECOMMIT_MYPY", str(_mypy(repo / "mypy", f"{error}\nFound 1 error", 1)))
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and "pre-commit: REFUSED: " in said and error in said
    assert "uv run mypy --strict --platform win32 ." in said, said


def test_the_real_mypy_refuses_a_posix_only_call_and_passes_its_guarded_twin(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """No seam: the hook runs mypy itself, on a tree that types clean on this host."""
    monkeypatch.delenv("PRECOMMIT_MYPY")
    _plant(repo, "posix.py", "import sys\nimport termios\n\nif sys.platform != 'win32':\n"
                             "    termios.tcgetattr(0)\n")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_PASS and "win32: 2 files clean on win32" in said, said
    _plant(repo, "posix.py", "import termios\n\ntermios.tcgetattr(0)\n")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_FAIL and 'posix.py:3: error: Module has no attribute "tcgetattr"' \
        in said, said


def test_this_repository_is_within_its_prose_ceiling() -> None:
    """scry-core has no pre-commit of its own (it holds no server), so its suite runs the check."""
    assert hook.prose(Path(__file__).resolve().parent.parent).startswith("prose: ")
