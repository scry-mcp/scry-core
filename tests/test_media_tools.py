"""The file tools as a server calls them: each body on real files, each judge refusing a wrong
shape before any file is read, the descriptions within what a client carries, and `register`
handing every tool to the server's own decorator."""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path
from typing import Any

import pytest

from scry_core import media_replies, media_tools, png, reply_schema, series
from scry_core.client_cap import CLIENT_TEXT_CAP, utf16_units
from scry_core.host_program import absolute as _abs
from scry_core.reply_contract import Invalid

RED, BLACK = (255, 0, 0), (0, 0, 0)


@pytest.fixture(autouse=True)
def judged_by_its_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every reply a tool here builds is held to the model both servers publish for it
    (`scry_core.media_replies`), as their batteries hold their own."""
    for name, model in media_replies.MODELS.items():
        judge = reply_schema.judged(model)
        body = getattr(media_tools, name)

        @functools.wraps(body)
        def checked(*a: Any, _body: Any = body, _judge: Any = judge, **k: Any) -> Any:
            out = _body(*a, **k)
            _judge.validate_python({"status": "ok", **out})
            return out
        monkeypatch.setattr(media_tools, name, checked)


def _line(tool: str, method: str, reply: dict[str, Any]) -> str:
    return media_tools.TOOLS[tool].summary({"method": method}, reply)


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
    got = media_tools.image_compare("image", a, b)
    assert (got["differing_pixels"], got["bbox"], got["max_delta"]) == (2, [1, 1, 2, 1],
                                                                          [255, 0, 0])
    assert got["crop"] == [0, 0, 4, 3] and got["shift"] == [0, 0] and got["tolerance"] == 0
    assert (got["width"], got["height"]) == (4, 3)
    assert got["a"] == {"path": a, "sha256": hashlib.sha256(Path(a).read_bytes()).hexdigest()}
    moved = media_tools.image_compare("image", a, b, shift=[1, 0])
    assert moved["differing_pixels"] == 0 and moved["crop"] == [0, 0, 3, 3]
    assert _line("image_compare", "image", moved) == (
        "image_compare image: no pixel differs over 3x3 at [0, 0]")
    assert _line("image_compare", "image", got) == (
        "image_compare image: 2 pixels differ over 4x3, bbox [1, 1, 2, 1]")
    near = media_tools.image_compare("image", a, b, tolerance=255)
    assert _line("image_compare", "image", near) == (
        "image_compare image: no pixel differs past tolerance 255 over 4x3 at [0, 0]")


def test_series_diff_region_track_and_golden_check_on_one_series(tmp_path: Path) -> None:
    lit = {n: ({(0, 0)} if n in (2, 3) else set()) | {(3, 2)} for n in range(5)}
    one = _series(tmp_path / "one", lit)
    two = _series(tmp_path / "two", {**lit, 4: {(0, 0), (3, 2)}})
    diff = media_tools.image_compare("series", one, two)
    assert (diff["pairs"], diff["identical"], diff["differing"]) == (5, 4, 1)
    assert diff["first_differing"]["frame"] == 4 and diff["a"] == one
    assert diff["crop"] == [0, 0, 4, 3], "the region compared, said whole"
    assert _line("image_compare", "series", diff) == (
        "image_compare series: 5 pairs, 4 identical, 1 differing, first at frame 4")
    track = media_tools.image_compare("region", manifest=one, crop=[0, 0, 1, 1],
                                      measure="changed_pixels")
    assert track["transitions"] == [[2, 1], [4, 1]] and track["manifest"] == one
    assert track["start"]["available"] is False, track
    assert _line("image_compare", "region", track) == (
        "image_compare region: changed_pixels, 2 transitions over 5 frames")
    cut = media_tools.image_compare("region", manifest=one, crop=[0, 0, 1, 1],
                                    measure="changed_pixels", limit=1)
    assert _line("image_compare", "region", cut) == (
        "image_compare region: changed_pixels, 2 transitions over 5 frames, the first 1 listed")
    assert _line("image_compare", "region", {**track, "transitions_total": 1}).endswith(
        ", 1 transition over 5 frames")
    ref = _png(tmp_path / "ref.png", {(0, 0)}, 1, 1)
    matched = media_tools.image_compare("region", manifest=one, crop=[0, 0, 1, 1],
                                        measure="match", ref=ref, threshold=1)
    assert matched["start"] == [0, False] and matched["transitions"] == [[2, True], [4, False]]
    folder = Path(one).parent
    sums = tmp_path / "g.sha256"
    sums.write_text("".join(
        f"{hashlib.sha256((folder / series.frame_name(n)).read_bytes()).hexdigest()}  "
        f"{series.frame_name(n)}\n" for n in range(4)))
    gold = media_tools.image_compare("golden", manifest=one, checksums=str(sums))
    assert gold == {"matched": 4, "differing": [], "missing": [], "extra": ["f000004.png"],
                    "differing_total": 0, "missing_total": 0, "extra_total": 1,
                    "checksums": str(sums), "manifest": one}
    by_dir = media_tools.image_compare("golden", dir=str(folder), checksums=str(sums))
    assert by_dir["matched"] == 4 and by_dir["dir"] == str(folder)
    assert _line("image_compare", "golden", gold) == (
        "image_compare golden: 4 matched, 0 differing, 0 missing, 1 extra")
    with pytest.raises(Invalid, match="is not a directory"):
        media_tools.image_compare("golden", dir=str(sums), checksums=str(sums))
    (folder / series.frame_name(1)).unlink()
    with pytest.raises(Invalid, match="cannot be read"):
        media_tools.image_compare("golden", manifest=one, checksums=str(sums))


@pytest.mark.parametrize("method, kw, said", [
    ("image", {"a": "a.png", "b": "/b.png"}, "a='a.png' must be an absolute path"),
    ("image", {"a": _abs("a"), "b": _abs("b"), "crop": [0, 0, 0, 1]}, "crop="),
    ("image", {"a": _abs("a"), "b": _abs("b"), "shift": [1]}, "shift="),
    ("image", {"a": _abs("a"), "b": _abs("b"), "tolerance": 256}, "tolerance=256"),
    ("image", {"a": _abs("a"), "b": _abs("b"), "tolerance": True}, "tolerance=True"),
    ("series", {"a": _abs("a"), "b": ""}, "b is empty"),
    ("series", {"a": _abs("a"), "b": _abs("b"), "crop": [1]}, "crop="),
    ("region", {"manifest": _abs("m"), "measure": "area"}, "measure='area' is one of"),
    ("region", {"manifest": _abs("m"), "measure": "match"}, "`ref` goes with measure"),
    ("region", {"manifest": _abs("m"), "ref": "/r.png"}, "`ref` goes with measure"),
    ("region", {"manifest": _abs("m"), "measure": "match", "ref": "r.png"}, "ref='r.png'"),
    ("region", {"manifest": _abs("m"), "threshold": 0}, "threshold=0"),
    ("region", {"manifest": _abs("m"), "threshold": 1.5}, "threshold=1.5"),
    ("region", {"manifest": _abs("m"), "limit": 0}, "limit=0"),
    ("region", {"manifest": _abs("m"), "limit": series.LIMIT_MAX + 1}, "limit="),
    ("region", {"manifest": _abs("m"), "crop": "x"}, "crop="),
    ("golden", {"checksums": _abs("g")}, "one of the two"),
    ("golden", {"checksums": _abs("g"), "manifest": _abs("m"), "dir": _abs("d")}, "one of the two"),
    ("golden", {"checksums": "g", "dir": _abs("d")}, "checksums='g'"),
    ("golden", {"checksums": _abs("g"), "dir": "d"}, "dir='d'"),
    ("golden", {"checksums": _abs("g"), "manifest": "m"}, "manifest='m'"),
])
def test_a_wrong_shape_is_refused_by_the_judge_and_by_the_body(method: str, kw: dict[str, Any],
                                                               said: str) -> None:
    spec = media_tools.TOOLS["image_compare"]
    with pytest.raises(Invalid, match=said) as e:
        spec.check(method=method, **kw)
    assert e.value.code == "bad_argument"
    with pytest.raises(Invalid, match=said):
        spec.body(method, **kw)


@pytest.mark.parametrize("tool, method, kw, stray", [
    ("image_compare", "series", {"a": _abs("a"), "b": _abs("b"), "tolerance": 0}, "`tolerance`"),
    ("image_compare", "image", {"a": _abs("a"), "b": _abs("b"), "limit": 3}, "`limit`"),
    ("image_compare", "golden", {"checksums": _abs("g"), "dir": _abs("d"), "crop": [0, 0, 1, 1]},
     "`crop`"),
    ("image_compare", "region", {"manifest": _abs("m"), "a": _abs("a")}, "`a`"),
    ("audio_compare", "measure", {"path": "/p", "align": False}, "`align`"),
    ("audio_compare", "diff", {"a": _abs("a"), "b": _abs("b"), "channel": 0}, "`channel`"),
])
def test_an_argument_the_method_does_not_take_is_refused_naming_the_method(
        tool: str, method: str, kw: dict[str, Any], stray: str) -> None:
    spec = media_tools.TOOLS[tool]
    for call in (lambda: spec.check(method=method, **kw), lambda: spec.body(method, **kw)):
        with pytest.raises(Invalid, match=f"method `{method}` does not take {stray}") as e:
            call()
        assert e.value.code == "bad_argument"
    with pytest.raises(Invalid, match="method is one of"):
        spec.check(method="nope")


def test_the_limits_themselves_are_accepted() -> None:
    check = media_tools.TOOLS["image_compare"].check
    check(method="image", a=_abs("a"), b=_abs("b"), tolerance=255)
    check(method="region", manifest=_abs("m"), threshold=1, limit=series.LIMIT_MAX)
    check(method="region", manifest=_abs("m"), limit=1)


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
    assert not media_tools.TOOLS["image_compare"].read_only, "its region method writes a file"


def test_register_hands_each_tool_to_the_servers_own_decorator() -> None:
    seen: list[tuple[str, Any, bool, str, Any]] = []

    def wrap(title: str, *, summary: Any, read_only: bool, replay: Any) -> Any:
        def register(fn: Any) -> Any:
            seen.append((title, summary, read_only, fn.__name__, replay))
            return ("registered", fn.__name__)
        return register
    names = media_tools.IMAGE_TOOLS + media_tools.AUDIO_TOOLS
    got = media_tools.register(wrap, names, lambda body: body)
    assert got == {n: ("registered", n) for n in names}
    assert [s[3] for s in seen] == ["image_compare", "audio_compare"]
    assert [s[2] for s in seen] == [False, True]
    # None reads the machine, so an export drops them but for the check of what files hold.
    assert [s[4] for s in seen] == [
        {"image": "drop", "series": "drop", "region": "drop",
         "golden": ("matched", "differing_total", "missing_total", "extra_total", "differing",
                    "missing", "extra")}, "drop"]
    with pytest.raises(ValueError, match="no media tools named"):
        media_tools.register(wrap, ["screen_view"], lambda body: body)


def test_register_makes_each_body_s_fields_the_servers_reply(tmp_path: Path) -> None:
    """The server's reply builder wraps what the body answers, and the registered function
    keeps the body's name and description, which the client is shown."""
    def wrap(title: str, **_: Any) -> Any:
        return lambda fn: fn
    got = media_tools.register(wrap, ["image_compare"], lambda body: {"status": "ok", **body})
    assert got["image_compare"].__name__ == "image_compare"
    assert got["image_compare"].__doc__ == media_tools.image_compare.__doc__
    with pytest.raises(Invalid, match="one of the two"):
        got["image_compare"]("golden", checksums=_abs("g"))
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"a")
    sums = tmp_path / "sums"
    sums.write_text(f"{hashlib.sha256(b'a').hexdigest()}  a.png\n")
    answered = got["image_compare"]("golden", dir=str(folder), checksums=str(sums))
    assert answered["status"] == "ok" and answered["matched"] == 1, answered


