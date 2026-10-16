"""Goldens in the `shasum -a 256` format, held on files written here: one wrong line, the lines
that do not parse, and the case where nothing meets, which is no verdict."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scry_core import goldens
from scry_core.reply_contract import Invalid


def _sums(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n")
    return path


def test_goldens_with_one_wrong_line(tmp_path: Path) -> None:
    files = {}
    for name, body in (("a.png", b"aa"), ("b.png", b"bb"), ("c.png", b"cc")):
        (tmp_path / name).write_bytes(body)
        files[name] = tmp_path / name
    good = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in files.items()}
    sums = goldens.read_checksums("c", _sums(tmp_path / "g.sha256", [
        f"{good['a.png']}  goldens/a.png", f"{'0' * 64} *b.png", f"{good['c.png']}  c.png\r",
        "", f"{'1' * 64}  gone.png"]))
    got = goldens.compare(files, sums)
    assert got == {"matched": 2, "differing": ["b.png"], "missing": ["gone.png"], "extra": []}


def test_a_name_holding_a_line_separator_is_one_name(tmp_path: Path) -> None:
    sums = goldens.read_checksums("c", _sums(tmp_path / "g.sha256",
                                             [f"{'a' * 64}  x y.png"]))
    assert sums == {"x y.png": "a" * 64}


@pytest.mark.parametrize("lines, said", [
    (["not a line"], r"g.sha256:1 is not `<sha256>  <name>`"),
    ([f"{'a' * 64}  x.png", f"{'b' * 64}  d/x.png"], "g.sha256:2 names x.png a second time"),
    ([f"{'a' * 63}  x.png"], ":1 is not"),
    ([""], "holds no checksum line"),
])
def test_a_checksums_file_that_does_not_parse_is_refused_naming_the_line(
        tmp_path: Path, lines: list[str], said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        goldens.read_checksums("checksums", _sums(tmp_path / "g.sha256", lines))
    assert e.value.code == "bad_argument"


def test_an_unreadable_checksums_file_or_golden_is_refused(tmp_path: Path) -> None:
    (tmp_path / "bin.sha256").write_bytes(b"\xff\xfe")
    with pytest.raises(Invalid, match="cannot be read"):
        goldens.read_checksums("checksums", tmp_path / "bin.sha256")
    with pytest.raises(Invalid, match="cannot be read"):
        goldens.compare({"a.png": tmp_path / "a.png"}, {"a.png": "0" * 64})


def test_goldens_that_meet_no_file_compare_nothing(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"a")
    with pytest.raises(Invalid, match="nothing was compared") as e:
        goldens.compare({"a.png": tmp_path / "a.png"}, {"b.png": "0" * 64})
    assert e.value.code == "control_silent"


def test_a_directory_offers_its_pngs_by_name(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(b"a")
    (tmp_path / "notes.txt").write_bytes(b"n")
    (tmp_path / "sub.png").mkdir()
    assert goldens.in_dir("dir", tmp_path) == {"a.png": tmp_path / "a.png"}
    with pytest.raises(Invalid, match="is not a directory"):
        goldens.in_dir("dir", tmp_path / "a.png")
