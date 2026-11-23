"""A demo's loop: which frames of a recording a cut keeps and for how long, a doubled capture
halved, the limits refused, and the two programs that make the file."""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from scry_core import aspect, motion, png
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
    assert motion.facts(FIXTURE) == (120, Fraction(60))
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
    ((320, 200), 3), ((256, 240), 3), ((256, 224), 3), ((320, 240), 3), ((640, 480), 1),
    ((800, 600), 1), ((1024, 768), 1), ((160, 100), 6), ((960, 600), 1), ((961, 100), 1),
])
def test_a_frame_is_scaled_up_by_the_most_whole_times_that_fit_shown_at_4_to_3(
        size: tuple[int, int], times: int) -> None:
    box = motion.Box(0, 0, *size, size)
    assert motion.factor(box) == times
    wide, high = aspect.shown(size[0] * times, size[1] * times)
    assert times == 1 or (wide <= motion.FIT[0] and high <= motion.FIT[1])


def test_a_cut_frame_is_scaled_by_its_own_size_and_the_whole_frame_s_shape() -> None:
    cutscene = motion.Box(0, 28, 320, 144, (320, 200))
    assert motion.factor(cutscene) == 3, "320 wide shown at 3x is 960; 144 rows stretched, 518"
    narrow = motion.Box(100, 0, 40, 200, (320, 200))
    assert motion.factor(narrow) == 3, "the band is 200 rows of a 200-row frame, shown 240 tall"
    corner = motion.Box(0, 0, 30, 100, (320, 200))
    assert motion.factor(corner) == 6, "100 rows are shown 120 tall, and 720 holds 6 of those"


def test_a_frame_shown_keeps_each_pixel_as_one_sharp_block() -> None:
    red, blue, grey = (200, 0, 0), (0, 0, 200), (9, 9, 9)
    small = motion.Picture(3, 2, bytes(red + blue + grey + grey + red + blue), 70)
    big = motion.displayed(small, 2, range(6), range(4))
    assert (big.width, big.height, big.ms) == (6, 4, 70)
    assert big.rgb == _blocks([[red, blue, grey], [grey, red, blue]]).rgb
    assert motion.halved(big).rgb == small.rgb, "scaled up and halved back is the same frame"
    three = motion.displayed(small, 3, range(9), range(6))
    row = bytes(red * 3 + blue * 3 + grey * 3)
    assert three.rgb[:len(row) * 3] == row * 3, "three lines of three pixels each"


def test_a_frame_shown_repeats_the_rows_and_columns_its_shape_asks_for() -> None:
    red, blue = (200, 0, 0), (0, 0, 200)
    small = motion.Picture(2, 2, bytes(red + blue + blue + red), 70)
    stretched = motion.displayed(small, 1, [0, 1], [0, 0, 1, 1, 1])
    assert (stretched.width, stretched.height) == (2, 5)
    assert stretched.rgb == bytes(red + blue) * 2 + bytes(blue + red) * 3


