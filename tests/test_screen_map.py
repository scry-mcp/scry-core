"""Screen maps: the file, the two layers, one read per identification, a control named against
the identification it came from."""
from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from scry_core import raster, screen_map
from scry_core.reply_contract import Invalid
from scry_core.screen_map import Grid, Maps

W, H = 8, 4


def _grid(lit: set[tuple[int, int]] = frozenset(), kind: raster.Kind = "pixel",  # type: ignore[assignment]
          width: int = W, height: int = H) -> Grid:
    """A black `width` x `height` pixel screen with the pixels in `lit` white."""
    px = bytearray(3 * width * height)
    for x, y in lit:
        px[(y * width + x) * 3:(y * width + x) * 3 + 3] = b"\xff\xff\xff"
    if kind == "text":
        return Grid("text", width, height, bytes(7 * width * height))
    return Grid(kind, width, height, bytes(px))


class Reads:
    """A screen reader that counts its reads, the instrument of the one-read rule, and records
    whether each asked for the palette's indices."""

    def __init__(self, grid: Grid) -> None:
        self.grid, self.count, self.asked = grid, 0, list[bool]()

    def __call__(self, indices: bool = False) -> Grid:
        self.count += 1
        self.asked.append(indices)
        return self.grid


TITLE = _grid({(0, 0)})            # pixel (0, 0) lit: the title screen
PLAY = _grid({(7, 3)})             # pixel (7, 3) lit: the play screen


def _sig(grid: Grid, crop: list[int]) -> str:
    return raster.signature(grid.kind, grid.width, grid.height, grid.cells, crop)


def _doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format": "scry-screen-map/1", "application": "demo", "mode": "verified",
        "screens": [
            {"name": "title", "kind": "pixel", "size": [W, H],
             "match": [{"crop": [0, 0, 2, 2], "signature": _sig(TITLE, [0, 0, 2, 2])}],
             "controls": [{"name": "start", "rect": [2, 1, 4, 2]}]},
            {"name": "play", "kind": "pixel", "size": [W, H],
             "match": [{"crop": [6, 2, 2, 2], "signature": _sig(PLAY, [6, 2, 2, 2])},
                       {"crop": [0, 0, 2, 2], "signature": _sig(PLAY, [0, 0, 2, 2])}],
             "controls": [{"name": "paddle", "rect": [0, 3, 3, 1]},
                          {"name": "quit", "rect": [7, 0, 1, 1]}]},
        ]}
    doc.update(over)
    return doc


