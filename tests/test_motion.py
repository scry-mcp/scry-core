"""A demo's loop: which frames of a recording a cut keeps and for how long, a doubled capture
halved, the limits refused, and the two programs that make the file."""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from scry_core import motion, png
from scry_core.verdict import Invalid

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "demo" / "screen.avi"
needs_programs = pytest.mark.skipif(
    any(shutil.which(name) is None for name in motion.PROGRAMS),
    reason="a loop is made by ffmpeg and img2webp on PATH")


def _picture(width: int, height: int, colour: tuple[int, int, int] = (9, 8, 7),
             ms: int = 40) -> motion.Picture:
    return motion.Picture(width, height, bytes(colour) * (width * height), ms)


def _blocks(pixels: list[list[tuple[int, int, int]]]) -> motion.Picture:
    """A frame whose every pixel of `pixels` is a 2x2 block."""
    rows = []
    for row in pixels:
        line = b"".join(bytes(p) * 2 for p in row)
        rows += [line, line]
    return motion.Picture(len(pixels[0]) * 2, len(pixels) * 2, b"".join(rows), 40)


def test_the_fixture_recording_reads_as_the_frames_and_rate_it_holds() -> None:
    assert motion.facts(FIXTURE) == (72, Fraction(60))
    assert motion.rate(b"RIFF....AVI ") is None


@pytest.mark.parametrize(("per_second", "step"), [
    (Fraction(60), 2), (Fraction(30), 1), (Fraction(70086304, 1000000), 3), (Fraction(15), 1),
    (Fraction(1073741820, 18141941), 2), (Fraction(31), 2),
])
def test_frames_are_dropped_to_stay_within_thirty_a_second(per_second: Fraction,
                                                           step: int) -> None:
    assert motion.step_of(per_second) == step


def test_the_kept_frames_last_as_long_as_the_cut_to_the_millisecond() -> None:
    lasting = motion.durations(72, Fraction(60), 2)
    assert len(lasting) == 36 and sum(lasting) == 1200 and set(lasting) == {33, 34}, lasting
    odd = motion.durations(71, Fraction(70086304, 1000000), 3)
    assert len(odd) == 24 and sum(odd) == round(71000 / 70.086304), odd
    assert odd[-1] < odd[0], "the last kept frame stands for the two that are left"


def test_a_capture_the_emulator_doubled_is_told_and_halved_back() -> None:
    red, blue, grey = (200, 0, 0), (0, 0, 200), (9, 9, 9)
    doubled = _blocks([[red, blue, grey], [grey, red, blue]])
    assert motion.doubled(doubled)
    small = motion.halved(doubled)
    assert (small.width, small.height) == (3, 2) and small.ms == 40
    assert small.rgb == bytes(red + blue + grey + grey + red + blue)
    torn = motion.Picture(doubled.width, doubled.height,
                          doubled.rgb[:3] + b"\x01" + doubled.rgb[4:], 40)
    assert not motion.doubled(torn), "one pixel of a block differs"
    below = bytearray(doubled.rgb)
    below[doubled.width * 3] ^= 1
    assert not motion.doubled(motion.Picture(doubled.width, doubled.height, bytes(below), 40)), \
        "the second line of a row differs"
    assert not motion.doubled(_picture(3, 2)), "an odd width is nobody's double"


@pytest.mark.parametrize(("size", "times"), [
    ((320, 200), 3), ((256, 240), 2), ((256, 224), 2), ((320, 240), 2), ((640, 480), 1),
    ((800, 600), 1), ((1024, 768), 1), ((160, 100), 6), ((960, 600), 1), ((961, 100), 1),
])
def test_a_frame_is_scaled_up_by_the_most_whole_times_that_fit(size: tuple[int, int],
                                                               times: int) -> None:
    assert motion.factor(*size) == times
    assert size[0] * times <= max(size[0], motion.FIT[0])
    assert size[1] * times <= max(size[1], motion.FIT[1])


