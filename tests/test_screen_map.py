"""Screen maps: the file, the two layers, one read per identification, a control named against
the identification it came from."""
from __future__ import annotations

import json
import os
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
    """A screen reader that counts its reads: the instrument of the one-read rule."""

    def __init__(self, grid: Grid) -> None:
        self.grid, self.count = grid, 0

    def __call__(self) -> Grid:
        self.count += 1
        return self.grid


TITLE = _grid({(0, 0)})            # pixel (0, 0) lit: the title screen
PLAY = _grid({(7, 3)})             # pixel (7, 3) lit: the play screen


def _sig(grid: Grid, crop: list[int]) -> str:
    return raster.signature(grid.kind, grid.width, grid.height, grid.cells, crop)


def _doc(**over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "format": "scry-map/1", "application": "demo",
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


def _file(tmp_path: Path, doc: object, name: str = "demo.scry-map.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_a_loaded_map_finds_the_screen_shown_with_its_controls(tmp_path: Path) -> None:
    maps = Maps()
    got = maps.load(_file(tmp_path, _doc()))
    assert got == {"path": str(tmp_path / "demo.scry-map.json"), "application": "demo",
                   "screens": 2, "controls": 3}
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
                   "screens_mapped": 2} and "screen" not in got
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
    assert added == {"screen": "title", "kind": "pixel", "size": [W, H],
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
    with pytest.raises(Invalid, match="map_find` at a stop first") as e:
        maps.target("paddle")
    assert e.value.code == "needs_call"
    maps.find(Reads(PLAY), stop=12)
    assert maps.target("paddle") == {"target": "paddle", "centre": [1, 3], "screen": "play",
                                     "kind": "pixel", "size": (W, H), "identified_at_stop": 12}
    maps.find(Reads(PLAY), stop=None)
    assert maps.target("paddle")["identified_at_stop"] is None, "a stop nobody could name"
    with pytest.raises(Invalid, match=r"has no such control; its controls: paddle, quit") as e:
        maps.target("start")
    assert e.value.code == "unknown_ref"


def test_save_promotes_the_session_over_the_file_and_becomes_the_file_layer(
        tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.add("title", [[6, 2, 2, 2]], [], Reads(PLAY))
    maps.add("over", [[0, 0, 1, 1]], [{"name": "x", "rect": [0, 0, 8, 4]}], Reads(TITLE))
    out = tmp_path / "game.scry-map.json"
    got = maps.save(str(out), False)
    assert got == {"path": str(out), "application": "game", "screens": 3, "controls": 3,
                   "promoted": ["over", "title"]}
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
    out = tmp_path / "demo.scry-map.json"
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
        Maps().save(str(tmp_path / "x.scry-map.json"), False)
    assert e.value.code == "needs_call"
    assert not (tmp_path / "x.scry-map.json").exists()


@pytest.mark.parametrize("name", ["demo.json", "x/../demo.map", ".scry-map.json",
                                  "rel.scry-map.json"])
def test_a_map_path_is_absolute_and_named_by_its_application(tmp_path: Path, name: str) -> None:
    value = name if name.startswith("rel") else str(tmp_path / name)
    with pytest.raises(Invalid) as e:
        Maps().load(value)
    assert e.value.code == "bad_argument"


def test_a_map_path_from_home_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _file(tmp_path, _doc())
    assert Maps().load("~/demo.scry-map.json")["screens"] == 2


def test_a_missing_or_unreadable_file_is_refused_naming_it(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="no map file at"):
        Maps().load(str(tmp_path / "none.scry-map.json"))
    bad = tmp_path / "bad.scry-map.json"
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
    (["format"], "scry-map/2", "is not a scry-map/1 map"),
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
        "map_load: 1 screen, 2 controls of demo"
    assert screen_map.find_line({}, {"matched": True, "screen": "play", "layer": "file",
                                     "controls": [{}]}) == "map_find: play (file), 1 control"
    assert screen_map.find_line({}, {"matched": False, "kind": "text", "size": [80, 25],
                                     "screens_tried": 0, "screens_mapped": 3}) == (
        "map_find: no screen matched the text 80x25 screen (3 screens mapped, 0 of that kind "
        "and size)")
    assert screen_map.add_line({}, {"screen": "a", "kind": "pixel", "size": [8, 4],
                                    "match": [{}], "controls": 0, "shadows_file": True}) == (
        "map_add: a (pixel 8x4), 1 region, 0 controls, shadowing the file's")
    assert screen_map.save_line({}, {"screens": 2, "path": "/x/demo.scry-map.json",
                                     "promoted": ["a"]}) == (
        "map_save: 2 screens to demo.scry-map.json, 1 promoted from the session")


def test_the_odd_shapes_of_a_map_file_are_refused_by_name(tmp_path: Path) -> None:
    for broken, said in [
        (_doc(screens=["play"]), "screen 0 is not an object"),
        (_broken(["screens", 0, "match"], ["x"]), "match 0 is not an object"),
        (_broken(["screens", 0, "controls"], ["x"]), "control 0 is not an object"),
    ]:
        with pytest.raises(Invalid, match=_re(said)):
            Maps().load(_file(tmp_path, broken))
    folder = tmp_path / "dir.scry-map.json"
    folder.mkdir()
    with pytest.raises(Invalid, match="no map file at"):
        Maps().load(str(folder))


def test_map_add_and_save_refuse_what_their_arguments_cannot_be(tmp_path: Path) -> None:
    maps = Maps()
    with pytest.raises(Invalid, match="match is a list of at least one crop"):
        maps.add("a", "0,0,1,1", [], Reads(TITLE))
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    with pytest.raises(Invalid, match="overwrite='yes' is true or false"):
        maps.save(str(tmp_path / "x.scry-map.json"), "yes")  # type: ignore[arg-type]
    taken = tmp_path / "dir.scry-map.json"
    taken.mkdir()
    with pytest.raises(Invalid, match="is a directory"):
        maps.save(str(taken), True)


def test_a_save_over_a_file_that_fails_leaves_no_temporary(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    out = tmp_path / "demo.scry-map.json"
    out.write_text("keep")

    def refuse(*_a: Any) -> None:
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(Invalid, match="cannot be written: .*Permission denied"):
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
    screen_map.check_path("path", str(tmp_path / "demo.scry-map.json"))
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
        Maps().load(_file(tmp_path, _doc(), "bricks.scry-map.json"))
    maps = Maps()
    maps.add("a", [[0, 0, 1, 1]], [], Reads(TITLE))
    for bad in ("x" * 65 + ".scry-map.json", " x.scry-map.json", ".scry-map.json"):
        with pytest.raises(Invalid, match="is not named"):
            maps.save(str(tmp_path / bad), False)
    assert [p.name for p in tmp_path.iterdir()] == ["bricks.scry-map.json"]
    maps.save(str(tmp_path / ("x" * 64 + ".scry-map.json")), False)


def test_a_file_that_is_not_a_plain_json_map_is_refused_not_raised(tmp_path: Path) -> None:
    cases = {"twice": '{"format": "scry-map/1", "format": "scry-map/1"}',
             "digits": '{"format": 1' + "1" * 5000 + "}",
             "deep": "[" * 100000 + "]" * 100000}
    for name, text in cases.items():
        path = tmp_path / f"{name}.scry-map.json"
        path.write_text(text)
        with pytest.raises(Invalid, match="is not a JSON map") as e:
            Maps().load(str(path))
        assert e.value.code == "bad_argument", name
    big = tmp_path / "big.scry-map.json"
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
    maps.save(str(tmp_path / "demo.scry-map.json"), False)
    assert maps.found is not None and maps.found.layer == "file"
    assert maps.target("x")["identified_at_stop"] == 4
    maps.load(str(tmp_path / "demo.scry-map.json"))
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


def test_the_save_line_with_none_or_many_promoted() -> None:
    for n in (0, 2):
        line = screen_map.save_line({}, {"screens": 3, "path": "/x/a.scry-map.json",
                                         "promoted": ["s"] * n})
        assert line.endswith(f", {n} promoted from the session"), line


def test_a_map_that_is_not_utf8_is_refused_saying_so(tmp_path: Path) -> None:
    bad = tmp_path / "demo.scry-map.json"
    bad.write_bytes(b'{"format": "\xff"}')
    with pytest.raises(Invalid, match="cannot be read"):
        Maps().load(str(bad))


def test_a_find_whose_read_fails_forgets_the_last_screen(tmp_path: Path) -> None:
    maps = Maps()
    maps.load(_file(tmp_path, _doc()))
    maps.find(Reads(PLAY), stop=1)

    def fails() -> Grid:
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


def test_save_refuses_two_layers_bigger_than_a_map_can_load(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(screen_map, "SCREENS_MAX", 2)
    maps = Maps()
    maps.add("c", [[0, 0, 1, 1]], [], Reads(TITLE))
    maps.load(_file(tmp_path, _doc()))           # a load replaces the file layer whole
    out = tmp_path / "all.scry-map.json"
    with pytest.raises(Invalid, match="the two layers hold 3 screens") as e:
        maps.save(str(out), False)
    assert e.value.code == "bad_argument" and not out.exists()


def test_check_save_judges_the_path_and_the_overwrite() -> None:
    screen_map.check_save("/x/demo.scry-map.json", False)
    with pytest.raises(Invalid, match="overwrite='yes' is true or false"):
        screen_map.check_save("/x/demo.scry-map.json", "yes")
    with pytest.raises(Invalid, match="is not named"):
        screen_map.check_save("/x/demo.json", True)


def test_the_file_tools_descriptions_say_the_limits_the_code_enforces() -> None:
    assert screen_map.SUFFIX in screen_map.DOC_VALUES["MAP_LOAD"]
    assert f"({screen_map.SCREENS_MAX})" in screen_map.DOC_VALUES["MAP_SAVE"]