def _file(tmp_path: Path, doc: object, name: str = "demo.screen-map.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_a_loaded_map_finds_the_screen_shown_with_its_controls(tmp_path: Path) -> None:
    maps = Maps()
    got = maps.load(_file(tmp_path, _doc()))
    assert got == {"path": str(tmp_path / "demo.screen-map.json"), "application": "demo",
                   "mode": "verified", "screens": 2, "controls": 3}
    found = maps.find(Reads(PLAY), stop=7)
    assert found == {"matched": True, "screen": "play", "layer": "file", "kind": "pixel",
                     "size": [W, H],
                     "controls": [{"name": "paddle", "rect": [0, 3, 3, 1], "centre": [1, 3]},
                                  {"name": "quit", "rect": [7, 0, 1, 1], "centre": [7, 0]}]}
    assert maps.find(Reads(TITLE), stop=8)["screen"] == "title"


def test_one_read_per_identification_and_each_distinct_crop_signed_once(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    signed: list[Any] = []
    real = raster.signature

    def counting(*a: Any) -> str:
        signed.append(a[-1])
        return real(*a)
    monkeypatch.setattr(raster, "signature", counting)
    reads = Reads(PLAY)
    maps.find(reads, stop=1)
    assert reads.count == 1
    # title's [0, 0, 2, 2] fails, play's [6, 2, 2, 2] holds, play's [0, 0, 2, 2] is the one
    # already signed for title
    assert signed == [(0, 0, 2, 2), (6, 2, 2, 2)]


def test_a_screen_of_another_kind_or_size_is_never_hashed(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    signed: list[Any] = []
    def counting(*a: Any) -> str:
        signed.append(a)
        return "0" * 16
    monkeypatch.setattr(raster, "signature", counting)
    got = maps.find(Reads(_grid(width=9)), stop=1)
    assert got == {"matched": False, "kind": "pixel", "size": [9, H], "screens_tried": 0,
                   "screens_unjudged": 0, "screens_mapped": 2} and "screen" not in got
    assert signed == []
    assert maps.find(Reads(_grid(kind="text")), stop=1)["screens_tried"] == 0
    maps.find(Reads(PLAY), stop=1)
    assert signed, "the control: a screen of the map's size is hashed"


def test_no_match_says_how_many_were_tried_and_forgets_the_last_screen(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.find(Reads(PLAY), stop=1)
    got = maps.find(Reads(_grid()), stop=2)
    assert got["matched"] is False and got["screens_tried"] == 2 and "screen" not in got
    with pytest.raises(Invalid, match="no screen is identified") as e:
        maps.target("paddle")
    assert e.value.code == "needs_call"


def test_the_session_layer_is_tried_first_and_shadows_the_file(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    added = maps.add("title", [[6, 2, 2, 2]], [{"name": "go", "rect": [0, 0, 1, 1]}],
                     Reads(PLAY))
    assert added == {"screen": "title", "kind": "pixel", "size": [W, H], "cells": "rgb",
                     "match": [{"crop": [6, 2, 2, 2], "signature": _sig(PLAY, [6, 2, 2, 2])}],
                     "controls": 1, "replaced": False, "shadows_file": True}
    got = maps.find(Reads(PLAY), stop=3)
    assert (got["screen"], got["layer"], got["controls"][0]["name"]) == ("title", "session", "go")
    # the file's own title screen is not tried while the session's shadows it
    assert maps.find(Reads(TITLE), stop=4)["matched"] is False


def test_adding_a_screen_again_replaces_it(tmp_path: Path) -> None:
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], None, Reads(TITLE))
    again = maps.add("a", [[7, 3, 1, 1]], [], Reads(PLAY))
    assert again["replaced"] is True and again["shadows_file"] is False
    assert maps.find(Reads(PLAY), stop=1)["screen"] == "a"


def test_a_start_empties_the_session_layer_and_keeps_the_file(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.add("extra", [[0, 0, 1, 1]], [], Reads(_grid()))
    maps.find(Reads(PLAY), stop=1)
    maps.started()
    assert maps.session == {} and maps.found is None and set(maps.file) == {"title", "play"}


def test_find_with_nothing_mapped_asks_for_a_map() -> None:
    reads = Reads(PLAY)
    with pytest.raises(Invalid, match="no screen is mapped") as e:
        Maps().find(reads, stop=1)
    assert e.value.code == "needs_call" and reads.count == 0


def test_a_control_is_named_against_the_identification_it_came_from(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    with pytest.raises(Invalid, match="screen_map_find` at a stop first") as e:
        maps.target("paddle")
    assert e.value.code == "needs_call"
    maps.find(Reads(PLAY), stop=12)
    assert maps.target("paddle") == {"target": "paddle", "centre": [1, 3], "screen": "play",
                                     "kind": "pixel", "size": (W, H), "identified_at_stop": 12}
    maps.find(Reads(PLAY), stop=None)
    assert maps.target("paddle")["identified_at_stop"]["available"] is False, (
        "a stop nobody could name")
    with pytest.raises(Invalid, match=r"has no such control; its controls: paddle, quit") as e:
        maps.target("start")
    assert e.value.code == "unknown_ref"


def _anchored(mode: str) -> dict[str, Any]:
    doc = _doc(mode=mode)
    doc["screens"][0]["anchor"] = "DrawTitle"
    doc["screens"][1]["anchor"] = "DrawPlay"
    return doc


def test_a_consolidated_screen_is_entered_by_its_anchor_with_no_read(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("consolidated")))
    assert maps.anchor("play") == "DrawPlay"
    reads = Reads(TITLE)
    assert maps.arrived("play", reads, stop=4) == {"screen": "play", "layer": "file",
                                                   "mode": "consolidated", "judged": False}
    assert reads.count == 0, "a consolidated screen is taken as shown"
    assert maps.target("paddle")["identified_at_stop"] == 4
    assert maps.find(Reads(TITLE), stop=5)["screen"] == "title", "the hash, when asked for"


def test_a_verified_screen_is_judged_when_its_anchor_is_reached(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("verified")))
    reads = Reads(PLAY)
    assert maps.arrived("play", reads, stop=4)["judged"] is True and reads.count == 1
    assert maps.target("quit")["screen"] == "play"
    with pytest.raises(Invalid, match="no longer holds") as e:
        maps.arrived("play", Reads(TITLE), stop=5)
    assert e.value.code == "stale_map"
    with pytest.raises(Invalid, match="no screen is identified"):
        maps.target("quit")


def test_the_anchor_of_an_unknown_or_unanchored_screen_is_refused(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    with pytest.raises(Invalid, match="no screen 'menu'; mapped: title, play") as e:
        maps.anchor("menu")
    assert e.value.code == "unknown_ref"
    with pytest.raises(Invalid, match="screen 'play' names no `anchor`") as e:
        maps.anchor("play")
    assert e.value.code == "needs_call"


def test_a_session_screen_shadows_the_files_anchor_too(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("consolidated")))
    maps.add("play", [[6, 2, 2, 2]], [], Reads(PLAY), anchor="DrawPlayAgain")
    assert maps.anchor("play") == "DrawPlayAgain"
    assert maps.anchor("title") == "DrawTitle"


def test_a_consolidated_map_refuses_a_screen_with_no_anchor_and_saves_one_with(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("consolidated")))
    with pytest.raises(Invalid, match="`anchor`") as e:
        maps.add("extra", [[0, 0, 1, 1]], [], Reads(TITLE))
    assert e.value.code == "bad_argument" and "consolidated" in str(e.value)
    assert "extra" not in maps.session, "a refused add left a screen behind"
    added = maps.add("extra", [[0, 0, 1, 1]], [], Reads(TITLE), anchor="DrawExtra")
    assert added["anchor"] == "DrawExtra"
    out = tmp_path / "out.screen-map.json"
    maps.save(str(out), False)
    names = {s["name"]: s.get("anchor") for s in json.loads(out.read_text())["screens"]}
    assert names["extra"] == "DrawExtra"


def test_saving_a_consolidated_map_with_an_unanchored_session_screen_names_the_remedy(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("consolidated")))
    maps.session["loose"] = dataclasses.replace(maps.file["play"], name="loose", anchor="")
    with pytest.raises(Invalid, match="screen 'loose' has no `anchor`.*`add` it again with one"):
        maps.save(str(tmp_path / "out.screen-map.json"), False)


def test_a_verified_map_takes_an_anchor_on_add_and_keeps_it_out_of_the_reply_without_one() -> None:
    maps = Maps()
    assert "anchor" not in maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    assert maps.add("b", [[0, 0, 1, 1]], [], Reads(TITLE), anchor="DrawB")["anchor"] == "DrawB"


def test_a_control_on_a_frame_by_frame_run_is_refused_naming_the_screen() -> None:
    screen_map.check_frame_run("play", "")
    with pytest.raises(Invalid, match="screen 'play' names no anchor") as e:
        screen_map.check_frame_run("play", "frame")
    assert e.value.code == "bad_argument" and "`control`" in str(e.value)


def test_a_run_to_with_no_control_is_refused_once_for_both_servers() -> None:
    plain = screen_map.no_control()
    assert plain.code == "bad_argument" and "no control is named" in str(plain)
    assert "breakpoints never firing" in str(plain), "the reason, not only the rule"
    hinted = screen_map.no_control("declare one with `breakpoint_at(ref, role=\"control\")`")
    assert str(hinted).startswith(str(plain)) and "role=" in str(hinted)


def test_check_add_judges_the_anchor_before_any_read() -> None:
    screen_map.check_add("a", [[0, 0, 1, 1]], None, "", "DrawA")
    with pytest.raises(Invalid, match="`anchor` is a symbol or an address"):
        screen_map.check_add("a", [[0, 0, 1, 1]], None, "", 7)
    with pytest.raises(Invalid, match="no space at either end"):
        screen_map.check_add("a", [[0, 0, 1, 1]], None, "", " bad")


def test_save_keeps_the_maps_mode_and_a_map_begun_here_is_verified(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("consolidated")))
    out = tmp_path / "out" / "demo.screen-map.json"
    out.parent.mkdir()
    maps.save(str(out), False)
    doc = json.loads(out.read_text())
    assert doc["mode"] == "consolidated" and doc["screens"][1]["anchor"] == "DrawPlay"
    fresh = Maps()
    fresh.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    mine = tmp_path / "mine.screen-map.json"
    fresh.save(str(mine), False)
    assert json.loads(mine.read_text())["mode"] == "verified"
    assert "anchor" not in json.loads(mine.read_text())["screens"][0]


def _doubled(grid: Grid, margin_y: int) -> Grid:
    """`grid` drawn twice as large with `margin_y` black rows above and below: a PC port's
    640x480 screen showing the arcade's 320x200 picture."""
    width, height = grid.width * 2, grid.height * 2 + 2 * margin_y
    out, idx = bytearray(3 * width * height), bytearray(width * height)
    for y in range(height):
        for x in range(width):
            sy = (y - margin_y) // 2
            if 0 <= sy < grid.height:
                src = sy * grid.width + x // 2
                out[(y * width + x) * 3:(y * width + x) * 3 + 3] = grid.cells[src * 3:src * 3 + 3]
                idx[y * width + x] = 0 if grid.indices is None else grid.indices[src]
    return Grid("pixel", width, height, bytes(out),
                None if grid.indices is None else bytes(idx))


