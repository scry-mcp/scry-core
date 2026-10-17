"""The sound measures, held on recordings made here whose answers are known by construction: a
sine at a known level and onset, silence, a hard-clipped sine, the same sine a fraction of a dB
down for each SNR band, an 8-bit file, and two silences, which compare nothing."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from scry_core import media_tools, wav
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
    assert (m["silent"], m["onset_s"], m["peak_dbfs"], m["rms_dbfs"]) == (True, None, None, None)
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
    assert one_silent["class"] == "different" and one_silent["onset_delta_ms"] is None


def test_two_formats_are_refused(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.wav", [_sine(800)])
    b = _write(tmp_path / "b.wav", [_sine(800)], rate=11025)
    with pytest.raises(Invalid, match="compare two of one format"):
        wav.compare(wav.read("a", a), wav.read("b", b), None, True)


def test_the_two_tools_answer_and_judge_their_arguments(tmp_path: Path) -> None:
    path = _write(tmp_path / "s.wav", [_sine(RATE, start=800)])
    got = media_tools.audio_measure(path)
    assert got["path"] == path and got["measures"][0]["onset_s"] > 0.09
    assert media_tools._audio_measure_line({}, got).startswith("audio_measure: ch0 peak -6.23")
    same = media_tools.audio_diff(path, path)
    assert same["exact"] is True and same["class"] == "exact" and same["snr_db"] is None
    assert media_tools._audio_diff_line({}, same) == (
        "audio_diff: exact, equal, envelope 1.0")
    quiet = media_tools.audio_measure(_write(tmp_path / "q.wav", [[0] * 800]))
    assert media_tools._audio_measure_line({}, quiet) == "audio_measure: ch0 silent"
    for check, kw, said in (
            (media_tools.check_audio_measure, {"path": "s.wav"}, "is an absolute path"),
            (media_tools.check_audio_measure, {"path": "/s", "window": [1, 0]}, "window="),
            (media_tools.check_audio_measure, {"path": "/s", "window": [-1, 2]}, "window="),
            (media_tools.check_audio_measure, {"path": "/s", "channel": True}, "channel="),
            (media_tools.check_audio_diff, {"a": "/a", "b": "/b", "align": 1}, "align="),
            (media_tools.check_audio_diff, {"a": "/a", "b": "b"}, "b='b'")):
        with pytest.raises(Invalid, match=said):
            check(**kw)


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
    measure, diff = media_tools.audio_measure.__doc__ or "", media_tools.audio_diff.__doc__ or ""
    for said in (f"{wav.SILENT_RMS * 100:g}% of full scale", f"{wav.SILENCE_DBFS:g} dBFS",
                 f"{wav.SILENCE_MIN_S * 1000:g} ms", f"{wav.ONSET_FRACTION * 100:g}% of the peak",
                 f"{wav.PEAK_FRACTION * 100:g}% of the peak", f"a run past {wav.CLIP_RUN_MAX}"):
        assert said in " ".join(measure.split()), said
    for said in (f"{wav.SNR_INAUDIBLE_DB:g} dB or more", f"{wav.SNR_AUDIBLE_DB:g} to "
                 f"{wav.SNR_INAUDIBLE_DB:g}", f"{wav.ENVELOPE_WINDOWS}-window"):
        assert said in " ".join(diff.split()), said


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
    assert m["silent"] is True and m["onset_s"] is None and m["clipped"] is False
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
