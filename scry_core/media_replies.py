"""The reply models of the file tools both servers share (`scry_core.media_tools`), one per tool,
beside the envelope every reply carries: each server's `reply_schema.declare` takes them from here,
so the two never describe one tool two ways."""

from __future__ import annotations

from typing import Any

from scry_core.reply_schema import ReplyEnvelope


class ImageCompareReply(ReplyEnvelope, total=False):
    a: dict[str, Any] | str
    b: dict[str, Any] | str
    bbox: list[Any] | dict[str, Any]
    checksums: str
    crop: list[Any]
    differing: int | list[Any]
    differing_pixels: int
    differing_total: int
    dir: str
    extra: list[Any]
    extra_total: int
    first_differing: dict[str, Any]
    frames: int
    gaps: list[Any]
    height: int
    identical: int
    manifest: str
    matched: int
    max_delta: list[Any]
    measure: str
    missing: list[Any]
    missing_total: int
    only_in_a: list[Any]
    only_in_b: list[Any]
    pairs: int
    path: str
    shift: list[Any]
    start: list[Any] | dict[str, Any]
    tolerance: int
    transitions: list[Any]
    transitions_total: int
    width: int


class AudioCompareReply(ReplyEnvelope, total=False):
    a: str
    b: str
    aligned_by_samples: int
    bits: int
    channels: int
    envelope_correlation: float
    exact: bool
    length_delta_samples: int
    measures: list[Any]
    onset_delta_ms: float
    path: str
    pcm_sha256: str
    sample_rate_hz: int
    snr_db: float | dict[str, Any]
    window: list[Any]


# `class` is a word Python keeps for itself, so the field is declared by its JSON name here.
AudioCompareReply.__annotations__["class"] = str

#: Each shared file tool's reply model, by the tool's name.
MODELS: dict[str, type] = {"image_compare": ImageCompareReply, "audio_compare": AudioCompareReply}
