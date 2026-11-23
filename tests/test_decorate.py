"""`scry_core.decorate`: a clip decorated from its run's timeline, the same bytes every time, the
pointer on every real position at its frame, a clip no timeline speaks for refused, and the rest
of scry-core importable without the `decorate` extra."""

from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from scry_core import abbreviation as ab
from scry_core import decorate as dc
from scry_core import motion, placement, timeline
from scry_core import overlay as ov
from scry_core.verdict import EXIT_INVALID, EXIT_PASS, Invalid

#: The demo runner's own recorded fixture: 120 frames of 8 x 8 at 60 a second.
RECORDING = Path(__file__).resolve().parent / "fixtures" / "demo" / "screen.avi"
needs_programs = pytest.mark.skipif(
    any(shutil.which(name) is None for name in motion.PROGRAMS),
    reason="a loop is made by ffmpeg and img2webp on PATH")
GREY = 0x404040
SIZE = (320, 240)
RATE = Fraction(60)
BOX = motion.Box(0, 0, 32, 24, (32, 24))


def _run() -> dict[str, Any]:
    made = timeline.Builder("t")
    made.add("boot", "start", {}, "ok", (None, 100))
    made.add("aim", "send_mouse", {"x": 2}, "ok", (100, 130),
             [timeline.pointer(3, 4, 100), timeline.pointer(20, 15, 112),
              timeline.pointer(9, 9, 113), timeline.pointer(30, 2, 130)])
    made.add("click", "send_mouse", {"button": "left"}, "ok", (130, 140),
             [timeline.button("left", True, 131), timeline.button("left", False, 135)])
    made.add("keys", "send_keys", {"keys": ["Enter"]}, "ok", (140, 160),
             [timeline.key("Enter", True, 141), timeline.key("Enter", False, 150)])
    return timeline.loads(made.dumps())


def _clip(first: int = 100, frames: int = 60, size: tuple[int, int] = SIZE) -> dc.Clip:
    rgb = bytes([GREY >> 16, (GREY >> 8) & 0xFF, GREY & 0xFF]) * (size[0] * size[1])
    return dc.Clip(list(range(first, first + frames)),
                   [motion.Picture(*size, rgb, 17) for _ in range(frames)], BOX, RATE)


def _pixel(picture: motion.Picture, x: int, y: int) -> tuple[int, ...]:
    at = (y * picture.width + x) * 3
    return tuple(picture.rgb[at:at + 3])


def test_keycaps_sit_in_the_corner_the_caption_band_leaves_free_and_never_overlap() -> None:
    made = timeline.Builder("k")
    made.add("boot", "start", {}, "ok", (None, 100))
    made.add("hold", "send_keys", {"keys": ["a", "b", "c", "d", "e", "f"]}, "ok", (100, 190),
             [timeline.key(name, True, 101) for name in "abcdef"])
    for place in ("top", "bottom"):
        style = dc.Style(layers=("calls", "keys"), place=place)
        painter = dc._Painter(_clip(), style, dc._plan(timeline.loads(made.dumps()), _clip()))
        boxes = painter._keycap_boxes(list("abcdef"))
        assert boxes, place
        left, top, right, bottom = painter._band_box()
        for _, (x0, y0, x1, y1) in boxes:
            assert x0 >= 0 and x1 <= painter.size[0], place
            if place == "bottom":
                assert y1 <= top, (place, y0, y1, top)
            else:
                assert y0 >= bottom, (place, y0, bottom)
        rects = [b for _, b in boxes]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
                assert apart, (place, a, b)


def test_a_clip_decorated_twice_is_the_same_pixels() -> None:
    style = dc.Style(sine=True, raster=True, zooms=(dc.Zoom(105, 150, (4, 4, 8, 6)),))
    first, again = (dc.decorate(_run(), _clip(), style) for _ in range(2))
    assert [p.rgb for p in first] == [p.rgb for p in again]
    assert first[0].rgb != _clip().pictures[0].rgb, "nothing was drawn, so nothing was compared"


@needs_programs
def test_a_loop_of_the_recorded_fixture_decorated_twice_is_the_same_bytes(tmp_path: Path) -> None:
    def once(n: int) -> motion.Built:
        return motion.build([motion.Cut(RECORDING, 0, 120)], tmp_path / f"w{n}",
                            dc.for_loop(_run(), [100]))

    one, two = once(1), once(2)
    plain = motion.build([motion.Cut(RECORDING, 0, 120)], tmp_path / "plain")
    assert one.data == two.data
    assert one.data != plain.data, "the decorated loop is the plain one"


