"""The argument judges, at their edges: a bool is never a number, a NUL is never in a path, and
a picture is read once so its digest and its pixels are one file's."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from scry_core import judges, png
from scry_core.reply_contract import Invalid


def test_whole_numbers_and_their_bounds() -> None:
    assert judges.whole(0) and judges.whole(5, 5) and judges.whole(5, 0, 5)
    for bad, lo, hi in ((True, 0, None), (-1, 0, None), (4, 5, None), (6, 0, 5), (1.0, 0, None),
                        ("1", 0, None)):
        assert not judges.whole(bad, lo, hi), (bad, lo, hi)


#: Windows builds a `~user` path beside the home without asking whether that user exists.
NTPATH = "ntpath expands any ~user"


@pytest.mark.parametrize("value, said", [
    ("a.png", "a='a.png' must be an absolute path or start with `~`"),
    ("", "a is empty: give an absolute path, or one starting with `~`"),
    (None, "a=None is not a path"), (3, "a=3 is not a path"),
    ("/x\x00y", "holds a NUL"), ("/x\ud800", "holds a lone surrogate"),
    pytest.param("~no-such-user-here/x", "names a home directory this host cannot find",
                 marks=pytest.mark.skipif(sys.platform == "win32", reason=NTPATH)),
])
def test_a_path_that_is_not_absolute_is_refused(value: object, said: str) -> None:
    with pytest.raises(Invalid, match=re.escape(said)) as e:
        judges.absolute("a", value, tool="t")
    assert e.value.code == "bad_argument" and e.value.fields == {"tool": "t"}


def test_a_tilde_path_is_expanded_as_a_person_means_it(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert judges.absolute("a", "~/x.png") == tmp_path / "x.png"
    assert judges.absolute("a", "~") == tmp_path
    assert judges.absolute("a", str(tmp_path / "y")) == tmp_path / "y"


def test_a_picture_is_read_once_with_its_digest(tmp_path: Path) -> None:
    raster = png.Raster(1, 1, bytes(3))
    path = tmp_path / "p.png"
    path.write_bytes(png.encode(raster))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert judges.picture_file("p", path) == (raster, digest)
    assert judges.picture_file("p", path, digest)[0] == raster
    with pytest.raises(Invalid, match="no longer matches"):
        judges.picture_file("p", path, "0" * 64)
    path.write_bytes(b"junk")
    with pytest.raises(Invalid, match="not a PNG"):
        judges.picture_file("p", path)
    with pytest.raises(Invalid, match="cannot be read"):
        judges.picture_file("p", tmp_path / "absent.png")
    with pytest.raises(Invalid, match="is not a file"):
        judges.existing_file("p", str(tmp_path))


def test_expanded_hands_on_the_text_absolute_would_judge(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert judges.expanded("~/roms") == str(tmp_path / "roms")
    assert judges.expanded("/abs/~x") == "/abs/~x" and judges.expanded("rel") == "rel"
    if sys.platform != "win32":                  # NTPATH
        assert judges.expanded("~no-such-user-here/x") == "~no-such-user-here/x"
    assert judges.absolute("a", judges.expanded("~/roms")) == judges.absolute("a", "~/roms")


def test_a_file_to_write_has_a_directory_and_a_fresh_one_nothing_there(tmp_path: Path) -> None:
    there = tmp_path / "there.png"
    there.write_bytes(b"x")
    (tmp_path / "dangling").symlink_to(tmp_path / "nowhere")
    assert judges.writable_file("dest", str(there)) == there
    assert judges.fresh_file("dest", str(tmp_path / "new.png")) == tmp_path / "new.png"
    for taken in (there, tmp_path / "dangling"):
        with pytest.raises(Invalid, match=r"already exists\. This will not overwrite it") as e:
            judges.fresh_file("dest", str(taken), tool="t")
        assert e.value.code == "bad_argument" and e.value.fields == {"tool": "t"}
    with pytest.raises(Invalid, match=r"dest: .*[/\\]no is not a directory, so x\.png has nowhere"):
        judges.writable_file("dest", str(tmp_path / "no" / "x.png"))
    with pytest.raises(Invalid, match="must be an absolute path"):
        judges.fresh_file("dest", "x.png")


def test_a_name_too_long_to_look_at_is_refused_not_raised(tmp_path: Path) -> None:
    with pytest.raises(Invalid) as e:
        judges.writable_file("dest", str(tmp_path / ("x" * 300) / "y"))
    assert e.value.code == "bad_argument"
    assert judges.fresh_file("dest", str(tmp_path / ("x" * 300))).name == "x" * 300


@pytest.mark.parametrize(("judge", "method"), [(judges.writable_file, "is_dir"),
                                               (judges.fresh_file, "is_dir"),
                                               (judges.fresh_file, "exists")])
def test_a_path_the_filesystem_will_not_look_at_is_refused_not_raised(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, judge: Any, method: str) -> None:
    """Before Python 3.14 `exists` and `is_dir` raise on EACCES rather than answering False."""
    def denied(self: Path, *a: Any, **k: Any) -> bool:
        raise PermissionError(13, "Permission denied", str(self))
    monkeypatch.setattr(Path, method, denied)
    with pytest.raises(Invalid, match="cannot be looked at: .*Permission denied") as e:
        judge("dest", str(tmp_path / "x.png"))
    assert e.value.code == "bad_argument"


def test_a_file_the_filesystem_will_not_look_at_is_refused_not_raised(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(self: Path) -> bool:
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(Path, "is_file", denied)
    with pytest.raises(Invalid, match="cannot be looked at") as e:
        judges.existing_file("a", str(tmp_path / "x.png"))
    assert e.value.code == "bad_argument"


@pytest.mark.parametrize(("value", "want"), [(7, 7), ("0x1F", 0x1F), (" 0xff ", 0xFF), (0, 0)])
def test_a_number_is_an_integer_or_the_hex_it_spells(value: object, want: int) -> None:
    assert judges.number("value", value, 32, "the debugger") == want


@pytest.mark.parametrize(("value", "words"), [
    (True, "an integer or a `0x` hex string"), (1.5, "an integer or a `0x` hex string"),
    ("12", "decimal text is refused"), ("0xZZ", "starts like hex and is not"),
    ("", "is empty: an integer or a `0x` hex string"), ("  ", "is empty"),
    ("-0x1", "not an integer or a `0x` hex string"), (1 << 32, "wider than 32 bits"),
    ("0x100000000", "wider than 32 bits, the widest number the debugger holds")])
def test_a_number_refuses_what_it_does_not_spell_naming_the_argument(
        value: object, words: str) -> None:
    with pytest.raises(Invalid) as refused:
        judges.number("value", value, 32, "the debugger")
    assert refused.value.code == "bad_argument" and words in str(refused.value), refused.value
    assert "value" in str(refused.value)


def test_a_written_file_is_named_by_its_path_size_and_hash(tmp_path: Path) -> None:
    f = tmp_path / "x.png"
    f.write_bytes(b"abc")
    assert judges.file_facts(f) == {"path": str(f), "bytes": 3,
                                    "sha256": hashlib.sha256(b"abc").hexdigest()}
