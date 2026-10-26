"""The sound measures, held on recordings made here whose answers are known by construction: a
sine at a known level and onset, silence, a hard-clipped sine, the same sine a fraction of a dB
down for each SNR band, an 8-bit file, and two silences, which compare nothing."""

from __future__ import annotations

import math
import struct
import sys
import wave
from array import array
from pathlib import Path
from typing import Any

import pytest
from test_media_tools import judged_by_its_model  # noqa: F401  (every reply held to its model)

from scry_core import media_tools, wav
from scry_core.host_program import absolute as _abs
from scry_core.reply_contract import Invalid

RATE = 8000
AMP = 16000                       # a sine of this amplitude peaks at 20*log10(16000/32768)


def _write(path: Path, channels: list[list[int]], width: int = 2, rate: int = RATE) -> str:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(width)
        w.setframerate(rate)
        frames = list(zip(*channels, strict=True))
        if width == 2:
            w.writeframes(b"".join(struct.pack(f"<{len(f)}h", *f) for f in frames))
        else:
            w.writeframes(bytes(v + 128 for f in frames for v in f))
    return str(path)


def _sine(n: int, amp: float = AMP, freq: float = 400.0, start: int = 0,
          clip: float | None = None) -> list[int]:
    out = []
    for i in range(n):
        v = amp * math.sin(2 * math.pi * freq * (i - start) / RATE) if i >= start else 0.0
        if clip is not None:
            v = max(-clip, min(clip, v))
        out.append(round(v))
    return out


def test_a_sine_measures_at_its_level_and_its_onset(tmp_path: Path) -> None:
    """A 400 Hz sine of amplitude 16000 starting at sample 800 (0.1 s), in one second: its peak
    is 20 log10(16000/32768) = -6.23 dBFS, its RMS over the sounding 0.9 s that over sqrt 2,
    and its onset the first sample over 2% of the peak, a hair after 0.1 s."""
    path = _write(tmp_path / "s.wav", [_sine(RATE, start=800)])
    got = wav.measure(wav.read("path", path), None, None)
    m = got["measures"][0]
    assert m["peak_dbfs"] == pytest.approx(20 * math.log10(AMP / 32768), abs=0.01)
    want_rms = AMP / math.sqrt(2) * math.sqrt(0.9)
    assert m["rms_dbfs"] == pytest.approx(20 * math.log10(want_rms / 32768), abs=0.05)
    assert 0.1 <= m["onset_s"] <= 0.1 + 1 / RATE
    assert m["silent"] is False and m["clipped"] is False and m["clipping_run"] <= 2
    # The first 0.1 s is silence long enough to count (50 ms or more), from the start.
    assert m["silence_spans"]["count"] == 1 and m["silence_spans"]["first"][0] == 0.0
    assert m["silence_spans"]["first"][1] == pytest.approx(0.1, abs=1 / RATE)
    assert (got["sample_rate_hz"], got["channels"], got["bits"], got["window"]) == (
        RATE, 1, 16, [0.0, 1.0])


def test_silence_is_silent_with_no_onset_and_no_level(tmp_path: Path) -> None:
    m = wav.measure(wav.read("p", _write(tmp_path / "q.wav", [[0] * 4000])), None, None)[
        "measures"][0]
    assert m["silent"] is True and m["onset_s"]["available"] is False, m
    assert m["peak_dbfs"]["available"] is False and m["rms_dbfs"]["available"] is False, m
    assert m["silence_spans"] == {"count": 1, "first": [0.0, 0.5]}


def test_a_clipped_sine_is_flat_topped_and_its_clean_twin_is_not(tmp_path: Path) -> None:
    """Clipped at half its amplitude, a 100 Hz sine sits flat on the lid for a third of each
    half-cycle, a dozen samples and more at 8 kHz; unclipped it touches its peak for one or two."""
    clipped = wav.measure(wav.read("p", _write(tmp_path / "c.wav", [
        _sine(RATE, freq=100, clip=AMP / 2)])), None, None)["measures"][0]
    clean = wav.measure(wav.read("p", _write(tmp_path / "k.wav", [
        _sine(RATE, freq=100)])), None, None)["measures"][0]
    assert clipped["clipped"] is True and clipped["clipping_run"] > wav.CLIP_RUN_MAX
    assert clean["clipped"] is False and clean["clipping_run"] <= wav.CLIP_RUN_MAX