def test_a_program_shown_doubled_with_a_margin_is_found_in_its_own_units(tmp_path: Path) -> None:
    """Speed Fight's PC port shows the arcade's picture doubled into 640x480, 40 rows of margin
    above and below: one map in the program's units knows both, and aims in the machine's."""
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    pc = Maps()
    assert pc.load(_file(tmp_path, _doc()), scale=2, margin=[0, 1])["screens"] == 2
    shown = _doubled(PLAY, 1)
    assert (shown.width, shown.height) == (2 * W, 2 * H + 2)
    got = pc.find(Reads(shown), stop=3)
    assert got["screen"] == "play" and got["size"] == [W, H], "the program's units"
    assert maps.find(Reads(PLAY), stop=3)["screen"] == "play"
    # paddle [0, 3, 3, 1]: centre (1, 3) in the program; on the doubled screen its block is
    # x 2..3 and y 7..8 (a row of margin), aimed at the block's lower-right middle
    assert pc.target("paddle")["centre"] == [3, 8]
    assert pc.target("paddle")["size"] == (2 * W, 2 * H + 2)
    assert pc.find(Reads(PLAY), stop=4)["matched"] is False, "the undoubled screen is another"
    added = pc.add("again", [[6, 2, 2, 2]], [], Reads(shown))
    assert added["size"] == [W, H]
    assert added["match"][0]["signature"] == _sig(PLAY, [6, 2, 2, 2])


def _doubled_in_x(grid: Grid, margin_x: int) -> Grid:
    """`grid` drawn twice as large with `margin_x` black columns left and right."""
    width, height = grid.width * 2 + 2 * margin_x, grid.height * 2
    out = bytearray(3 * width * height)
    for y in range(height):
        for x in range(width):
            sx = (x - margin_x) // 2
            if 0 <= sx < grid.width:
                src = (y // 2) * grid.width + sx
                out[(y * width + x) * 3:(y * width + x) * 3 + 3] = grid.cells[src * 3:src * 3 + 3]
    return Grid("pixel", width, height, bytes(out))


def test_a_verified_screen_is_judged_at_its_anchor_through_a_view_with_an_x_margin(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("verified")), scale=2, margin=[2, 0])
    shown = _doubled_in_x(PLAY, 2)
    assert (shown.width, shown.height) == (2 * W + 4, 2 * H)
    assert maps.arrived("play", Reads(shown), stop=7)["judged"] is True
    assert maps.target("quit")["size"] == (2 * W + 4, 2 * H)
    with pytest.raises(Invalid, match="no longer holds") as e:
        maps.arrived("play", Reads(_doubled_in_x(TITLE, 2)), stop=8)
    assert e.value.code == "stale_map"


def test_a_screen_the_view_does_not_fit_is_said_so_not_unmatched(tmp_path: Path) -> None:
    pc = Maps()
    pc.load(_file(tmp_path, _doc()), scale=2, margin=[0, 1])
    got = pc.find(Reads(_grid(width=2 * W, height=2 * H + 1)), stop=1)
    assert got["matched"] is False and got["view_fits"] is False
    assert "does not fit the view" in screen_map.find_line({}, got)


@pytest.mark.parametrize("scale, margin, said", [
    (0, [0, 0], "`scale` is a whole number 1..8"),
    (9, [0, 0], "`scale` is a whole number 1..8"),
    (2, [-1, 0], "`margin` is [x, y]"),
    (2, [0], "`margin` is [x, y]"),
])
def test_a_view_a_map_cannot_be_seen_through_is_refused(tmp_path: Path, scale: int,
                                                        margin: Any, said: str) -> None:
    with pytest.raises(Invalid, match=_re(said)) as e:
        Maps().load(_file(tmp_path, _doc()), scale=scale, margin=margin)
    assert e.value.code == "bad_argument"


@pytest.mark.parametrize("unit", [1, 3])
@pytest.mark.parametrize("scale, margin", [(1, (0, 0)), (1, (2, 1)), (2, (0, 0)), (3, (1, 2))])
def test_a_view_samples_the_top_left_unit_of_each_block(unit: int, scale: int,
                                                        margin: tuple[int, int]) -> None:
    width, height = 4 * scale + 2 * margin[0], 3 * scale + 2 * margin[1]
    cells = bytes((i * 7 + 1) % 251 for i in range(width * height * unit))
    indices = bytes(i % 256 for i in range(width * height))
    got = screen_map.View(scale, margin).through(
        Grid("pixel", width, height, cells, indices))
    assert (got.width, got.height) == (4, 3)

    def pick(data: bytes, size: int, x: int, y: int) -> bytes:
        at = ((margin[1] + y * scale) * width + margin[0] + x * scale) * size
        return data[at:at + size]
    assert got.cells == b"".join(pick(cells, unit, x, y) for y in range(3) for x in range(4))
    assert got.indices == b"".join(pick(indices, 1, x, y) for y in range(3) for x in range(4))


def test_a_screen_added_through_a_view_it_does_not_fit_is_the_machines_answer() -> None:
    maps = Maps()
    maps.view = screen_map.View(2, (0, 1))
    with pytest.raises(Invalid, match="does not fit") as e:
        maps.add("odd", [[0, 0, 1, 1]], [], Reads(_grid(width=7, height=4)))
    assert e.value.code == "unexpected_answer"


