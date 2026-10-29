"""The views of a screen by pen, drawn and said alike on every server; each reads its own pens."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from scry_core.reply_contract import unavailable

MODES = ("render", "isolate", "histogram", "pixel")
INDEX_MODES = MODES[1:]
PENS_MAX = 64
# The pens asked for in one hue, the rest grey in a band without black or white: a dimmed dark
# pen would sink into the dark round it. Magenta: the hue a palette least often spends.
ISOLATE_COLOUR = (255, 0, 255)
GREY_LOW, GREY_HIGH = 0x30, 0xB0
LUMA_WEIGHTS = (299, 587, 114)     # BT.601's luma, in thousandths: they sum to 1000
# The pixel view's crop round the point, and its rings, with a border as wide so an edge keeps them.
PIXEL_CROP = 48
POINT_RINGS = ((255, 255, 255), (0, 0, 0))


def hex_colour(rgb: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def isolated(colour: tuple[int, int, int], chosen: bool) -> tuple[int, int, int]:
    if chosen:
        return ISOLATE_COLOUR
    luma = sum(w * v for w, v in zip(LUMA_WEIGHTS, colour, strict=True))
    grey = GREY_LOW + luma * (GREY_HIGH - GREY_LOW) // (255 * sum(LUMA_WEIGHTS))
    return (grey, grey, grey)


def isolation(values: Sequence[int], width: int, x0: int, y0: int,
              selected: set[int]) -> dict[str, Any]:
    """`isolate`'s fields for a `width`-wide window at (`x0`, `y0`), the box in screen units."""
    hits = [(i % width + x0, i // width + y0) for i, p in enumerate(values) if p in selected]
    return {"pixels": len(hits),
            "bbox": ([min(x for x, _ in hits), min(y for _, y in hits),
                      max(x for x, _ in hits), max(y for _, y in hits)] if hits
                     else unavailable("no pixel holds the pens asked for")),
            "pens": sorted(selected), "isolate_color": hex_colour(ISOLATE_COLOUR)}


def pixel_crop(x: int, y: int, width: int, height: int) -> list[int]:
    cw, ch = min(PIXEL_CROP, width), min(PIXEL_CROP, height)
    return [min(max(x - PIXEL_CROP // 2, 0), width - cw),
            min(max(y - PIXEL_CROP // 2, 0), height - ch), cw, ch]


def runs(pens: list[int]) -> list[str]:
    """Sorted pens as `0xa-0xf` runs, which a large palette's list would bury."""
    out: list[str] = []
    start = prev = None
    for p in [*pens, None]:
        if p is not None and prev is not None and p == prev + 1:
            prev = p
            continue
        if start is not None and prev is not None:
            out.append(f"{start:#x}" if start == prev else f"{start:#x}-{prev:#x}")
        start = prev = p
    return out
