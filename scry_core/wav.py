"""What a recording says, measured on the host from the WAV: whether it sounded, how loud, when,
whether it clipped, and how close two recordings are. Sound reaches the model as these numbers and
the file's path.

The measures are the ones a tracker's audio gates use, so the two agree. Clipping is the longest run
of flat samples near the peak (a clipped top is flat at any
level). A comparison grades each channel against its twin, never a mixdown (antiphase channels
would cancel, swapped ones average to one sound), takes the worst grade, and reports the
envelope correlation beside it. Two lengths more than a tenth of a second apart are `different`.

A resting chip's steady level is no sound: the RMS, the plateau and every
comparison read the window less its mean; the silences, a DC blocker; the onset, the move from
the level the window starts at. The peak reads the samples as written. 8-bit (unsigned) and 16-bit
PCM are read, the extensible header's PCM subformat
included; any other WAV is refused by what it is. Two silent recordings compare nothing:
`control_silent`.

A recorder's own file is checked before its path is handed back (`header`, `levels`): both
emulators write the 44-byte PCM header and fill its two sizes only at close, so a file still
open reads 0 there whatever it holds.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import sys
import wave
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from scry_core import judges
from scry_core.prose import counted
from scry_core.reply_contract import Invalid, unavailable

SILENT_RMS = 0.005
SILENCE_DBFS = -60.0
SILENCE_MIN_S = 0.050
ONSET_FRACTION = 0.02
#: The onset puts two recordings near each other; the waveforms put them exactly, within this
#: many samples of it, over this many from the reference's onset.
REFINE_LAG = 512
REFINE_SPAN = 2048
#: Plateau detector: samples within `FLAT_EPS` 16-bit steps are flat; a run past `CLIP_RUN_MAX`
#: clips.
FLAT_EPS = 2
PEAK_FRACTION = 0.95
CLIP_RUN_MAX = 8
ENVELOPE_WINDOWS = 64
SNR_INAUDIBLE_DB, SNR_AUDIBLE_DB = 60.0, 30.0
#: The tracker's rule: lengths a tenth of a second apart differ.
LENGTH_TENTHS = 10
#: An envelope deviating less than this fraction of full scale has no shape.
FLAT_ENVELOPE = 1e-6
#: Under any pitch a chip plays, over the drift of a resting level.
DC_CORNER_HZ = 5.0
FULL_SCALE = {1: 128, 2: 32768}


@dataclass(frozen=True)
class Recording:
    """A WAV as read: samples signed around zero per channel, plus the raw frames."""

    path: Path
    rate: int
    channels: list[array[int]]
    full: int
    raw: bytes
    width: int

    @property
    def length(self) -> int:
        return len(self.channels[0])


# The stdlib reads the extensible PCM subformat only from 3.12 on.
# fmt chunk: the tag first, the GUID after 24 bytes of fields.
_TAG_PCM, _TAG_EXTENSIBLE = 1, 0xFFFE
_SUBFORMAT = slice(24, 40)
_PCM_SUBFORMAT = bytes.fromhex("0100000000001000800000aa00389b71")

HEADER_BYTES = 44
_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")
CHUNK_BYTES = 1 << 20


class Header(NamedTuple):
    """A finished 16-bit PCM WAV's header; `samples` is frames per channel."""
    channels: int
    sample_rate: int
    data_bytes: int
    samples: int


