"""The tools that read media files and touch no emulator, held once for both servers: each has ONE
body, ONE description, ONE summary line and ONE judge, so the two servers cannot describe or judge
one tool two ways.

A server registers them with `register(wrap, names, answer)`, `wrap` being its own registration
decorator (`wrap(title, summary=..., read_only=...)`) and `answer` the function that makes a body's
bare fields that server's reply, with its `session` block. Each tool's judge (`TOOLS[n].check`,
machine-independent) goes in the server's pre-gate table, so a call of the wrong shape is refused
before any file is read.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from scry_core import goldens, judges, methods, narrowing, prose, raster, series, wav
from scry_core import vocabulary as vocab
from scry_core.recording import Replay
from scry_core.reply_contract import Invalid

Summary = Callable[[dict[str, Any], dict[str, Any]], str]
#: A server's registration decorator: `wrap(title, summary=..., read_only=..., replay=...)(body)`.
Wrap = Callable[..., Callable[[Callable[..., Any]], Any]]
TOLERANCE_MAX = 255
REFERENCE = "Reference: REFERENCE.md, Media files."
PATHS = "Every path is absolute or starts with `~`."
READS_ONLY = "Reads files only: it needs no machine and alters nothing."
WRITES_ITS_FILE = "Reads files, and `region` writes one, `path`: it needs no machine."


def _optional_rect(name: str, value: object) -> None:
    if value is not None:
        judges.rect(name, value)


def _judge_image(a: object, b: object, crop: object, shift: object,
                      tolerance: object) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    _optional_rect("crop", crop)
    if shift is not None:
        judges.shift(shift)
    if not judges.whole(tolerance, 0, TOLERANCE_MAX):
        raise Invalid("bad_argument", f"tolerance={tolerance!r} is the per-channel difference "
                      f"still counted equal, 0..{TOLERANCE_MAX}")


def _image(a: str, b: str, crop: list[int] | None = None, shift: list[int] | None = None,
               tolerance: int = 0) -> dict[str, Any]:
    _judge_image(a, b, crop, shift, tolerance)
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


def _judge_series(a: object, b: object, crop: object) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    _optional_rect("crop", crop)


def _series(a: str, b: str, crop: list[int] | None = None) -> dict[str, Any]:
    _judge_series(a, b, crop)
    one, two = series.read_manifest("a", a), series.read_manifest("b", b)
    return {**series.compare(one, two, crop), "a": str(one.path), "b": str(two.path)}


def _judge_region(manifest: object, crop: object, measure: object, ref: object,
                        threshold: object, limit: object) -> None:
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


def _region(manifest: str, crop: list[int] | None = None, measure: str = "signature",
                 ref: str = "", threshold: float = series.THRESHOLD_DEFAULT,
                 limit: int = series.LIMIT_DEFAULT) -> dict[str, Any]:
    _judge_region(manifest, crop, measure, ref, threshold, limit)
    track = series.read_manifest("manifest", manifest)
    reference = judges.picture_file("ref", judges.existing_file("ref", ref))[0] if ref else None
    return {**series.track(track, crop, cast(series.Measure, measure), reference,
                                  float(threshold), limit),
            "manifest": str(track.path)}


def _judge_golden(manifest: object, dir: object, checksums: object, limit: object) -> None:
    if bool(manifest) == bool(dir):
        raise Invalid("bad_argument", "name the files to check either as `manifest` (a series) "
                      "or as `dir` (a directory of PNGs), one of the two")
    if manifest:
        judges.absolute("manifest", manifest)
    else:
        judges.absolute("dir", dir)
    judges.absolute("checksums", checksums)
    if not judges.whole(limit, 1, series.LIMIT_MAX):
        raise Invalid("bad_argument", f"limit={limit!r} is how many names each list shows, "
                      f"1..{series.LIMIT_MAX}")


def _golden(manifest: str = "", dir: str = "", checksums: str = "",
                 limit: int = series.LIMIT_DEFAULT) -> dict[str, Any]:
    _judge_golden(manifest, dir, checksums, limit)
    sums = goldens.read_checksums("checksums", judges.existing_file("checksums", checksums))
    if manifest:
        track = series.read_manifest("manifest", manifest)
        files = {r.path.name: r.path for r in track.rows}
        where = {"manifest": str(track.path)}
    else:
        folder = judges.absolute("dir", dir)
        files = goldens.in_dir("dir", folder)
        where = {"dir": str(folder)}
    got = goldens.compare(files, sums)
    lists = ("differing", "missing", "extra")
    cut = [name for name in lists if len(got[name]) > limit]
    return {"matched": got["matched"],
            **{name: got[name][:limit] for name in lists},
            **{f"{name}_total": len(got[name]) for name in lists},
            "checksums": str(judges.absolute("checksums", checksums)), **where,
            **narrowing.omission(cut, f"each list shows its first {limit} names and its whole "
                                 "count is beside it: raise `limit` for more")}


def _judge_measure(path: object, window: object, channel: object) -> None:
    judges.absolute("path", path)
    judges.window("window", window)
    if channel is not None and not judges.whole(channel):
        raise Invalid("bad_argument", f"channel={channel!r} is a channel number, from 0")


def _measure(path: str, window: list[float] | None = None,
                  channel: int | None = None) -> dict[str, Any]:
    _judge_measure(path, window, channel)
    recording = wav.read("path", path)
    return {**wav.measure(recording, window, channel), "path": str(recording.path)}


def _judge_diff(a: object, b: object, window: object, align: object) -> None:
    judges.absolute("a", a)
    judges.absolute("b", b)
    judges.window("window", window)
    vocab.check_bool("align", align)


def _diff(a: str, b: str, window: list[float] | None = None,
               align: bool = True) -> dict[str, Any]:
    _judge_diff(a, b, window, align)
    one, two = wav.read("a", a), wav.read("b", b)
    return {**wav.compare(one, two, window, align), "a": str(one.path), "b": str(two.path)}


def _gate(body: Callable[..., Any], judge: Callable[..., None]) -> Callable[..., None]:
    """The pre-gate's judge of `body`: the arguments a call named, the body's own defaults for
    the rest, so each default is written once, on the body; an argument the body takes and the
    call left out with no default is `""`, the spelling of "not given" every judge refuses."""
    params = inspect.signature(body).parameters

    def gate(**given: Any) -> None:
        judge(**{name: given.get(name, "" if p.default is p.empty else p.default)
                 for name, p in params.items()})
    gate.__name__ = gate.__qualname__ = judge.__name__
    return gate


def _image_line(reply: dict[str, Any]) -> str:
    x, y, w, h = reply["crop"]
    past = f" past tolerance {reply['tolerance']}" if reply["tolerance"] else ""
    if not reply["differing_pixels"]:
        return f"no pixel differs{past} over {w}x{h} at [{x}, {y}]"
    return f"{reply['differing_pixels']} pixels differ{past} over {w}x{h}, bbox {reply['bbox']}"


def _series_line(reply: dict[str, Any]) -> str:
    first = reply["first_differing"]
    tail = f", first at frame {first['frame']}" if "frame" in first else ""
    return (f"{reply['pairs']} pairs, {reply['identical']} identical, "
            f"{reply['differing']} differing{tail}")


def _region_line(reply: dict[str, Any]) -> str:
    total = reply["transitions_total"]
    cut = f", the first {len(reply['transitions'])} listed" if reply.get("omitted") else ""
    return (f"{reply['measure']}, {prose.counted(total, 'transition')} "
            f"over {reply['frames']} frames{cut}")


def _golden_line(reply: dict[str, Any]) -> str:
    return (f"{reply['matched']} matched, {reply['differing_total']} differing, "
            f"{reply['missing_total']} missing, {reply['extra_total']} extra")


def _measure_line(reply: dict[str, Any]) -> str:
    return ", ".join(f"ch{m['channel']} " + ("silent" if m["silent"] else
                     f"peak {m['peak_dbfs']} dBFS, onset {m['onset_s']} s"
                     + (", clipped" if m["clipped"] else "")) for m in reply["measures"])


def _diff_line(reply: dict[str, Any]) -> str:
    snr = "equal" if isinstance(reply["snr_db"], dict) else f"SNR {reply['snr_db']} dB"
    return f"{reply['class']}, {snr}, envelope {reply['envelope_correlation']}"


IMAGE_METHODS: dict[str, methods.Method] = {
    "image": methods.Method(_image, _gate(_image, _judge_image), _image_line),
    "series": methods.Method(_series, _gate(_series, _judge_series), _series_line),
    "region": methods.Method(_region, _gate(_region, _judge_region), _region_line),
    "golden": methods.Method(_golden, _gate(_golden, _judge_golden), _golden_line),
}
AUDIO_METHODS: dict[str, methods.Method] = {
    "measure": methods.Method(_measure, _gate(_measure, _judge_measure), _measure_line),
    "diff": methods.Method(_diff, _gate(_diff, _judge_diff), _diff_line),
}


ImageMethod = Literal["image", "series", "region", "golden"]
AudioMethod = Literal["measure", "diff"]


def image_compare(method: ImageMethod, a: str = "", b: str = "", crop: list[int] | None = None,
                  shift: list[int] | None = None, tolerance: int | None = None,
                  manifest: str = "", measure: str = "", ref: str = "",
                  threshold: float | None = None, limit: int | None = None, dir: str = "",
                  checksums: str = "") -> dict[str, Any]:
    """Compare PNGs, series or a region of one, in numbers. `crop` [x, y, w, h];
    `limit` 1..1000 (default 40) cuts a list, its count beside it.

    `image`: PNGs `a`, `b`; two sizes need `crop`; `shift` [dx, dy] moves `b`; `tolerance`
    0..255. Reply: `differing_pixels`, `bbox`, `max_delta`, `width`, `height`, `crop`, `shift`,
    `tolerance`, `a`, `b`.

    `series`: `scry-series/1` manifests `a`, `b`. Reply: `pairs`, `identical`, `differing`,
    `first_differing`, `only_in_a`, `only_in_b`, `crop`, `a`, `b`.

    `region`: `crop` of `manifest` by `measure`: `signature`, `changed_pixels`, or `match`
    against `ref` at `threshold` (0.98). Reply: `start`, `transitions`, `gaps`,
    `transitions_total`, `frames`, `measure`, `crop`, `manifest`, `path`.

    `golden`: `manifest` or `dir` against `checksums` (`shasum -a 256`). Reply: `matched`,
    `differing`, `missing`, `extra`, `differing_total`, `missing_total`, `extra_total`,
    `checksums`, `manifest` or `dir`.

    Refused: an argument the method does not take; `control_silent` when nothing can differ."""
    chosen, given = methods.chosen(IMAGE_METHODS, locals())
    return chosen.run(given)


def audio_compare(method: AudioMethod, path: str = "", a: str = "", b: str = "",
                  window: list[float] | None = None, channel: int | None = None,
                  align: bool | None = None) -> dict[str, Any]:
    """Measure a WAV or compare two, and answer in numbers: the sound never comes back.
    8- or 16-bit PCM; `window` [from_s, to_s], seconds, default the whole file.

    `measure`: `path`, every channel or `channel` (0 the first). Reply: `measures`, per channel
    `channel`, `peak_dbfs`, `rms_dbfs`, `silent` (RMS under 0.5% of full scale),
    `silence_spans` (under -60 dBFS for 50 ms or more), `onset_s` (over 2% of the peak),
    `clipping_run` (flat at 95% of the peak or above), `clipped` (a run past 8); then
    `sample_rate_hz`, `channels`, `bits`, `window`, `pcm_sha256`, `path`.

    `diff`: `a` against the reference `b`, of one format; `align` (default true) meets the
    onsets. Reply: `exact`, `snr_db`, `class` (`exact`; `inaudible` 60 dB or more; `audible` 30
    to 60; `different`), `envelope_correlation` (64-window envelopes), `onset_delta_ms`,
    `length_delta_samples`, `aligned_by_samples`, `a`, `b`.

    Refused: an argument the method does not take; `control_silent` when both are silent."""
    chosen, given = methods.chosen(AUDIO_METHODS, locals())
    return chosen.run(given)


@dataclass(frozen=True)
class FileTool:
    """One media tool: what the client shows, its body, its judge, its summary line, whether it
    is read-only (a tool that writes a file is not, whatever it reads), and what its calls become
    in an exported session (`scry_core.recording`): dropped, since none reads the machine, but
    for a check of what files hold."""

    title: str
    body: Callable[..., dict[str, Any]]
    check: Callable[..., None]
    summary: Summary
    read_only: bool
    replay: Replay = "drop"


TOOLS: dict[str, FileTool] = {
    "image_compare": FileTool("Compare pictures", image_compare,
                              methods.fold_check(IMAGE_METHODS),
                              methods.fold_line("image_compare", IMAGE_METHODS), False,
                              {"image": "drop", "series": "drop", "region": "drop",
                               "golden": ("matched", "differing_total", "missing_total",
                                          "extra_total", "differing", "missing", "extra")}),
    "audio_compare": FileTool("Measure or compare WAV recordings", audio_compare,
                              methods.fold_check(AUDIO_METHODS),
                              methods.fold_line("audio_compare", AUDIO_METHODS), True),
}
#: The tools of the image layer, which both servers register.
IMAGE_TOOLS = ("image_compare",)
#: The tools of the sound layer, which a server registers once it records a WAV.
AUDIO_TOOLS = ("audio_compare",)


def register(wrap: Wrap, names: Sequence[str],
             answer: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Register the tools `names` through the server's own decorator, each body's bare fields
    made a reply by `answer`, the server's own reply builder (its `status` and `session`), and
    answer each as the decorator returned it, so the server calls them as it calls its own."""
    unknown = sorted(set(names) - TOOLS.keys())
    if unknown:
        raise ValueError(f"no media tools named {unknown}")

    def answered(body: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(body)
        def reply(*a: Any, **k: Any) -> dict[str, Any]:
            return answer(body(*a, **k))
        return reply
    return {n: wrap(TOOLS[n].title, summary=TOOLS[n].summary, read_only=TOOLS[n].read_only,
                    replay=TOOLS[n].replay)(answered(TOOLS[n].body)) for n in names}


for _tool in TOOLS.values():
    _tool.body.__doc__ = ((_tool.body.__doc__ or "").rstrip() + "\n\n    "
                          + (READS_ONLY if _tool.read_only else WRITES_ITS_FILE) + " " + PATHS
                          + f"\n\n    {REFERENCE}\n")