def test_a_window_and_a_channel_are_measured_alone(tmp_path: Path) -> None:
    path = _write(tmp_path / "st.wav", [_sine(RATE), [0] * RATE])
    rec = wav.read("p", path)
    both = wav.measure(rec, None, None)["measures"]
    assert [m["silent"] for m in both] == [False, True]
    right = wav.measure(rec, [0.5, 0.75], 1)
    assert right["window"] == [0.5, 0.75] and [m["channel"] for m in right["measures"]] == [1]
    left = wav.measure(rec, [0.5, 0.75], 0)
    assert left["pcm_sha256"] == right["pcm_sha256"], "the hash is the window's frames, whole"
    # Another span of the same sine: [0.25, 0.5] would be the same samples (a whole number of
    # periods away), so the control is a span of another length.
    assert left["pcm_sha256"] != wav.measure(rec, [0.3, 0.5], 0)["pcm_sha256"]
    with pytest.raises(Invalid, match="has 2 channel"):
        wav.measure(rec, None, 2)
    with pytest.raises(Invalid, match="is not inside"):
        wav.measure(rec, [0.5, 1.5], None)
    with pytest.raises(Invalid, match=r"is \[from_s, to_s\]"):
        wav.measure(rec, [0.5], None)


def test_an_8_bit_file_reads_centred_on_128(tmp_path: Path) -> None:
    """8-bit PCM is unsigned: a full-scale 8-bit sine of amplitude 64 peaks at 20 log10(64/128),
    -6.02 dBFS, as its 16-bit twin of 16384 does."""
    path = _write(tmp_path / "b.wav", [_sine(RATE, amp=64)], width=1)
    m = wav.measure(wav.read("p", path), None, None)["measures"][0]
    assert m["peak_dbfs"] == pytest.approx(-6.02, abs=0.01)
    assert wav.measure(wav.read("p", path), None, None)["bits"] == 8


def test_another_kind_of_wav_is_refused_by_what_it_is(tmp_path: Path) -> None:
    path = tmp_path / "w24.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(RATE)
        w.writeframes(bytes(30))
    with pytest.raises(Invalid, match="24-bit PCM; this reads 8- and 16-bit only"):
        wav.read("path", str(path))
    (tmp_path / "x.wav").write_bytes(b"RIFF....not a wave")
    with pytest.raises(Invalid, match="is not a PCM WAV"):
        wav.read("path", str(tmp_path / "x.wav"))
    empty = _write(tmp_path / "e.wav", [[]])
    with pytest.raises(Invalid, match="holds no sample"):
        wav.read("path", empty)
    # A header that says 0 samples a second, which the stdlib reader lets through: every time in
    # the reply divides by it.
    still = bytearray(Path(_write(tmp_path / "z.wav", [[1, 2, 3]])).read_bytes())
    still[24:28] = struct.pack("<I", 0)
    (tmp_path / "z.wav").write_bytes(still)
    with pytest.raises(Invalid, match="0 samples a second"):
        wav.read("path", str(tmp_path / "z.wav"))


def test_a_window_that_rounds_past_the_last_sample_is_refused(tmp_path: Path) -> None:
    """101 samples at 2 Hz: [50.3, 50.75] s round to samples 101 and 102, both past the last
    (100); the window holds no sample of the file, so it is refused, never measured empty."""
    rec = wav.read("p", _write(tmp_path / "o.wav", [[16] * 101], rate=2))
    with pytest.raises(Invalid, match="is not inside"):
        wav.span(rec, [50.3, 50.75])
    assert wav.span(rec, [50.0, 50.5]) == (100, 101), "the last sample is still inside"


