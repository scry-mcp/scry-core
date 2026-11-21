"""`scry_core.placement`: the sample grid of each band, a band's score, the move that waits for a
margin on consecutive samples, and the committed vectors the other renderers replay."""

from __future__ import annotations

import pytest

from scry_core import placement as pl


def test_each_band_is_sampled_on_a_grid_at_the_centre_of_its_cells() -> None:
    top, bottom = pl.points(320, 200)
    assert len(top) == len(bottom) == pl.COLUMNS * pl.ROWS
    band = 200 // pl.BAND_DIVISOR
    assert top[0] == (10, 6) and top[-1] == (310, 18)
    assert bottom[0] == (10, 200 - band + 6) and bottom[-1] == (310, 200 - band + 18)
    assert all(0 <= x < 320 and 0 <= y < band for x, y in top)
    assert all(0 <= x < 320 and 200 - band <= y < 200 for x, y in bottom)


def test_a_picture_too_small_for_a_band_still_samples_one_row() -> None:
    top, bottom = pl.points(1, 1)
    assert set(top) == set(bottom) == {(0, 0)}
    with pytest.raises(ValueError, match="at least 1 x 1"):
        pl.points(0, 10)


@pytest.mark.parametrize(("colours", "count"), [
    ([7] * 32, 0), ([7] * 30 + [1, 2], 2), ([1, 2] * 16, 16), ([], 0), (list(range(5)), 4)])
def test_a_band_scores_how_many_samples_differ_from_its_most_common_colour(
        colours: list[int], count: int) -> None:
    assert pl.score(colours) == count


@pytest.mark.parametrize(("scores", "bands"), [
    ([(0, 10)] * 3, ["bottom", "top", "top"]),
    ([(0, 10), (9, 10), (0, 10), (0, 10)], ["bottom", "bottom", "bottom", "top"]),
    ([(10 - pl.MARGIN + 1, 10)] * 4, ["bottom"] * 4),
    ([(10 - pl.MARGIN, 10)] * 2, ["bottom", "top"]),
])
def test_the_captions_move_only_on_a_margin_held_for_consecutive_samples(
        scores: list[tuple[int, int]], bands: list[pl.Band]) -> None:
    assert pl.walk(scores) == bands


def test_the_move_is_the_same_rule_from_the_top() -> None:
    assert pl.walk([(20, 0), (20, 0), (0, 20), (0, 20)], "top") == [
        "top", "bottom", "bottom", "top"]


def test_the_committed_vectors_are_the_ones_these_rules_write() -> None:
    assert pl.vectors_file() == pl.vectors_text(), (
        "regenerate src/scry_core/placement_vectors.txt from placement.vectors_text()")


def test_the_vectors_replay_from_their_text_alone() -> None:
    """What a renderer in another language does: parse the words, recompute, compare."""
    seen = set()
    for line in pl.vectors_file().splitlines():
        words = line.split(" ")
        seen.add(words[0])
        if words[0] == "points":
            w, h = int(words[1]), int(words[2])
            cut = words.index("bottom")
            top = [tuple(map(int, p.split(","))) for p in words[4:cut]]
            bottom = [tuple(map(int, p.split(","))) for p in words[cut + 1:]]
            assert (top, bottom) == pl.points(w, h)
        elif words[0] == "score":
            cut = words.index("=")
            assert pl.score(int(c, 16) for c in words[1:cut]) == int(words[cut + 1])
        elif words[0] == "walk":
            cut = words.index("=")
            pairs = [tuple(map(int, s.split("/"))) for s in words[2:cut]]
            assert pl.walk([(t, b) for t, b in pairs], words[1]) == words[cut + 1:]  # type: ignore[arg-type]
    assert {"constants", "points", "score", "walk"} <= seen
    assert all(ord(c) < 128 for c in pl.vectors_file())