def test_save_promotes_the_session_over_the_file_and_becomes_the_file_layer(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.add("title", [[6, 2, 2, 2]], [], Reads(PLAY))
    maps.add("over", [[0, 0, 1, 1]], [{"name": "x", "rect": [0, 0, 8, 4]}], Reads(TITLE))
    out = tmp_path / "game.screen-map.json"
    got = maps.save(str(out), False)
    assert got == {"path": str(out), "application": "game", "mode": "verified", "screens": 3,
                   "controls": 3, "promoted": ["over", "title"]}
    doc = json.loads(out.read_text())
    assert [s["name"] for s in doc["screens"]] == ["title", "play", "over"]
    assert doc["screens"][0]["match"][0]["crop"] == [6, 2, 2, 2]
    assert maps.session == {} and maps.find(Reads(PLAY), stop=1)["layer"] == "file"
    # the file a save wrote is a map a load takes back whole
    again = Maps()
    assert again.load(str(out))["screens"] == 3


def test_save_refuses_a_file_already_there_unless_told_and_then_replaces_it(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    out = tmp_path / "demo.screen-map.json"
    out.write_text("keep")
    with pytest.raises(Invalid, match="already there") as e:
        maps.save(str(out), False)
    assert e.value.code == "bad_argument" and out.read_text() == "keep"
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    maps.save(str(out), True)
    assert json.loads(out.read_text())["screens"][0]["name"] == "a"
    assert [p.name for p in tmp_path.iterdir()] == [out.name], "no temporary file left"


def test_save_with_nothing_mapped_asks_for_a_screen(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="no screen is mapped") as e:
        Maps().save(str(tmp_path / "x.screen-map.json"), False)
    assert e.value.code == "needs_call"
    assert not (tmp_path / "x.screen-map.json").exists()


@pytest.mark.parametrize("name", ["demo.json", "x/../demo.map", ".screen-map.json",
                                  "rel.screen-map.json"])
def test_a_map_path_is_absolute_and_named_by_its_application(tmp_path: Path, name: str) -> None:
    value = name if name.startswith("rel") else str(tmp_path / name)
    with pytest.raises(Invalid) as e:
        Maps().load(value)
    assert e.value.code == "bad_argument"


def test_a_map_path_from_home_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _file(tmp_path, _doc())
    assert Maps().load("~/demo.screen-map.json")["screens"] == 2


def test_a_missing_or_unreadable_file_is_refused_naming_it(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="no map file at"):
        Maps().load(str(tmp_path / "none.screen-map.json"))
    bad = tmp_path / "bad.screen-map.json"
    bad.write_text("{not json")
    with pytest.raises(Invalid, match="is not a JSON map"):
        Maps().load(str(bad))


def _broken(path: list[Any], value: Any) -> Any:
    doc: Any = _doc()
    target = doc
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return doc


@pytest.mark.parametrize("path, value, said", [
    (["format"], "scry-screen-map/2", "is not a scry-screen-map/1 map"),
    (["application"], "", "`application` is a name"),
    (["extra"], 1, "carries ['extra']"),
    (["screens"], [], "`screens` is a list of at least one"),
    (["screens", 0, "name"], "play", "named 'play' again"),
    (["screens", 0, "name"], " pad", "`name` is a name"),
    (["screens", 0, "kind"], "vector", "`kind` is `text` or `pixel`"),
    (["screens", 0, "size"], [8, 0], "`size` is [width, height]"),
    (["screens", 0, "match"], [], "`match` is a list of 1..16"),
    (["screens", 0, "match", 0, "crop"], [7, 0, 2, 1], "match 0 crop [7, 0] + 2x1 leaves"),
    (["screens", 0, "match", 0, "signature"], "ABC", "16 lowercase hex"),
    (["screens", 0, "match", 0, "why"], 1, "carries ['why']"),
    (["screens", 0, "controls", 0, "rect"], [0, 0, 9, 1], "control 'start' rect"),
    (["screens", 0, "controls", 0, "name"], "", "`name` is a name"),
    (["screens", 1, "controls", 1, "name"], "paddle", "control 'paddle' is named twice"),
    (["screens", 0, "controls"], "start", "`controls` is a list"),
    (["screens", 0, "size"], KeyError, "`size` is [width, height]"),
    (["mode"], "draft", "`mode` is `verified` or `consolidated`"),
    (["mode"], KeyError, "`mode` is `verified` or `consolidated`"),
    (["screens", 0, "anchor"], "", "`anchor` is a symbol or an address"),
    (["mode"], "consolidated", "entered by theirs: name one in the file"),
])
def test_a_broken_map_is_refused_whole_naming_its_first_fault(
        tmp_path: Path, path: list[Any], value: Any, said: str) -> None:
    maps = Maps()
    (tmp_path / "ok").mkdir()
    maps.load(_file(tmp_path / "ok", _doc()))
    with pytest.raises(Invalid, match=_re(said)) as e:
        maps.load(_file(tmp_path, _broken(path, value)))
    assert e.value.code == "bad_argument"
    assert maps.application == "demo" and set(maps.file) == {"title", "play"}, \
        "a refused file leaves the loaded one as it was"


def _re(text: str) -> str:
    import re
    return re.escape(text)


def test_a_map_bigger_than_its_limits_is_refused(tmp_path: Path) -> None:
    many = _doc(screens=[{**_doc()["screens"][0], "name": f"s{i}"}
                         for i in range(screen_map.SCREENS_MAX + 1)])
    with pytest.raises(Invalid, match=f"{screen_map.SCREENS_MAX + 1} screens"):
        Maps().load(_file(tmp_path, many))


@pytest.mark.parametrize("screen, match, controls, said", [
    ("", [[0, 0, 1, 1]], None, "screen='' is a name"),
    ("a", [], None, "match is a list of 1..16"),
    ("a", [[0, 0, 0, 1]], None, "match 0="),
    ("a", [[0, 0, 1, 1]], "x", "controls is a list"),
])
def test_map_add_is_judged_before_the_machine(screen: Any, match: Any, controls: Any,
                                              said: str) -> None:
    with pytest.raises(Invalid, match=_re(said)) as e:
        screen_map.check_add(screen, match, controls)
    assert e.value.code == "bad_argument"


def test_map_add_refuses_a_crop_off_the_screen_it_read() -> None:
    maps = Maps()
    with pytest.raises(Invalid, match=r"leaves screen 'a' \(8x4\)"):
        maps.add("a", [[0, 0, 9, 1]], [], Reads(TITLE))
    assert maps.session == {}


def test_the_summary_lines() -> None:
    assert screen_map.load_line({}, {"screens": 1, "controls": 2, "application": "demo"}) == \
        "1 screen, 2 controls of demo"
    assert screen_map.find_line({}, {"matched": True, "screen": "play", "layer": "file",
                                     "controls": [{}]}) == "screen_map_find: play (file), 1 control"
    assert screen_map.find_line({}, {"matched": False, "kind": "text", "size": [80, 25],
                                     "screens_tried": 0, "screens_mapped": 3}) == (
        "screen_map_find: no screen matched the text 80x25 screen (3 screens mapped, 0 of that "
        "kind and size)")
    assert screen_map.add_line({}, {"screen": "a", "kind": "pixel", "size": [8, 4],
                                    "match": [{}], "controls": 0, "shadows_file": True}) == (
        "a (pixel 8x4), 1 region, 0 controls, shadowing the file's")
    assert screen_map.save_line({}, {"screens": 2, "path": "/x/demo.screen-map.json",
                                     "promoted": ["a"]}) == (
        "2 screens to demo.screen-map.json, 1 promoted from the session")


def test_the_odd_shapes_of_a_map_file_are_refused_by_name(tmp_path: Path) -> None:
    for broken, said in [
        (_doc(screens=["play"]), "screen 0 is not an object"),
        (_broken(["screens", 0, "match"], ["x"]), "match 0 is not an object"),
        (_broken(["screens", 0, "controls"], ["x"]), "control 0 is not an object"),
    ]:
        with pytest.raises(Invalid, match=_re(said)):
            Maps().load(_file(tmp_path, broken))
    folder = tmp_path / "dir.screen-map.json"
    folder.mkdir()
    with pytest.raises(Invalid, match="no map file at"):
        Maps().load(str(folder))


def test_map_add_and_save_refuse_what_their_arguments_cannot_be(tmp_path: Path) -> None:
    maps = Maps()
    with pytest.raises(Invalid, match="match is a list of at least one crop"):
        maps.add("a", "0,0,1,1", [], Reads(TITLE))
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    with pytest.raises(Invalid, match="overwrite is true or false; got 'yes'"):
        maps.save(str(tmp_path / "x.screen-map.json"), "yes")  # type: ignore[arg-type]
    taken = tmp_path / "dir.screen-map.json"
    taken.mkdir()
    with pytest.raises(Invalid, match="is a directory"):
        maps.save(str(taken), True)


def test_a_save_over_a_file_that_fails_leaves_no_temporary(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    out = tmp_path / "demo.screen-map.json"
    out.write_text("keep")

    def refuse(*_a: Any) -> None:
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(Invalid, match="could not be written: .*Permission denied"):
        maps.save(str(out), True)
    assert out.read_text() == "keep" and [p.name for p in tmp_path.iterdir()] == [out.name]


def test_map_add_stops_at_the_most_screens_a_map_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screen_map, "SCREENS_MAX", 2)
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    maps.add("b", [[0, 0, 1, 1]], [], Reads(TITLE))
    with pytest.raises(Invalid, match="the map holds 2 screens"):
        maps.add("c", [[0, 0, 1, 1]], [], Reads(TITLE))
    assert maps.add("b", [[0, 0, 1, 1]], [], Reads(TITLE))["replaced"] is True


def test_the_shape_checks_a_server_runs_before_the_machine(tmp_path: Path) -> None:
    screen_map.check_path("path", str(tmp_path / "demo.screen-map.json"))
    with pytest.raises(Invalid, match="is not named"):
        screen_map.check_path("path", str(tmp_path / "demo.json"))
    screen_map.check_add("a", [[0, 0, 1, 1]], [{"name": "x", "rect": [0, 0, 1, 1]}])
    screen_map.check_add("a", [[0, 0, 1, 1]], None)


@pytest.mark.parametrize("path, said", [
    (["screens", 0, "match", 0, "crop"], "match 0 has no `crop`"),
    (["screens", 0, "controls", 0, "rect"], "control 'start' has no `rect`"),
])
def test_a_region_or_a_control_without_its_rectangle_is_never_the_whole_screen(
        tmp_path: Path, path: list[Any], said: str) -> None:
    with pytest.raises(Invalid, match=_re(said)):
        Maps().load(_file(tmp_path, _broken(path, KeyError)))
    with pytest.raises(Invalid, match=_re(said)):
        Maps().load(_file(tmp_path, _broken(path, None)))


def test_a_map_is_named_by_the_application_it_maps(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="names application 'bricks' and the file says 'demo'"):
        Maps().load(_file(tmp_path, _doc(), "bricks.screen-map.json"))
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    for bad in ("x" * 65 + ".screen-map.json", " x.screen-map.json", ".screen-map.json"):
        with pytest.raises(Invalid, match="is not named"):
            maps.save(str(tmp_path / bad), False)
    assert [p.name for p in tmp_path.iterdir()] == ["bricks.screen-map.json"]
    maps.save(str(tmp_path / ("x" * 64 + ".screen-map.json")), False)


def test_a_file_that_is_not_a_plain_json_map_is_refused_not_raised(tmp_path: Path) -> None:
    cases = {"twice": '{"format": "scry-screen-map/1", "format": "scry-screen-map/1"}',
             "digits": '{"format": 1' + "1" * 5000 + "}",
             "deep": "[" * 100000 + "]" * 100000}
    for name, text in cases.items():
        path = tmp_path / f"{name}.screen-map.json"
        path.write_text(text)
        # How deep a nesting the JSON parser reaches depends on the host's C stack: where it
        # parses, the list is refused as no map instead.
        said = "is not a (JSON|scry-screen-map/1) map" if name == "deep" else "is not a JSON map"
        with pytest.raises(Invalid, match=said) as e:
            Maps().load(str(path))
        assert e.value.code == "bad_argument", name
    big = tmp_path / "big.screen-map.json"
    big.write_bytes(b" " * (screen_map.FILE_BYTES_MAX + 1))
    with pytest.raises(Invalid, match="far past the most a map holds"):
        Maps().load(str(big))


def test_a_shadowing_screen_does_not_count_twice_against_the_cap(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screen_map, "SCREENS_MAX", 2)
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    assert maps.add("play", [[6, 2, 2, 2]], [], Reads(PLAY))["shadows_file"] is True
    with pytest.raises(Invalid, match="the map holds 2 screens"):
        maps.add("new", [[0, 0, 1, 1]], [], Reads(TITLE))


def test_a_screen_read_with_no_size_is_the_machines_answer_not_the_callers() -> None:
    with pytest.raises(Invalid, match="the screen read is 0x0") as e:
        Maps().add("a", [[0, 0, 1, 1]], [], Reads(Grid("pixel", 0, 0, b"")))
    assert e.value.code == "unexpected_answer"


def test_load_forgets_the_last_identification_and_save_moves_it_to_the_file(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.add("a", [[7, 3, 1, 1]], [{"name": "x", "rect": [0, 0, 1, 1]}], Reads(PLAY))
    assert maps.find(Reads(PLAY), stop=4)["layer"] == "session"
    maps.save(str(tmp_path / "demo.screen-map.json"), False)
    assert maps.found is not None and maps.found.layer == "file"
    assert maps.target("x")["identified_at_stop"] == 4
    maps.load(str(tmp_path / "demo.screen-map.json"))
    with pytest.raises(Invalid, match="no screen is identified"):
        maps.target("x")


def test_the_limits_are_inclusive_and_one_past_is_refused(tmp_path: Path) -> None:
    screen = _doc()["screens"][0]
    at_max = _doc(screens=[{**screen,
                            "match": [screen["match"][0]] * screen_map.MATCH_MAX,
                            "controls": [{"name": f"c{i}", "rect": [0, 0, 1, 1]}
                                         for i in range(screen_map.CONTROLS_MAX)]}])
    assert Maps().load(_file(tmp_path, at_max))["controls"] == screen_map.CONTROLS_MAX
    for key, extra in (("match", screen["match"][0]),
                       ("controls", {"name": "one-more", "rect": [0, 0, 1, 1]})):
        over = _doc(screens=[{**at_max["screens"][0],
                              key: [*at_max["screens"][0][key], extra]}])
        with pytest.raises(Invalid):
            Maps().load(_file(tmp_path, over))
    screen_map.check_add("a" * 64, [[0, 0, 1, 1]] * screen_map.MATCH_MAX)
    for name, match in (("a" * 65, [[0, 0, 1, 1]]),
                        ("a", [[0, 0, 1, 1]] * (screen_map.MATCH_MAX + 1))):
        with pytest.raises(Invalid):
            screen_map.check_add(name, match)


def test_a_text_screen_is_matched_by_its_cells() -> None:
    cells = bytearray(7 * 80 * 25)
    cells[0] = ord("A")
    grid = Grid("text", 80, 25, bytes(cells))
    maps = Maps()
    maps.add("prompt", [[0, 0, 4, 1]], [{"name": "menu", "rect": [0, 24, 10, 1]}], Reads(grid))
    got = maps.find(Reads(grid), stop=1)
    assert got["matched"] and got["controls"][0]["centre"] == [5, 24]
    assert maps.find(Reads(Grid("text", 80, 25, bytes(7 * 80 * 25))), stop=2)["matched"] is False


def _indexed(pens: list[int], colour: bytes) -> Grid:
    """A 2 x 1 pixel screen drawn with `pens`, every pen shown as `colour`: two machines drawing
    the same pens through palettes of their own."""
    return Grid("pixel", 2, 1, colour * 2, raster.index_cells(pens))


ARCADE = _indexed([4, 9], b"\x21\x21\x21")    # a 5-bit DAC: 4 is 0x21
PC = _indexed([4, 9], b"\x20\x20\x20")        # a 6-bit DAC: the same colour is 0x20


def test_an_index_screen_matches_the_same_pens_through_another_palette(tmp_path: Path) -> None:
    maps = Maps()
    added = maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE), cells="index")
    assert added["cells"] == "index"
    reads = Reads(PC)
    assert maps.find(reads, stop=1)["screen"] == "board"
    assert reads.asked == [True]
    assert maps.find(Reads(_indexed([4, 8], b"\x21\x21\x21")), stop=2)["matched"] is False
    path = tmp_path / "demo.screen-map.json"
    maps.save(str(path), False)
    assert json.loads(path.read_text())["screens"][0]["cells"] == "index"
    again = Maps()
    again.load(str(path))
    assert again.find(Reads(PC), stop=3)["screen"] == "board"


def test_an_rgb_screen_tells_the_two_palettes_apart_and_asks_for_no_indices() -> None:
    maps = Maps()
    assert maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE))["cells"] == "rgb"
    reads = Reads(PC)
    assert maps.find(reads, stop=1)["matched"] is False
    assert reads.asked == [False]