def test_a_frame_scaled_up_keeps_each_pixel_as_one_sharp_block() -> None:
    red, blue, grey = (200, 0, 0), (0, 0, 200), (9, 9, 9)
    small = motion.Picture(3, 2, bytes(red + blue + grey + grey + red + blue), 70)
    big = motion.scaled(small, 2)
    assert (big.width, big.height, big.ms) == (6, 4, 70)
    assert big.rgb == _blocks([[red, blue, grey], [grey, red, blue]]).rgb
    assert motion.halved(big).rgb == small.rgb, "scaled up and halved back is the same frame"
    assert motion.scaled(small, 1) is small
    three = motion.scaled(small, 3)
    row = bytes(red * 3 + blue * 3 + grey * 3)
    assert three.rgb[:len(row) * 3] == row * 3, "three lines of three pixels each"


def _rows(rows: list[list[tuple[int, int, int]]], ms: int = 40) -> motion.Picture:
    return motion.Picture(len(rows[0]), len(rows), b"".join(bytes(p) for row in rows
                                                             for p in row), ms)


BLACK, SKY, SEA, SUN = (0, 0, 0), (20, 20, 90), (10, 60, 200), (250, 240, 60)


def test_edges_of_one_colour_the_same_in_every_frame_are_cut_and_nothing_else() -> None:
    """A scene over a black band, as a cutscene leaves a game's verb area: the band goes, and so
    does a border column; an inner row of one colour stays, and so does an edge row whose colour
    changes from frame to frame."""
    first = _rows([[SKY, SKY, SUN, BLACK], [SEA, SEA, SEA, BLACK], [SEA, SUN, SEA, BLACK],
                   [BLACK, BLACK, BLACK, BLACK], [BLACK, BLACK, BLACK, BLACK]])
    second = _rows([[SKY, SUN, SKY, BLACK], [SEA, SEA, SEA, BLACK], [SUN, SEA, SEA, BLACK],
                    [BLACK, BLACK, BLACK, BLACK], [BLACK, BLACK, BLACK, BLACK]])
    assert motion.kept([first, second]) == motion.Box(0, 0, 3, 3, (4, 5))
    flashing = _rows([[SUN] * 4, [SEA, SUN, SKY, SEA], [SUN, SEA, SEA, SKY], [SUN] * 4])
    calm = _rows([[SKY] * 4, [SKY, SEA, SUN, SEA], [SEA, SKY, SEA, SUN], [SEA] * 4])
    assert motion.kept([flashing, calm]) == motion.Box(0, 0, 4, 4, (4, 4)), \
        "each edge row is one colour in each frame, and not the same one in both"
    assert motion.kept([_picture(3, 2)]) == motion.Box(0, 0, 3, 2, (3, 2)), \
        "a frame all of one colour has nothing to cut down to: it is kept whole"
    framed = [_rows([[SKY] * 5, [BLACK, SUN, SEA, SKY, SEA], [BLACK, SEA, SUN, SEA, SEA],
                     [BLACK, SKY, SEA, SUN, SEA], [BLACK] * 5]),
              _rows([[SKY] * 5, [BLACK, SEA, SKY, SUN, SEA], [BLACK, SUN, SEA, SEA, SEA],
                     [BLACK, SEA, SUN, SKY, SEA], [BLACK] * 5])]
    assert motion.kept(framed) == motion.Box(1, 1, 3, 3, (5, 5)), \
        "a band above, a column at the left, and one at the right that is one colour only in " \
        "the rows left once the bands are cut"
    stripes = _rows([[SKY, SEA], [SKY, SEA]])
    assert motion.kept([stripes, stripes]) == motion.Box(0, 0, 2, 2, (2, 2)), \
        "columns each of one colour leave nothing to cut down to: the frame is kept whole"
    cut = motion.cropped(first, motion.kept([first, second]))
    assert (cut.width, cut.height, cut.ms) == (3, 3, 40)
    assert cut.rgb == b"".join(bytes(p) for p in (SKY, SKY, SUN, SEA, SEA, SEA, SEA, SUN, SEA))


def _still(width: int, height: int, k: int) -> bytes:
    """A capture `k` times the size of `width` x `height` frames, each pixel its own colour."""
    small = png.Raster(width, height, bytes((n * 7) % 256 for n in range(width * height * 3)))
    return png.encode(png.enlarged(small, k))


