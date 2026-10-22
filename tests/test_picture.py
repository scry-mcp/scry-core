"""The picture in the reply: the inline ceiling, the scale, the file written once and recorded,
and the attachment beside the JSON at the MCP boundary. Each written file is read back with the
decoder, so what is held is the file's pixels, never the writer's idea of them."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from scry_core import picture, png
from scry_core.reply_contract import Invalid


class Recorded(list[Path]):
    def __call__(self, path: Path) -> None:
        self.append(path)


def test_the_ceiling_is_the_side_and_the_tile_count() -> None:
    """The inline ceiling at its edges: a side of exactly the maximum fits, one more does not;
    a picture whose sides fit but whose tiles of 28 px add up past the budget does not either."""
    side = picture.INLINE_SIDE_MAX
    assert picture.within_ceiling(side, 28)
    assert not picture.within_ceiling(side + 1, 28)
    # 40 x 40 tiles = 1600 > 1568, with both sides well under the side maximum.
    assert not picture.within_ceiling(40 * picture.TOKEN_SIDE, 40 * picture.TOKEN_SIDE)
    assert picture.within_ceiling(39 * picture.TOKEN_SIDE, 40 * picture.TOKEN_SIDE)
    assert picture.tiles(960, 720) == 35 * 26 and picture.tiles(28, 29) == 2


def test_the_automatic_scale_is_the_largest_that_fits() -> None:
    assert picture.auto_scale(8, 8) == picture.SCALE_MAX, "a tile is enlarged all the way"
    factor = picture.auto_scale(256, 224)
    assert picture.within_ceiling(256 * factor, 224 * factor)
    assert not picture.within_ceiling(256 * (factor + 1), 224 * (factor + 1))
    assert picture.auto_scale(2000, 10) == 1, "a source past the ceiling is not shrunk"
    side = picture.INLINE_SIDE_MAX // picture.SCALE_MAX
    assert picture.auto_scale(side, 10) == picture.SCALE_MAX
    assert picture.auto_scale(side, 10, border=2) == picture.SCALE_MAX - 1, (
        "a border is part of the picture the ceiling judges")
    assert picture.auto_scale(320, 240) == 3, "a DOS screen: 960x720"


def test_a_border_frames_an_rgb_picture_and_refuses_an_indexed_one() -> None:
    rgb = png.Raster(2, 1, bytes([1, 2, 3, 4, 5, 6]))
    framed = picture.bordered(rgb, 1)
    grey = bytes(picture.BORDER_COLOUR)
    assert (framed.width, framed.height) == (4, 3)
    assert framed.pixels == grey * 4 + grey + bytes([1, 2, 3, 4, 5, 6]) + grey + grey * 4
    with pytest.raises(ValueError, match="an indexed one is data"):
        picture.bordered(png.Raster(1, 1, b"\x00", ((0, 0, 0),)), 1)
    with pytest.raises(ValueError, match="an indexed one is data"):
        picture.outlined(png.Raster(1, 1, b"\x00", ((0, 0, 0),)), [], [], 1)


def test_marks_and_rings_are_drawn_after_the_enlargement() -> None:
    """A mark on source pixel (0, 0) at x2 outlines output pixels 0..1; a ring of gap 1 runs one
    output pixel outside source pixel (1, 1), so it covers none of it."""
    base = png.Raster(3, 3, bytes(27))
    red, blue = (255, 0, 0), (0, 0, 255)
    out = picture.outlined(png.enlarged(base, 2), [(0, 0, 1, 1, red)], [(1, 1, 1, 1, blue, 1)], 2)

    def at(x: int, y: int) -> tuple[int, ...]:
        i = (y * out.width + x) * 3
        return tuple(out.pixels[i:i + 3])
    assert at(0, 0) == red and at(1, 0) == red and at(0, 1) == red
    assert at(1, 1) == blue, "a ring is drawn after the marks, over them"
    assert at(2, 2) == (0, 0, 0) and at(3, 3) == (0, 0, 0), "the ringed pixel is left as it was"
    assert at(1, 4) == blue and at(4, 1) == blue


@pytest.mark.parametrize("bad", [-1, picture.SCALE_MAX + 1, True, 1.5])
def test_a_scale_outside_its_range_is_refused(bad: object) -> None:
    with pytest.raises(Invalid, match="scale=") as e:
        picture.check_scale(bad)
    assert e.value.code == "bad_argument"
    picture.check_scale(0)
    picture.check_scale(picture.SCALE_MAX)


def test_publish_writes_one_png_names_it_and_records_it(tmp_path: Path) -> None:
    raster = png.Raster(4, 4, bytes(range(16)), tuple((i, i, i) for i in range(16)))
    record = Recorded()
    image = picture.publish(raster, 0, None, tmp_path, "palette", record)
    path = Path(image["path"])
    data = path.read_bytes()
    assert path.parent == tmp_path / "gfx" and path.name == "palette-1.png"
    assert image["sha256"] == hashlib.sha256(data).hexdigest() and image["bytes"] == len(data)
    assert image["scale"] == picture.SCALE_MAX and image["inline"] is True
    assert (image["width"], image["height"]) == (4 * picture.SCALE_MAX, 4 * picture.SCALE_MAX)
    assert "not_inlined" not in image and image["indexed"] is True
    assert png.decode(data) == png.enlarged(raster, picture.SCALE_MAX)
    assert record == [path]
    again = picture.publish(raster, 1, None, tmp_path, "palette", record)
    assert Path(again["path"]).name == "palette-2.png", "a second picture never overwrites"


def test_publish_draws_marks_and_a_ring_off_the_edge_is_clipped(tmp_path: Path) -> None:
    """A mark through `publish` reaches the file; a ring round pixel (0, 0) with no border runs
    off the picture, and the part off it is simply not drawn."""
    red = (255, 0, 0)
    image = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "m", Recorded(),
                            marks=[(1, 1, 1, 1, red)], rings=[(0, 0, 1, 1, red, 1)])
    out = png.decode(Path(image["path"]).read_bytes())
    assert out.pixels[9:12] == bytes(red) and out.pixels[3:6] == bytes(red)
    assert out.pixels[:3] == bytes(3), "the ringed pixel itself is left as it was"


def test_a_transparent_index_and_a_border_reach_the_file(tmp_path: Path) -> None:
    raster = png.Raster(2, 1, bytes([0, 1]), ((0, 0, 0), (9, 9, 9)))
    image = picture.publish(raster, 1, None, tmp_path, "swatch", Recorded(), clear=1)
    assert b"tRNS" in Path(image["path"]).read_bytes()
    framed = picture.publish(png.Raster(1, 1, bytes(3)), 1, None, tmp_path, "pixel", Recorded(),
                             border=2)
    assert framed["border"] == 2 and (framed["width"], framed["height"]) == (5, 5)


def test_a_dest_is_written_once_and_never_over(tmp_path: Path) -> None:
    dest = tmp_path / "shot.png"
    record = Recorded()
    image = picture.publish(png.Raster(1, 1, bytes(3)), 1, dest, tmp_path, "screen", record)
    assert image["path"] == str(dest) and record == [dest]
    with pytest.raises(Invalid, match="will not overwrite it") as e:
        picture.publish(png.Raster(1, 1, bytes(3)), 1, dest, tmp_path, "screen", record)
    assert e.value.code == "bad_argument" and record == [dest], "a refused write records nothing"
    with pytest.raises(Invalid, match="cannot be created") as e:
        picture.publish(png.Raster(1, 1, bytes(3)), 1, tmp_path / "no" / "x.png", tmp_path,
                        "screen", record)
    assert e.value.code == "bad_argument", "a dest the caller named that cannot be opened"


def test_a_picture_past_the_ceiling_is_written_and_not_inlined(tmp_path: Path) -> None:
    raster = png.Raster(picture.INLINE_SIDE_MAX + 1, 1, bytes(picture.INLINE_SIDE_MAX + 1),
                        ((0, 0, 0),))
    image = picture.publish(raster, 0, None, tmp_path, "screen", Recorded())
    assert image["inline"] is False and Path(image["path"]).is_file()
    assert "a smaller `scale`, or a `crop` where the tool takes one" in image["not_inlined"]
    assert image["scale"] == 1


def test_a_data_file_is_the_raster_unscaled(tmp_path: Path) -> None:
    raster = png.Raster(2, 1, bytes([0, 1]), ((0, 0, 0), (1, 1, 1)))
    block = picture.data_file(raster, tmp_path, "data", Recorded())
    assert png.decode(Path(block["path"]).read_bytes()) == raster
    assert (block["width"], block["height"], block["indexed"]) == (2, 1, True)


def _result(image: dict[str, object]) -> CallToolResult:
    body = {"summary": "x", "status": "ok", "image": image}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))],
                          structured_content=body)


def test_the_picture_is_attached_after_the_json_and_is_the_file(tmp_path: Path) -> None:
    image = picture.publish(png.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p",
                            Recorded())
    out = picture.attached(_result(image))
    assert [c.type for c in out.content] == ["text", "image"]
    shown = out.content[1]
    assert isinstance(shown, ImageContent) and shown.mime_type == "image/png"
    assert hashlib.sha256(base64.b64decode(shown.data)).hexdigest() == image["sha256"]
    assert out.structured_content == _result(image).structured_content


def test_nothing_is_attached_when_the_body_says_not_inline(tmp_path: Path) -> None:
    image = picture.publish(png.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p",
                            Recorded())
    out = picture.attached(_result({**image, "inline": False}))
    assert [c.type for c in out.content] == ["text"]
    plain = CallToolResult(content=[TextContent(type="text", text="{}")], structured_content={})
    assert picture.attached(plain) is plain, "a reply with no image is left alone"


def test_an_inline_block_that_names_no_file_is_left_as_written() -> None:
    body = {"status": "ok", "image": {"inline": True}}
    result = CallToolResult(content=[TextContent(type="text", text="{}")], structured_content=body)
    assert picture.attached(result).structured_content == body


def test_a_file_that_changed_is_not_attached_and_the_body_says_so(tmp_path: Path) -> None:
    image = picture.publish(png.Raster(2, 2, bytes(4), ((1, 2, 3),)), 0, None, tmp_path, "p",
                            Recorded())
    Path(str(image["path"])).write_bytes(b"not the picture")
    out = picture.attached(_result(image))
    assert [c.type for c in out.content] == ["text"]
    assert out.structured_content is not None
    said = out.structured_content["image"]
    assert said["inline"] is False and "sha256" in said["not_inlined"]
    text = out.content[0]
    assert isinstance(text, TextContent) and json.loads(text.text)["image"]["inline"] is False
    Path(str(image["path"])).unlink()
    assert picture.attached(_result(image)).structured_content["image"]["inline"] is False


def test_a_numbered_picture_never_lands_on_a_file_already_there(tmp_path: Path) -> None:
    (tmp_path / "gfx").mkdir()
    (tmp_path / "gfx" / "screen-1.png").write_bytes(b"somebody else's")
    (tmp_path / "gfx" / "palette-1.png").write_bytes(b"another tool's")
    image = picture.publish(png.Raster(1, 1, bytes(1), ((0, 0, 0),)), 1, None, tmp_path,
                            "screen", Recorded())
    assert Path(image["path"]).name == "screen-2.png"
    assert (tmp_path / "gfx" / "screen-1.png").read_bytes() == b"somebody else's"


def test_a_reply_whose_body_is_not_an_object_is_left_alone() -> None:
    bare = CallToolResult(content=[TextContent(type="text", text="x")], structured_content=None)
    assert picture.attached(bare) is bare
    assert picture.attached("not a result") == "not a result"


def test_the_shared_sentences_carry_the_constants_that_enforce_them() -> None:
    for value in (picture.INLINE_SIDE_MAX, picture.INLINE_TOKENS_MAX, picture.TOKEN_SIDE):
        assert str(value) in picture.DESCRIBED
    assert str(picture.SCALE_MAX) in picture.ARGUMENTS and "gone at `close`" in picture.ARGUMENTS


def test_a_server_that_records_nothing_names_no_recorder(tmp_path: Path) -> None:
    block = picture.publish(png.Raster(1, 1, bytes(3)), 1, None, tmp_path, "shot")
    assert Path(block["path"]).is_file()
    data = picture.data_file(png.Raster(1, 1, bytes(3)), tmp_path, "data")
    assert Path(data["path"]).is_file()


def test_a_view_asked_not_to_attach_writes_its_file_and_says_why(tmp_path: Path) -> None:
    block = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "shot", attach=False)
    assert Path(block["path"]).is_file()
    assert block["inline"] is False and block["not_inlined"] == "attach=false"
    result = picture.attached(_result(block))
    assert not [c for c in result.content if isinstance(c, ImageContent)]


def test_a_picture_inside_a_step_is_never_attached_and_says_nested(tmp_path: Path) -> None:
    """Only a reply's own picture crosses: a sequence's step pictures are files it names, so
    their blocks say so, and the reply's own one is still attached."""
    own = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "own")
    step = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "step")
    body: dict[str, Any] = {"status": "ok", "image": own,
                            "ran": [{"op": "screen_view", "image": step}, {"op": "registers"}]}
    result = picture.attached(CallToolResult(content=[TextContent(type="text",
                                                                  text=json.dumps(body))],
                                             structured_content=body))
    out = result.structured_content
    assert out["ran"][0]["image"]["inline"] is False
    assert out["ran"][0]["image"]["not_inlined"] == "nested"
    assert out["image"]["inline"] is True
    assert json.loads(result.content[0].text) == out, "the text half says what the body says"
    images = [c for c in result.content if isinstance(c, ImageContent)]
    assert len(images) == 1 and base64.b64decode(images[0].data) == Path(own["path"]).read_bytes()
    assert body["ran"][0]["image"]["inline"] is True, "the caller's dict is not mutated"