def test_a_map_that_declares_no_cells_is_saved_without_them(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    out = tmp_path / "out" / "demo.screen-map.json"
    out.parent.mkdir()
    maps.save(str(out), False)
    assert all("cells" not in s for s in json.loads(out.read_text())["screens"])


def test_a_screen_with_no_palette_is_still_matched_by_the_maps_colour_screens() -> None:
    """A map that holds both kinds asks for indices; a screen that has none is judged by its
    colour screens and says how many it could not judge."""
    no_palette = Grid("pixel", 2, 1, b"\x21\x21\x21" * 2)
    maps = Maps()
    maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE), cells="index")
    maps.add("menu", [[0, 0, 2, 1]], [], Reads(no_palette))
    reads = Reads(no_palette)
    found = maps.find(reads, stop=1)
    assert (found["matched"], found["screen"], reads.asked) == (True, "menu", [True])
    maps.session.pop("menu")
    missed = maps.find(Reads(no_palette), stop=2)
    assert missed["matched"] is False
    assert (missed["screens_tried"], missed["screens_unjudged"]) == (0, 1)
    line = screen_map.find_line({}, missed)
    assert ("0 of that kind and size, 1 more left unjudged: signed by index, on a screen "
            "whose pens") in line


class _NoPens(Reads):
    """A machine whose palette cannot name its pens: asked for them it refuses, as MAME does for
    a palette with shadows enabled; asked for colours alone it answers."""

    def __call__(self, indices: bool = False) -> Grid:
        if indices:
            self.asked.append(indices)
            raise Invalid("no_channel", "the palette has shadows enabled")
        return super().__call__(indices)