def test_a_still_is_cut_as_its_loop_is_at_the_still_s_own_scale() -> None:
    data = _still(4, 5, 2)
    box = motion.Box(1, 0, 3, 3, (4, 5))
    cut = png.decode(motion.still(data, box))
    assert (cut.width, cut.height) == (6, 6)
    assert cut == png.cropped(png.decode(data), 2, 0, 6, 6)
    lower = png.decode(motion.still(data, motion.Box(1, 1, 2, 2, (4, 5))))
    assert lower == png.cropped(png.decode(data), 2, 2, 4, 4)
    assert motion.still(data, motion.Box(0, 0, 4, 5, (4, 5))) is data, \
        "a still whose loop cuts nothing is the capture, byte for byte"
    with pytest.raises(Invalid, match=r"the still is 8x10, not a whole number of times the "
                                      r"loop's 3x5 frames, so it cannot be cut as the loop is"):
        motion.still(data, motion.Box(0, 0, 3, 4, (3, 5)))


def test_equal_frames_in_a_row_become_one_that_lasts_as_long() -> None:
    a, b = _picture(2, 2, (1, 1, 1), 30), _picture(2, 2, (2, 2, 2), 40)
    merged = motion.merged([a, a, b, a, a, a])
    assert [(p.rgb[0], p.ms) for p in merged] == [(1, 60), (2, 40), (1, 90)]


def test_a_ppm_is_read_and_written_back() -> None:
    picture = _picture(4, 2, (10, 32, 255))
    assert motion.read_ppm(motion.ppm(picture)) == (4, 2, picture.rgb)
    with pytest.raises(Invalid, match="not an 8-bit binary PPM"):
        motion.read_ppm(b"P3\n1 1\n255\n0 0 0\n")
    with pytest.raises(Invalid, match="a 4x2 frame holds 3 bytes"):
        motion.read_ppm(b"P6\n4 2\n255\nabc")


@pytest.mark.parametrize(("cuts", "why"), [
    ([], "a loop shows 1 to 3 moments, and this one has 0"),
    ([(0, 36)] * 4, "and this one has 4"),
    ([(0, 30)], r"moment 1 lasts 0.50 s \(30 frames at 60.00 a second\), and a moment lasts 1 to"),
    ([(10, 72)], "moment 1 asks frames 10 to 81 of .*screen.avi, which holds 72"),
    ([(-1, 60)], "moment 1 asks frames -1 to"),
    ([(0, 72), (0, 0)], "moment 2 asks frames 0 to -1"),
])
def test_cuts_past_a_limit_of_the_loop_are_invalid(cuts: list[tuple[int, int]],
                                                   why: str) -> None:
    with pytest.raises(Invalid, match=why):
        motion.planned([motion.Cut(FIXTURE, first, frames) for first, frames in cuts])


def test_moments_that_last_more_than_the_loop_together_are_invalid(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "LOOP_SECONDS", 3.0)
    with pytest.raises(Invalid, match=r"the moments last 3.60 s together, and a loop lasts at "
                                      r"most 3 s: show less"):
        motion.planned([motion.Cut(FIXTURE, 0, 72)] * 3)
    assert motion.lasting([motion.Cut(FIXTURE, 0, 72), motion.Cut(FIXTURE, 12, 60)]) == (1200,
                                                                                         1000)


def test_a_recording_that_is_no_avi_is_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "no.avi"
    with pytest.raises(Invalid, match="cannot be read"):
        motion.facts(bad)
    bad.write_bytes(b"not an AVI at all")
    with pytest.raises(Invalid, match="does not read as an AVI with a video stream"):
        motion.facts(bad)


@needs_programs
def test_a_loop_is_built_from_cuts_of_a_real_recording(tmp_path: Path) -> None:
    cuts = [motion.Cut(FIXTURE, 0, 72), motion.Cut(FIXTURE, 6, 60)]
    assert motion.build(cuts[:1], tmp_path).cut_ms == (1200,)
    built = motion.build(cuts, tmp_path)  # in the folder an earlier build left its frames in
    assert built.cut_ms == (1200, 1000) and built.lossless
    assert built.data[:4] == b"RIFF" and built.data[8:12] == b"WEBP"
    out = tmp_path / "loop.webp"
    out.write_bytes(built.data)
    webpmux = shutil.which("webpmux")
    if webpmux is not None:
        info = subprocess.run([webpmux, "-info", str(out)], capture_output=True, text=True,
                              check=True).stdout
        assert "Canvas size: 600 x 600" in info and "Loop Count : 0" in info, \
            f"the fixture's 8 x 8 frames are not scaled up 75 times: {info}"
        lasting = [int(line.split()[6]) for line in info.splitlines() if line.strip()[:1].isdigit()
                   and ":" in line.split()[0]]
        assert sum(lasting) == 2200, info


