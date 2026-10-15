"""`scry_core.live_bench`, driven through its `main` in process on a manifest and a bench of the
test's own: what it says and how it exits for a bench that matches, one that does not, and one it
could not examine."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scry_core import live_bench as bench

DATA = b"the pinned bytes\n"
PIN = hashlib.sha256(DATA).hexdigest()


def _entry(path: str, sha256: str = PIN, source_path: str = "",
           **extra: object) -> dict[str, object]:
    return {"path": path, "sha256": sha256, "source_repo": "src",
            "source_path": source_path or path, "source_commit": "", **extra}


@pytest.fixture(autouse=True)
def plain_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Git as a fresh machine has it: no user config (a signing or hook setting would break the
    commits made here), no repository inherited from a hook's environment, and no walk above
    the test's own directory to a HEAD that is not the one under test."""
    for var in [v for v in os.environ if v.startswith("GIT_")]:
        monkeypatch.delenv(var)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


@pytest.fixture
def manifest(tmp_path: Path) -> Path:
    """The manifest of the bench each case names: `bench.json` inside a bench of the test's own,
    an empty directory."""
    (tmp_path / "bench").mkdir()
    return tmp_path / "bench" / bench.MANIFEST


def _write(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(entries))


def _at(manifest: Path) -> list[str]:
    """The bench every case names: the one holding `manifest`."""
    return ["--bench", str(manifest.parent)]


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    rc = bench.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


def _checkout(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """A git checkout of `files`, committed, so `--record` has a HEAD to read."""
    at = tmp_path / "checkout"
    for name, data in files.items():
        (at / name).parent.mkdir(parents=True, exist_ok=True)
        (at / name).write_bytes(data)
    git = ["git", "-C", str(at), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(at)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "files"], check=True)
    return at


