"""A demo's loop: which frames of a recording a cut keeps and for how long, a doubled capture
halved, the limits refused, and the two programs that make the file."""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from scry_core import motion
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
        assert "Canvas size: 8 x 8" in info and "Loop Count : 0" in info, info
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
    """`build` with the two programs replaced: each cut's frames given, each file's size too."""
    assembled: list[list[motion.Picture]] = []

    def given(ffmpeg: str, cut: motion.Cut, *_: object) -> list[motion.Picture]:
        return frames[cut.first]

    def weigh(img2webp: str, pictures: list[motion.Picture], work: Path,
              lossless: bool) -> bytes:
        assembled.append(list(pictures))
        return b"w" * sizes[len(assembled) - 1]

    monkeypatch.setattr(motion, "programs", lambda: {"ffmpeg": "f", "img2webp": "i"})
    monkeypatch.setattr(motion, "_frames", given)
    monkeypatch.setattr(motion, "_assembled", weigh)
    return assembled


def test_a_capture_nearly_all_doubled_is_halved_torn_frames_included(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whole = _blocks([[(1, 2, 3), (4, 5, 6)]])
    torn = motion.Picture(whole.width, whole.height, b"\x09" + whole.rgb[1:], 40)
    assembled = _faked(monkeypatch, {0: [whole] * 9 + [torn]}, [1])
    built = motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    assert built.lossless and built.cut_ms == (400,)
    assert {(p.width, p.height) for p in assembled[0]} == {(2, 1)}, "the capture was not halved"
    assert [p.ms for p in assembled[0]] == [360, 40], "equal frames were not merged"
    assembled = _faked(monkeypatch, {0: [whole] * 8 + [torn] * 2}, [1])
    motion.build([motion.Cut(FIXTURE, 0, 72)], tmp_path)
    assert {(p.width, p.height) for p in assembled[0]} == {(4, 2)}, \
        "a capture a fifth of whose frames are not doubled is the machine's own size"


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
        motion._assembled("img2webp", [_picture(2, 2)], tmp_path, True)


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