@needs_programs
def test_a_loop_past_the_budget_lossless_and_lossy_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "BUDGET_BYTES", 10)
    with pytest.raises(Invalid, match=r"the loop is \d+ bytes lossless and \d+ bytes lossy, past "
                                      r"the 10-byte budget: show less"):
        motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)


@needs_programs
def test_a_recording_ffmpeg_cannot_decode_is_invalid_with_its_own_words(
        tmp_path: Path) -> None:
    broken = tmp_path / "broken.avi"
    data = FIXTURE.read_bytes()
    at = data.index(b"movi")
    broken.write_bytes(data[:at + 4] + b"idx1")  # the header's 72 frames, and none to decode
    with pytest.raises(Invalid, match="ffmpeg (refused to decode|decoded 0 frames)"):
        motion.build([motion.Cut(broken, 0, 72)], tmp_path / "work")


def test_a_frame_doubled_down_and_not_across_is_not_a_double() -> None:
    line = bytes((1, 1, 1, 2, 2, 2, 3, 3, 3, 3, 3, 3))
    assert not motion.doubled(motion.Picture(4, 2, line * 2, 40))


def _faked(monkeypatch: pytest.MonkeyPatch, frames: dict[int, list[motion.Picture]],
           sizes: list[int]) -> list[list[motion.Picture]]:
    """`build` with the two programs replaced: each cut's frames given, each file's size too.
    What it answers is the frames each assembly wrote, at the size it wrote them."""
    assembled: list[list[motion.Picture]] = []

    def given(ffmpeg: str, cut: motion.Cut, *_: object) -> list[motion.Picture]:
        return frames[cut.first]

    def weigh(img2webp: str, pictures: list[motion.Picture], work: Path,
              lossless: bool, times: int) -> bytes:
        assembled.append([motion.scaled(picture, times) for picture in pictures])
        return b"w" * sizes[len(assembled) - 1]

    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "f", "img2webp": "i"})
    monkeypatch.setattr(motion, "_frames", given)
    monkeypatch.setattr(motion, "_assembled", weigh)
    return assembled


def test_a_capture_nearly_all_doubled_is_halved_torn_frames_included(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whole = _blocks([[(1, 2, 3), (4, 5, 6)], [(4, 5, 6), (1, 2, 3)]])
    torn = motion.Picture(whole.width, whole.height, b"\x09" + whole.rgb[1:], 40)
    assembled = _faked(monkeypatch, {0: [whole] * 9 + [torn]}, [1])
    built = motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    assert built.lossless and built.cut_ms == (400,)
    times = motion.factor(2, 2)
    assert {(p.width, p.height) for p in assembled[0]} == {(2 * times, 2 * times)}, \
        "the capture was not halved, then scaled up to fit"
    assert [p.ms for p in assembled[0]] == [360, 40], "equal frames were not merged"
    assembled = _faked(monkeypatch, {0: [whole] * 8 + [torn] * 2}, [1])
    motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    times = motion.factor(4, 4)
    assert {(p.width, p.height) for p in assembled[0]} == {(4 * times, 4 * times)}, \
        "a capture a fifth of whose frames are not doubled is the machine's own size, scaled"


def test_moments_of_two_sizes_are_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _faked(monkeypatch, {0: [_picture(3, 3)], 6: [_picture(5, 3)]}, [1])
    with pytest.raises(Invalid, match=r"the moments are not one size: 3x3 and \[\(5, 3\)\]"):
        motion.build([motion.Cut(FIXTURE, 0, 72), motion.Cut(FIXTURE, 6, 60)], tmp_path)


def test_a_loop_too_heavy_lossless_is_made_lossy(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _faked(monkeypatch, {0: [_picture(3, 3)]}, [motion.BUDGET_BYTES + 1, motion.BUDGET_BYTES])
    built = motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    assert not built.lossless and len(built.data) == motion.BUDGET_BYTES


@pytest.mark.parametrize(("code", "stderr", "why"), [
    (1, "first\nInvalid data found", r"ffmpeg refused to decode .* \(exit 1\): Invalid data found"),
    (1, "", r"ffmpeg refused to decode .* \(exit 1\): no words"),
    (0, "", "ffmpeg decoded 0 frames of .* where frames 0 to 71, one in 2, are 36"),
])
def test_a_decode_that_fails_or_comes_short_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, stderr: str, why: str) -> None:
    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "f", "img2webp": "i"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, code, "", stderr))
    with pytest.raises(Invalid, match=why):
        motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)


