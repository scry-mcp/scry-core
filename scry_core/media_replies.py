"""The reply models of the file tools both servers share (`scry_core.media_tools`), one per tool,
beside the envelope every reply carries: each server's `reply_schema.declare` takes them from here,
so the two never describe one tool two ways."""

from __future__ import annotations

from typing import Any

from scry_core.reply_schema import ReplyEnvelope


class ImageDiffReply(ReplyEnvelope, total=False):
    a: dict[str, Any]
    b: dict[str, Any]
    bbox: list[Any] | dict[str, Any]
    crop: list[Any]
    differing_pixels: int
    height: int
    max_delta: list[Any]
    shift: list[Any]
    tolerance: int
    width: int


class SeriesDiffReply(ReplyEnvelope, total=False):
    a: str
    b: str
    crop: list[Any]
    differing: int
    first_differing: dict[str, Any]
    identical: int
    only_in_a: list[Any]
    only_in_b: list[Any]
    pairs: int


class RegionTrackReply(ReplyEnvelope, total=False):
    crop: list[Any]
    frames: int
    gaps: list[Any]
    manifest: str
    measure: str
    path: str
    start: list[Any] | dict[str, Any]
    transitions: list[Any]
    transitions_total: int


class GoldenCheckReply(ReplyEnvelope, total=False):
    checksums: str
    differing: list[Any]
    differing_total: int
    dir: str
    extra: list[Any]
    extra_total: int
    manifest: str
    matched: int
    missing: list[Any]
    missing_total: int


class AudioMeasureReply(ReplyEnvelope, total=False):
    bits: int
    channels: int
    measures: list[Any]
    path: str
    pcm_sha256: str
    sample_rate_hz: int
    window: list[Any]


class AudioDiffReply(ReplyEnvelope, total=False):
    a: str
    b: str
    aligned_by_samples: int
    envelope_correlation: float
    exact: bool
    length_delta_samples: int
    onset_delta_ms: float
    snr_db: float | dict[str, Any]


# `class` is a word Python keeps for itself, so the field is declared by its JSON name here.
AudioDiffReply.__annotations__["class"] = str

#: Each shared file tool's reply model, by the tool's name.
MODELS: dict[str, type] = {
    "image_diff": ImageDiffReply, "series_diff": SeriesDiffReply,
    "region_track": RegionTrackReply, "golden_check": GoldenCheckReply,
    "audio_measure": AudioMeasureReply, "audio_diff": AudioDiffReply,
}