def test_a_screen_whose_pens_cannot_be_read_is_still_judged_by_its_colours() -> None:
    """A map holding an index screen asks for pens; a machine that cannot give them must not
    stop the colour screens being judged."""
    maps = Maps()
    maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE), cells="index")
    maps.add("menu", [[0, 0, 2, 1]], [], Reads(PC))
    colours = Grid("pixel", 2, 1, b"\x20\x20\x20" * 2)
    reads = _NoPens(colours)
    found = maps.find(reads, stop=1)
    assert (found["matched"], found["screen"]) == (True, "menu"), found
    assert reads.asked == [True, False], "pens asked for, then the colours alone"
    other = Grid("pixel", 2, 1, b"\x00" * 6)
    missed = maps.find(_NoPens(other), stop=2)
    assert (missed["matched"], missed["screens_tried"], missed["screens_unjudged"]) == (
        False, 1, 1), missed


def test_pens_that_cannot_be_read_are_refused_when_no_screen_can_be_judged_without_them() -> None:
    maps = Maps()
    maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE), cells="index")
    reads = _NoPens(PC)
    with pytest.raises(Invalid, match="shadows enabled") as e:
        maps.find(reads, stop=1)
    assert e.value.code == "no_channel" and reads.asked == [True], "read again for nothing"


def test_a_machine_that_refuses_the_read_for_another_reason_is_not_retried() -> None:
    class Dead(Reads):
        def __call__(self, indices: bool = False) -> Grid:
            self.count += 1
            raise Invalid("host_failed", "the emulator went away")
    maps = Maps()
    maps.add("board", [[0, 0, 2, 1]], [], Reads(ARCADE), cells="index")
    dead = Dead(PC)
    with pytest.raises(Invalid, match="went away"):
        maps.find(dead, stop=1)
    assert dead.count == 1


def test_an_index_screen_on_a_read_without_indices_is_the_machines_answer() -> None:
    with pytest.raises(Invalid, match="indices") as e:
        Maps().add("board", [[0, 0, 2, 1]], [], Reads(_grid()), cells="index")
    assert e.value.code == "no_channel"


@pytest.mark.parametrize(("screen", "said"), [
    ({"cells": "palette"}, "`cells` is"),
    ({"kind": "text", "cells": "index"}, "a text screen"),
])
def test_cells_a_map_cannot_mean_are_refused(tmp_path: Path, screen: dict[str, Any],
                                              said: str) -> None:
    doc = _doc()
    doc["screens"][0].update(screen)
    with pytest.raises(Invalid, match=said):
        Maps().load(_file(tmp_path, doc))
    with pytest.raises(Invalid, match="`cells` is"):
        screen_map.check_add("a", [[0, 0, 1, 1]], None, "palette")


def test_the_save_line_with_none_or_many_promoted() -> None:
    for n in (0, 2):
        line = screen_map.save_line({}, {"screens": 3, "path": "/x/a.screen-map.json",
                                     "promoted": ["s"] * n})
        assert line.endswith(f", {n} promoted from the session"), line