@needs_programs
def test_each_cut_of_a_loop_is_decorated_with_its_own_frames_and_lasts_as_undecorated(
        tmp_path: Path) -> None:
    cuts = [motion.Cut(RECORDING, 0, 120), motion.Cut(RECORDING, 12, 108)]
    seen: list[tuple[int, list[int], int]] = []
    shown: list[bytes] = []
    decorated = dc.for_loop(_run(), [100, 300])

    def watched(n: int, numbers: Sequence[int], pictures: Sequence[motion.Picture],
                rate: Fraction, box: motion.Box) -> list[motion.Picture]:
        seen.append((n, list(numbers), len(pictures)))
        shown.append(pictures[6].rgb)
        return decorated(n, numbers, pictures, rate, box) if n == 0 else list(pictures)

    built = motion.build(cuts, tmp_path / "d", watched)
    assert seen == [(0, list(range(0, 120, 2)), 60), (1, list(range(12, 120, 2)), 54)]
    assert built.cut_ms == motion.build(cuts, tmp_path / "p").cut_ms
    assert shown[0] != shown[1], "the second cut was handed the first one's frames"


def test_the_pointer_is_on_every_position_the_server_sent_at_the_frame_it_was_sent() -> None:
    """Frame 112 and 113 each carry one; between two the path is eased and may leave the
    line, never the positions."""
    run, clip = _run(), _clip()
    drawn = dc.decorate(run, clip)
    sent = [e for c in run["calls"] for e in c["events"] if e["kind"] == "pointer"]
    for event in sent:
        x, y = dc._shown(BOX, clip.pictures[0], event["x"], event["y"])
        assert dc.pointer_at([(0.0, 1.0, 1.0), (1.0, x, y), (2.0, 5.0, 5.0)], 1.0) == (x, y)
        picture = drawn[clip.frames.index(event["frame"])]
        assert _pixel(picture, round(x), round(y)) == (255, 255, 255), event


def test_of_two_positions_sent_at_one_frame_the_later_is_drawn() -> None:
    made = timeline.Builder("t")
    made.add("aim", "send_mouse", {}, "ok", (100, 110),
             [timeline.pointer(3, 4, 105), timeline.pointer(20, 15, 105)])
    plan = dc._plan(timeline.loads(made.dumps()), _clip())
    assert plan.points == [(5 / 60, *dc._shown(BOX, _clip().pictures[0], 20, 15))]
    assert dc.pointer_at([(1.0, 0.0, 0.0), (2.0, 5.0, 5.0), (2.0, 9.0, 9.0)], 2.0) == (9.0, 9.0)


def test_a_press_ripples_where_the_pointer_is_drawn_and_none_before_any_position() -> None:
    """A position sent after the press moves the pointer during the press already."""
    made = timeline.Builder("t")
    made.add("early", "send_mouse", {}, "ok", (100, 102), [timeline.button("left", True, 101)])
    made.add("aim", "send_mouse", {}, "ok", (102, 110), [timeline.pointer(1, 1, 110)])
    made.add("click", "send_mouse", {}, "ok", (110, 120), [timeline.button("left", True, 111)])
    made.add("away", "send_mouse", {}, "ok", (120, 130), [timeline.pointer(30, 1, 120)])
    plan = dc._plan(timeline.loads(made.dumps()), _clip())
    assert [p[0] for p in plan.presses] == [11 / 60]
    assert plan.presses[0][1:] == dc.pointer_at(plan.points, 11 / 60)


def test_a_name_the_bitmap_font_cannot_draw_is_drawn_as_a_question_mark() -> None:
    font = dc._Font(1)
    assert font.mask("\u00e9\u2192").tobytes() == font.mask("??").tobytes()


def test_a_zoom_on_a_box_wider_than_the_picture_shows_the_whole_picture() -> None:
    style = dc.Style(layers=("edge",), zooms=(dc.Zoom(100, 159, (0, 0, 64, 48)),))
    plain = dc.Style(layers=("edge",))
    assert [p.rgb for p in dc.decorate(_run(), _clip(), style)] == \
        [p.rgb for p in dc.decorate(_run(), _clip(), plain)]


def test_the_pointer_waits_then_eases_and_is_not_drawn_before_its_first_position() -> None:
    points = [(1.0, 0.0, 0.0), (3.0, 100.0, 0.0)]
    assert dc.pointer_at(points, 0.5) is None
    assert dc.pointer_at(points, 2.0) == (0.0, 0.0), "it waits until the last MOVE_S"
    moving = dc.pointer_at(points, 3.0 - dc.MOVE_S / 2)
    assert moving is not None and moving[0] > 0 and moving[1] != 0, "eased on a curve"
    assert dc.pointer_at(points, 9.0) == (100.0, 0.0)