@pytest.mark.parametrize("down_db, grade", [(0.0, "exact"), (0.005, "inaudible"),
                                            (0.1, "audible"), (0.5, "different"),
                                            (1.0, "different")])
def test_a_sine_a_fraction_of_a_db_down_falls_in_its_snr_band(
        tmp_path: Path, down_db: float, grade: str) -> None:
    """The same sine scaled by g: the error is (1 - g) of the signal, so the SNR is
    -20 log10(1 - g): 0.005 dB down is 64.8 dB (inaudible), 0.1 dB 38.8 (audible), 1 dB 19.3
    (different), and 0.5 dB 25.0, just under the 30 dB edge (different); unscaled it is the
    same file, exact."""
    g = 10 ** (-down_db / 20)
    ref = _write(tmp_path / "r.wav", [_sine(RATE)])
    a = _write(tmp_path / "a.wav", [_sine(RATE, amp=AMP * g)])
    got = wav.compare(wav.read("a", a), wav.read("b", ref), None, True)
    assert got["class"] == grade, got
    if down_db:
        assert got["snr_db"] == pytest.approx(-20 * math.log10(1 - g), abs=0.6)
    assert got["envelope_correlation"] > 0.999 or got["envelope_correlation"] == 1.0


def test_alignment_meets_the_onsets_and_says_how_far(tmp_path: Path) -> None:
    """The same burst 400 samples (50 ms) later: aligned it is the same sound, unaligned it is
    different, and the onset delta is the delay either way."""
    early = _write(tmp_path / "e.wav", [_sine(RATE, start=800)])
    late = _write(tmp_path / "l.wav", [_sine(RATE, start=1200)])
    aligned = wav.compare(wav.read("a", late), wav.read("b", early), None, True)
    assert aligned["aligned_by_samples"] == 400 and aligned["onset_delta_ms"] == 50.0
    assert aligned["class"] in ("exact", "inaudible") and aligned["exact"] is False
    raw = wav.compare(wav.read("a", late), wav.read("b", early), None, False)
    assert raw["class"] == "different" and raw["aligned_by_samples"] == 0
    assert raw["length_delta_samples"] == 0