def test_a_map_that_is_not_utf8_is_refused_saying_so(tmp_path: Path) -> None:
    bad = tmp_path / "demo.screen-map.json"
    bad.write_bytes(b'{"format": "\xff"}')
    with pytest.raises(Invalid, match="cannot be read"):
        Maps().load(str(bad))


def test_a_find_whose_read_fails_forgets_the_last_screen(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.find(Reads(PLAY), stop=1)

    def fails(indices: bool = False) -> Grid:
        raise Invalid("no_channel", "the screen could not be read")
    with pytest.raises(Invalid, match="could not be read"):
        maps.find(fails, stop=2)
    assert maps.found is None, "a failed read is no identification"


@pytest.mark.parametrize("controls, said", [
    ([{"name": "a"}], "control 'a' has no `rect`"),
    ([{"name": "a", "rect": [0, 0, 1, 1], "x": 1}], "carries ['x']"),
    ([{"name": "a", "rect": [0, 0, 1, 1]}, {"name": "a", "rect": [0, 0, 1, 1]}],
     "named twice"),
    (["a"], "control 0 is not an object"),
    ([{"name": "", "rect": [0, 0, 1, 1]}], "control 0's `name`"),
], ids=["no rect", "an extra key", "a name twice", "not an object", "an empty name"])
def test_map_adds_controls_are_judged_whole_before_the_read(controls: Any, said: str) -> None:
    with pytest.raises(Invalid, match=_re(said)) as e:
        screen_map.check_add("a", [[0, 0, 1, 1]], controls)
    assert e.value.code == "bad_argument"


def test_a_load_that_would_make_the_two_layers_unsaveable_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screen_map, "SCREENS_MAX", 2)
    maps = Maps()
    maps.add("c", [[0, 0, 1, 1]], [], Reads(TITLE))
    with pytest.raises(Invalid, match="the session layer 1 more, past the 2") as e:
        maps.load(_file(tmp_path, _doc()))
    assert e.value.code == "bad_argument" and maps.file == {}
    maps.add("title", [[0, 0, 1, 1]], [], Reads(TITLE))   # a name the file shares counts once
    del maps.session["c"]
    assert maps.load(_file(tmp_path, _doc()))["screens"] == 2


def test_check_save_judges_the_path_and_the_overwrite(tmp_path: Path) -> None:
    screen_map.check_save(str(tmp_path / "demo.screen-map.json"), False)
    with pytest.raises(Invalid, match="overwrite is true or false; got 'yes'"):
        screen_map.check_save(str(tmp_path / "demo.screen-map.json"), "yes")
    with pytest.raises(Invalid, match="is not named"):
        screen_map.check_save(str(tmp_path / "demo.json"), True)


def test_the_descriptions_name_the_suffix_the_code_enforces() -> None:
    assert screen_map.DOC_VALUES["MAP_SUFFIX"] == screen_map.SUFFIX


def test_mapping_the_identified_screen_again_forgets_the_identification(tmp_path: Path) -> None:
    maps = Maps()
    maps.add("play", [[0, 0, 1, 1]], [{"name": "a", "rect": [0, 0, 1, 1]}], Reads(TITLE))
    maps.find(Reads(TITLE), stop=1)
    maps.add("play", [[0, 0, 1, 1]], [{"name": "b", "rect": [0, 0, 1, 1]}], Reads(TITLE))
    with pytest.raises(Invalid, match="no screen is identified"):
        maps.target("a")
    maps.find(Reads(TITLE), stop=2)
    maps.add("other", [[0, 0, 1, 1]], [], Reads(TITLE))
    assert maps.target("b")["screen"] == "play", "another screen added keeps the identification"


def test_where_a_crop_lies_is_never_judged_before_the_read() -> None:
    screen_map.check_add("x", [[70000, 0, 1, 1]], [{"name": "c", "rect": [0, 90000, 1, 1]}])
    with pytest.raises(Invalid, match=r"leaves screen 'x' \(8x4\)"):
        Maps().add("x", [[70000, 0, 1, 1]], [], Reads(TITLE))


def test_a_save_names_the_file_it_writes_dest_in_its_refusals(
        tmp_path: Path) -> None:
    with pytest.raises(Invalid, match=r"^dest: .*x\.json is not named"):
        screen_map.check_save(str(tmp_path / "x.json"), False)
    with pytest.raises(Invalid, match=r"^dest: .* is not named"):
        Maps().save(str(tmp_path / "x.json"), False)


def test_a_run_to_a_screen_carries_its_arrival_or_refuses_a_stale_one(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("verified")))
    arrived = {"status": "ok", "verdict": "TARGET", "pc": "0x10", "summary": "s"}
    got = screen_map.at_anchor(maps, "play", arrived, Reads(PLAY), 3)
    assert got["screen"] == {"screen": "play", "layer": "file", "mode": "verified",
                             "judged": True} and got["pc"] == "0x10"
    stale = screen_map.at_anchor(maps, "play", arrived, Reads(TITLE), 4)
    assert (stale["status"], stale["code"], stale["pc"]) == ("INVALID", "stale_map", "0x10")
    assert "verdict" not in stale and "summary" not in stale
    maps.arrived("play", Reads(PLAY), 5)
    timed_out = {"status": "ok", "verdict": "TIMEOUT"}
    assert screen_map.at_anchor(maps, "play", timed_out, Reads(PLAY), 6) is timed_out
    assert maps.found is None, "a run that did not arrive leaves no screen identified"


def test_one_run_to_screen_flow_serves_a_screen_with_an_anchor_and_one_without(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _anchored("verified")))
    assert maps.is_anchored("play")
    ran: list[str] = []

    def to_anchor(anchor: str) -> dict[str, Any]:
        ran.append(anchor)
        return {"status": "ok", "verdict": "TARGET", "stop_seq": 7, "pc": "0x10"}
    machine = Frames([PLAY])
    flow: dict[str, Any] = dict(step=machine.step, run_to_anchor=to_anchor, read=machine.read,
                stop_seq=lambda r: r["stop_seq"], run_for_only=frozenset({"frame"}))
    got = screen_map.run_to_screen(maps, "play", "vblank", 30.0, **flow)
    assert ran == [maps.anchor("play")] and got["screen"]["screen"] == "play", got
    with pytest.raises(Invalid, match="no control is named") as e:
        screen_map.run_to_screen(maps, "play", "", 30.0, declare="declare it here", **flow)
    assert e.value.code == "bad_argument" and "declare it here" in str(e.value)
    refused: list[str] = []
    maps.load(_file(tmp_path, _doc()))
    assert not maps.is_anchored("play")
    tail = Frames([TITLE, PLAY])
    got = screen_map.run_to_screen(
        maps, "play", "", 30.0, **{**flow, "step": tail.step, "read": tail.read},
        frame_run=lambda: refused.append("checked"))
    assert refused == ["checked"] and got["verdict"] == "TARGET" and "frame" not in got, got
    assert len(ran) == 1, "a screen with no anchor never ran to one"


