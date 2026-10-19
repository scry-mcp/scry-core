"""What a recording says, measured on the host from the WAV: whether it sounded, how loud, when,
whether it clipped, and how close two recordings are. Sound never reaches the model as content:
it reaches it as these numbers and the file's path.

THE MEASURES are the ones a tracker's own audio gates use, so a server's answer and a project's
gate agree: a peak and an RMS in dBFS; silence as an RMS under `SILENT_RMS` of full scale; spans
of silence at `SILENCE_DBFS` lasting `SILENCE_MIN_S` or more; the onset as the first sample over
`ONSET_FRACTION` of the peak; clipping as the longest run of flat samples near the peak (a
clipped top is flat at any level, so its signature is the plateau, not the full-scale value);
and between two recordings, channel by channel with the worst grading, the signal-to-error
ratio, sorted into `exact`, `inaudible`, `audible` and `different`, beside the correlation of
their energy envelopes, which gives away a change of shape that leaves the global level where it
was. Two lengths more than a tenth of a second apart are `different` whatever the overlap says,
as in the gate. A channel is compared with its twin, never through a mixdown: a channel in
antiphase would cancel to silence and two swapped channels would average to one sound.

An emulated chip at rest sits at a steady level rather than at zero, and a steady level is no
sound. The RMS, the plateau and every comparison read the window less its mean, so the level a
chip rests at is never the top it was clipped against, while a clipped top stays flat (and a plateau
cannot tell it from a square wave's); the silences read it through a DC blocker; the onset reads
how far it moves from the level it starts at (a window opened mid-sound starts at its first
change). A silent window has no onset and no plateau. The peak reads the samples as written: the
headroom left. 8- and 16-bit PCM are read (8-bit is unsigned, centred on 128), the extensible
header's PCM subformat included; any other WAV is refused by what it is. A comparison of two
recordings that are both silent compares nothing, so it is `control_silent`, never a match.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core import judges
from scry_core.reply_contract import Invalid

SILENT_RMS = 0.005
SILENCE_DBFS = -60.0
SILENCE_MIN_S = 0.050
ONSET_FRACTION = 0.02
#: The plateau detector's constants: two samples within `FLAT_EPS` 16-bit steps are flat; only a
#: plateau at `PEAK_FRACTION` of the peak or above counts; a run past `CLIP_RUN_MAX` is clipping.
FLAT_EPS = 2
PEAK_FRACTION = 0.95
CLIP_RUN_MAX = 8
ENVELOPE_WINDOWS = 64
SNR_INAUDIBLE_DB, SNR_AUDIBLE_DB = 60.0, 30.0
#: Two lengths more than a tenth of a second apart are different recordings, the tracker's rule.
LENGTH_TENTHS = 10
#: An envelope whose deviation is under this fraction of full scale has no shape to correlate.
FLAT_ENVELOPE = 1e-6
#: The DC blocker's corner: under any pitch a chip plays, over the drift of a resting level.
DC_CORNER_HZ = 5.0
#: The sample widths read, in bytes, with their full scale.
FULL_SCALE = {1: 128, 2: 32768}


@dataclass(frozen=True)
class Recording:
    """A WAV as read: its rate, its channels' samples signed around zero, its full scale, and
    the raw frames the samples came from."""

    path: Path
    rate: int
    channels: list[array[int]]
    full: int
    raw: bytes
    width: int

    @property
    def length(self) -> int:
        return len(self.channels[0])


# THE EXTENSIBLE HEADER'S PCM subformat: the stdlib reads it only from 3.12 on, so a PCM file that
# carries it is handed over as the plain PCM it is, the one tag rewritten. The fmt chunk's layout:
# its tag first, the subformat GUID after the 24 bytes of fields before it.
_TAG_PCM, _TAG_EXTENSIBLE = 1, 0xFFFE
_SUBFORMAT = slice(24, 40)
_PCM_SUBFORMAT = bytes.fromhex("0100000000001000800000aa00389b71")


def _as_plain_pcm(path: Path) -> str | io.BytesIO:
    """`path`, or its bytes with an extensible PCM tag rewritten as plain PCM. Anything else
    (another subformat, a header this cannot walk) goes to the stdlib as it is, which refuses it
    by what it is."""
    with path.open("rb") as f:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return str(path)
        while len(chunk := f.read(8)) == 8:
            kind, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
            if kind != b"fmt ":
                f.seek(size + size % 2, io.SEEK_CUR)       # a chunk is padded to an even size
                continue
            fmt_at, fmt = f.tell(), f.read(min(size, _SUBFORMAT.stop))
            if (len(fmt) < _SUBFORMAT.stop or struct.unpack_from("<H", fmt)[0] != _TAG_EXTENSIBLE
                    or fmt[_SUBFORMAT] != _PCM_SUBFORMAT):
                return str(path)
            # ONE COPY: the buffer is grown to the file's size and the file read straight into
            # it, then the tag rewritten in place; a `bytearray(f.read())` and a `BytesIO` of it
            # would each copy the whole recording again.
            size = f.seek(0, io.SEEK_END)
            f.seek(0)
            whole = io.BytesIO()
            whole.seek(size - 1)
            whole.write(b"\0")
            with whole.getbuffer() as view:
                got = f.readinto(view)
                view[fmt_at:fmt_at + 2] = struct.pack("<H", _TAG_PCM)
            # A file that shrank since its size was read ends where it ends, never padded
            # with a silence nobody recorded.
            whole.truncate(got)
            whole.seek(0)
            return whole
    return str(path)


def read(name: str, value: object) -> Recording:
    """The WAV at `value`, or the refusal naming what it is when it is not 8- or 16-bit PCM."""
    path = judges.existing_file(name, value)
    try:
        with wave.open(_as_plain_pcm(path), "rb") as w:
            width, count, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise Invalid("bad_argument", f"{name}: {path} is not a PCM WAV this reads: {e}") from None
    except OSError as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}") from None
    if rate < 1:
        raise Invalid("bad_argument", f"{name}: {path} declares {rate} samples a second")
    if width not in FULL_SCALE:
        raise Invalid("bad_argument", f"{name}: {path} is {8 * width}-bit PCM; this reads 8- and "
                      "16-bit only")
    # A file cut inside a frame (a run killed mid-write) is read to its last whole frame, so
    # every channel holds as many samples as the others.
    raw = raw[:len(raw) // (width * count) * (width * count)]
    if width == 1:
        flat = array("h", (b - 128 for b in raw))
    else:
        flat = array("h")
        flat.frombytes(raw)
    channels = [flat[c::count] for c in range(count)]
    if not len(channels[0]):
        raise Invalid("bad_argument", f"{name}: {path} holds no sample")
    return Recording(path, rate, channels, FULL_SCALE[width], raw, width)


def span(recording: Recording, window: Sequence[float] | None) -> tuple[int, int]:
    """The sample range `window` (`[from_s, to_s]`, seconds) names, judged inside the file."""
    seconds = judges.window("window", window)
    if seconds is None:
        return 0, recording.length
    # Judged on the samples it rounds to, which is what is read: a time half a sample past the
    # last one rounds either way.
    start, end = (round(t * recording.rate) for t in seconds)
    if end > recording.length:
        raise Invalid("bad_argument", f"window {list(seconds)} is not inside "
                      f"{recording.path.name}, which is {recording.length / recording.rate:g} s")
    if start >= end:
        raise Invalid("bad_argument", f"window {list(seconds)} holds no sample at "
                      f"{recording.rate} Hz")
    return start, end


def _dbfs(level: float, full: int) -> float | None:
    """`level` in dB of full scale, rounded; None for a level of zero, which has none."""
    return round(20 * math.log10(level / full), 2) if level > 0 else None


def _rms(samples: Sequence[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in samples) / len(samples)) if len(samples) else 0.0


def onset(samples: Sequence[float]) -> int | None:
    """The index of the first sample over `ONSET_FRACTION` of the peak; None for silence."""
    peak = max((abs(x) for x in samples), default=0)
    if not peak:
        return None
    floor = ONSET_FRACTION * peak
    return next(i for i, x in enumerate(samples) if abs(x) > floor)


def plateau(samples: Sequence[float], full: int) -> int:
    """The longest run of flat samples at `PEAK_FRACTION` of the peak or above."""
    peak = max((abs(x) for x in samples), default=0)
    if not peak:
        return 0
    eps, high = FLAT_EPS * full // 32768, PEAK_FRACTION * peak
    run = longest = 0
    for prev, x in zip(samples, samples[1:], strict=False):
        if abs(x) >= high and abs(x - prev) <= eps:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest


def silences(samples: Sequence[float], rate: int, full: int,
             offset: int) -> list[list[float]]:
    """Every span quieter than `SILENCE_DBFS` lasting `SILENCE_MIN_S` or more, as `[from_s,
    to_s]` from the file's start (`offset` is the window's first sample)."""
    floor = full * 10 ** (SILENCE_DBFS / 20)
    least = round(SILENCE_MIN_S * rate)
    out: list[list[float]] = []
    begun: int | None = None
    for i, x in enumerate([*samples, floor + 1]):
        if abs(x) < floor:
            if begun is None:
                begun = i
        elif begun is not None:
            if i - begun >= least:
                out.append([round((offset + begun) / rate, 4), round((offset + i) / rate, 4)])
            begun = None
    return out


def centred(samples: Sequence[int]) -> list[float]:
    """`samples` less their mean: the part that is heard, which a level and a comparison read."""
    mean = math.fsum(samples) / len(samples) if len(samples) else 0.0
    return [x - mean for x in samples]


def from_rest(samples: Sequence[int]) -> list[int]:
    """`samples` less the level the window starts at, where a sound's onset is read: the first
    sample over `ONSET_FRACTION` of how far the window moves from that level."""
    rest = samples[0] if len(samples) else 0
    return [x - rest for x in samples]


def dc_blocked(samples: Sequence[int], rate: int) -> list[float]:
    """`samples` through a one-pole DC blocker (`y[n] = x[n] - x[n-1] + R y[n-1]`, its corner at
    `DC_CORNER_HZ`), primed as if the window's first sample had always been there: a steady
    level is zeros from the first sample, and a change of level is the click it is heard as.
    Where a sound falls quiet is read here, so a chip resting away from zero, or settling from one
    resting level to another, is quiet."""
    pole = 1 - 2 * math.pi * DC_CORNER_HZ / rate
    out: list[float] = []
    prev_x, prev_y = (samples[0] if len(samples) else 0), 0.0
    for x in samples:
        prev_y = x - prev_x + pole * prev_y
        prev_x = x
        out.append(prev_y)
    return out


def measure(recording: Recording, window: Sequence[float] | None,
            channel: int | None) -> dict[str, Any]:
    """The measures of each channel (or of `channel`) over `window`, and the window's PCM hash."""
    start, end = span(recording, window)
    count = len(recording.channels)
    if channel is not None and not judges.whole(channel, 0, count - 1):
        raise Invalid("bad_argument", f"channel={channel!r}: {recording.path.name} has "
                      f"{count} channel(s), numbered from 0")
    chosen = range(count) if channel is None else [channel]
    out = []
    for c in chosen:
        raw = recording.channels[c][start:end]
        heard = dc_blocked(raw, recording.rate)
        peak, rms = max(abs(x) for x in raw), _rms(centred(raw))
        silent = _quiet(rms, recording.full)
        quiet = silences(heard, recording.rate, recording.full, start)
        first = None if silent else onset(from_rest(raw))
        # The plateau reads the window less its mean, where a clipped top is still flat and the
        # level a chip rests at is near zero, not a top; a silent window has no top to clip.
        run = 0 if silent else plateau(centred(raw), recording.full)
        out.append({"channel": c, "peak_dbfs": _dbfs(peak, recording.full),
                    "rms_dbfs": _dbfs(rms, recording.full),
                    "silent": silent,
                    "silence_spans": {"count": len(quiet), "first": quiet[0] if quiet else None},
                    "onset_s": None if first is None else round((start + first) / recording.rate,
                                                                4),
                    "clipping_run": run, "clipped": run > CLIP_RUN_MAX})
    frame = recording.width * count
    pcm = recording.raw[start * frame:end * frame]
    return {"sample_rate_hz": recording.rate, "channels": count, "bits": 8 * recording.width,
            "window": [round(start / recording.rate, 4), round(end / recording.rate, 4)],
            "measures": out, "pcm_sha256": hashlib.sha256(pcm).hexdigest()}