def test_a_bench_that_matches_says_so_in_one_line_counting_the_manifest(
    manifest: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _write(manifest, [_entry("board/a.bin"), _entry("board/b.bin")])
    (manifest.parent / "board").mkdir()
    for name in ("a.bin", "b.bin", "stray.bin"):
        (manifest.parent / "board" / name).write_bytes(DATA)
    assert _run(capsys, "check", *_at(manifest)) == (
        0, f"OK {manifest.parent}: 2 files match the manifest\n", "")


def test_a_flipped_byte_is_named_and_exits_1(
    manifest: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _write(manifest, [_entry("board/a.bin"), _entry("board/b.bin")])
    (manifest.parent / "board").mkdir()
    (manifest.parent / "board/a.bin").write_bytes(b"X" + DATA[1:])
    (manifest.parent / "board/b.bin").write_bytes(DATA)
    rc, out, _ = _run(capsys, "check", *_at(manifest))
    got = hashlib.sha256(b"X" + DATA[1:]).hexdigest()
    assert (rc, out) == (1, f"MISMATCH board/a.bin: sha256 {got}, the manifest pins {PIN}\n")


def test_every_missing_or_wrong_file_is_named_in_manifest_order_and_exits_1(
    manifest: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    _write(manifest, [_entry("board/a.bin"), _entry("board/b.bin", sha256="")])
    (manifest.parent / "board").mkdir()
    (manifest.parent / "board/b.bin").write_bytes(DATA)
    rc, out, _ = _run(capsys, "check", *_at(manifest))
    at = manifest.parent
    assert (rc, out) == (1, f"MISSING board/a.bin: not in the bench at {at}\n"
                            f"MISMATCH board/b.bin: sha256 {PIN}, the manifest pins none\n")


@pytest.mark.parametrize("text", ["[]", "{}", "not json", json.dumps([{"path": "a"}]),
                                  json.dumps([_entry("../escape")]),
                                  json.dumps([_entry("a"), _entry("a")]),
                                  json.dumps([_entry("a/b"), _entry("a/./b")]),
                                  json.dumps([_entry("a", capture=[])]),
                                  json.dumps([_entry("a", capture="python gen.py")]),
                                  json.dumps([_entry("/etc/passwd")]), json.dumps([_entry(".")]),
                                  json.dumps([_entry("a", source_path="../out")]),
                                  json.dumps([{**_entry("a"), "sha256": 5}]),
                                  json.dumps([{**_entry("a"), "comment": "x"}])])
def test_a_manifest_that_names_nothing_or_is_not_one_is_invalid(
    manifest: Path, capsys: pytest.CaptureFixture[str], text: str,
) -> None:
    manifest.write_text(text)
    rc, out, err = _run(capsys, "check", *_at(manifest))
    assert (rc, out) == (3, "") and err.startswith("INVALID: ")


def test_a_manifest_file_that_is_not_there_is_invalid(
    manifest: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc, _, err = _run(capsys, "check", *_at(manifest))
    assert rc == 3 and "is not a manifest" in err


def test_a_bench_root_that_does_not_exist_is_invalid(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    rc, _, err = _run(capsys, "check", "--bench", str(tmp_path / "nowhere"))
    assert rc == 3 and "does not exist" in err


B = ["--bench", "b"]


@pytest.mark.parametrize("argv", [["check", *B, "--quiet"], ["check"], ["verify"],
                                  ["check", "--server", "mame", *B],
                                  ["check", *B, "--manifest", "b/bench.json"],
                                  ["fill", *B], ["fill", "--from", "src=a"],
                                  ["fill", *B, "--from", "nameonly"],
                                  ["fill", *B, "--from", "src="],
                                  ["fill", *B, "--from", "=path"],
                                  ["fill", *B, "--from", "src=a", "--from", "src=b"]])
def test_an_unknown_or_malformed_option_exits_2(
    manifest: Path, capsys: pytest.CaptureFixture[str], argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as e:
        bench.main(argv)
    assert e.value.code == 2


def test_fill_copies_what_matches_its_pin_and_keeps_the_mode(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"bin/tool": DATA})
    (checkout / "bin/tool").chmod(0o755)
    _write(manifest, [_entry("board/tool", source_path="bin/tool")])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    copy = manifest.parent / "board/tool"
    assert rc == 0 and copy.read_bytes() == DATA and copy.stat().st_mode & 0o111
    assert out == ("copied board/tool <- src:bin/tool\n"
                   f"fill {manifest.parent}: 1 copied, 0 already in place, 0 refused, "
                   "0 from sources not named\n")
    assert _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")[1].endswith(
        "0 copied, 1 already in place, 0 refused, 0 from sources not named\n")


def test_fill_replaces_a_copy_that_lost_its_pin_and_leaves_no_temporary(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"a.bin": DATA})
    _write(manifest, [_entry("a.bin")])
    pinned = manifest.read_bytes()
    (manifest.parent / "a.bin").write_bytes(b"corrupt")
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 0 and out.endswith("1 copied, 0 already in place, 0 refused, "
                                    "0 from sources not named\n")
    assert (manifest.parent / "a.bin").read_bytes() == DATA
    assert sorted(p.name for p in manifest.parent.iterdir()) == ["a.bin", bench.MANIFEST]
    assert manifest.read_bytes() == pinned, "only --record writes the manifest"


def test_fill_refuses_a_source_that_is_not_the_pinned_one_and_leaves_the_copy(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"a.bin": b"another build\n"})
    _write(manifest, [_entry("a.bin")])
    (manifest.parent / "a.bin").write_bytes(b"left alone")
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 1 and out.startswith("REFUSED a.bin: src:a.bin: sha256 ")
    assert (manifest.parent / "a.bin").read_bytes() == b"left alone"
    assert sorted(p.name for p in manifest.parent.iterdir()) == ["a.bin", bench.MANIFEST]


def test_fill_refuses_an_absent_source(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"other": DATA})
    _write(manifest, [_entry("a.bin")])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 1 and "is not a file" in out


def test_record_pins_the_fresh_copies_and_the_source_head(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"a.bin": DATA})
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    other = {**_entry("b.bin", sha256="kept"), "source_repo": "elsewhere"}
    _write(manifest, [_entry("a.bin", sha256=""), other])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}",
                      "--record")
    assert rc == 0 and out.endswith("1 from sources not named; manifest recorded\n")
    assert json.loads(manifest.read_text()) == [
        {**_entry("a.bin"), "source_commit": head}, other]


