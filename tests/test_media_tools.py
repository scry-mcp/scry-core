"""The file tools as a server calls them: each body on real files, each judge refusing a wrong
shape before any file is read, the descriptions within what a client carries, and `register`
handing every tool to the server's own decorator."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from scry_core import media_tools, png, series
from scry_core.client_cap import CLIENT_TEXT_CAP, utf16_units
from scry_core.reply_contract import Invalid

RED, BLACK = (255, 0, 0), (0, 0, 0)


def _png(path: Path, lit: set[tuple[int, int]], width: int = 4, height: int = 3) -> str:
    px = bytearray(bytes(BLACK) * (width * height))
    for x, y in lit:
        px[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes(RED)
    path.write_bytes(png.encode(png.Raster(width, height, bytes(px))))
    return str(path)


def _series(folder: Path, lit_by_frame: dict[int, set[tuple[int, int]]]) -> str:
    folder.mkdir()
    for n, lit in lit_by_frame.items():
        _png(folder / series.frame_name(n), lit)
    return str(series.write_manifest(folder, "t", "frame_number", None,
                                     sorted(lit_by_frame))["manifest"])


def test_image_diff_answers_numbers_and_names_both_files(tmp_path: Path) -> None:
    a = _png(tmp_path / "a.png", {(1, 1)})
    b = _png(tmp_path / "b.png", {(2, 1)})
    got = media_tools.image_diff(a, b)
    assert (got["differing_pixels"], got["bbox"], got["max_delta"]) == (2, [1, 1, 2, 1],
                                                                          [255, 0, 0])
    assert got["crop"] == [0, 0, 4, 3] and got["shift"] == [0, 0] and got["tolerance"] == 0
    assert (got["width"], got["height"]) == (4, 3)
    assert got["a"] == {"path": a, "sha256": hashlib.sha256(Path(a).read_bytes()).hexdigest()}
    moved = media_tools.image_diff(a, b, shift=[1, 0])
    assert moved["differing_pixels"] == 0 and moved["crop"] == [0, 0, 3, 3]
    assert media_tools._image_diff_line({}, moved) == (
        "image_diff: no pixel differs over 3x3 at [0, 0]")
    assert media_tools._image_diff_line({}, got) == (
        "image_diff: 2 pixels differ over 4x3, bbox [1, 1, 2, 1]")
    near = media_tools.image_diff(a, b, tolerance=255)
    assert media_tools._image_diff_line({}, near) == (
        "image_diff: no pixel differs past tolerance 255 over 4x3 at [0, 0]")


def test_series_diff_region_track_and_golden_check_on_one_series(tmp_path: Path) -> None:
    lit = {n: ({(0, 0)} if n in (2, 3) else set()) | {(3, 2)} for n in range(5)}
    one = _series(tmp_path / "one", lit)
    two = _series(tmp_path / "two", {**lit, 4: {(0, 0), (3, 2)}})
    diff = media_tools.series_diff(one, two)
    assert (diff["pairs"], diff["identical"], diff["differing"]) == (5, 4, 1)
    assert diff["first_differing"]["frame"] == 4 and diff["a"] == one
    assert diff["crop"] == [0, 0, 4, 3], "the region compared, said whole"
    assert media_tools._series_diff_line({}, diff) == (
        "series_diff: 5 pairs, 4 identical, 1 differing, first at frame 4")
    track = media_tools.region_track(one, crop=[0, 0, 1, 1], measure="changed_pixels")
    assert track["transitions"] == [[2, 1], [4, 1]] and track["manifest"] == one
    assert track["start"] is None
    assert media_tools._region_track_line({}, track) == (
        "region_track changed_pixels: 2 transitions over 5 frames")
    ref = _png(tmp_path / "ref.png", {(0, 0)}, 1, 1)
    matched = media_tools.region_track(one, crop=[0, 0, 1, 1], measure="match", ref=ref,
                                       threshold=1)
    assert matched["start"] == [0, False] and matched["transitions"] == [[2, True], [4, False]]
    folder = Path(one).parent
    sums = tmp_path / "g.sha256"
    sums.write_text("".join(
        f"{hashlib.sha256((folder / series.frame_name(n)).read_bytes()).hexdigest()}  "
        f"{series.frame_name(n)}\n" for n in range(4)))
    gold = media_tools.golden_check(manifest=one, checksums=str(sums))
    assert gold == {"matched": 4, "differing": [], "missing": [], "extra": ["f000004.png"],
                    "checksums": str(sums), "manifest": one}
    by_dir = media_tools.golden_check(dir=str(folder), checksums=str(sums))
    assert by_dir["matched"] == 4 and by_dir["dir"] == str(folder)
    assert media_tools._golden_check_line({}, gold) == (
        "golden_check: 4 matched, 0 differing, 0 missing, 1 extra")
    with pytest.raises(Invalid, match="is not a directory"):
        media_tools.golden_check(dir=str(sums), checksums=str(sums))
    (folder / series.frame_name(1)).unlink()
    with pytest.raises(Invalid, match="cannot be read"):
        media_tools.golden_check(manifest=one, checksums=str(sums))


@pytest.mark.parametrize("tool, kw, said", [
    ("image_diff", {"a": "a.png", "b": "/b.png"}, "a='a.png' is an absolute path"),
    ("image_diff", {"a": "/a", "b": "/b", "crop": [0, 0, 0, 1]}, "crop="),
    ("image_diff", {"a": "/a", "b": "/b", "shift": [1]}, "shift="),
    ("image_diff", {"a": "/a", "b": "/b", "tolerance": 256}, "tolerance=256"),
    ("image_diff", {"a": "/a", "b": "/b", "tolerance": True}, "tolerance=True"),
    ("series_diff", {"a": "/a", "b": ""}, "b='' is an absolute path"),
    ("series_diff", {"a": "/a", "b": "/b", "crop": [1]}, "crop="),
    ("region_track", {"manifest": "/m", "measure": "area"}, "measure='area' is one of"),
    ("region_track", {"manifest": "/m", "measure": "match"}, "`ref` goes with measure"),
    ("region_track", {"manifest": "/m", "ref": "/r.png"}, "`ref` goes with measure"),
    ("region_track", {"manifest": "/m", "measure": "match", "ref": "r.png"}, "ref='r.png'"),
    ("region_track", {"manifest": "/m", "threshold": 0}, "threshold=0"),
    ("region_track", {"manifest": "/m", "threshold": 1.5}, "threshold=1.5"),
    ("region_track", {"manifest": "/m", "limit": 0}, "limit=0"),
    ("region_track", {"manifest": "/m", "limit": series.LIMIT_MAX + 1}, "limit="),
    ("region_track", {"manifest": "/m", "crop": "x"}, "crop="),
    ("golden_check", {"checksums": "/g"}, "one of the two"),
    ("golden_check", {"checksums": "/g", "manifest": "/m", "dir": "/d"}, "one of the two"),
    ("golden_check", {"checksums": "g", "dir": "/d"}, "checksums='g'"),
    ("golden_check", {"checksums": "/g", "dir": "d"}, "dir='d'"),
    ("golden_check", {"checksums": "/g", "manifest": "m"}, "manifest='m'"),
])
def test_a_wrong_shape_is_refused_by_the_judge_and_by_the_body(tool: str, kw: dict[str, Any],
                                                               said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        media_tools.TOOLS[tool].check(**kw)
    assert e.value.code == "bad_argument"
    with pytest.raises(Invalid, match=said):
        media_tools.TOOLS[tool].body(**kw)


def test_the_limits_themselves_are_accepted() -> None:
    media_tools.check_image_diff("/a", "/b", tolerance=255)
    media_tools.check_region_track("/m", threshold=1, limit=series.LIMIT_MAX)
    media_tools.check_region_track("/m", limit=1)


def test_every_description_fits_a_client_and_says_what_it_touches() -> None:
    """A tool that writes a file says so and is not read-only; the others say they alter
    nothing, which is what their read-only flag tells a client."""
    for name, spec in media_tools.TOOLS.items():
        doc = spec.body.__doc__ or ""
        assert utf16_units(doc) <= CLIENT_TEXT_CAP, name
        assert doc.rstrip().endswith(media_tools.REFERENCE), name
        said = media_tools.READS_ONLY if spec.read_only else media_tools.WRITES_ITS_FILE
        assert said in doc and doc.count("needs no machine") == 1, name
        assert spec.body.__name__ == name
    assert not media_tools.TOOLS["region_track"].read_only


def test_register_hands_each_tool_to_the_servers_own_decorator() -> None:
    seen: list[tuple[str, Any, bool, str]] = []

    def wrap(title: str, *, summary: Any, read_only: bool) -> Any:
        def register(fn: Any) -> Any:
            seen.append((title, summary, read_only, fn.__name__))
            return ("registered", fn.__name__)
        return register
    got = media_tools.register(wrap, media_tools.IMAGE_TOOLS)
    assert got == {n: ("registered", n) for n in media_tools.IMAGE_TOOLS}
    assert [s[3] for s in seen] == list(media_tools.IMAGE_TOOLS)
    assert [s[2] for s in seen] == [True, True, False, True], "region_track writes its file"
    with pytest.raises(ValueError, match="no media tools named"):
        media_tools.register(wrap, ["screen_view"])
