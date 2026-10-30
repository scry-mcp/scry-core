"""The reply models of the file tools both servers share (`scry_core.media_tools`), one per tool,
beside the envelope every reply carries: each server's `reply_schema.declare` takes them from here,
so the two never describe one tool two ways. A method's own fields come only with that method."""

from __future__ import annotations

from typing import Annotated, Any, Required

from typing_extensions import TypedDict

from scry_core.reply_contract import When
from scry_core.reply_schema import ReplyEnvelope


class CapturesFields(TypedDict, total=False):
    """What `captures` lists, whichever envelope a server's reply sits in."""

    captures: Required[list[Any]]


class PerformExportFields(TypedDict, total=False):
    """What `perform(export=)` answers: the replay file and what it holds."""

    checks: Required[int]
    cut: Required[dict[str, Any]]
    dropped: Required[list[Any]]
    dropped_total: Required[int]
    path: Required[str]
    replay: Required[str]
    steps: Required[int]


class ImageCompareReply(ReplyEnvelope, total=False):
    a: dict[str, Any] | str
    b: dict[str, Any] | str
    bbox: Annotated[list[Any] | dict[str, Any], When("image")]
    checksums: str
    crop: list[Any]
    differing: Annotated[int | list[Any], When("series", "golden")]
    differing_pixels: Annotated[int, When("image")]
    differing_total: Annotated[int, When("golden")]
    dir: str
    extra: Annotated[list[Any], When("golden")]
    extra_total: Annotated[int, When("golden")]
    first_differing: Annotated[dict[str, Any], When("series")]
    frames: Annotated[int, When("region")]
    gaps: Annotated[list[Any], When("region")]
    height: Annotated[int, When("image")]
    identical: Annotated[int, When("series")]
    manifest: str
    matched: Annotated[int, When("golden")]
    max_delta: Annotated[list[Any], When("image")]
    measure: str
    missing: Annotated[list[Any], When("golden")]
    missing_total: Annotated[int, When("golden")]
    only_in_a: Annotated[list[Any], When("series")]
    only_in_b: Annotated[list[Any], When("series")]
    pairs: Annotated[int, When("series")]
    path: Annotated[str, When("region")]
    shift: list[Any]
    start: Annotated[list[Any] | dict[str, Any], When("region")]
    tolerance: int
    transitions: Annotated[list[Any], When("region")]
    transitions_total: Annotated[int, When("region")]
    width: Annotated[int, When("image")]


class AudioCompareReply(ReplyEnvelope, total=False):
    a: str
    b: str
    aligned_by_samples: Annotated[int, When("diff")]
    bits: Annotated[int, When("measure")]
    channels: Annotated[int, When("measure")]
    envelope_correlation: Annotated[float, When("diff")]
    exact: Annotated[bool, When("diff")]
    length_delta_samples: Annotated[int, When("diff")]
    measures: Annotated[list[Any], When("measure")]
    onset_delta_ms: Annotated[float, When("diff")]
    path: str
    pcm_sha256: Annotated[str, When("measure")]
    sample_rate_hz: Annotated[int, When("measure")]
    snr_db: Annotated[float | dict[str, Any], When("diff")]
    window: list[Any]


# `class` is a word Python keeps for itself, so the field is declared by its JSON name here.
AudioCompareReply.__annotations__["class"] = Annotated[str, When("diff")]

#: Each shared file tool's reply model, by the tool's name.
MODELS: dict[str, type] = {"image_compare": ImageCompareReply, "audio_compare": AudioCompareReply}

#: Words a media tool's `Reply` text quotes that are no field of its reply: the per-channel
#: measures sit inside `measures`.
REPLY_WORDS: dict[str, tuple[str, ...]] = {
    "audio_compare": ("peak_dbfs", "rms_dbfs", "silent", "silence_spans", "onset_s",
                      "clipping_run", "clipped"),
}