def test_a_320_by_200_frame_is_shown_at_4_to_3_with_no_row_dropped() -> None:
    whole = motion.Box(0, 0, 320, 200, (320, 200))
    columns, rows = whole.display(4)
    assert (len(columns), len(rows)) == (1280, 960), "the card's 1280 x 800 shown at 1280 x 960"
    assert columns == list(range(1280)) and set(r // 4 for r in rows) == set(range(200)), \
        "every pixel row of the game is shown, each one 4.8 pixels tall"
    cutscene = motion.Box(0, 28, 320, 144, (320, 200))
    columns, rows = cutscene.display(2)
    assert (len(columns), len(rows)) == (640, 345), "the card's 640 x 288 is 640 x 345.6"
    assert min(rows) == 0 and max(rows) // 2 == 143, "the rows are the cutscene's, no more"
    shown_whole = whole.display(2)[1]
    assert rows == [r - 56 for r in shown_whole if 56 <= r < 56 + 288], \
        "the cut's rows are those of the stretched whole frame that fall within the cut"


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
    data = _still(4, 3, 2)
    box = motion.Box(1, 0, 3, 2, (4, 3))
    cut = png.decode(motion.still(data, box))
    assert (cut.width, cut.height) == (6, 4)
    assert cut == png.cropped(png.decode(data), 2, 0, 6, 4)
    lower = png.decode(motion.still(data, motion.Box(1, 1, 2, 2, (4, 3))))
    assert lower == png.cropped(png.decode(data), 2, 2, 4, 4)
    assert motion.still(data, motion.Box(0, 0, 4, 3, (4, 3))) is data, \
        "a still already at 4:3 whose loop cuts nothing is the capture, byte for byte"
    with pytest.raises(Invalid, match=r"the still is 8x6, not a whole number of times the "
                                      r"loop's 3x5 frames, so it cannot be cut as the loop is"):
        motion.still(data, motion.Box(0, 0, 3, 4, (3, 5)))


def _nearest(raster: png.Raster, rows: list[int]) -> png.Raster:
    stride = raster.width * 3
    return png.Raster(raster.width, len(rows),
                      b"".join(raster.pixels[y * stride:(y + 1) * stride] for y in rows))


def test_a_still_is_shown_at_4_to_3_as_the_loop_beside_it_is() -> None:
    """An 8 x 5 game at 2x: 16 x 10 shown 16 x 12, each of its 10 rows 1.2 shown rows tall."""
    data = _still(8, 5, 2)
    raster = png.decode(data)
    whole = png.decode(motion.still(data, motion.Box(0, 0, 8, 5, (8, 5))))
    assert whole == _nearest(raster, [y * 10 // 12 for y in range(12)])
    cut = png.decode(motion.still(data, motion.Box(0, 1, 8, 3, (8, 5))))
    assert (cut.width, cut.height) == (16, 7)
    assert cut == _nearest(png.cropped(raster, 0, 2, 16, 6),
                           [y * 10 // 12 - 2 for y in range(3, 10)]), \
        "the cut is the rows of the stretched whole frame that fall within it"
    assert png.decode(motion.still(data, motion.whole(data))) == whole


def test_a_capture_with_no_loop_is_shown_whole_and_a_wider_one_is_widened() -> None:
    wide = png.encode(png.Raster(4, 5, bytes(range(60))))
    shown = png.decode(motion.still(wide, motion.whole(wide)))
    assert (shown.width, shown.height) == (7, 5), "a portrait frame grows wider, never shorter"
    assert motion.shows_capture(wide, png.encode(shown))
    assert not motion.shows_capture(wide, wide), "the capture as it was is not what is shown"
    assert not motion.shows_capture(wide, b"not a picture")
    assert not motion.shows_capture(b"not a picture", wide)


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
    ([], "a loop shows 1 to 5 moments, and this one has 0"),
    ([(0, 36)] * 6, "and this one has 6"),
    ([(0, 30)], r"moment 1 lasts 0.50 s \(30 frames at 60.00 a second\), and a moment "
     r"lasts 1.5 to"),
    ([(10, 120)], "moment 1 asks frames 10 to 129 of .*screen.avi, which holds 120"),
    ([(-1, 60)], "moment 1 asks frames -1 to"),
    ([(0, 120), (0, 0)], "moment 2 asks frames 0 to -1"),
])
def test_cuts_past_a_limit_of_the_loop_are_invalid(cuts: list[tuple[int, int]],
                                                   why: str) -> None:
    with pytest.raises(Invalid, match=why):
        motion.planned([motion.Cut(FIXTURE, first, frames) for first, frames in cuts])


def test_the_loop_s_budget_is_five_moments_of_one_and_a_half_to_four_seconds(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A lead clip is not rushed: a moment lasts 1.5 to 4 s, five of them, 16 s in all."""
    monkeypatch.setattr(motion, "facts", lambda source: (100_000, Fraction(60)))

    def moments(*frames: int) -> list[motion.Cut]:
        return [motion.Cut(FIXTURE, 0, n) for n in frames]

    assert len(motion.planned(moments(90))) == 1, "1.5 s is a moment"
    assert len(motion.planned(moments(240))) == 1, "4 s is a moment"
    assert len(motion.planned(moments(240, 240, 240, 240))) == 4, "16 s is a loop"
    for frames in (84, 246):
        with pytest.raises(Invalid, match=rf"moment 1 lasts {frames / 60:.2f} s"):
            motion.planned(moments(frames))
    with pytest.raises(Invalid, match=r"the moments last 20.00 s together, and a loop lasts at "
                                      r"most 16 s: show less"):
        motion.planned(moments(*[240] * 5))


def test_moments_that_last_more_than_the_loop_together_are_invalid(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "LOOP_SECONDS", 3.0)
    with pytest.raises(Invalid, match=r"the moments last 4.50 s together, and a loop lasts at "
                                      r"most 3 s: show less"):
        motion.planned([motion.Cut(FIXTURE, 0, 90)] * 3)
    assert motion.lasting([motion.Cut(FIXTURE, 0, 90), motion.Cut(FIXTURE, 12, 90)]) == (1500,
                                                                                        1500)


def test_a_recording_that_is_no_avi_is_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "no.avi"
    with pytest.raises(Invalid, match="cannot be read"):
        motion.facts(bad)
    bad.write_bytes(b"not an AVI at all")
    with pytest.raises(Invalid, match="does not read as an AVI with a video stream"):
        motion.facts(bad)


@needs_programs
def test_a_loop_is_built_from_cuts_of_a_real_recording(tmp_path: Path) -> None:
    cuts = [motion.Cut(FIXTURE, 0, 120), motion.Cut(FIXTURE, 6, 114)]
    assert motion.build(cuts[:1], tmp_path).cut_ms == (2000,)
    built = motion.build(cuts, tmp_path)  # in the folder an earlier build left its frames in
    assert built.cut_ms == (2000, 1900) and built.lossless
    assert built.data[:4] == b"RIFF" and built.data[8:12] == b"WEBP"
    out = tmp_path / "loop.webp"
    out.write_bytes(built.data)
    webpmux = shutil.which("webpmux")
    if webpmux is not None:
        info = subprocess.run([webpmux, "-info", str(out)], capture_output=True, text=True,
                              check=True).stdout
        assert "Canvas size: 960 x 720" in info and "Loop Count : 0" in info, \
            f"the fixture's 8 x 8 frames are not scaled up 90 times, shown at 4:3: {info}"
        lasting = [int(line.split()[6]) for line in info.splitlines() if line.strip()[:1].isdigit()
                   and ":" in line.split()[0]]
        assert sum(lasting) == 3900, info


@needs_programs
def test_a_loop_past_the_budget_lossless_and_lossy_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(motion, "BUDGET_BYTES", 10)
    with pytest.raises(Invalid, match=r"the loop is \d+ bytes lossless and \d+ bytes lossy, past "
                                      r"the 10-byte budget: show less"):
        motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)


@needs_programs
def test_a_recording_ffmpeg_cannot_decode_is_invalid_with_its_own_words(
        tmp_path: Path) -> None:
    broken = tmp_path / "broken.avi"
    data = FIXTURE.read_bytes()
    at = data.index(b"movi")
    broken.write_bytes(data[:at + 4] + b"idx1")  # the header's 120 frames, and none to decode
    with pytest.raises(Invalid, match="ffmpeg (refused to decode|decoded 0 frames)"):
        motion.build([motion.Cut(broken, 0, 120)], tmp_path / "work")


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
              lossless: bool, times: int, shape: tuple[list[int], list[int]]) -> bytes:
        assembled.append([motion.displayed(picture, times, *shape) for picture in pictures])
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
    built = motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)
    assert built.lossless and built.cut_ms == (400,)
    assert built.kept.whole == (2, 2), "the capture was not halved"
    times = motion.factor(built.kept)
    assert {(p.width, p.height) for p in assembled[0]} == {aspect.shown(2 * times, 2 * times)}, \
        "the halved capture was not scaled up to fit and shown at 4:3"
    assert [p.ms for p in assembled[0]] == [360, 40], "equal frames were not merged"
    assembled = _faked(monkeypatch, {0: [whole] * 8 + [torn] * 2}, [1])
    built = motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)
    assert built.kept.whole == (4, 4), "the capture was halved"
    times = motion.factor(motion.Box(0, 0, 4, 4, (4, 4)))
    assert {(p.width, p.height) for p in assembled[0]} == {aspect.shown(4 * times, 4 * times)}, \
        "a capture a fifth of whose frames are not doubled is the machine's own size, scaled"


def test_moments_of_two_sizes_are_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _faked(monkeypatch, {0: [_picture(3, 3)], 6: [_picture(5, 3)]}, [1])
    with pytest.raises(Invalid, match=r"the moments are not one size: 3x3 and \[\(5, 3\)\]"):
        motion.build([motion.Cut(FIXTURE, 0, 120), motion.Cut(FIXTURE, 6, 114)], tmp_path)


def test_a_loop_too_heavy_lossless_is_made_lossy(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _faked(monkeypatch, {0: [_picture(3, 3)]}, [motion.BUDGET_BYTES + 1, motion.BUDGET_BYTES])
    built = motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)
    assert not built.lossless and len(built.data) == motion.BUDGET_BYTES


@pytest.mark.parametrize(("code", "stderr", "why"), [
    (1, "first\nInvalid data found", r"ffmpeg refused to decode .* \(exit 1\): Invalid data found"),
    (1, "", r"ffmpeg refused to decode .* \(exit 1\): no words"),
    (0, "", "ffmpeg decoded 0 frames of .* where frames 0 to 119, one in 2, are 60"),
])
def test_a_decode_that_fails_or_comes_short_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, stderr: str, why: str) -> None:
    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "f", "img2webp": "i"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, code, "", stderr))
    with pytest.raises(Invalid, match=why):
        motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)


def test_an_assembly_that_fails_is_invalid_with_its_own_words(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 2, "", "Error! Frame dimensions mismatched"))
    with pytest.raises(Invalid, match=r"img2webp refused to assemble the loop \(exit 2\): Error! "
                                      "Frame dimensions mismatched"):
        motion._assembled("img2webp", [_picture(2, 2)], tmp_path, True, 1,
                          ([0, 1], [0, 1]))


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
    """A 320 x 200 scene that moves only in its top left 160 x 100, black elsewhere in every
    frame: whole it scales 3 times; cut to the quarter it scales 6 times, shown at 960 x 720,
    and the loop says what it kept."""
    def scene(seed: int) -> motion.Picture:
        row = bytes((n * 7 + seed) % 256 for n in range(3 * 160)) + bytes(3 * 160)
        return motion.Picture(320, 200, row * 100 + bytes(3 * 320 * 100), 40)

    assembled = _faked(monkeypatch, {0: [scene(0), scene(1)]}, [1])
    built = motion.build([motion.Cut(FIXTURE, 0, 120)], tmp_path)
    kept = motion.Box(0, 0, 160, 100, (320, 200))
    assert built.kept == kept
    assert (motion.factor(motion.Box(0, 0, 320, 200, (320, 200))), motion.factor(kept)) == (3, 6), \
        "the case needs both"
    assert {(p.width, p.height) for p in assembled[0]} == {(960, 720)}, \
        "the quarter was scaled up with the scene"