def test_a_map_declares_where_the_program_keeps_its_pointer(tmp_path: Path) -> None:
    maps = Maps()
    assert Maps().pointer is None
    got = maps.load(_file(tmp_path, {**_doc(), "pointer": {"x": "1A2B:0010", "y": "_pointer_y"}}))
    assert got["pointer"] == {"x": "1A2B:0010", "y": "_pointer_y", "bytes": 2}, got
    assert maps.pointer == screen_map.Pointer("1A2B:0010", "_pointer_y", 2)
    maps.add("extra", [[0, 0, 1, 1]], [], Reads(TITLE))
    saved = maps.save(str(tmp_path / "again.screen-map.json"), False)
    assert saved["path"].endswith("again.screen-map.json")
    doc = json.loads((tmp_path / "again.screen-map.json").read_text())
    assert doc["pointer"] == {"x": "1A2B:0010", "y": "_pointer_y", "bytes": 2}, doc
    (tmp_path / "plain").mkdir()
    plain = Maps()
    got = plain.load(_file(tmp_path / "plain", _doc()))
    assert plain.pointer is None and "pointer" not in got, got


@pytest.mark.parametrize("ref, screen, said", [
    ("", "", "got neither"),
    ("Main", "play", "got ref and screen"),
    ("", " play", "is a name"),
])
def test_a_run_to_names_a_ref_or_a_screen_exactly_once(ref: str, screen: str, said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        screen_map.check_run_to(ref, screen)
    assert e.value.code == "bad_argument"
    screen_map.check_run_to("Main", "")
    screen_map.check_run_to("", "play")


def test_a_run_to_summary_names_its_ref_or_its_screen_and_how_it_was_taken() -> None:
    assert screen_map.run_to_named({"ref": "Main"}, {}) == "Main"
    assert screen_map.run_to_named({"ref": "", "screen": "play"},
                                   {"screen": {"judged": True}}) == "screen play (judged)"
    assert screen_map.run_to_named({"screen": "play"},
                                   {"screen": {"judged": False}}) == "screen play (taken as shown)"
    assert screen_map.run_to_named({"screen": "play"}, {}) == "screen play"


@pytest.mark.parametrize("pointer, said", [
    ("here", "`pointer` is an object"),
    ({"x": "a"}, "`pointer` needs `x` and `y`"),
    ({"x": "a", "y": ""}, "`pointer.y` is a ref"),
    ({"x": "a", "y": "b", "bytes": 3}, "`pointer.bytes` is 1, 2 or 4"),
    ({"x": "a", "y": "b", "bytes": 2.0}, "`pointer.bytes` is 1, 2 or 4"),
    ({"x": "a", "y": "b", "extra": 1}, "extra"),
])
def test_a_misshapen_pointer_declaration_refuses_the_whole_map(
        tmp_path: Path, pointer: object, said: str) -> None:
    with pytest.raises(Invalid, match=said) as e:
        Maps().load(_file(tmp_path, {**_doc(), "pointer": pointer}))
    assert e.value.code == "bad_argument"


class Frames:
    """A machine that shows `shown[n]` after n frames and answers one frame per `step`."""

    def __init__(self, shown: list[Grid], verdicts: dict[int, str] | None = None) -> None:
        self.shown, self.frames, self.verdicts = shown, 0, verdicts or {}

    def step(self, left: float = 0.0) -> dict[str, Any]:
        self.frames += 1
        return {"status": "ok", "verdict": self.verdicts.get(self.frames, "ELAPSED"),
                "stop_seq": 10 + self.frames, "pc": f"0x{self.frames:x}", "summary": "frame"}

    def read(self, indices: bool = False) -> Grid:
        return self.shown[min(self.frames, len(self.shown) - 1)]


def test_a_screen_with_no_anchor_is_run_to_a_frame_at_a_time_until_the_map_names_it(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    assert not maps.is_anchored("play")
    machine = Frames([TITLE, TITLE, TITLE, PLAY])
    got = screen_map.run_until(maps, "play", machine.step, machine.read, 30.0)
    assert got["verdict"] == "TARGET" and got["frames"] == 3 and got["pc"] == "0x3", got
    assert got["screen"] == {"screen": "play", "layer": "file", "mode": "verified",
                             "judged": True}, got
    assert maps.target("paddle")["identified_at_stop"] == 13, "the control is of this stop"


def test_a_run_to_a_screen_that_never_shows_times_out_naming_the_frames_it_ran(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    machine = Frames([TITLE])

    def step(left: float) -> dict[str, Any]:
        now[0] += 1.0
        return machine.step()
    got = screen_map.run_until(maps, "play", step, machine.read, 3.0)
    assert got["verdict"] == "TIMEOUT" and got["frames"] == 3 and "screen" not in got, got
    assert maps.found is None


def test_a_stop_that_is_not_a_frame_ends_the_run_to_a_screen_as_it_is(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    machine = Frames([TITLE], {2: "OTHER_STOP"})
    got = screen_map.run_until(maps, "play", machine.step, machine.read, 30.0)
    assert got["verdict"] == "OTHER_STOP" and got["frames"] == 2, got
    assert maps.found is None


def test_a_screen_named_nowhere_is_refused_before_a_frame_runs(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    machine = Frames([TITLE])
    with pytest.raises(Invalid, match="no screen") as e:
        screen_map.run_until(maps, "nowhere", machine.step, machine.read, 30.0)
    assert e.value.code == "unknown_ref" and machine.frames == 0


def test_a_pointer_is_refused_under_a_view_that_is_not_the_programs_own(tmp_path: Path) -> None:
    """The pointer is read in the program's units; a scaled or margined view aims in the
    machine's, so the two would never be compared fairly."""
    doc = {**_doc(), "pointer": {"x": "a", "y": "b"}}
    for scale, margin in ((2, None), (1, [0, 40])):
        with pytest.raises(Invalid, match="scale 1 and no margin") as e:
            Maps().load(_file(tmp_path, doc), scale=scale, margin=margin)
        assert e.value.code == "bad_argument"
    Maps().load(_file(tmp_path, doc), scale=1, margin=[0, 0])


class Slow(Frames):
    """Each frame takes `cost` seconds of the clock."""

    def __init__(self, cost: float) -> None:
        super().__init__([TITLE])
        self.cost = cost


def test_each_frame_is_given_the_time_left_and_not_the_whole_bound(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    machine = Slow(4.0)
    asked: list[float] = []

    def step(left: float) -> dict[str, Any]:
        asked.append(left)
        now[0] += machine.cost
        return machine.step()
    got = screen_map.run_until(maps, "play", step, machine.read, 10.0)
    assert got["verdict"] == "TIMEOUT", got
    assert asked == [10.0, 6.0, 2.0], asked
