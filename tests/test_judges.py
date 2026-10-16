"""The argument judges, at their edges: a bool is never a number, a NUL is never in a path, and
a picture is read once so its digest and its pixels are one file's."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scry_core import judges, png
from scry_core.reply_contract import Invalid


def test_whole_numbers_and_their_bounds() -> None:
    assert judges.whole(0) and judges.whole(5, 5) and judges.whole(5, 0, 5)
    for bad, lo, hi in ((True, 0, None), (-1, 0, None), (4, 5, None), (6, 0, 5), (1.0, 0, None),
                        ("1", 0, None)):
        assert not judges.whole(bad, lo, hi), (bad, lo, hi)


@pytest.mark.parametrize("value", ["a.png", "", None, 3, "/x\x00y"])
def test_a_path_that_is_not_absolute_is_refused(value: object) -> None:
    with pytest.raises(Invalid, match="is an absolute path") as e:
        judges.absolute("a", value)
    assert e.value.code == "bad_argument"


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
