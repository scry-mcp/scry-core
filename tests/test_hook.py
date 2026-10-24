"""`scry_core.hook`, run in process inside a repository of the test's own, every case through its
seams: the outcomes that matter cannot be produced by asking the real jscpd nicely (a tool that
examined nothing, one that found new duplication, one that wrote no report at all). The clean run
is the CONTROL: without it, a hook that blocked everything would satisfy every red."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scry_core import hook, verdict


def _program(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return path


#: A report jscpd's JSON reporter wrote on a real tree, the template every fake report is cut from.
REPORT = Path(__file__).resolve().parent / "fixtures" / "hook" / "jscpd-report.json"
#: What the hook must ask of jscpd: the fake refuses a call missing any of them.
FLAGS = ("--baseline", "--fail-on-new-clones", "--reporters")


def _jscpd(at: Path, sources: int, new: int, rc: int, report: bool = True) -> None:
    """A jscpd that writes the real report with this case's `sources`, `newClones` and the
    duplicated lines (the tree's and the new clones') into the `--output` it is given, after
    checking it was asked for the baseline, new clones and the JSON reporter."""
    write = ("doc = json.loads(pathlib.Path(sys.argv[0] + '.json').read_text())\n"
             f"doc['statistics']['total'].update(sources={sources}, newClones={new}, "
             "duplicatedLines=640, newDuplicatedLines=48)\n"
             "pathlib.Path(out, 'jscpd-report.json').write_text(json.dumps(doc))\n"
             ) if report else ""
    Path(f"{at}.json").write_text(REPORT.read_text())
    _program(at, "import json, os, pathlib, sys\n"
                 f"if not all(f in sys.argv for f in {FLAGS!r}) or 'json' not in sys.argv:\n"
                 "    sys.exit(97)\n"
                 "out = sys.argv[sys.argv.index('--output') + 1]\n"
                 "pathlib.Path(sys.argv[0] + '.cwd').write_text(os.getcwd())\n"
                 "pathlib.Path(out).mkdir(parents=True, exist_ok=True)\n" + write +
                 f"print('fake jscpd: sources={sources} newClones={new}')\nsys.exit({rc})\n")


def _probe(at: Path, printed: str, rc: int) -> None:
    _program(at, f"import sys\nprint({printed!r})\nsys.exit({rc})\n")


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
    _jscpd(tmp_path / "jscpd", 3, 0, 0)
    _probe(tmp_path / "probe", "OK mame: 4 tasks cover 2 tools", 0)
    monkeypatch.setenv("PRECOMMIT_JSCPD", str(tmp_path / "jscpd"))
    monkeypatch.setenv("PRECOMMIT_PROBE", str(tmp_path / "probe"))
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
            "--servers mcp_probe/servers.py --tasks mcp_probe/tasks") in said
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


def test_the_real_probe_check_is_what_runs_without_its_seam(
        repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `PRECOMMIT_PROBE` the hook runs the probe module itself on the repository's own
    servers file: here there is none, so the real check answers INVALID about it."""
    monkeypatch.delenv("PRECOMMIT_PROBE")
    rc, said = _hook(capsys)
    assert rc == verdict.EXIT_INVALID and "mcp_probe/servers.py" in said, said


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
    assert rc == verdict.EXIT_FAIL and "2 new clone(s)" in said


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
