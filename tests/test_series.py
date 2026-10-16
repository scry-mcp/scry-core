"""Series on disk, held on series built here: a manifest written and read back, a uniform series
and two series with nothing in common refused by their controls, a region whose transitions are
known by construction, offset series paired by frame, and manifests a hand edited wrongly."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scry_core import png, raster, series
from scry_core.reply_contract import Invalid

BLACK, WHITE = (0, 0, 0), (255, 255, 255)


def _frame(lit: set[tuple[int, int]], width: int = 4, height: int = 3) -> png.Raster:
    """A black picture with the pixels in `lit` white."""
    px = bytearray(bytes(BLACK) * (width * height))
    for x, y in lit:
        px[(y * width + x) * 3:(y * width + x) * 3 + 3] = bytes(WHITE)
    return png.Raster(width, height, bytes(px))


def _series(folder: Path, frames: dict[int, png.Raster], crop: list[int] | None = None) -> Path:
    folder.mkdir()
    for n, picture in frames.items():
        (folder / series.frame_name(n)).write_bytes(png.encode(picture))
    reply = series.write_manifest(folder, "test", "frame_number", crop, sorted(frames))
    return Path(reply["manifest"])


def _read(path: Path) -> series.Manifest:
    return series.read_manifest("m", str(path))


#: Frames 10..15. Pixel (0, 0) is lit on 12, 13 and 14 only: the region [0, 0, 1, 1] turns on at
#: 12 and off at 15. Pixel (3, 2) is lit on every frame: a region there never changes.
TRACKED = {10 + i: _frame({(3, 2)} | ({(0, 0)} if 2 <= i <= 4 else set())) for i in range(6)}


def test_a_manifest_is_written_beside_its_pngs_and_read_back(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    path = _series(folder, TRACKED, crop=[8, 8, 4, 3])
    doc = json.loads(path.read_text())
    assert doc["format"] == "scry-series/1" and doc["source"] == "frame_number"
    assert doc["crop"] == [8, 8, 4, 3] and len(doc["frames"]) == 6
    row = doc["frames"][2]
    data = (folder / "f000012.png").read_bytes()
    assert row == {"frame": 12, "path": "f000012.png", "sha256": hashlib.sha256(data).hexdigest(),
                   "bytes": len(data), "signature": raster.picture_signature(TRACKED[12])}
    back = _read(path)
    assert [r.frame for r in back.rows] == list(range(10, 16)) and back.size() == (4, 3)
    assert back.picture(back.rows[2]) == TRACKED[12]


def test_the_reply_half_names_the_manifest_and_counts_distinct_signatures(tmp_path: Path) -> None:
    folder = tmp_path / "s"
    folder.mkdir()
    for n, picture in TRACKED.items():
        (folder / series.frame_name(n)).write_bytes(png.encode(picture))
    got = series.write_manifest(folder, "test", "avi", None, sorted(TRACKED))
    assert got == {"manifest": str(folder / "manifest.json"), "count": 6, "first": 10,
                   "last": 15, "distinct": 2}
    with pytest.raises(Invalid, match="already there") as e:
        series.write_manifest(folder, "test", "avi", None, sorted(TRACKED))
    assert e.value.code == "bad_argument"
    with pytest.raises(Invalid, match="frame 99's picture") as e:
        series.write_manifest(folder, "test", "avi", None, [99])
    assert e.value.code == "host_failed"
    with pytest.raises(ValueError):
        series.write_manifest(folder, "test", "radio", None, [10])


@pytest.mark.parametrize("measure, transitions, gaps", [
    ("changed_pixels", [[12, 1], [15, 1]], [3]),
    ("signature", None, [3]),
])
def test_a_region_track_finds_the_transitions_built_in(tmp_path: Path, measure: series.Measure,
                                                       transitions: list[list[object]] | None,
                                                       gaps: list[int]) -> None:
    track = _read(_series(tmp_path / "s", TRACKED))
    got = series.region_track(track, [0, 0, 1, 1], measure, None, 0.98, 40)
    off = raster.picture_signature(TRACKED[10], [0, 0, 1, 1])
    on = raster.picture_signature(TRACKED[12], [0, 0, 1, 1])
    if transitions is None:
        transitions = [[12, on], [15, off]]
        assert got["start"] == [10, off]
    else:
        assert got["start"] is None, "changed_pixels has no frame before the first"
    assert got["transitions"] == transitions and got["gaps"] == gaps
    assert got["transitions_total"] == 2 and got["frames"] == 6 and got["crop"] == [0, 0, 1, 1]
    assert "omitted" not in got
    kept = json.loads(Path(got["path"]).read_text())
    assert kept["transitions"] == transitions and Path(got["path"]).parent == tmp_path / "s"


def test_a_match_track_flips_on_and_off_at_the_threshold(tmp_path: Path) -> None:
    track = _read(_series(tmp_path / "s", TRACKED))
    lit = png.Raster(2, 1, bytes(WHITE) + bytes(BLACK))
    got = series.region_track(track, [0, 0, 2, 1], "match", lit, 1.0, 40)
    assert got["start"] == [10, False] and got["transitions"] == [[12, True], [15, False]]
    # At half the region, the black half alone matches: on from the start, never off.
    with pytest.raises(Invalid) as e:
        series.region_track(track, [0, 0, 2, 1], "match", lit, 0.5, 40)
    assert e.value.code == "control_silent"


def test_a_crop_that_missed_is_control_silent_for_every_measure(tmp_path: Path) -> None:
    track = _read(_series(tmp_path / "s", TRACKED))
    measures: tuple[series.Measure, ...] = ("signature", "changed_pixels")
    for measure in measures:
        with pytest.raises(Invalid, match="the crop missed") as e:
            series.region_track(track, [3, 2, 1, 1], measure, None, 0.98, 40)
        assert e.value.code == "control_silent" and e.value.fields == {"frames": 6}


def test_a_long_list_is_cut_at_the_limit_and_says_so(tmp_path: Path) -> None:
    blink = {n: _frame({(0, 0)} if n % 2 else set()) for n in range(9)}
    track = _read(_series(tmp_path / "s", blink))
    got = series.region_track(track, None, "signature", None, 0.98, 3)
    assert got["transitions_total"] == 8 and len(got["transitions"]) == 3
    assert got["gaps"] == [1, 1] and got["omitted"] == ["transitions", "gaps"]
    assert "every one" in got["how"]
    assert len(json.loads(Path(got["path"]).read_text())["transitions"]) == 8
    again = series.region_track(track, None, "signature", None, 0.98, 3)
    assert again["path"] != got["path"], "a second track never overwrites the first"


def test_a_misused_track_is_the_callers_bug(tmp_path: Path) -> None:
    track = _read(_series(tmp_path / "s", TRACKED))
    for measure, ref, limit in (("area", None, 40), ("match", None, 40),
                                ("signature", None, 0)):
        with pytest.raises(ValueError):
            series.region_track(track, None, measure, ref, 0.98, limit)  # type: ignore[arg-type]


def test_a_uniform_series_is_refused_by_the_control(tmp_path: Path) -> None:
    still = _read(_series(tmp_path / "a", {n: _frame(set()) for n in range(3)}))
    moving = _read(_series(tmp_path / "b", TRACKED))
    for one, two, name in ((still, moving, "a"), (moving, still, "b")):
        with pytest.raises(Invalid, match=f"series `{name}`") as e:
            series.series_diff(one, two, None)
        assert e.value.code == "control_silent" and e.value.fields == {"series": name}
    # A crop where the moving series never changes silences it too.
    with pytest.raises(Invalid, match="over the crop"):
        series.series_diff(moving, moving, [3, 2, 1, 1])


def test_two_series_with_no_frame_in_common_compare_nothing(tmp_path: Path) -> None:
    a = _read(_series(tmp_path / "a", TRACKED))
    later = _read(_series(tmp_path / "b", {n + 100: p for n, p in TRACKED.items()}))
    with pytest.raises(Invalid, match="share no frame number") as e:
        series.series_diff(a, later, None)
    assert e.value.code == "control_silent"


def test_two_series_are_paired_by_frame_and_offsets_are_runs(tmp_path: Path) -> None:
    a = _read(_series(tmp_path / "a", TRACKED))
    shifted = {n + 3: p for n, p in TRACKED.items()}           # frames 13..18
    shifted[14] = _frame({(1, 1), (2, 2), (3, 2), (0, 0)})       # one more change on frame 14
    b = _read(_series(tmp_path / "b", shifted))
    got = series.series_diff(a, b, None)
    # Paired frames 13, 14, 15: a's 13 is lit at (0, 0), b's 13 is a's 10 (not lit), so 13
    # differs at one pixel; 14 differs at three; 15: a is off, b (a's 12) is on.
    assert got["pairs"] == 3 and got["identical"] == 0 and got["differing"] == 3
    assert got["first_differing"] == {"frame": 13, "differing_pixels": 1, "bbox": [0, 0, 1, 1]}
    assert got["only_in_a"] == [[10, 12]] and got["only_in_b"] == [[16, 18]]
    assert got["crop"] == [0, 0, 4, 3]
    same = series.series_diff(a, a, None)
    assert same["identical"] == 6 and same["first_differing"] is None
    assert series.series_diff(a, a, [0, 0, 1, 1])["identical"] == 6


def test_runs_are_inclusive_and_split_at_a_gap() -> None:
    assert series.runs([1, 2, 3, 7, 9, 10]) == [[1, 3], [7, 7], [9, 10]]
    assert series.runs([]) == []


@pytest.mark.parametrize("kw, want", [
    ({"frames": [0, 5, 9]}, [0, 5, 9]),
    ({"frames": (2, 3)}, [2, 3]),
    ({"first": 2, "last": 8, "step": 3}, [2, 5, 8]),
    ({"first": 4, "last": 4}, [4]),
])
def test_the_frames_a_capture_asks_for(kw: dict[str, object], want: list[int]) -> None:
    assert series.frame_list(kw.get("frames"), kw.get("first"), kw.get("last"),  # type: ignore[arg-type]
                             kw.get("step", 1)) == want  # type: ignore[arg-type]


@pytest.mark.parametrize("kw, said", [
    ({}, "one of the two"),
    ({"frames": [1], "first": 1, "last": 2}, "one of the two"),
    ({"frames": []}, "non-empty list"),
    ({"frames": [3, 3]}, "ascending, each frame once"),
    ({"frames": [-1]}, "at or above zero"),
    ({"frames": [1, 2], "step": 2}, "`step` goes with `first` and `last`"),
    ({"first": 5, "last": 4}, "before first=5"),
    ({"first": 0, "last": 4, "step": 0}, "a step above it"),
    ({"first": 0, "last": series.SERIES_MAX}, f"at most {series.SERIES_MAX}"),
    ({"frames": list(range(series.SERIES_MAX + 1))}, f"at most {series.SERIES_MAX}"),
])
def test_frames_of_the_wrong_shape_are_refused(kw: dict[str, object], said: str) -> None:
    with pytest.raises(Invalid, match=said):
        series.frame_list(kw.get("frames"), kw.get("first"), kw.get("last"),  # type: ignore[arg-type]
                          kw.get("step", 1))  # type: ignore[arg-type]


def test_the_largest_series_is_accepted() -> None:
    assert len(series.frame_list(None, 0, series.SERIES_MAX - 1)) == series.SERIES_MAX
    assert len(series.frame_list(list(range(series.SERIES_MAX)), None, None)) == series.SERIES_MAX


@pytest.mark.parametrize("doc, said", [
    ("{half", "is not JSON"),
    ({"format": "x"}, "is not a scry-series/1 manifest"),
    ({"format": "scry-series/1", "frames": []}, "lists no frames"),
    ({"format": "scry-series/1", "frames": [{"frame": 1}]}, "row 0 lacks"),
])
def test_a_manifest_of_another_shape_is_refused(tmp_path: Path, doc: object, said: str) -> None:
    path = tmp_path / "m.json"
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    with pytest.raises(Invalid, match=said):
        series.read_manifest("manifest", str(path))
    with pytest.raises(Invalid, match="is an absolute path"):
        series.read_manifest("manifest", "m.json")
    with pytest.raises(Invalid, match="is not a file"):
        series.read_manifest("manifest", str(tmp_path / "absent.json"))


def _edited(manifest: Path, i: int, fields: dict[str, object]) -> None:
    doc = json.loads(manifest.read_text())
    doc["frames"][i].update(fields)
    manifest.write_text(json.dumps(doc))


@pytest.mark.parametrize("fields, said", [
    ({"path": "../f000010.png"}, "not a file name in the manifest's own directory"),
    ({"path": "/etc/hosts"}, "not a file name"),
    ({"path": "x\x00"}, "not a file name"),
    ({"path": ".."}, "not a file name"),
    ({"frame": 10}, "row 1 is frame 10, not after frame 10"),
    ({"path": "absent.png"}, "cannot be read"),
])
def test_a_manifest_edited_wrongly_is_refused_naming_the_row(tmp_path: Path,
                                                             fields: dict[str, object],
                                                             said: str) -> None:
    path = _series(tmp_path / "s", TRACKED)
    _edited(path, 1, fields)
    with pytest.raises(Invalid, match=said) as e:
        _read(path)
    assert e.value.code == "bad_argument"


def test_a_frame_that_changed_since_its_manifest_is_refused_however_it_is_used(
        tmp_path: Path) -> None:
    """At reading, and after it: a file changed under a manifest read earlier is refused when its
    picture is asked for, so neither the fast path nor the slow one trusts a stale row."""
    path = _series(tmp_path / "s", TRACKED)
    (tmp_path / "s" / "f000011.png").write_bytes(png.encode(_frame({(1, 1)})))
    with pytest.raises(Invalid, match="no longer matches the sha256"):
        _read(path)
    other = _series(tmp_path / "t", TRACKED)
    track = _read(other)
    (tmp_path / "t" / "f000012.png").write_bytes(png.encode(_frame({(2, 2)})))
    with pytest.raises(Invalid, match="no longer matches the sha256"):
        track.picture(track.rows[2])
