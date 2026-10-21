"""A series of frames on disk, and what is asked of one: is it another series, where does a region
change. No emulator here: a server writes the PNGs and calls `write_manifest`; everything after
reads files.

THE MANIFEST is one JSON file, `"format": "scry-series/1"`, beside its PNGs (`f000123.png`, the
frame number in six digits): `server`, `source` (what the frame numbers count, in the server's own
word: an emulated frame counter, or a capture file's own frames), `crop` (the rectangle of the
screen each PNG holds, or None for the whole screen) and `frames`, one row per frame `{frame,
path, sha256, bytes, signature}`, ascending. A row's `path` is a file name in the manifest's own
directory, so the directory can move. Its `signature` is `raster.picture_signature` over the
whole PNG, the number the screen's own signature over that crop gives. Reading a manifest hashes
every file it lists and signs each picture again, so a frame that changed since, or a row edited by
hand, is refused rather than trusted.

EVERY COMPARISON HAS A CONTROL, because a result that cannot come out the other way is no result:
a series whose frames never change says nothing about another series, two series with no frame in
common compare nothing, and a region whose measure never moves was missed rather than measured.
Each is `control_silent`, never a clean answer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scry_core import fresh, judges, narrowing, png, raster
from scry_core.reply_contract import Invalid, unavailable

MANIFEST_FORMAT = "scry-series/1"
MANIFEST_NAME = "manifest.json"
#: The most frames one series holds: seconds of animation at 60 Hz.
SERIES_MAX = 1000
#: What a tool's description fills from here (`scry_core.docs.filled`).
DOC_VALUES = {"SERIES_MAX": str(SERIES_MAX)}
MEASURES = ("signature", "changed_pixels", "match")
Measure = Literal["signature", "changed_pixels", "match"]
#: `region_track`'s default list length and its ceiling.
LIMIT_DEFAULT, LIMIT_MAX = 40, 1000
THRESHOLD_DEFAULT = 0.98
#: The decimals a `match` fraction is shown with in the track's file.
FRACTION_DIGITS = 4


def frame_name(frame: int) -> str:
    """The file name of frame `frame`'s PNG in a series."""
    return f"f{frame:06d}.png"


def frame_list(at_frames: Sequence[int] | None, first: int | None, last: int | None,
               step: int = 1) -> list[int]:
    """The frames a capture asks for: `at_frames` (a list, ascending, each once) or `first`..`last`
    by `step`, never both and never neither, at most `SERIES_MAX`."""
    if (at_frames is None) == (first is None and last is None):
        raise Invalid("bad_argument", "name the frames either as `at_frames` (a list) or as "
                      "`first` and `last` (with `step`), one of the two")
    if at_frames is not None:
        if not (isinstance(at_frames, list | tuple) and at_frames
                and all(judges.whole(f) for f in at_frames)):
            raise Invalid("bad_argument", f"at_frames={at_frames!r} is a non-empty list of frame "
                          "numbers at or above zero")
        if step != 1:
            raise Invalid("bad_argument", "`step` goes with `first` and `last`; an `at_frames` "
                          "list names each frame itself")
        if any(b <= a for a, b in zip(at_frames, at_frames[1:], strict=False)):
            raise Invalid("bad_argument", f"at_frames={at_frames!r} is ascending, each frame once")
        if len(at_frames) > SERIES_MAX:
            raise Invalid("bad_argument", f"{len(at_frames)} frames; a series holds at most "
                          f"{SERIES_MAX}")
        return list(at_frames)
    if not (judges.whole(first) and judges.whole(last) and judges.whole(step, 1)):
        raise Invalid("bad_argument", f"first={first!r}, last={last!r}, step={step!r}: frame "
                      "numbers at or above zero and a step above it")
    assert isinstance(first, int) and isinstance(last, int)     # `whole` said so; mypy cannot
    if last < first:
        raise Invalid("bad_argument", f"last={last} is before first={first}")
    # Judged before the range is built: `last` may be any number a caller sent.
    count = (last - first) // step + 1
    if count > SERIES_MAX:
        raise Invalid("bad_argument", f"{first}..{last} by {step} is {count} frames; a series "
                      f"holds at most {SERIES_MAX}")
    return list(range(first, last + 1, step))