def test_a_judge_takes_the_defaults_its_body_declares(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each default is written once, on the body: the pre-gate judges a call that left an
    argument out with the value the body would run with."""
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(media_tools, "_judge_region", lambda **kw: seen.append(kw))
    gate = media_tools._gate(media_tools._region, media_tools._judge_region)
    gate(manifest=_abs("m"))
    assert seen == [{"manifest": _abs("m"), "crop": None, "measure": "signature", "ref": "",
                     "threshold": series.THRESHOLD_DEFAULT, "limit": series.LIMIT_DEFAULT}]
    gate(limit=3, ctx="ignored")
    assert seen[-1]["manifest"] == "" and seen[-1]["limit"] == 3 and "ctx" not in seen[-1]


def test_golden_check_cuts_each_list_at_limit_and_keeps_the_counts_whole(tmp_path: Path) -> None:
    """A thousand frames against another run's goldens with one name in common would list every
    other name; the lists stop at `limit`, the counts stay whole and the cut says so."""
    folder = tmp_path / "d"
    folder.mkdir()
    for n in range(6):
        (folder / f"f{n}.png").write_bytes(b"x%d" % n)
    sums = tmp_path / "sums"
    sums.write_text(f"{hashlib.sha256(b'x0').hexdigest()}  f0.png\n"
                    + "".join(f"{'0' * 64}  g{n}.png\n" for n in range(5)))
    got = media_tools.image_compare("golden", dir=str(folder), checksums=str(sums), limit=2)
    assert (got["matched"], got["extra"], got["extra_total"], got["missing"],
            got["missing_total"]) == (1, ["f1.png", "f2.png"], 5, ["g0.png", "g1.png"], 5)
    assert got["omitted"] == ["missing", "extra"] and "raise `limit`" in got["how"]
    assert _line("image_compare", "golden", got) == (
        "image_compare golden: 1 matched, 0 differing, 5 missing, 5 extra")
    whole = media_tools.image_compare("golden", dir=str(folder), checksums=str(sums))
    assert len(whole["extra"]) == 5 and "omitted" not in whole
    for bad in (0, series.LIMIT_MAX + 1, True):
        with pytest.raises(Invalid, match="limit="):
            media_tools.TOOLS["image_compare"].check(method="golden", dir=str(folder),
                                                      checksums=str(sums), limit=bad)


def test_golden_check_cuts_a_list_only_past_limit_and_counts_differing_whole(
        tmp_path: Path) -> None:
    folder = tmp_path / "d"
    folder.mkdir()
    for n in range(3):
        (folder / f"f{n}.png").write_bytes(b"x%d" % n)
    sums = tmp_path / "sums"
    sums.write_text("".join(f"{'0' * 64}  f{n}.png\n" for n in range(3)))
    at = media_tools.image_compare("golden", dir=str(folder), checksums=str(sums), limit=3)
    assert at["differing"] == ["f0.png", "f1.png", "f2.png"] and "omitted" not in at
    cut = media_tools.image_compare("golden", dir=str(folder), checksums=str(sums), limit=2)
    assert cut["differing"] == ["f0.png", "f1.png"] and cut["differing_total"] == 3
    assert cut["omitted"] == ["differing"]


def test_the_appended_tail_carries_no_indentation_of_its_own() -> None:
    for name in ("image_compare", "audio_compare"):
        doc = media_tools.TOOLS[name].body.__doc__ or ""
        assert not [line for line in doc.split("\n") if line.startswith(" ")], name