def test_before_its_first_call_a_frame_carries_the_edge_alone() -> None:
    drawn = dc.decorate(_run(), _clip(first=90, frames=20))
    edge = dc.decorate(_run(), _clip(first=90, frames=20), dc.Style(layers=("edge",)))
    assert drawn[0].rgb == edge[0].rgb and drawn[15].rgb != edge[15].rgb


def test_a_caption_wider_than_its_band_scrolls_and_one_that_fits_stands_still() -> None:
    def band(values: int, frame: int) -> bytes:
        made = timeline.Builder("t")
        made.add("go", "run_for", {f"v{n}": f"{n}" * 20 for n in range(values)}, "ok",
                 (100, 160))
        picture = dc.decorate(timeline.loads(made.dumps()), _clip(),
                              dc.Style(layers=("calls",)))[frame]
        row = picture.width * 3
        return picture.rgb[(SIZE[1] - 25) * row:(SIZE[1] - 15) * row]

    assert band(1, 20) == band(1, 40)
    assert band(6, 20) != band(6, 40)


@pytest.mark.parametrize(("clip", "why"), [
    (dc.Clip([1, 2], [_clip().pictures[0]], BOX, RATE), "1 pictures and 2 frames"),
    (dc.Clip([], [], BOX, RATE), "0 pictures and 0 frames"),
    (dc.Clip([100, 101], [_clip().pictures[0], _clip(size=(64, 48)).pictures[0]], BOX, RATE),
     "one size"),
])
def test_a_clip_that_is_not_one_picture_per_frame_of_one_size_is_refused(
        clip: dc.Clip, why: str) -> None:
    with pytest.raises(Invalid, match=why):
        dc.decorate(_run(), clip)


def test_the_module_runs_as_a_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["decorate", str(RECORDING), "--timeline",
                                      str(tmp_path / "none.json"), "--at", "0", "--frames", "1",
                                      "--out", str(tmp_path / "o.webp")])
    monkeypatch.delitem(sys.modules, "scry_core.decorate")
    with pytest.raises(SystemExit) as ended:
        runpy.run_module("scry_core.decorate", run_name="__main__")
    assert ended.value.code == EXIT_INVALID


def test_a_clip_the_timeline_names_no_call_over_is_refused_not_passed_through() -> None:
    with pytest.raises(Invalid, match="names no call over frames 400 to 409"):
        dc.decorate(_run(), _clip(first=400, frames=10))


def test_the_command_refuses_a_clip_with_no_timeline(tmp_path: Path) -> None:
    said: list[str] = []
    out = tmp_path / "loop.webp"
    code = dc.main([str(RECORDING), "--timeline", str(tmp_path / "none.json"), "--at", "100",
                    "--frames", "120", "--out", str(out)], said.append)
    assert code == EXIT_INVALID and not out.exists()
    assert said[0].startswith("INVALID: the timeline") and "decorated only from" in said[0]
    (tmp_path / "bytes.json").write_bytes(b"\xff\xfe")
    code = dc.main([str(RECORDING), "--timeline", str(tmp_path / "bytes.json"), "--at", "100",
                    "--frames", "120", "--out", str(out)], said.append)
    assert code == EXIT_INVALID and said[-1].startswith("INVALID: the timeline")


@needs_programs
def test_the_command_writes_the_decorated_loop_and_leaves_nothing_beside_it(
        tmp_path: Path) -> None:
    (tmp_path / "t.json").write_text(json.dumps(_run()))
    said: list[str] = []
    code = dc.main([str(RECORDING), "--timeline", str(tmp_path / "t.json"), "--at", "100",
                    "--frames", "120", "--out", str(tmp_path / "loop.webp"), "--place", "top",
                    "--without", "keys", "--sine"], said.append)
    assert code == EXIT_PASS, said
    assert sorted(p.name for p in tmp_path.iterdir()) == ["loop.webp", "t.json"]
    code = dc.main([str(RECORDING), "--timeline", str(tmp_path / "t.json"), "--at", "100",
                    "--frames", "120", "--out", str(tmp_path / "none" / "loop.webp")], said.append)
    assert code == EXIT_INVALID and said[-1].startswith("INVALID: the loop cannot be written")


def _band_changed(picture: motion.Picture, rows: range) -> bool:
    centre = picture.width // 2
    return any(_pixel(picture, centre, y) != _pixel(_clip().pictures[0], centre, y)
               for y in rows)