def _header_fields(path: Path) -> tuple[int, tuple[Any, ...]] | None:
    """The file's size and its unpacked 44-byte header, or None."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(HEADER_BYTES)
    except OSError:
        return None
    return (size, _HEADER.unpack(head)) if len(head) == HEADER_BYTES else None


def header(path: Path) -> Header | None:
    """The header of a finished 16-bit PCM WAV whose sizes agree with the file, or None."""
    got = _header_fields(path)
    if got is None:
        return None
    size, (riff, riff_size, wave_, fmt, fmt_size, fmt_tag, channels, rate, byte_rate, align,
           bits, data, data_size) = got
    if (riff, wave_, fmt, data) != (b"RIFF", b"WAVE", b"fmt ", b"data"):
        return None
    if fmt_size != 16 or fmt_tag != _TAG_PCM or bits != 16 or channels < 1 or rate <= 0:
        return None
    if align != 2 * channels or byte_rate != rate * align:
        return None
    if riff_size != size - 8 or data_size != size - HEADER_BYTES or data_size % align:
        return None
    return Header(channels, rate, data_size, data_size // align)


def without_channel(path: Path) -> bool:
    """A WAV header naming zero channels: what a mixer with no speaker writes."""
    got = _header_fields(path)
    if got is None:
        return False
    riff, _, wave_, _, _, _, channels, *_ = got[1]
    return (riff, wave_, channels) == (b"RIFF", b"WAVE", 0)


def levels(path: Path) -> tuple[int, int]:
    """The lowest and highest sample over every channel: equal is one constant level, silence."""
    lo = hi = None
    with open(path, "rb") as fh:
        fh.seek(HEADER_BYTES)
        while chunk := fh.read(CHUNK_BYTES):
            samples = array("h")
            samples.frombytes(chunk[: len(chunk) // 2 * 2])
            if sys.byteorder == "big":
                samples.byteswap()
            if samples:
                lo = min(samples) if lo is None else min(lo, min(samples))
                hi = max(samples) if hi is None else max(hi, max(samples))
    return (lo or 0, hi or 0)



def _as_plain_pcm(path: Path) -> str | io.BytesIO:
    """`path`, or its bytes with an extensible PCM tag rewritten as plain PCM."""
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
                    # One copy: read straight into a presized buffer.
            size = f.seek(0, io.SEEK_END)
            f.seek(0)
            whole = io.BytesIO()
            whole.seek(size - 1)
            whole.write(b"\0")
            with whole.getbuffer() as view:
                got = f.readinto(view)
                view[fmt_at:fmt_at + 2] = struct.pack("<H", _TAG_PCM)
            # A file that shrank since its size was read is not padded with silence.
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
    # A file cut mid-frame is read to its last whole frame.
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
    """The sample range `window` (`[from_s, to_s]`) names, judged inside the file."""
    seconds = judges.window("window", window)
    if seconds is None:
        return 0, recording.length
    start, end = (round(t * recording.rate) for t in seconds)
    if end > recording.length:
        raise Invalid("bad_argument", f"window {list(seconds)} is not inside "
                      f"{recording.path.name}, which is {recording.length / recording.rate:g} s")
    if start >= end:
        raise Invalid("bad_argument", f"window {list(seconds)} holds no sample at "
                      f"{recording.rate} Hz")
    return start, end


def _dbfs(level: float, full: int) -> float | dict[str, Any]:
    """`level` in dB of full scale, rounded; unavailable for a level of zero, which has none."""
    return (round(20 * math.log10(level / full), 2) if level > 0
            else unavailable("a level of zero has no value in dB"))


def _rms(samples: Sequence[float]) -> float:
    return math.sqrt(math.fsum(x * x for x in samples) / len(samples)) if len(samples) else 0.0


def onset(samples: Sequence[float]) -> int | None:
    """Index of the first sample over `ONSET_FRACTION` of the peak; None for silence."""
    peak = max((abs(x) for x in samples), default=0)
    if not peak:
        return None
    floor = ONSET_FRACTION * peak
    return next(i for i, x in enumerate(samples) if abs(x) > floor)


def plateau(samples: Sequence[float], full: int) -> int:
    """The longest run of flat samples at `PEAK_FRACTION` of the peak or more."""
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
    """Spans quieter than `SILENCE_DBFS` for `SILENCE_MIN_S`+, as `[from_s, to_s]` from the file's
    start (`offset` is the window's first sample)."""
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
    """`samples` less their mean: the part that is heard."""
    mean = math.fsum(samples) / len(samples) if len(samples) else 0.0
    return [x - mean for x in samples]


def from_rest(samples: Sequence[int]) -> list[int]:
    """`samples` less the level the window starts at, where the onset is read."""
    rest = samples[0] if len(samples) else 0
    return [x - rest for x in samples]


def dc_blocked(samples: Sequence[int], rate: int) -> list[float]:
    """`samples` through a one-pole DC blocker at `DC_CORNER_HZ`, primed as if the first sample
    had always been there: a steady level is zeros, a change of level is the click it is heard
    as."""
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
    """The measures of each channel (or `channel`) over `window`, and its PCM hash."""
    start, end = span(recording, window)
    count = len(recording.channels)
    if channel is not None and not judges.whole(channel, 0, count - 1):
        raise Invalid("bad_argument", f"channel={channel!r}: {recording.path.name} has "
                      f"{counted(count, 'channel')}, numbered from 0")
    chosen = range(count) if channel is None else [channel]
    out = []
    for c in chosen:
        raw = recording.channels[c][start:end]
        heard = dc_blocked(raw, recording.rate)
        peak, rms = max(abs(x) for x in raw), _rms(centred(raw))
        silent = _quiet(rms, recording.full)
        quiet = silences(heard, recording.rate, recording.full, start)
        first = None if silent else onset(from_rest(raw))
        # Less its mean, a resting level is near zero rather than a top; silence has no top.
        run = 0 if silent else plateau(centred(raw), recording.full)
        out.append({"channel": c, "peak_dbfs": _dbfs(peak, recording.full),
                    "rms_dbfs": _dbfs(rms, recording.full),
                    "silent": silent,
                    "silence_spans": {"count": len(quiet), "first": quiet[0] if quiet else
                                      unavailable("no silence in the window")},
                    "onset_s": (unavailable("a silent window has no onset") if first is None
                                else round((start + first) / recording.rate, 4)),
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
    """Pearson's correlation of two envelopes; two flat ones (no shape) give 1, one flat gives 0."""
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
    """One aligned channel pair: the SNR (None when equal) and the envelopes' correlation."""
    n = min(len(pa), len(pb))
    signal = math.fsum(x * x for x in pb[:n])
    error = math.fsum((pa[i] - pb[i]) ** 2 for i in range(n))
    snr = None if error == 0 else (10 * math.log10(signal / error) if signal else 0.0)
    return snr, correlation(envelope(pa[:n]), envelope(pb[:n]), full)


def _quiet(rms: float, full: int) -> bool:
    """The one silence, shared by `measure` and the control `compare` keys on."""
    return rms / full < SILENT_RMS


def _sounding(recording: Recording, start: int, end: int) -> list[Sequence[int]]:
    """The channels of `recording` that are not silent over `start`..`end`, each cut to it."""
    return [cut for ch in recording.channels
            if not _quiet(_rms(centred(cut := ch[start:end])), recording.full)]


def _first_onset(recording: Recording, start: int, end: int) -> int | None:
    """The earliest onset of any sounding channel over `start`..`end`."""
    return min((o for cut in _sounding(recording, start, end)
                if (o := onset(from_rest(cut))) is not None), default=None)


def _refined(pa: Sequence[int], pb: Sequence[int], shift: int) -> int:
    """The lag within `REFINE_LAG` of `shift` at which `pa` best follows `pb` from `pb`'s onset
    (normalised cross-correlation): a threshold crossing wanders with the least difference
    between two renders, and a soft first bar moves it by tens of samples."""
    start = onset(from_rest(pb)) or 0
    span = min(REFINE_SPAN, len(pb) - start)
    ref = centred(pb)[start:start + span]
    follower = centred(pa)
    best, at = -2.0, shift
    for lag in range(shift - REFINE_LAG, shift + REFINE_LAG + 1):
        lo = start + lag
        if lo < 0 or lo + span > len(follower):
            continue
        seg = follower[lo:lo + span]
        energy = sum(v * v for v in seg)
        if not energy:
            continue
        score = sum(x * y for x, y in zip(seg, ref, strict=True)) / math.sqrt(energy)
        if score > best:
            best, at = score, lag
    return at


def compare(a: Recording, b: Recording, window: Sequence[float] | None,
            align: bool) -> dict[str, Any]:
    """`a` against reference `b` over `window`; when `align`, shifted so the onsets meet, then the
    waveforms."""
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
    if align and oa is not None and ob is not None:
        loud = max(range(len(b.channels)), key=lambda k: _rms(centred(b.channels[k][sb:eb])))
        shift = _refined(a.channels[loud][sa:ea], b.channels[loud][sb:eb], shift)
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
    return {"exact": exact,
            "snr_db": unavailable("the two are equal after alignment: there is no error to "
                                  "measure the signal against") if snr is None
            else round(snr, 2), "class": grade,
            "envelope_correlation": min(c for _, c in pairs),
            "onset_delta_ms": unavailable("one of the two is silent, so has no onset")
            if oa is None or ob is None else round((oa - ob) * 1000 / a.rate, 3),
            "length_delta_samples": length_delta, "aligned_by_samples": shift}