def test_record_keeps_a_captures_argv_and_pins_its_output(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"gen.py": b"print('the pinned bytes')\n"})
    argv = [sys.executable, "gen.py"]
    _write(manifest, [_entry("out.bin", sha256="", source_path="gen.py", capture=argv)])
    assert _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}",
                "--record")[0] == 0
    (held,) = json.loads(manifest.read_text())
    assert held["capture"] == argv and held["sha256"] == PIN and held["source_commit"]


def test_record_with_a_refusal_writes_no_manifest(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"a.bin": DATA})
    _write(manifest, [_entry("a.bin", sha256=""), _entry("gone.bin", sha256="")])
    before = manifest.read_bytes()
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}",
                      "--record")
    assert rc == 1 and manifest.read_bytes() == before
    assert out.endswith("; manifest NOT recorded, so the copies made now are off their old pins\n")


def test_a_capture_is_the_output_of_its_program_run_in_the_checkout(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    checkout = _checkout(tmp_path, {"gen.py": b"import helper\nprint(helper.TEXT)\n",
                                    "helper.py": b"TEXT = 'the pinned bytes'\n"})
    argv = [sys.executable, "gen.py"]
    _write(manifest, [_entry("out.bin", source_path="gen.py", capture=argv)])
    rc, _, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 0 and (manifest.parent / "out.bin").read_bytes() == DATA
    assert not (checkout / "__pycache__").exists(), "an imported module wrote its bytecode"
    _write(manifest, [_entry("out.bin", source_path="gen.py",
                             capture=[sys.executable, "-c", "raise SystemExit(4)"])])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 1 and "its capture answered rc=4 with 0 bytes" in out
    _write(manifest, [_entry("out.bin", source_path="gen.py", capture=[sys.executable, "-c", ""])])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 1 and "its capture answered rc=0 with 0 bytes" in out
    _write(manifest, [_entry("out.bin", source_path="gen.py", capture=["./no-such-program"])])
    rc, out, _ = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    assert rc == 1 and "its capture could not run" in out


@pytest.mark.parametrize(("source", "why"), [("nobody", "names no file from it"),
                                              ("src", "not a directory")])
def test_fill_from_a_source_the_manifest_does_not_name_or_that_is_not_there_is_invalid(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path, source: str, why: str,
) -> None:
    _write(manifest, [_entry("a.bin")])
    rc, _, err = _run(capsys, "fill", *_at(manifest), "--from",
                      f"{source}={tmp_path / 'absent'}")
    assert rc == 3 and why in err


def test_record_on_a_directory_with_no_git_head_is_invalid(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    _write(manifest, [_entry("a.bin")])
    (tmp_path / "plain").mkdir()
    rc, _, err = _run(capsys, "fill", *_at(manifest), "--from", f"src={tmp_path / 'plain'}",
                      "--record")
    assert rc == 3 and "rev-parse HEAD" in err


def test_missing_names_the_first_problem_and_the_remedy_or_nothing(
    manifest: Path, tmp_path: Path,
) -> None:
    _write(manifest, [_entry("board/a.bin"), _entry("board/b.bin"), _entry("other/c.bin")])
    at = bench.Bench(manifest.parent)
    reason = at.missing("board/")
    assert reason.startswith("bench MISSING board/a.bin") and "(and 1 more)" in reason
    assert (f"`python -m scry_core.live_bench fill --bench {manifest.parent} --from "
            "<source_repo>=<checkout>`" in reason)
    assert f"`python -m scry_core.live_bench check --bench {manifest.parent}`" in reason
    unusable = at.missing("none/")
    assert unusable.startswith("bench unusable: ") and "names no file under 'none/'" in unusable
    assert "fill" not in unusable, "fill cannot make a manifest name a file"
    gone = bench.Bench(tmp_path / "nowhere").missing("board/")
    assert gone == ("bench unusable: the bench does not exist: "
                    f"{tmp_path / 'nowhere'} is not a directory")
    (tmp_path / "bench/other").mkdir()
    (tmp_path / "bench/other/c.bin").write_bytes(DATA)
    assert at.missing("other/") == ""
    assert at.missing("other/c.bin") == "", "one file is a prefix too"
    assert "names no file under 'othe'" in at.missing("othe"), "whole segments only"


def test_missing_is_worked_out_once_per_bench_and_prefix(manifest: Path, tmp_path: Path) -> None:
    """A run asks every cell's board the same question: the first answer is the run's, and a
    bench filled meanwhile is a new run's, so a new `Bench` reads it again."""
    _write(manifest, [_entry("board/a.bin")])
    at = bench.Bench(manifest.parent)
    first = at.missing("board/")
    assert first.startswith("bench MISSING board/a.bin")
    (tmp_path / "bench/board").mkdir()
    (tmp_path / "bench/board/a.bin").write_bytes(DATA)
    assert at.missing("board/") == first
    assert bench.Bench(manifest.parent).missing("board/") == ""


def test_an_absent_manifest_is_its_own_reason_with_the_check_to_run(tmp_path: Path) -> None:
    (tmp_path / "bench").mkdir()
    reason = bench.Bench(tmp_path / "bench").missing("board/")
    assert reason.startswith(f"bench manifest ABSENT: {tmp_path / 'bench' / bench.MANIFEST}")
    assert reason.endswith(f"`python -m scry_core.live_bench check --bench {tmp_path / 'bench'}`")


def test_pinned_is_every_path_the_manifest_pins_or_invalid(manifest: Path) -> None:
    _write(manifest, [_entry("board/a.bin"), _entry("other/c.bin")])
    assert bench.Bench(manifest.parent).pinned == {"board/a.bin", "other/c.bin"}
    manifest.write_text("[]")
    with pytest.raises(bench.Invalid, match="names no file"):
        _ = bench.Bench(manifest.parent).pinned


def test_a_copy_that_cannot_be_read_is_a_reason_and_not_a_crash(
    manifest: Path, tmp_path: Path,
) -> None:
    _write(manifest, [_entry("a.bin")])
    copy = tmp_path / "bench/a.bin"
    copy.write_bytes(DATA)
    copy.chmod(0)
    try:
        assert bench.Bench(manifest.parent).missing("a.bin").startswith(
            "bench unusable: [Errno 13]")
    finally:
        copy.chmod(0o644)


def test_check_of_a_copy_that_cannot_be_read_is_invalid_naming_it(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """1 is a verdict about the bench; an error that stopped the check before one is INVALID, in
    one line naming the file, and never a traceback."""
    _write(manifest, [_entry("a.bin")])
    copy = tmp_path / "bench/a.bin"
    copy.write_bytes(DATA)
    copy.chmod(0)
    try:
        rc, out, err = _run(capsys, "check", *_at(manifest))
    finally:
        copy.chmod(0o644)
    assert (rc, out) == (3, "") and str(copy) in err and "Traceback" not in err
    assert err.startswith("INVALID: check stopped before its verdict") and err.count("\n") == 1


def test_fill_into_a_bench_it_cannot_write_is_invalid(
    manifest: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path, {"a.bin": DATA})
    _write(manifest, [_entry("a.bin")])
    manifest.parent.chmod(0o555)
    try:
        rc, _, err = _run(capsys, "fill", *_at(manifest), "--from", f"src={checkout}")
    finally:
        manifest.parent.chmod(0o755)
    assert rc == 3 and err.startswith("INVALID: fill stopped before its verdict")
    assert "Traceback" not in err


def test_a_bench_copied_with_replace_works_its_own_answers_out(
    manifest: Path, tmp_path: Path,
) -> None:
    """The memo belongs to one bench: a copy pointed elsewhere starts with none."""
    import dataclasses

    _write(manifest, [_entry("board/a.bin")])
    first = bench.Bench(manifest.parent)
    assert first.missing("board/").startswith("bench MISSING")
    other = tmp_path / "other"
    (other / "board").mkdir(parents=True)
    _write(other / bench.MANIFEST, [_entry("board/a.bin")])
    (other / "board/a.bin").write_bytes(DATA)
    assert dataclasses.replace(first, root=other).missing("board/") == ""


def test_a_bench_root_that_is_not_there_is_named_as_such(tmp_path: Path) -> None:
    reason = bench.Bench(tmp_path / "nowhere").missing("board/")
    assert "the bench does not exist" in reason and "ABSENT" not in reason