def tail(asked: int, kept: bool, source: str) -> dict[str, Any]:
    """The fields every `series_capture` reply ends on: how many frames were asked, whether the
    directory outlives the session, and what the frame numbers count."""
    return {"frames_asked": asked, "kept_after_close": kept, "frame_source": source}


def write_manifest(folder: Path, server: str, source: str, crop: Sequence[int] | None,
                   frames: Sequence[int],
                   signed: Mapping[int, str] | None = None) -> dict[str, Any]:
    """The manifest of the PNGs a capture wrote into `folder` as `frame_name(n)`, each hashed
    and signed, written beside them; answers the reply's half: `manifest`, `count`, `first`,
    `last`, `distinct` (signatures). A frame's signature is decoded off its file unless the
    server encoded that file itself and hands the signature of the picture it encoded
    (`signed`): decoding back what was just encoded is a whole frame's work for an answer in
    hand. No `source` word or no frame is the server's bug, a `ValueError`."""
    if not source or not frames:
        raise ValueError(f"a series of {len(frames)} frames from source {source!r}")
    rows = []
    for frame in frames:
        path = folder / frame_name(frame)
        try:
            data = path.read_bytes()
            signature = (signed[frame] if signed is not None and frame in signed
                         else raster.picture_signature(png.decode(data)))
        except (OSError, png.NotAPicture) as e:
            raise Invalid("host_failed", f"frame {frame}'s picture {path} was not written as a "
                          f"readable PNG: {e}") from None
        rows.append({"frame": frame, "path": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                     "bytes": len(data), "signature": signature})
    doc = {"format": MANIFEST_FORMAT, "server": server, "source": source,
           "crop": list(crop) if crop is not None else None, "frames": rows}
    manifest = folder / MANIFEST_NAME
    fresh.create(manifest, json.dumps(doc, indent=1).encode(), "the manifest")
    return {"manifest": str(manifest), "count": len(rows), "first": rows[0]["frame"],
            "last": rows[-1]["frame"], "distinct": len({r["signature"] for r in rows})}


@dataclass(frozen=True)
class FrameRow:
    """One frame of a manifest, its `path` resolved and its file checked when it was read."""

    frame: int
    path: Path
    sha256: str
    signature: str


@dataclass(frozen=True)
class Manifest:
    """A manifest as read: where it is and its frames, ascending."""

    path: Path
    rows: list[FrameRow]

    def picture(self, row: FrameRow) -> png.Raster:
        """Frame `row`'s picture, its file checked against its sha256 again."""
        return judges.picture_file(f"frame {row.frame} of {self.path}", row.path, row.sha256)[0]

    def size(self) -> tuple[int, int]:
        """The size of the series' pictures, read off its first frame."""
        first = self.picture(self.rows[0])
        return first.width, first.height


