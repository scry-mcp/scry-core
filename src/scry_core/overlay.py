"""`start`'s `overlay` argument, which layers a session's presence draws over the edge, and the
`overlay` field of `start`'s and `status`'s replies, the same on both servers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, NotRequired

from pydantic import BaseModel, ConfigDict
from typing_extensions import TypedDict

Place = Literal["top", "bottom", "auto"]
Layer = Literal["edge", "calls", "keys", "pointer", "pause"]
#: Drawing order, bottom first; `edge` is drawn whenever presence is.
LAYERS: tuple[Layer, ...] = ("edge", "pointer", "keys", "calls", "pause")

ARGUMENT = ("Layers drawn over the presence edge, each on by default: `calls` a caption "
            "naming each call and its arguments, abbreviated (paths by their last name); "
            "`keys` the keys or fields held down; `pointer` the guest's mouse pointer; `pause` "
            "a mark while the session holds the machine stopped. `place`: where the captions go, "
            "`top`, `bottom`, or `auto`, the band of the picture that shows less. Ignored with "
            "`presence=false`.")


class Overlay(BaseModel):
    """The layers asked for; `edge` is not one, it comes with `presence`."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    calls: bool = True
    keys: bool = True
    pointer: bool = True
    pause: bool = True
    place: Place = "auto"

    def asked(self) -> tuple[Layer, ...]:
        """The layers this asks to draw, in `LAYERS` order."""
        on = {"edge": True, "calls": self.calls, "keys": self.keys, "pointer": self.pointer,
              "pause": self.pause}
        return tuple(layer for layer in LAYERS if on[layer])


OVERLAY = Overlay()


class OverlayReply(TypedDict):
    """`layers`: drawn, in `LAYERS` order. `place`: in effect, `auto` resolved where a server
    cannot sample. `lacking`: per layer asked, why it cannot be drawn; absent when none."""

    layers: list[Layer]
    place: Place
    lacking: NotRequired[dict[Layer, str]]


def reply(asked: Overlay, lacking: Mapping[Layer, str], place: Place | None = None
          ) -> OverlayReply:
    """The reply's `overlay`: what `asked` asked, less what `lacking` says cannot be drawn.

    A reason for a layer not asked, or an empty reason, is a programmer's error."""
    wanted = asked.asked()
    stray = sorted(set(lacking) - set(wanted))
    if stray:
        raise ValueError(f"a reason is given for a layer not asked: {', '.join(stray)}")
    if any(not isinstance(why, str) or not why.strip() for why in lacking.values()):
        raise ValueError("a layer that cannot be drawn says why")
    out: OverlayReply = {"layers": [layer for layer in wanted if layer not in lacking],
                         "place": asked.place if place is None else place}
    if lacking:
        out["lacking"] = {layer: lacking[layer] for layer in wanted if layer in lacking}
    return out
