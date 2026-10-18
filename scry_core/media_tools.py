"""The tools that read media files and touch no emulator, held once for both servers: each has ONE
body, ONE description, ONE summary line and ONE judge, so the two servers cannot describe or judge
one tool two ways.

A server registers them with `register(wrap, names)`, `wrap` being its own registration decorator
(`wrap(title, summary=..., read_only=...)`), which already registers on the server and wraps every
reply in that server's envelope with its `session` block. Each tool's judge (`TOOLS[n].check`,
machine-independent) goes in the server's pre-gate table, so a call of the wrong shape is refused
before any file is read.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from scry_core import goldens, judges, raster, series, wav
from scry_core.recording import ExportAs
from scry_core.reply_contract import Invalid

Summary = Callable[[dict[str, Any], dict[str, Any]], str]
#: A server's registration decorator: `wrap(title, summary=..., read_only=..., replay=...)(body)`.
Wrap = Callable[..., Callable[[Callable[..., Any]], Any]]
TOLERANCE_MAX = 255
REFERENCE = "Reference: REFERENCE.md, Media files."
READS_ONLY = "Reads files only: it needs no machine and alters nothing."
WRITES_ITS_FILE = "Reads files and writes one, `path`: it needs no machine."


def _optional_rect(name: str, value: object) -> None:
    if value is not None:
        judges.rect(name, value)


def check_image_diff(a: object = "", b: object = "", crop: object = None, shift: object = None,
                     tolerance: object = 0, **_: Any) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    _optional_rect("crop", crop)
    if shift is not None:
        judges.shift(shift)
    if not judges.whole(tolerance, 0, TOLERANCE_MAX):
        raise Invalid("bad_argument", f"tolerance={tolerance!r} is the per-channel difference "
                      f"still counted equal, 0..{TOLERANCE_MAX}")


def image_diff(a: str, b: str, crop: list[int] | None = None, shift: list[int] | None = None,
               tolerance: int = 0) -> dict[str, Any]:
    """Compare two PNG files pixel by pixel, in the colours they show, and answer where they
    differ without sending either picture.

    `a`, `b`: absolute paths of PNGs (8-bit, indexed or RGB). `crop` [x, y, width, height] is
    the rectangle compared on both; it must lie inside both (it is never padded), and pictures
    of two sizes need one. `shift` [dx, dy] compares pixel (x, y) of `a` with (x + dx, y + dy) of
    `b`, over the part of the crop both stay in: a sprite that moved compares equal at its
    move. `tolerance` (0..255) is the per-channel difference still counted equal.

    Reply: `differing_pixels`, `bbox` ([x, y, w, h] in `a`'s pixels, null when none differ),
    `max_delta` ([r, g, b], the largest channel difference seen), `width` and `height` (`a`'s),
    `crop` (the rectangle of `a` compared), `shift`, `tolerance`, and `a` and `b` (`path`,
    `sha256`).
    """
    check_image_diff(a, b, crop, shift, tolerance)
    read = {name: (path, *judges.picture_file(name, path))
            for name, path in (("a", judges.existing_file("a", a)),
                               ("b", judges.existing_file("b", b)))}
    first, second = read["a"][1], read["b"][1]
    got = raster.diff(first, second, crop, judges.shift(shift) if shift is not None else (0, 0),
                      tolerance)
    return {"differing_pixels": got["differing_pixels"], "bbox": got["bbox"],
            "max_delta": got["max_delta"], "width": first.width, "height": first.height,
            "crop": got["compared"], "shift": list(shift) if shift is not None else [0, 0],
            "tolerance": tolerance,
            **{name: {"path": str(path), "sha256": digest}
               for name, (path, _, digest) in read.items()}}


def check_series_diff(a: object = "", b: object = "", crop: object = None, **_: Any) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    _optional_rect("crop", crop)


def series_diff(a: str, b: str, crop: list[int] | None = None) -> dict[str, Any]:
    """Compare two series frame by frame, paired by frame number, after checking that each one
    can tell frames apart at all.

    `a`, `b`: absolute paths of `scry-series/1` manifests (what `series_capture` writes); every
    file a manifest lists is checked against its sha256 first. `crop` [x, y, width, height] is
    compared on every frame of both, inside the PNGs. THE CONTROLS: a series whose every frame
    has one signature over the crop is `control_silent` naming it, since it says nothing about
    the other one; two series with no frame number in common are `control_silent` too.

    Reply: `pairs`, `identical`, `differing`, `first_differing` (`frame`, `differing_pixels`,
    `bbox`, or null), `only_in_a` and `only_in_b` (frames with no partner, as [first, last]
    runs), `crop` (the rectangle compared), and `a`, `b`.
    """
    check_series_diff(a, b, crop)
    one, two = series.read_manifest("a", a), series.read_manifest("b", b)
    return {**series.series_diff(one, two, crop), "a": str(one.path), "b": str(two.path)}


def check_region_track(manifest: object = "", crop: object = None, measure: object = "signature",
                       ref: object = "", threshold: object = series.THRESHOLD_DEFAULT,
                       limit: object = series.LIMIT_DEFAULT, **_: Any) -> None:
    judges.absolute("manifest", manifest)
    _optional_rect("crop", crop)
    if measure not in series.MEASURES:
        raise Invalid("bad_argument", f"measure={measure!r} is one of "
                      f"{', '.join(series.MEASURES)}")
    if (measure == "match") != bool(ref):
        raise Invalid("bad_argument", "`ref` goes with measure `match`, and `match` needs it: "
                      "the PNG, of the crop's size, the region is matched against")
    if ref:
        judges.absolute("ref", ref)
    if not (isinstance(threshold, int | float) and not isinstance(threshold, bool)
            and 0 < threshold <= 1):
        raise Invalid("bad_argument", f"threshold={threshold!r} is the fraction of the crop that "
                      "must match for `match` to be on, above 0 and at most 1")
    if not judges.whole(limit, 1, series.LIMIT_MAX):
        raise Invalid("bad_argument", f"limit={limit!r} is how many transitions the reply lists, "
                      f"1..{series.LIMIT_MAX}")


def region_track(manifest: str, crop: list[int] | None = None, measure: str = "signature",
                 ref: str = "", threshold: float = series.THRESHOLD_DEFAULT,
                 limit: int = series.LIMIT_DEFAULT) -> dict[str, Any]:
    """Follow one region through a series and answer the frames where it changes, as numbers,
    never as pictures.

    `manifest`: an absolute path of a `scry-series/1` manifest. `crop` [x, y, width, height],
    inside its PNGs (default the whole picture). `measure`: `signature` (the region's
    signature; a transition is a new one), `changed_pixels` (pixels changed since the previous
    frame; a transition is a frame where any did), `match` (the fraction of the region equal to
    `ref`, the absolute path of a PNG of the crop's size; on at `threshold` or more, default
    0.98, and a transition is a flip). `limit` (1..1000, default 40): transitions listed. THE
    CONTROL: a measure that never changes over the series is `control_silent`, the crop having
    missed.

    Reply: `start` ([frame, value] at the first frame; null for `changed_pixels`),
    `transitions` ([frame, value]: the new signature, the count, or true/false), `gaps` (frame
    numbers between consecutive transitions), `transitions_total`, `frames`, `measure`, `crop`
    (the rectangle measured), `manifest`, and `path`, a JSON file beside the manifest holding
    every transition and each frame's value; a list cut at `limit` says so in `omitted` and
    `how`.
    """
    check_region_track(manifest, crop, measure, ref, threshold, limit)
    track = series.read_manifest("manifest", manifest)
    reference = judges.picture_file("ref", judges.existing_file("ref", ref))[0] if ref else None
    return {**series.region_track(track, crop, cast(series.Measure, measure), reference,
                                  float(threshold), limit),
            "manifest": str(track.path)}


def check_golden_check(manifest: object = "", dir: object = "", checksums: object = "",
                       **_: Any) -> None:
    if bool(manifest) == bool(dir):
        raise Invalid("bad_argument", "name the files to check either as `manifest` (a series) "
                      "or as `dir` (a directory of PNGs), one of the two")
    if manifest:
        judges.absolute("manifest", manifest)
    else:
        judges.absolute("dir", dir)
    judges.absolute("checksums", checksums)


def golden_check(manifest: str = "", dir: str = "", checksums: str = "") -> dict[str, Any]:
    """Check a series, or a directory of PNGs, against goldens written by `shasum -a 256`:
    exact bytes, by file name.

    ONE of `manifest`, the absolute path of a `scry-series/1` manifest (its frames), or `dir`, an
    absolute directory (its `*.png`); and `checksums`, the absolute path of a file of
    `<sha256>  <name>` lines (the name's last part is matched, so a line may carry a directory).
    A file and a golden that meet nowhere compare nothing, so no name in common is
    `control_silent`; a line that does not parse is refused naming it.

    Reply: `matched` (a count), `differing`, `missing` (goldens with no file) and `extra` (files
    with no golden), each a sorted list of names, and `checksums`, and `manifest` or `dir`.
    """
    check_golden_check(manifest, dir, checksums)
    sums = goldens.read_checksums("checksums", judges.existing_file("checksums", checksums))
    if manifest:
        track = series.read_manifest("manifest", manifest)
        files = {r.path.name: r.path for r in track.rows}
        where = {"manifest": str(track.path)}
    else:
        folder = judges.absolute("dir", dir)
        files = goldens.in_dir("dir", folder)
        where = {"dir": str(folder)}
    return {**goldens.compare(files, sums), "checksums": checksums, **where}


def check_audio_measure(path: object = "", window: object = None, channel: object = None,
                        **_: Any) -> None:
    judges.absolute("path", path)
    judges.window("window", window)
    if channel is not None and not judges.whole(channel):
        raise Invalid("bad_argument", f"channel={channel!r} is a channel number, from 0")


def audio_measure(path: str, window: list[float] | None = None,
                  channel: int | None = None) -> dict[str, Any]:
    """Measure a WAV (what `audio_record` writes) and answer whether it sounded, how loud, when
    and whether it clipped, as numbers: the sound itself never comes back.

    `path`: the absolute path of an 8- or 16-bit PCM WAV. `window` [from_s, to_s], seconds
    (default the whole file). `channel` (default every channel).

    A chip resting at a steady level is silent: the RMS and the plateau read the window less its
    mean, the silences read it through a DC blocker, the onset against its first sample, the
    peak as written (a square wave's flat top reads as a plateau too).
    Reply, per channel in `measures` (`channel`, 0 the first, the left of a stereo file):
    `peak_dbfs` and `rms_dbfs` (null for zero), `silent` (an RMS under 0.5% of full scale),
    `silence_spans` (`count`, and the `first` [from_s, to_s] quieter than -60 dBFS for 50 ms or
    more), `onset_s` (the first sample over 2% of the peak, from the file's start; null when
    silent), `clipping_run` (the longest run of flat samples at 95% of the peak or above)
    and `clipped` (a run past 8); then `sample_rate_hz`, `channels`,
    `bits`, `window` and `pcm_sha256` (the window's frames, every channel's, for an exact
    comparison), and `path`.
    """
    check_audio_measure(path, window, channel)
    recording = wav.read("path", path)
    return {**wav.measure(recording, window, channel), "path": str(recording.path)}


def check_audio_diff(a: object = "", b: object = "", window: object = None, align: object = True,
                     **_: Any) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    judges.window("window", window)
    if not isinstance(align, bool):
        raise Invalid("bad_argument", f"align={align!r} is true or false")


def audio_diff(a: str, b: str, window: list[float] | None = None,
               align: bool = True) -> dict[str, Any]:
    """Compare two WAVs of one format, `b` the reference, and answer how close they are as
    numbers.

    `a`, `b`: absolute paths of 8- or 16-bit PCM WAVs of one rate, channel count and width.
    `window` [from_s, to_s], seconds, on each. `align` (default true) drops the head of the
    later one so the two onsets meet, so a recording that starts later is not called different
    for it. Each channel is compared with its twin and the worst grades. THE CONTROL: two
    recordings both `silent` (as `audio_measure` says) over the window compare nothing, so that
    is `control_silent`.

    Reply: `exact` (the windows' bytes equal), `snr_db` (signal to error, the reference's
    energy over the difference's, the worst channel's; null when equal after alignment),
    `class` (`exact`, `inaudible` at 60 dB or more, `audible` 30 to 60, `different` under 30 or
    lengths a tenth of a second apart), `envelope_correlation` (of the 64-window energy
    envelopes, the worst channel's), `onset_delta_ms` (a's onset minus b's),
    `length_delta_samples` (a's minus b's), `aligned_by_samples` (positive: a's head dropped;
    negative: b's), and `a`, `b`.
    """
    check_audio_diff(a, b, window, align)
    one, two = wav.read("a", a), wav.read("b", b)
    return {**wav.compare(one, two, window, align), "a": str(one.path), "b": str(two.path)}


def _audio_measure_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    said = ", ".join(f"ch{m['channel']} " + ("silent" if m["silent"] else
                     f"peak {m['peak_dbfs']} dBFS, onset {m['onset_s']} s"
                     + (", clipped" if m["clipped"] else "")) for m in reply["measures"])
    return f"audio_measure: {said}"


def _audio_diff_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    snr = "equal" if reply["snr_db"] is None else f"SNR {reply['snr_db']} dB"
    return f"audio_diff: {reply['class']}, {snr}, envelope {reply['envelope_correlation']}"


def _image_diff_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    x, y, w, h = reply["crop"]
    past = f" past tolerance {reply['tolerance']}" if reply["tolerance"] else ""
    if not reply["differing_pixels"]:
        return f"image_diff: no pixel differs{past} over {w}x{h} at [{x}, {y}]"
    return (f"image_diff: {reply['differing_pixels']} pixels differ{past} over {w}x{h}, "
            f"bbox {reply['bbox']}")


def _series_diff_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    first = reply["first_differing"]
    tail = f", first at frame {first['frame']}" if first else ""
    return (f"series_diff: {reply['pairs']} pairs, {reply['identical']} identical, "
            f"{reply['differing']} differing{tail}")


def _region_track_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    total = reply["transitions_total"]
    cut = f", the first {len(reply['transitions'])} listed" if reply.get("omitted") else ""
    return (f"region_track {reply['measure']}: {total} transition{'' if total == 1 else 's'} "
            f"over {reply['frames']} frames{cut}")


def _golden_check_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"golden_check: {reply['matched']} matched, {len(reply['differing'])} differing, "
            f"{len(reply['missing'])} missing, {len(reply['extra'])} extra")


@dataclass(frozen=True)
class FileTool:
    """One media tool: what the client shows, its body, its judge, its summary line, whether it
    is read-only (a tool that writes a file is not, whatever it reads), and what its calls become
    in an exported session (`scry_core.recording`): dropped, since none reads the machine, but
    for a check of what a file holds."""

    title: str
    body: Callable[..., dict[str, Any]]
    check: Callable[..., None]
    summary: Summary
    read_only: bool
    replay: ExportAs = "drop"


TOOLS: dict[str, FileTool] = {
    "image_diff": FileTool("Compare two pictures", image_diff, check_image_diff,
                           _image_diff_line, True),
    "series_diff": FileTool("Compare two series", series_diff, check_series_diff,
                            _series_diff_line, True),
    "region_track": FileTool("Track a region through a series", region_track,
                             check_region_track, _region_track_line, False),
    "golden_check": FileTool("Check files against goldens", golden_check, check_golden_check,
                             _golden_check_line, True,
                             ("matched", "differing", "missing", "extra")),
    "audio_measure": FileTool("Measure a WAV recording", audio_measure, check_audio_measure,
                              _audio_measure_line, True),
    "audio_diff": FileTool("Compare two WAV recordings", audio_diff, check_audio_diff,
                           _audio_diff_line, True),
}
#: The tools of the image layer, which both servers register.
IMAGE_TOOLS = ("image_diff", "series_diff", "region_track", "golden_check")
#: The tools of the sound layer, which a server registers once it records a WAV.
AUDIO_TOOLS = ("audio_measure", "audio_diff")


def register(wrap: Wrap, names: Sequence[str]) -> dict[str, Any]:
    """Register the tools `names` through the server's own decorator, and answer each as the
    decorator returned it, so the server can call them as it calls its own."""
    unknown = sorted(set(names) - TOOLS.keys())
    if unknown:
        raise ValueError(f"no media tools named {unknown}")
    return {n: wrap(TOOLS[n].title, summary=TOOLS[n].summary, read_only=TOOLS[n].read_only,
                    replay=TOOLS[n].replay)(TOOLS[n].body) for n in names}


for _tool in TOOLS.values():
    # The two sentences every description ends on, said once here for all of them.
    _tool.body.__doc__ = ((_tool.body.__doc__ or "").rstrip() + "\n\n    "
                          + (READS_ONLY if _tool.read_only else WRITES_ITS_FILE)
                          + f"\n\n    {REFERENCE}\n")
