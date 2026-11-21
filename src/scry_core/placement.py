"""Where `place="auto"` puts the captions: the band, top or bottom, that shows less content
(a still score bar counts). Every `SAMPLE_S` a renderer samples each band (`points`), scores it
(`score`) and moves once the other band scored `MARGIN` lower `CONSECUTIVE` times (`step`).
The other renderers replay `placement_vectors.txt`; integers only, so all compute alike."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from importlib import resources
from typing import Literal

Band = Literal["top", "bottom"]
Point = tuple[int, int]

SAMPLE_S = 1.0
BAND_DIVISOR = 8
COLUMNS = 16
ROWS = 2
MARGIN = 4
CONSECUTIVE = 2
START: Band = "bottom"
VECTORS = "placement_vectors.txt"


def points(width: int, height: int) -> tuple[list[Point], list[Point]]:
    """The top band's and the bottom band's samples, row by row, at their cells' centres."""
    if width < 1 or height < 1:
        raise ValueError(f"a picture is at least 1 x 1; got {width} x {height}")
    band = max(1, height // BAND_DIVISOR)
    xs = [(2 * i + 1) * width // (2 * COLUMNS) for i in range(COLUMNS)]
    ys = [(2 * j + 1) * band // (2 * ROWS) for j in range(ROWS)]
    return ([(x, y) for y in ys for x in xs],
            [(x, height - band + y) for y in ys for x in xs])


def score(colours: Iterable[int]) -> int:
    """How many samples differ from the most common colour (a tie gives one count)."""
    counts = Counter(colours)
    return sum(counts.values()) - max(counts.values(), default=0)


def step(band: Band, streak: int, top: int, bottom: int) -> tuple[Band, int]:
    """The band and streak after one sample."""
    here, other = (top, bottom) if band == "top" else (bottom, top)
    if here - other < MARGIN:
        return band, 0
    if streak + 1 < CONSECUTIVE:
        return band, streak + 1
    return ("bottom" if band == "top" else "top"), 0


def walk(scores: Sequence[tuple[int, int]], band: Band = START) -> list[Band]:
    """The band after each `(top, bottom)` sample."""
    streak, out = 0, []
    for top, bottom in scores:
        band, streak = step(band, streak, top, bottom)
        out.append(band)
    return out


_POINTS_CASES = ((320, 200), (640, 480), (256, 224), (384, 224), (16, 8), (1, 1))
_SCORE_CASES: tuple[tuple[int, ...], ...] = (
    (0x000000,) * 32,
    (0x000000,) * 30 + (0xFFFFFF, 0xFF0000),
    (0x101010, 0x202020) * 16,
    tuple(range(32)),
    (0x00AA00,) * 20 + (0x0000AA,) * 12,
)
_WALK_CASES: tuple[tuple[Band, tuple[tuple[int, int], ...]], ...] = (
    ("bottom", ((0, 10), (0, 10), (0, 10))),
    ("bottom", ((0, 10), (9, 10), (0, 10), (0, 10))),
    ("bottom", ((6, 10), (7, 10), (6, 10))),
    ("bottom", ((7, 10), (6, 10))),
    ("top", ((20, 0), (20, 0), (0, 20), (0, 20))),
    ("top", ((0, 0), (32, 0), (0, 0), (32, 0))),
)


def _point_words(ps: list[Point]) -> str:
    return " ".join(f"{x},{y}" for x, y in ps)


def vectors_text() -> str:
    """The test vectors, one per line."""
    lines = [
        "# The placement rules of scry_core.placement, for a renderer in any language to replay.",
        "# Words are separated by one space; colours are 6 hex digits; points are x,y.",
        "# points <width> <height> top <x,y>... bottom <x,y>...",
        "# score <colour>... = <count>",
        "# walk <start band> <top>/<bottom>... = <band after each sample>...",
        f"constants band_divisor={BAND_DIVISOR} columns={COLUMNS} rows={ROWS} margin={MARGIN} "
        f"consecutive={CONSECUTIVE} start={START} sample_s={SAMPLE_S:g}",
    ]
    for w, h in _POINTS_CASES:
        top, bottom = points(w, h)
        lines.append(f"points {w} {h} top {_point_words(top)} bottom {_point_words(bottom)}")
    for colours in _SCORE_CASES:
        lines.append("score " + " ".join(f"{c:06X}" for c in colours) + f" = {score(colours)}")
    for band, scores in _WALK_CASES:
        lines.append(f"walk {band} " + " ".join(f"{t}/{b}" for t, b in scores) + " = "
                     + " ".join(walk(scores, band)))
    return "\n".join(lines) + "\n"


def vectors_file() -> str:
    """The committed vectors."""
    return resources.files("scry_core").joinpath(VECTORS).read_text(encoding="ascii")