def test_an_assembly_that_fails_is_invalid_with_its_own_words(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 2, "", "Error! Frame dimensions mismatched"))
    with pytest.raises(Invalid, match=r"img2webp refused to assemble the loop \(exit 2\): Error! "
                                      "Frame dimensions mismatched"):
        motion._assembled("img2webp", [_picture(2, 2)], tmp_path, True, 1)


def test_a_cut_longer_than_a_moment_is_invalid_with_half_a_frame_of_slack(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's 72 frames last 1.2 s: over a 1 s ceiling, inside a 1.19 s one by the slack."""
    monkeypatch.setattr(motion, "CUT_SECONDS", (0.5, 1.0))
    with pytest.raises(Invalid, match=r"moment 1 lasts 1.20 s .*, and a moment lasts 0.5 to 1 s"):
        motion.planned([motion.Cut(FIXTURE, 0, 72)])
    monkeypatch.setattr(motion, "CUT_SECONDS", (0.5, 1.19))
    assert len(motion.planned([motion.Cut(FIXTURE, 0, 72)])) == 1
    monkeypatch.setattr(motion, "SLACK_SECONDS", 0.0)
    with pytest.raises(Invalid, match="moment 1 lasts 1.20 s"):
        motion.planned([motion.Cut(FIXTURE, 0, 72)])
    monkeypatch.setattr(motion, "CUT_SECONDS", (0.5, 3.0))
    monkeypatch.setattr(motion, "LOOP_SECONDS", 2.39)
    with pytest.raises(Invalid, match="the moments last 2.40 s together"):
        motion.planned([motion.Cut(FIXTURE, 0, 72)] * 2)
    monkeypatch.setattr(motion, "SLACK_SECONDS", 0.02)
    assert len(motion.planned([motion.Cut(FIXTURE, 0, 72)] * 2)) == 2


@needs_programs
def test_a_cut_decodes_the_frames_it_names_and_no_others(tmp_path: Path) -> None:
    ffmpeg = motion.programs()["ffmpeg"]
    every = motion._frames(ffmpeg, motion.Cut(FIXTURE, 0, 72), Fraction(60), 1, tmp_path / "all")
    assert len({picture.rgb for picture in every}) > 60, "the fixture's frames do not differ"
    kept = motion._frames(ffmpeg, motion.Cut(FIXTURE, 7, 20), Fraction(60), 2, tmp_path / "cut")
    assert [picture.rgb for picture in kept] == [every[n].rgb for n in range(7, 27, 2)]


def test_a_loop_shows_only_what_moves_its_band_cut_before_it_is_scaled_up(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 160 x 200 scene whose last 100 rows are black in every frame: whole it scales 3 times;
    cut to 160 x 100 it scales 6 times and fills the width, and the loop says what it kept."""
    def scene(seed: int) -> motion.Picture:
        moving = bytes((n * 7 + seed) % 256 for n in range(3 * 160 * 100))
        return motion.Picture(160, 200, moving + bytes(3 * 160 * 100), 40)

    assembled = _faked(monkeypatch, {0: [scene(0), scene(1)]}, [1])
    built = motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    assert built.kept == motion.Box(0, 0, 160, 100, (160, 200))
    assert (motion.factor(160, 200), motion.factor(160, 100)) == (3, 6), "the case needs both"
    assert {(p.width, p.height) for p in assembled[0]} == {(960, 600)}, \
        "the band was scaled up with the scene"