def read_manifest(name: str, value: object) -> Manifest:
    """The manifest at `value`, read and checked, every file it lists hashed against its row,
    or the refusal naming what is wrong."""
    path = judges.existing_file(name, value)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Invalid("bad_argument", f"{name}: {path} is not JSON: {e}") from None
    if not isinstance(doc, dict) or doc.get("format") != MANIFEST_FORMAT:
        raise Invalid("bad_argument", f"{name}: {path} is not a {MANIFEST_FORMAT} manifest")
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        raise Invalid("bad_argument", f"{name}: {path} lists no frames")
    rows: list[FrameRow] = []
    for i, r in enumerate(frames):
        file = r.get("path") if isinstance(r, dict) else None
        if not (isinstance(r, dict) and judges.whole(r.get("frame")) and isinstance(file, str)
                and isinstance(r.get("sha256"), str) and isinstance(r.get("signature"), str)):
            raise Invalid("bad_argument", f"{name}: {path} row {i} lacks frame, path, sha256 or "
                          "signature")
        if not file or Path(file).name != file or file in (".", "..") or "\x00" in file:
            raise Invalid("bad_argument", f"{name}: {path} row {i} names {file!r}, which is not "
                          "a file name in the manifest's own directory")
        if rows and r["frame"] <= rows[-1].frame:
            raise Invalid("bad_argument", f"{name}: {path} row {i} is frame {r['frame']}, not "
                          f"after frame {rows[-1].frame}: the frames are ascending, each once")
        row = FrameRow(r["frame"], path.parent / file, r["sha256"], r["signature"])
        try:
            data = row.path.read_bytes()
        except OSError as e:
            raise Invalid("bad_argument", f"{name}: frame {row.frame}'s file {row.path} cannot "
                          f"be read: {e}") from None
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise Invalid("bad_argument", f"{name}: frame {row.frame}'s file {row.path} no longer "
                          "matches the sha256 its row names, so it is not that frame")
        # THE SIGNATURE IS CHECKED, NOT TAKEN AT THE WRITER'S WORD: the control of a comparison
        # and a track by `signature` read these, so a row edited by hand would pass the one and
        # invent transitions in the other.
        try:
            picture = png.decode(data)
        except png.NotAPicture as e:
            raise Invalid("bad_argument", f"{name}: frame {row.frame}'s file {row.path}: "
                          f"{e}") from None
        if raster.picture_signature(picture) != row.signature:
            raise Invalid("bad_argument", f"{name}: frame {row.frame}'s row names signature "
                          f"{row.signature}, and its picture's is "
                          f"{raster.picture_signature(picture)}: the row is not that frame's")
        rows.append(row)
    return Manifest(path, rows)


def _signatures(series: Manifest, crop: Sequence[int] | None) -> list[str]:
    """Each frame's signature over `crop`: the manifest's own when there is no crop."""
    if crop is None:
        return [r.signature for r in series.rows]
    return [raster.picture_signature(series.picture(r), crop) for r in series.rows]


def resolved(series: Manifest, crop: Sequence[int] | None) -> list[int]:
    """The rectangle `crop` names on the series' pictures, judged inside them: the region a
    reply says it compared."""
    return list(raster.inside(crop, *series.size(), f"the pictures of {series.path}"))


def series_diff(a: Manifest, b: Manifest, crop: Sequence[int] | None) -> dict[str, Any]:
    """Two series paired by frame number, after each one's control: at least two of its frames
    differ over `crop`, or the series says nothing about the other; and at least one frame in
    common, or nothing was compared."""
    for name, one in (("a", a), ("b", b)):
        if len(set(_signatures(one, crop))) < 2:
            raise Invalid("control_silent", f"series `{name}` ({one.path}) never changes over "
                          f"{'the crop' if crop else 'its frames'}: a series that cannot differ "
                          "from itself says nothing about another one", series=name)
    by_a = {r.frame: r for r in a.rows}
    by_b = {r.frame: r for r in b.rows}
    paired = sorted(by_a.keys() & by_b.keys())
    if not paired:
        raise Invalid("control_silent", f"the series share no frame number ({a.rows[0].frame}.."
                      f"{a.rows[-1].frame} against {b.rows[0].frame}..{b.rows[-1].frame}): "
                      "nothing was compared, which is no verdict")
    first: tuple[int, dict[str, Any]] | None = None
    identical = differing = 0
    for frame in paired:
        ra, rb = by_a[frame], by_b[frame]
        if crop is None and ra.sha256 == rb.sha256:      # one file's bytes: one picture
            identical += 1
            continue
        got = raster.diff(a.picture(ra), b.picture(rb), crop)
        if got["differing_pixels"] == 0:
            identical += 1
            continue
        differing += 1
        if first is None:
            first = (frame, got)
    return {
        "pairs": len(paired), "identical": identical, "differing": differing,
        "first_differing": unavailable("every paired frame is identical") if first is None else {
            "frame": first[0], "differing_pixels": first[1]["differing_pixels"],
            "bbox": first[1]["bbox"]},
        "only_in_a": runs(sorted(by_a.keys() - by_b.keys())),
        "only_in_b": runs(sorted(by_b.keys() - by_a.keys())),
        "crop": resolved(a, crop),
    }