def envelope(samples: Sequence[float]) -> list[float]:
    """The RMS of each of `ENVELOPE_WINDOWS` equal windows."""
    width = max(1, len(samples) // ENVELOPE_WINDOWS)
    return [_rms(samples[i * width:(i + 1) * width]) for i in range(ENVELOPE_WINDOWS)]


def correlation(a: Sequence[float], b: Sequence[float], full: int) -> float:
    """Pearson's correlation of two equal-length envelopes in samples of `full` scale. An
    envelope flat to `FLAT_ENVELOPE` of full scale has no shape: two of them correlate 1, and
    one against a shaped one 0."""
    n = min(len(a), len(b))
    ma, mb = math.fsum(a[:n]) / n, math.fsum(b[:n]) / n
    num = math.fsum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(math.fsum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(math.fsum((b[i] - mb) ** 2 for i in range(n)))
    flat_a, flat_b = da / full < FLAT_ENVELOPE, db / full < FLAT_ENVELOPE
    if flat_a or flat_b:
        return 1.0 if flat_a and flat_b else 0.0
    return round(num / (da * db), 6)


def _channel(pa: Sequence[float], pb: Sequence[float], full: int) -> tuple[float | None, float]:
    """One channel pair, already aligned: the SNR (None when equal) and the envelopes'
    correlation."""
    n = min(len(pa), len(pb))
    signal = math.fsum(x * x for x in pb[:n])
    error = math.fsum((pa[i] - pb[i]) ** 2 for i in range(n))
    snr = None if error == 0 else (10 * math.log10(signal / error) if signal else 0.0)
    return snr, correlation(envelope(pa[:n]), envelope(pb[:n]), full)


def _quiet(rms: float, full: int) -> bool:
    """THE ONE SILENCE: an RMS under `SILENT_RMS` of full scale, the word `measure` says and
    the control `compare` keys on."""
    return rms / full < SILENT_RMS


def _sounding(recording: Recording, start: int, end: int) -> list[Sequence[int]]:
    """The channels of `recording` that are not silent over `start`..`end`, each cut to it."""
    return [cut for ch in recording.channels
            if not _quiet(_rms(centred(cut := ch[start:end])), recording.full)]


def _first_onset(recording: Recording, start: int, end: int) -> int | None:
    """The earliest onset of any sounding channel over `start`..`end`, read as `measure` reads
    each channel's."""
    return min((o for cut in _sounding(recording, start, end)
                if (o := onset(from_rest(cut))) is not None), default=None)


def compare(a: Recording, b: Recording, window: Sequence[float] | None,
            align: bool) -> dict[str, Any]:
    """`a` against `b`, the reference, over `window` of each, `b` shifted so the onsets meet when
    `align`; the module docstring says what is answered."""
    if (a.rate, len(a.channels), a.width) != (b.rate, len(b.channels), b.width):
        raise Invalid("bad_argument", f"the recordings are {a.rate} Hz x {len(a.channels)} "
                      f"x {8 * a.width}-bit and {b.rate} Hz x {len(b.channels)} x "
                      f"{8 * b.width}-bit: compare two of one format")
    (sa, ea), (sb, eb) = span(a, window), span(b, window)
    if not _sounding(a, sa, ea) and not _sounding(b, sb, eb):
        raise Invalid("control_silent", "both recordings are silent over the window: two "
                      "silences compare equal whatever produced them, which is no verdict")
    frame = len(a.channels) * a.width
    exact = a.raw[sa * frame:ea * frame] == b.raw[sb * frame:eb * frame]
    oa, ob = _first_onset(a, sa, ea), _first_onset(b, sb, eb)
    shift = oa - ob if align and oa is not None and ob is not None else 0
    pairs = []
    for ca, cb in zip(a.channels, b.channels, strict=True):
        pa, pb = centred(ca[sa:ea]), centred(cb[sb:eb])
        pairs.append(_channel(pa[shift:], pb, a.full) if shift >= 0
                     else _channel(pa, pb[-shift:], a.full))
    known = [snr for snr, _ in pairs if snr is not None]
    snr = min(known, default=None)
    length_delta = (ea - sa) - (eb - sb)
    grade = ("exact" if exact else "different" if abs(length_delta) > a.rate // LENGTH_TENTHS
             else "inaudible" if snr is None or snr >= SNR_INAUDIBLE_DB
             else "audible" if snr >= SNR_AUDIBLE_DB else "different")
    return {"exact": exact, "snr_db": None if snr is None else round(snr, 2), "class": grade,
            "envelope_correlation": min(c for _, c in pairs),
            "onset_delta_ms": None if oa is None or ob is None
            else round((oa - ob) * 1000 / a.rate, 3),
            "length_delta_samples": length_delta, "aligned_by_samples": shift}
