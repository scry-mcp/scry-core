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

from scry_core import decorate as dc
from scry_core import motion, timeline
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


def _button(name: str, down: bool, frame: int | None = None) -> timeline.Event:
    return timeline.Event("button", frame, name=name, down=down)


def _run() -> dict[str, Any]:
    made = timeline.Builder("t")
    made.add("boot", "start", {}, "ok", (None, 100))
    made.add("aim", "send_mouse", {"x": 2}, "ok", (100, 130),
             [timeline.pointer(3, 4, 100), timeline.pointer(20, 15, 112),
              timeline.pointer(9, 9, 113), timeline.pointer(30, 2, 130)])
    made.add("click", "send_mouse", {"button": "left"}, "ok", (130, 140),
             [_button("left", True, 131), _button("left", False, 135)])
    made.add("more", "send_mouse", {}, "ok", (140, 160),
             [timeline.pointer(2, 2, 141), timeline.pointer(4, 4, 150)])
    return timeline.loads(made.dumps())


def _clip(first: int = 100, frames: int = 60, size: tuple[int, int] = SIZE) -> dc.Clip:
    rgb = bytes([GREY >> 16, (GREY >> 8) & 0xFF, GREY & 0xFF]) * (size[0] * size[1])
    return dc.Clip(list(range(first, first + frames)),
                   [motion.Picture(*size, rgb, 17) for _ in range(frames)], BOX, RATE)


def _pixel(picture: motion.Picture, x: int, y: int) -> tuple[int, ...]:
    at = (y * picture.width + x) * 3
    return tuple(picture.rgb[at:at + 3])


def test_a_clip_decorated_twice_is_the_same_pixels() -> None:
    style = dc.Style(zooms=(dc.Zoom(105, 150, (4, 4, 8, 6)),))
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
    made.add("early", "send_mouse", {}, "ok", (100, 102), [_button("left", True, 101)])
    made.add("aim", "send_mouse", {}, "ok", (102, 110), [timeline.pointer(1, 1, 110)])
    made.add("click", "send_mouse", {}, "ok", (110, 120), [_button("left", True, 111)])
    made.add("away", "send_mouse", {}, "ok", (120, 130), [timeline.pointer(30, 1, 120)])
    plan = dc._plan(timeline.loads(made.dumps()), _clip())
    assert [p[0] for p in plan.presses] == [11 / 60]
    assert plan.presses[0][1:] == dc.pointer_at(plan.points, 11 / 60)


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


def test_the_edge_is_drawn_at_the_look_s_held_alpha_on_every_frame() -> None:
    drawn = dc.decorate(_run(), _clip(), dc.Style(layers=("edge",)))
    border = [_pixel(picture, 0, 120) for picture in drawn]
    assert len(set(border)) == 1 and border[0] != _pixel(_clip().pictures[0], 0, 120)


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
                    "--frames", "120", "--out", str(tmp_path / "loop.webp")], said.append)
    assert code == EXIT_PASS, said
    assert sorted(p.name for p in tmp_path.iterdir()) == ["loop.webp", "t.json"]
    code = dc.main([str(RECORDING), "--timeline", str(tmp_path / "t.json"), "--at", "100",
                    "--frames", "120", "--out", str(tmp_path / "none" / "loop.webp")], said.append)
    assert code == EXIT_INVALID and said[-1].startswith("INVALID: the loop cannot be written")


def test_a_call_that_counted_only_one_of_its_frames_is_still_the_clip_s() -> None:
    """A first call whose reply named only its end frame ran somewhere in the clip: it is placed
    at that frame with the events it fired, never dropped for the frame it could not name."""
    made = timeline.Builder("t")
    made.add("boot", "start", {}, "ok", (None, None))
    made.add("aim", "send_mouse", {}, "ok", (None, 3), [timeline.pointer(1, 2, 3)])
    calls = dc._span(timeline.loads(made.dumps())["calls"], (0, 10))
    assert [c["step"] for c in calls] == ["aim"]
    assert dc._ran(calls[0]) == (3, 3)


def test_a_later_call_that_counted_one_frame_walks_back_over_an_earlier_one() -> None:
    """A call that named only its end frame after a counted one: the walk back to the stretch
    the clip shows must not compare a frame against a missing one."""
    made = timeline.Builder("t")
    made.add("a", "run_for", {}, "ok", (0, 1))
    made.add("b", "send_mouse", {}, "ok", (5, 5), [timeline.pointer(1, 2, 5)])
    document = timeline.loads(made.dumps())
    document["calls"][1]["before"] = None      # a timeline a writer did not make
    calls = dc._span(document["calls"], (0, 10))
    assert [c["step"] for c in calls] == ["a", "b"]


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


def test_a_style_that_leaves_the_pointer_out_draws_no_pointer_from_the_same_timeline() -> None:
    """A server whose overlay names the pointer lacking: the style leaves it out."""
    style = dc.Style(layers=("edge",))
    with_events = dc.decorate(_run(), _clip(), style)
    run = _run()
    for call in run["calls"]:
        call["events"] = [e for e in call["events"] if e["kind"] != "pointer"]
    assert [p.rgb for p in with_events] == [p.rgb for p in dc.decorate(run, _clip(), style)]