@pytest.mark.parametrize("place", ["top", "bottom"])
def test_the_caption_goes_to_the_band_asked_and_nowhere_else(place: placement.Band) -> None:
    drawn = dc.decorate(_run(), _clip(), dc.Style(place=place))[30]
    top, bottom = range(10, 60), range(SIZE[1] - 60, SIZE[1] - 10)
    assert _band_changed(drawn, top if place == "top" else bottom)
    assert not _band_changed(drawn, bottom if place == "top" else top)


def _busy_bottom_clip(frames: int) -> dc.Clip:
    """A clip whose bottom band is a checkerboard and whose top is flat: the picture `auto`'s
    sampler used to move the captions away from, over a clip long enough for it to do so."""
    width, height = SIZE
    band = height // 8
    rgb = bytearray(bytes([GREY >> 16, (GREY >> 8) & 0xFF, GREY & 0xFF]) * (width * height))
    for y in range(height - band, height):
        for x in range(width):
            at = (y * width + x) * 3
            rgb[at:at + 3] = b"\xff\xff\xff" if (x + y) % 2 else b"\x00\x00\x00"
    picture = motion.Picture(width, height, bytes(rgb), 17)
    return dc.Clip(list(range(100, 100 + frames)), [picture] * frames, BOX, RATE)


@pytest.mark.parametrize("place", ["top", "bottom"])
def test_a_style_with_a_place_never_samples_the_picture(place: placement.Band) -> None:
    """The band is the style's place at every second of the clip, whatever the picture holds: a
    bottom edge busy enough to have drawn `auto` away from it is never consulted."""
    clip = _busy_bottom_clip(145)
    drawn = dc.decorate(_run(), clip, dc.Style(layers=("calls",), place=place))
    plain = clip.pictures[0]
    top, bottom = range(10, 60), range(SIZE[1] - 60, SIZE[1] - 10)
    here, elsewhere = (top, bottom) if place == "top" else (bottom, top)

    def changed(picture: motion.Picture, rows: range) -> bool:
        return any(_pixel(picture, x, y) != _pixel(plain, x, y)
                   for x in range(16, SIZE[0] - 16, 8) for y in rows)

    for index in (5, 60, 140):
        assert changed(drawn[index], here), (place, index)
        assert not changed(drawn[index], elsewhere), (place, index)


def test_the_parser_refuses_the_place_it_no_longer_draws(tmp_path: Path) -> None:
    """The band never moves, so `auto` is not a choice: a caller asking for it is refused, not
    quietly handed the bottom edge."""
    (tmp_path / "t.json").write_text(json.dumps(_run()))
    said: list[str] = []
    with pytest.raises(SystemExit) as quit:
        dc.main([str(RECORDING), "--timeline", str(tmp_path / "t.json"), "--at", "100",
                 "--frames", "120", "--out", str(tmp_path / "loop.webp"), "--place", "auto"],
                said.append)
    assert quit.value.code == 2


def test_a_caption_wider_than_its_band_scrolls_a_whole_travel_inside_its_call() -> None:
    """A long caption is re-timed, never cut: one full travel inside the span of its own call,
    so it reads whole and ends the frame it began."""
    made = timeline.Builder("t")
    made.add("wide", "read_memory", {f"a{i}": "v" * 20 for i in range(12)}, "ok", (100, 130))
    run = timeline.loads(made.dumps())
    assert len(run["calls"][0]["caption"]["text"]) == ab.MAX_BYTES, "the fixture is not wide"
    drawn = dc.decorate(run, _clip(frames=61), dc.Style(layers=("calls",)))
    band = range(SIZE[1] - 21, SIZE[1] - 7)

    def caption_pixels(picture: motion.Picture) -> list[tuple[int, ...]]:
        return [_pixel(picture, x, y) for x in range(16, SIZE[0] - 16) for y in band]

    assert caption_pixels(drawn[15]) != caption_pixels(drawn[30]), "it moves, never cut"
    assert caption_pixels(drawn[30]) == caption_pixels(drawn[60]), "one travel inside its span"


