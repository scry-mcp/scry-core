"""`start`'s `overlay` argument: which layers presence draws, as both servers answer it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, NotRequired

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

Layer = Literal["edge", "pointer", "record"]
#: Drawing order, bottom first; `edge` is drawn whenever presence is.
LAYERS: tuple[Layer, ...] = ("edge", "pointer", "record")

ARGUMENT = ("Layers drawn over the presence edge, each on by default: `pointer` the guest's "
            "mouse pointer; `record` a blinking mark while it records video or audio. Ignored "
            "with `presence=false`.")


class Overlay(BaseModel):
    """The layers asked for; `edge` comes with `presence`."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    pointer: bool = True
    record: bool = True

    def asked(self) -> tuple[Layer, ...]:
        """The layers asked, in `LAYERS` order."""
        on = {"edge": True, "pointer": self.pointer, "record": self.record}
        return tuple(layer for layer in LAYERS if on[layer])


OVERLAY = Overlay()


class OverlayReply(TypedDict):
    """`layers`: drawn, in `LAYERS` order; `lacking`: per layer asked, why it cannot be;
    `notes`: per layer drawn, what it is drawn without. Each absent when empty."""

    layers: list[Layer]
    lacking: NotRequired[dict[Layer, str]]
    notes: NotRequired[dict[Layer, str]]


def reply(asked: Overlay, lacking: Mapping[Layer, str],
          notes: Mapping[Layer, str] | None = None) -> OverlayReply:
    """The reply's `overlay`: what `asked` asked, less what `lacking` says cannot be drawn, and
    `notes` for a layer drawn. A stray reason or note, or an empty text, is an error."""
    wanted = asked.asked()
    notes = notes or {}
    stray = sorted(set(lacking) - set(wanted))
    if stray:
        raise ValueError(f"a reason is given for a layer not asked: {', '.join(stray)}")
    if undrawn := sorted(set(notes) - {layer for layer in wanted if layer not in lacking}):
        raise ValueError(f"a note is given for a layer not drawn: {', '.join(undrawn)}")
    if any(not isinstance(why, str) or not why.strip() for why in (*lacking.values(),
                                                                    *notes.values())):
        raise ValueError("a layer that cannot be drawn, or is drawn with a note, says why")
    out: OverlayReply = {"layers": [layer for layer in wanted if layer not in lacking]}
    if lacking:
        out["lacking"] = {layer: lacking[layer] for layer in wanted if layer in lacking}
    if notes:
        out["notes"] = {layer: notes[layer] for layer in LAYERS if layer in notes}
    return out