def test_two_silences_compare_nothing(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.wav", [[0] * 800])
    b = _write(tmp_path / "b.wav", [[0] * 800])
    with pytest.raises(Invalid, match="both recordings are silent") as e:
        wav.compare(wav.read("a", a), wav.read("b", b), None, True)
    assert e.value.code == "control_silent"
    loud = _write(tmp_path / "c.wav", [_sine(800)])
    one_silent = wav.compare(wav.read("a", loud), wav.read("b", a), None, True)
    assert one_silent["class"] == "different" and one_silent["onset_delta_ms"]["available"] is False


def test_two_formats_are_refused(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.wav", [_sine(800)])
    b = _write(tmp_path / "b.wav", [_sine(800)], rate=11025)
    with pytest.raises(Invalid, match="compare two of one format"):
        wav.compare(wav.read("a", a), wav.read("b", b), None, True)


def test_the_two_tools_answer_and_judge_their_arguments(tmp_path: Path) -> None:
    path = _write(tmp_path / "s.wav", [_sine(RATE, start=800)])
    got = media_tools.audio_compare("measure", path)
    assert got["path"] == path and got["measures"][0]["onset_s"] > 0.09
    assert media_tools.TOOLS["audio_compare"].summary({"method": "measure"}, got).startswith(
        "audio_compare measure: ch0 peak -6.23")
    same = media_tools.audio_compare("diff", a=path, b=path)
    assert same["exact"] is True and same["class"] == "exact"
    assert same["snr_db"]["available"] is False, same
    assert media_tools.TOOLS["audio_compare"].summary({"method": "diff"}, same) == (
        "audio_compare diff: exact, equal, envelope 1.0")
    quiet = media_tools.audio_compare("measure", _write(tmp_path / "q.wav", [[0] * 800]))
    assert media_tools.TOOLS["audio_compare"].summary({"method": "measure"}, quiet) == (
        "audio_compare measure: ch0 silent")
    check = media_tools.TOOLS["audio_compare"].check
    for kw, said in (
            ({"method": "measure", "path": "s.wav"}, "must be an absolute path"),
            ({"method": "measure", "path": _abs("s"), "window": [1, 0]}, "window="),
            ({"method": "measure", "path": _abs("s"), "window": [-1, 2]}, "window="),
            ({"method": "measure", "path": _abs("s"), "channel": True}, "channel="),
            ({"method": "diff", "a": _abs("a"), "b": _abs("b"), "align": 1}, "align is true"),
            ({"method": "diff", "a": _abs("a"), "b": "b"}, "b='b'")):
        with pytest.raises(Invalid, match=said):
            check(**kw)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps no mode that refuses a read")
def test_an_unreadable_wav_is_refused(tmp_path: Path) -> None:
    path = Path(_write(tmp_path / "s.wav", [_sine(800)]))
    path.chmod(0)
    try:
        with pytest.raises(Invalid, match="cannot be read"):
            wav.read("path", str(path))
    finally:
        path.chmod(0o644)


def test_the_onset_is_the_first_sample_over_two_percent_of_the_peak(tmp_path: Path) -> None:
    """A linear ramp from 0 to 16000 over 1000 samples, from sample 800: the first sample over
    2% of the peak (320) is 800 + 21, at 0.102625 s; a threshold of 20% would say 1001."""
    ramp = [0] * 800 + [round(AMP * i / 1000) for i in range(1000)] + [AMP] * 200
    m = wav.measure(wav.read("p", _write(tmp_path / "r.wav", [ramp])), None, None)["measures"][0]
    assert m["onset_s"] == round((800 + 21) / RATE, 4)


def test_a_sound_under_half_a_percent_of_full_scale_is_silent(tmp_path: Path) -> None:
    """An RMS of 0.2% of full scale is mute to the ear and to the gate; 1% is not."""
    faint = wav.measure(wav.read("p", _write(tmp_path / "f.wav", [_sine(RATE, amp=100)])),
                        None, None)["measures"][0]
    heard = wav.measure(wav.read("p", _write(tmp_path / "h.wav", [_sine(RATE, amp=500)])),
                        None, None)["measures"][0]
    assert faint["silent"] is True and heard["silent"] is False


def test_stereo_compares_each_channel_so_neither_antiphase_nor_a_swap_hides(
        tmp_path: Path) -> None:
    """A mixdown hides both: a channel in antiphase cancels to silence, and the two channels
    swapped average to the same mono. Each channel is compared, and the worst one grades."""
    s, z = _sine(RATE), [0] * RATE
    anti = wav.read("a", _write(tmp_path / "anti.wav", [s, [-v for v in s]]))
    got = wav.compare(anti, anti, None, True)
    assert got["class"] == "exact"
    left = wav.read("a", _write(tmp_path / "l.wav", [s, z]))
    right = wav.read("b", _write(tmp_path / "r.wav", [z, s]))
    swapped = wav.compare(left, right, None, True)
    assert swapped["class"] == "different" and swapped["exact"] is False


def test_a_file_cut_inside_a_frame_is_read_to_its_last_whole_frame(tmp_path: Path) -> None:
    path = tmp_path / "cut.wav"
    _write(path, [_sine(RATE), _sine(RATE)])
    raw = path.read_bytes()
    cut = tmp_path / "short.wav"
    cut.write_bytes(raw[:-2])
    rec = wav.read("path", str(cut))
    assert {len(c) for c in rec.channels} == {RATE - 1}
    assert wav.compare(rec, rec, None, True)["class"] == "exact"
    assert wav.measure(rec, None, 1)["measures"][0]["channel"] == 1


def test_a_length_apart_by_a_tenth_of_a_second_is_different(tmp_path: Path) -> None:
    """The tracker's gate fails two recordings whose lengths part by more than a tenth of a
    second, whatever the overlap says."""
    short = wav.read("a", _write(tmp_path / "a.wav", [_sine(RATE)]))
    long_ = wav.read("b", _write(tmp_path / "b.wav", [_sine(2 * RATE)]))
    got = wav.compare(short, long_, None, False)
    assert got["length_delta_samples"] == -RATE and got["class"] == "different"
    near = wav.read("c", _write(tmp_path / "c.wav", [_sine(RATE + RATE // 20)]))
    assert wav.compare(short, near, None, False)["class"] == "inaudible"


def test_silence_on_both_sides_is_the_measure_s_silence(tmp_path: Path) -> None:
    """A faint hum under half a percent measures `silent`, so two of them compare nothing,
    the same as two exact silences."""
    hum = wav.read("a", _write(tmp_path / "h.wav", [[100] * RATE]))
    assert wav.measure(hum, None, None)["measures"][0]["silent"] is True
    with pytest.raises(Invalid) as e:
        wav.compare(hum, hum, None, True)
    assert e.value.code == "control_silent"


def test_one_silent_side_aligns_nothing_and_a_later_b_shifts_the_other_way(
        tmp_path: Path) -> None:
    loud = wav.read("a", _write(tmp_path / "a.wav", [_sine(RATE, start=800)]))
    quiet = wav.read("b", _write(tmp_path / "b.wav", [[0] * RATE]))
    got = wav.compare(loud, quiet, None, True)
    assert got["aligned_by_samples"] == 0 and got["class"] == "different"
    late = wav.read("c", _write(tmp_path / "c.wav", [_sine(RATE, start=1600)]))
    back = wav.compare(loud, late, None, True)
    assert back["aligned_by_samples"] == -800 and back["class"] in ("exact", "inaudible")


def test_a_change_of_shape_at_one_level_drops_the_envelope_correlation(tmp_path: Path) -> None:
    """Loud then quiet against quiet then loud: the same energy, the opposite envelope."""
    half = RATE // 2
    a = _sine(half) + _sine(half, amp=AMP / 8)
    b = _sine(half, amp=AMP / 8) + _sine(half)
    got = wav.compare(wav.read("a", _write(tmp_path / "a.wav", [a])),
                      wav.read("b", _write(tmp_path / "b.wav", [b])), None, False)
    assert got["envelope_correlation"] < 0


def test_a_window_that_is_not_finite_or_holds_no_sample_is_refused(tmp_path: Path) -> None:
    rec = wav.read("path", _write(tmp_path / "s.wav", [_sine(RATE)]))
    for window, said in (([0, math.inf], "finite"), ([0.5, 0.50001], "holds no sample")):
        with pytest.raises(Invalid, match=said) as e:
            wav.span(rec, window)
        assert e.value.code == "bad_argument"


def test_an_8_bit_clipped_top_is_a_plateau(tmp_path: Path) -> None:
    s = [round(v / 256) for v in _sine(RATE, amp=AMP * 4, freq=100.0, clip=30000)]
    m = wav.measure(wav.read("p", _write(tmp_path / "c.wav", [s], width=1)), None, None)
    assert m["measures"][0]["clipped"] is True


def test_the_descriptions_state_the_constants_the_code_uses() -> None:
    doc = " ".join((media_tools.audio_compare.__doc__ or "").split())
    for said in (f"{wav.SILENT_RMS * 100:g}% of full scale", f"{wav.SILENCE_DBFS:g} dBFS",
                 f"{wav.SILENCE_MIN_S * 1000:g} ms", f"{wav.ONSET_FRACTION * 100:g}% of the peak",
                 f"{wav.PEAK_FRACTION * 100:g}% of the peak", f"a run past {wav.CLIP_RUN_MAX}",
                 f"{wav.SNR_INAUDIBLE_DB:g} dB or more", f"{wav.SNR_AUDIBLE_DB:g} to "
                 f"{wav.SNR_INAUDIBLE_DB:g}", f"{wav.ENVELOPE_WINDOWS}-window"):
        assert said in doc, said


def test_every_media_tool_is_an_image_tool_or_an_audio_tool() -> None:
    assert sorted(media_tools.IMAGE_TOOLS + media_tools.AUDIO_TOOLS) == sorted(media_tools.TOOLS)


def test_the_worst_channel_grades_the_pair(tmp_path: Path) -> None:
    s = _sine(RATE)
    a = wav.read("a", _write(tmp_path / "a.wav", [s, s]))
    # Both channels differ, the first by a hair (well over 60 dB) and the second by half.
    b = wav.read("b", _write(tmp_path / "b.wav", [[v + (i % 2) for i, v in enumerate(s)],
                                                 [v // 2 for v in s]]))
    got = wav.compare(a, b, None, True)
    assert got["class"] == "different" and got["snr_db"] is not None and got["snr_db"] < 30


def test_a_steady_offset_is_silence_and_a_tone_on_it_starts_at_its_onset(
        tmp_path: Path) -> None:
    """An emulated chip at volume 0 sits at a steady level, not at zero: inaudible, so silent
    with no onset, though its peak says where it sits. A tone riding that level starts where the
    tone starts, not at the file's first sample."""
    dc = wav.read("p", _write(tmp_path / "dc.wav", [[-11000 + (i % 3) for i in range(RATE)]]))
    m = wav.measure(dc, None, None)["measures"][0]
    assert m["silent"] is True and m["onset_s"]["available"] is False and m["clipped"] is False
    assert m["peak_dbfs"] == pytest.approx(20 * math.log10(11000 / 32768), abs=0.01)
    ride = [v - 8000 for v in _sine(RATE, amp=AMP / 2, start=800)]
    t = wav.measure(wav.read("p", _write(tmp_path / "t.wav", [ride])), None, None)["measures"][0]
    assert t["silent"] is False and 0.1 <= t["onset_s"] <= 0.1 + 1 / RATE
    with pytest.raises(Invalid) as e:
        wav.compare(dc, dc, None, True)
    assert e.value.code == "control_silent"


def test_one_tone_resting_at_two_levels_compares_the_same(tmp_path: Path) -> None:
    """A steady level is no sound, so one tone over two resting levels is one sound."""
    s = _sine(RATE, amp=AMP / 2)
    low = wav.read("a", _write(tmp_path / "a.wav", [[v - 9000 for v in s]]))
    high = wav.read("b", _write(tmp_path / "b.wav", [[v + 3000 for v in s]]))
    assert wav.compare(low, high, None, False)["class"] == "inaudible"


@pytest.mark.parametrize("name, samples", [
    ("a click at the first sample, then the rest", [0] + [-11000] * (RATE - 1)),
    ("a one-step settle of the rest", [-11000] * (RATE // 4) + [-10999] * (3 * RATE // 4)),
])
def test_a_resting_chip_is_silent_unclipped_and_quiet(tmp_path: Path, name: str,
                                                       samples: list[int]) -> None:
    m = wav.measure(wav.read("p", _write(tmp_path / "r.wav", [samples])), None, None)
    got = m["measures"][0]
    assert got["silent"] is True and got["onset_s"]["available"] is False, name
    assert got["clipped"] is False and got["clipping_run"] == 0, name


def test_a_clipped_top_is_found_wherever_the_window_starts(tmp_path: Path) -> None:
    """A wave clipped on one side only, its first sample on the flat top: the plateau is the
    top, not the far side of the first sample."""
    wave_ = [min(16000, v) if v > 0 else round(0.7 * v) for v in _sine(RATE, amp=20000,
                                                                      freq=100.0)]
    rec = wav.read("p", _write(tmp_path / "c.wav", [wave_]))
    for start in (0.0, 0.0125, 0.003):
        got = wav.measure(rec, [start, 0.9], None)["measures"][0]
        assert got["clipped"] is True, start


def test_a_rest_that_steps_to_another_level_is_quiet_on_both_sides(tmp_path: Path) -> None:
    """A step of the resting level is one click, and quiet before and after it."""
    step = [-11000] * (RATE // 5) + [-5000] * (4 * RATE // 5)
    got = wav.measure(wav.read("p", _write(tmp_path / "s.wav", [step])), None, None)
    spans = got["measures"][0]["silence_spans"]
    assert spans["count"] == 2 and spans["first"] == [0.0, 0.2], spans


def test_a_sound_rising_from_a_rest_below_zero_is_not_clipped_at_its_rest(
        tmp_path: Path) -> None:
    """A chip resting at -8500 that rises in short swells: the rest is the sample farthest from
    zero and it is flat, but it is where the sound rests, not a top it was clipped against."""
    swell = [-8500 + round(1500 * math.sin(math.pi * i / 20)) for i in range(20)]
    s = ([-8500] * 60 + swell) * (RATE // 80)
    got = wav.measure(wav.read("p", _write(tmp_path / "r.wav", [s])), None, None)["measures"][0]
    assert got["silent"] is False and got["clipped"] is False, got


# THE EXTENSIBLE HEADER (tag 0xFFFE, the PCM subformat GUID): what a recorder writes for more than
# two channels or more than 16 bits, and what some write always. The stdlib reads it from 3.12 on;
# 3.11, which `requires-python` still promises, refuses its tag as `unknown format: 65534`. The
# GUIDs are written out here, not imported, so the header is the format's and not the reader's.
_PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
_FLOAT_GUID = bytes.fromhex("0300000000001000800000aa00389b71")


def _extensible(path: Path, samples: list[int], guid: bytes = _PCM_GUID,
                before: bytes = b"") -> str:
    """An extensible WAV of `samples`, with the chunks `before` ahead of its fmt chunk."""
    data = struct.pack(f"<{len(samples)}h", *samples)
    fmt = struct.pack("<HHIIHH", 0xFFFE, 1, RATE, RATE * 2, 2, 16)
    fmt += struct.pack("<HHI", 22, 16, 0x4) + guid
    body = b"WAVE" + before + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def _stdlib_without_extensible(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stdlib reader as 3.11 ships it: an extensible tag is an unknown format."""
    real: Any = wave.Wave_read._read_fmt_chunk  # type: ignore[attr-defined]  # private, typeshed omits it

    def refuse(self: wave.Wave_read, chunk: Any) -> None:
        tag = struct.unpack_from("<H", chunk.read(2))[0]
        chunk.seek(0)
        if tag != 1:
            raise wave.Error(f"unknown format: {tag!r}")
        real(self, chunk)
    monkeypatch.setattr(wave.Wave_read, "_read_fmt_chunk", refuse)


@pytest.mark.parametrize("stdlib", ["this one", "3.11's"])
def test_an_extensible_pcm_header_reads_as_its_plain_twin(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdlib: str) -> None:
    if stdlib == "3.11's":
        _stdlib_without_extensible(monkeypatch)
    samples = _sine(RATE // 4)
    ext = wav.read("p", _extensible(tmp_path / "x.wav", samples))
    plain = wav.read("p", _write(tmp_path / "p.wav", [samples]))
    assert (ext.rate, ext.width, ext.raw) == (plain.rate, plain.width, plain.raw)
    assert list(ext.channels[0]) == samples


def test_a_chunk_of_odd_size_before_the_fmt_chunk_is_stepped_over_with_its_pad(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stdlib_without_extensible(monkeypatch)
    odd = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\0"
    got = wav.read("p", _extensible(tmp_path / "x.wav", [5, 6, 7], before=odd))
    assert list(got.channels[0]) == [5, 6, 7]


def test_an_extensible_header_of_another_subformat_is_refused_by_what_it_is(
        tmp_path: Path) -> None:
    path = _extensible(tmp_path / "f.wav", [0, 1, 2], guid=_FLOAT_GUID)
    with pytest.raises(Invalid, match="is not a PCM WAV this reads"):
        wav.read("p", path)


# ------------------------------------------------------------------- a recorder's own file

def _stereo(path: Path, n: int = 64) -> Path:
    """A finished 16-bit stereo file at 48000 Hz, as both emulators' recorders write one."""
    _write(path, [_sine(n, freq=1000.0), _sine(n, amp=AMP // 2, freq=1000.0)], rate=48000)
    return path


def _edit(data: bytes, at: int, fmt: str, value: int) -> bytes:
    out = bytearray(data)
    struct.pack_into(fmt, out, at, value)
    return bytes(out)


def _with_sizes(data: bytes) -> bytes:
    out = bytearray(data)
    struct.pack_into("<I", out, 4, len(out) - 8)
    struct.pack_into("<I", out, 40, len(out) - wav.HEADER_BYTES)
    return bytes(out)


def test_the_header_agrees_with_stdlib_wave_and_the_levels_with_the_samples(
        tmp_path: Path) -> None:
    path = _stereo(tmp_path / "s.wav")
    got = wav.header(path)
    with wave.open(str(path)) as w:
        want = (w.getnchannels(), w.getframerate(), w.getnframes())
        every = array("h", w.readframes(w.getnframes()))
    assert got is not None and (got.channels, got.sample_rate, got.samples) == want
    assert got.data_bytes == path.stat().st_size - wav.HEADER_BYTES
    assert wav.levels(path) == (min(every), max(every))


def test_the_levels_are_the_whole_file_s_across_chunks(monkeypatch: pytest.MonkeyPatch,
                                                        tmp_path: Path) -> None:
    path = _stereo(tmp_path / "s.wav", 300)
    whole = wav.levels(path)
    monkeypatch.setattr(wav, "CHUNK_BYTES", 6)
    assert wav.levels(path) == whole


def _refused(base: bytes) -> dict[str, bytes]:
    return {
        "RIFF magic": b"RIFX" + base[4:],
        "WAVE magic": base[:8] + b"WAVX" + base[12:],
        "fmt tag": base[:12] + b"fmtX" + base[16:],
        "fmt size 18": _edit(base, 16, "<I", 18),
        "not PCM": _edit(base, 20, "<H", 3),
        "rate zero": _edit(_edit(base, 24, "<I", 0), 28, "<I", 0),
        "byte rate": _edit(base, 28, "<I", 1),
        "block align": _edit(base, 32, "<H", 2),
        "8 bits": _edit(base, 34, "<H", 8),
        "data tag": base[:36] + b"LIST" + base[40:],
        "RIFF size": _edit(base, 4, "<I", len(base)),
        "data size": _edit(base, 40, "<I", len(base) - wav.HEADER_BYTES - 4),
        "unfinished: both sizes 0": _edit(_edit(base, 4, "<I", 0), 40, "<I", 0),
        "half a stereo frame": _with_sizes(base + b"\x00\x00"),
        "short header": base[:43],
    }


def test_a_header_that_disagrees_with_itself_or_the_file_is_no_header(tmp_path: Path) -> None:
    base = _stereo(tmp_path / "s.wav").read_bytes()
    path = tmp_path / "x.wav"
    for why, data in _refused(base).items():
        path.write_bytes(data)
        assert wav.header(path) is None, why
    assert wav.header(tmp_path / "never.wav") is None


def test_a_header_naming_no_channel_is_told_apart_from_a_file_that_is_no_wav(
        tmp_path: Path) -> None:
    base = _stereo(tmp_path / "s.wav").read_bytes()
    path = tmp_path / "x.wav"
    path.write_bytes(_edit(_edit(_edit(base, 22, "<H", 0), 28, "<I", 0), 32, "<H", 0))
    assert wav.header(path) is None and wav.without_channel(path)
    path.write_bytes(bytes(wav.HEADER_BYTES))
    assert not wav.without_channel(path)
    path.write_bytes(base)
    assert not wav.without_channel(path)
    assert not wav.without_channel(tmp_path / "never.wav")