def test_the_caption_is_the_timeline_s_own_text_and_tint() -> None:
    """A read tint is blue where a write tint is orange: the band takes the call's tint, read
    from the timeline and never worked out again."""
    run = _run()
    read = json.loads(json.dumps(run))
    for call in read["calls"]:
        call["caption"]["tint"] = "read"
    at = (SIZE[0] // 8, SIZE[1] - 20)
    written = _pixel(dc.decorate(run, _clip(), dc.Style(layers=("edge", "calls")))[5], *at)
    blue = _pixel(dc.decorate(read, _clip(), dc.Style(layers=("edge", "calls")))[5], *at)
    assert written[0] > written[2] and blue[2] > blue[0], (written, blue)


def test_a_record_step_is_the_camera_and_is_not_captioned() -> None:
    """A moment the demo records itself shows the machine, not the camera: `record` is not
    captioned, and any other step's caption is drawn as it was."""
    def drawn(tool: str, layers: tuple[ov.Layer, ...] = ("calls",)) -> list[bytes]:
        made = timeline.Builder("t")
        made.add("shoot", tool, {}, "ok", (100, 160))
        return [p.rgb for p in dc.decorate(timeline.loads(made.dumps()), _clip(),
                                           dc.Style(layers=layers))]

    assert drawn("record") == drawn("record", ())
    assert drawn("run_for") != drawn("run_for", ())


def test_a_server_with_no_pointer_layer_draws_no_pointer_from_the_same_timeline() -> None:
    """MAME's: `overlay` names the pointer lacking, so the style leaves it out."""
    style = dc.Style.of(ov.OVERLAY, lacking=("pointer",))
    assert "pointer" not in style.layers
    with_events = dc.decorate(_run(), _clip(), style)
    run = _run()
    for call in run["calls"]:
        call["events"] = [e for e in call["events"] if e["kind"] == "key"]
    assert [p.rgb for p in with_events] == [p.rgb for p in dc.decorate(run, _clip(), style)]


def test_the_edge_is_bright_while_a_call_runs_the_machine_and_dim_once_it_faded() -> None:
    made = timeline.Builder("t")
    made.add("go", "run_for", {}, "ok", (0, 30))
    made.add("look", "read_memory", {}, "ok", (30, 30), read_only=True)
    made.add("wait", "screen_wait", {}, "ok", (30, 300), read_only=True)
    drawn = dc.decorate(timeline.loads(made.dumps()), _clip(first=0, frames=300),
                        dc.Style(layers=("edge",)))
    running, faded = _pixel(drawn[10], 0, 120), _pixel(drawn[299], 0, 120)
    assert running[0] > faded[0] > GREY >> 16, (running, faded)


def test_calls_before_a_rewind_of_the_machine_are_not_this_clip_s() -> None:
    """A state load ends before it began; what came before it is another stretch of frames."""
    made = timeline.Builder("t")
    made.add("far", "run_to", {"ref": "far"}, "ok", (0, 500))
    made.add("load", "state_write", {"method": "load"}, "ok", (500, 100))
    made.add("near", "run_for", {}, "ok", (100, 160))
    calls = dc._span(timeline.loads(made.dumps())["calls"], (100, 159))
    assert [c["step"] for c in calls] == ["load", "near"]
    jumped = timeline.Builder("t")
    jumped.add("far", "run_to", {"ref": "far"}, "ok", (0, 500))
    jumped.add("near", "run_for", {}, "ok", (100, 160))
    calls = dc._span(timeline.loads(jumped.dumps())["calls"], (100, 159))
    assert [c["step"] for c in calls] == ["near"], "a call that began before the last ended"


def test_scry_core_and_its_demo_runner_import_without_the_decorate_extra() -> None:
    """Every module but the decorator, with Pillow and numpy made unimportable."""
    probe = (
        "import sys, pkgutil, importlib\n"
        "sys.modules['PIL'] = None\n"
        "sys.modules['numpy'] = None\n"
        "import scry_core\n"
        "names = [m.name for m in pkgutil.walk_packages(scry_core.__path__, 'scry_core.')\n"
        "         if m.name != 'scry_core.decorate']\n"
        "for name in names:\n"
        "    if name.endswith(('window_host', 'focus_listener')) and sys.platform != 'darwin':\n"
        "        continue\n"
        "    importlib.import_module(name)\n"
        "print(len(names))\n")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr
    assert int(done.stdout) > 50, "the walk imported almost nothing, so it proved nothing"
    blocked = subprocess.run([sys.executable, "-c", probe.split("import scry_core\n")[0]
                              + "import scry_core.decorate\n"], capture_output=True, text=True,
                             check=False)
    assert blocked.returncode != 0 and "halted" in blocked.stderr, "the block blocks nothing"


def test_the_record_layer_is_not_drawn_into_a_demo() -> None:
    """Live only: a clip carries no recording mark, whatever its style asks."""
    asked = dc.Style.of(ov.OVERLAY)
    assert "record" in asked.layers
    with_record = dc.decorate(_run(), _clip(), asked)
    without = dc.decorate(_run(), _clip(), dc.Style.of(ov.Overlay(record=False)))
    assert [p.rgb for p in with_record] == [p.rgb for p in without]