def runs(frames: list[int]) -> list[list[int]]:
    """Ascending frame numbers as inclusive `[first, last]` runs: a list that stays short when
    two series are offset by a block of frames, however long the block."""
    out: list[list[int]] = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


def region_track(series: Manifest, crop: Sequence[int] | None, measure: Measure,
                 ref: png.Raster | None, threshold: float, limit: int) -> dict[str, Any]:
    """Where `measure` over `crop` changes: `start` (the first frame and its value; none for
    `changed_pixels`, which has no frame before the first), then each transition, a change, as
    `[frame, value]`, and the gaps in frame numbers between consecutive transitions; the first
    `limit` in the reply and every one, with each frame's value, in a JSON file beside the
    manifest."""
    if measure not in MEASURES or limit < 1 or (measure == "match") != (ref is not None):
        raise ValueError(f"region_track({measure!r}, ref={ref is not None}, limit={limit})")
    start: list[Any] | dict[str, Any] = unavailable(
        "`changed_pixels` counts a change from the frame before, and the first frame has none")
    values: list[list[Any]]
    if measure == "signature":
        values = [[r.frame, s] for r, s in zip(series.rows, _signatures(series, crop),
                                                strict=True)]
        start = values[0]
        changes = [v for prev, v in zip(values, values[1:], strict=False) if v[1] != prev[1]]
    elif measure == "changed_pixels":
        values = []
        previous = series.picture(series.rows[0])
        for row in series.rows[1:]:
            current = series.picture(row)
            values.append([row.frame, raster.changed_pixels(previous, current, crop)])
            previous = current
        changes = [v for v in values if v[1] > 0]
    else:
        assert ref is not None                           # judged above; mypy cannot see it
        values = []
        for r in series.rows:
            fraction = raster.match_fraction(series.picture(r), ref, crop)
            values.append([r.frame, round(fraction, FRACTION_DIGITS), fraction >= threshold])
        start = [values[0][0], values[0][2]]
        changes = [[v[0], v[2]] for prev, v in zip(values, values[1:], strict=False)
                   if v[2] != prev[2]]
    if not changes:
        raise Invalid("control_silent", f"`{measure}` never changes over the "
                      f"{len(series.rows)} frames in {'the crop' if crop else 'the picture'}: "
                      "the crop missed what it was meant to watch, or the series shows "
                      "nothing moving there", frames=len(series.rows))
    gaps = [b[0] - a[0] for a, b in zip(changes, changes[1:], strict=False)]
    area = resolved(series, crop)
    doc = {"manifest": str(series.path), "measure": measure, "crop": area,
           "threshold": threshold, "values": values, "start": start, "transitions": changes,
           "gaps": gaps}
    path = fresh.numbered(series.path.parent, lambda n: f"track-{n}.json",
                          json.dumps(doc, indent=1).encode(), "the track")
    cut = len(changes) > limit
    return {"measure": measure, "crop": area, "frames": len(series.rows), "start": start,
            "transitions": changes[:limit], "gaps": gaps[:limit - 1],
            "transitions_total": len(changes), "path": str(path),
            **narrowing.omission(["transitions", "gaps"] if cut else [],
                                 f"the first {limit} of {len(changes)} transitions are here; every "
                                 "one, and each frame's value, is in the file at `path`, or "
                                 "raise `limit`")}