def test_a_nested_picture_in_a_reply_with_none_of_its_own_is_marked_too(tmp_path: Path) -> None:
    step = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "step")
    body = {"status": "ok", "ran": [{"reply": {"image": step}}]}
    out = picture.attached(CallToolResult(content=[TextContent(type="text", text="{}")],
                                          structured_content=body)).structured_content
    assert out["ran"][0]["reply"]["image"]["not_inlined"] == "nested"


def test_the_described_sentence_names_every_key_an_image_block_has(tmp_path: Path) -> None:
    block = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "b", border=1)
    block_over = picture.publish(png.Raster(2000, 2, bytes(12000)), 1, None, tmp_path, "o")
    for key in {*block, *block_over}:
        assert f"`{key}`" in picture.DESCRIBED, key


def test_a_nested_picture_keeps_any_reason_it_already_had_and_a_non_picture_is_left(
        tmp_path: Path) -> None:
    over = {"path": "/o.png", "inline": False, "not_inlined": "past the ceiling"}
    not_a_picture = {"inline": True, "width": 1, "height": 1}       # names no file
    body = {"ran": [[{"image": over}], {"image": not_a_picture}, {"image": "/a/path.png"}]}
    assert picture.unattached_below(body) == body
    deep = {"ran": [[{"image": {"path": "/s.png", "inline": True}}]]}
    assert picture.unattached_below(deep)["ran"][0][0]["image"]["not_inlined"] == "nested"


def test_a_rebuilt_reply_reads_as_the_sdk_writes_one(tmp_path: Path) -> None:
    """Marked or not, the text half is the SDK's own serialisation: no non-ASCII escaped."""
    step = picture.publish(png.Raster(2, 2, bytes(12)), 1, None, tmp_path, "step")
    body = {"status": "ok", "text": "café", "ran": [{"image": step}]}
    result = picture.attached(CallToolResult(content=[TextContent(type="text", text="{}")],
                                             structured_content=body))
    text = result.content[0]
    assert isinstance(text, TextContent) and "café" in text.text and "\\u" not in text.text


@pytest.mark.parametrize("attach", ["no", 1, None])
def test_an_attach_that_is_no_yes_or_no_is_refused(attach: object) -> None:
    with pytest.raises(Invalid, match="attach is true or false"):
        picture.check_attach(attach)
    picture.check_attach(False)
