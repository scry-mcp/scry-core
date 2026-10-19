"""The picture a view tool answers with: ONE PNG on disk, its `image` block in the reply, and the
same bytes attached beside the JSON when the model can see them unresampled. Both servers attach
through here; each passes in its scratch, and how it records a capture when it records one.

THE CEILING. Past a long side of `INLINE_SIDE_MAX` pixels, or past `INLINE_TOKENS_MAX` tiles of
`TOKEN_SIDE` pixels, the API resamples an image before the model sees it, and a resampled picture
of pixel art is a plausible wrong picture: pens blend, one-pixel lines vanish. So a picture above
it is written, named and NOT attached, and the reply says why; the caller asks for a crop.
Transport is not the limit: a far larger PNG crosses the protocol intact, and it is the
resampling that would make it wrong.

THE SCALE. Inside the ceiling a small source is enlarged by an integer factor, nearest neighbour,
so every source pixel is a square of one pen and nothing is resampled; the factor is in the
reply. `scale=0` picks the largest factor that stays inside, and a crop is the zoom.

WHY THE ATTACHMENT IS READ BACK FROM THE FILE. The body names a path and a sha256, and the
picture beside it is the file at that path, hashed again at the MCP boundary: a picture that is
not provably the file the body names would be two answers to one question.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pydantic_core
from mcp.types import CallToolResult, ImageContent, TextContent

from scry_core import fresh, png
from scry_core.judges import whole
from scry_core.reply_contract import Invalid

#: The API's standard tier: the long side and the visual tokens past which it downscales.
INLINE_SIDE_MAX = 1568
INLINE_TOKENS_MAX = 1568
#: The side, in pixels, of one visual token's tile in the API's count of an image's cost.
TOKEN_SIDE = 28
SCALE_MAX = 8
BORDER_COLOUR = (0x80, 0x80, 0x80)     # a neutral grey: what lies outside the picture's source

#: What a view tool's description says about its picture, the same on both servers: the picture,
#: the arguments every picture tool takes, and `attach`, which only a view takes.
DESCRIBED = (
    "The PNG is attached after the JSON when within the inline ceiling "
    f"({INLINE_SIDE_MAX} px a side, {INLINE_TOKENS_MAX} tiles of {TOKEN_SIDE} px); `image` names "
    "it either way (`path`, `bytes`, `sha256`, `width`, `height`, `scale`, `indexed`, `border`, "
    "`inline`, `not_inlined`)")
ARGUMENTS = (
    f"`scale` 0, the largest integer enlargement up to {SCALE_MAX} that fits; `dest` a new "
    "path, else the scratch, gone at `close`")
ATTACH = "`attach` false writes the file, unattached"
#: Why a picture written was not attached when the caller asked so (`not_inlined`); the ceiling's
#: reason is a sentence saying the size.
NOT_ASKED = "attach=false"
#: Why a step's picture inside a sequence was not attached: only a reply's own one is.
NESTED = "nested"

#: What a tool's description fills from here (`scry_core.docs.filled`).
DOC_VALUES = {"PICTURE": DESCRIBED, "PICTURE_ARGS": ARGUMENTS, "PICTURE_ATTACH": ATTACH}

#: How a server records a file it wrote for the session, so it is listed and cleaned with it.
Record = Callable[[Path], None]


def tiles(width: int, height: int) -> int:
    """The visual tokens a `width` x `height` picture costs as attached."""
    return -(-width // TOKEN_SIDE) * -(-height // TOKEN_SIDE)


def within_ceiling(width: int, height: int) -> bool:
    """Whether a `width` x `height` picture reaches the model as it is."""
    return max(width, height) <= INLINE_SIDE_MAX and tiles(width, height) <= INLINE_TOKENS_MAX


def auto_scale(width: int, height: int, border: int = 0) -> int:
    """The largest factor in 1..`SCALE_MAX` that keeps the enlarged picture, and a `border` of
    output pixels round it, inside the ceiling; 1 when even the source is above it (it is then
    written and not attached)."""
    for factor in range(SCALE_MAX, 1, -1):
        if within_ceiling(width * factor + 2 * border, height * factor + 2 * border):
            return factor
    return 1


def check_scale(scale: object) -> None:
    """A `scale` is 0 (the largest that fits) or a factor in 1..`SCALE_MAX`."""
    if not whole(scale, 0, SCALE_MAX):
        raise Invalid("bad_argument", f"scale={scale!r}: 0 picks the largest integer enlargement "
                      f"inside the inline ceiling, or name a factor in 1..{SCALE_MAX}")


def check_attach(attach: object) -> None:
    """An `attach` is a yes or a no, said in one sentence on both servers."""
    if not isinstance(attach, bool):
        raise Invalid("bad_argument", f"attach is a boolean; got {attach!r}")


#: A rectangle marked over a picture: `x`, `y`, `width`, `height` in source pixels, and its RGB.
Mark = tuple[int, int, int, int, tuple[int, int, int]]
#: A mark drawn round a rectangle instead: the same, and how many output pixels OUTSIDE it the
#: ring runs (1 hugs it), so two rings of different colours frame one pixel on any background.
Ring = tuple[int, int, int, int, tuple[int, int, int], int]


def publish(raster: png.Raster, scale: int, dest: Path | None, scratch: Path, stem: str,
            record: Record | None = None, marks: list[Mark] | None = None,
            rings: list[Ring] | None = None, border: int = 0,
            clear: int | None = None, attach: bool = True) -> dict[str, Any]:
    """Write `raster` as ONE PNG, enlarged by `scale` (0: the largest that fits), to `dest` (a
    path the server judged fresh) or to a numbered file in the scratch's `gfx`, and answer its
    `image` block. Marks and rings (RGB pictures only) are drawn AFTER the enlargement, one
    output pixel wide: a mark along its rectangle's outer pixel squares, a ring OUTSIDE them, so a
    ring covers none of what it frames. A `border` of that many output pixels in `BORDER_COLOUR`
    goes round the picture first (RGB only), where a ring round a pixel at the picture's edge has
    room; the block names it. `clear` is `png.encode`'s transparent index. With `attach` false the
    file is written and named, and never attached."""
    factor = scale or auto_scale(raster.width, raster.height, border)
    big = png.enlarged(raster, factor)
    if border:
        big = bordered(big, border)
    if marks or rings:
        big = outlined(big, marks or [], rings or [], factor, border)
    data = png.encode(big, clear)
    path = written(data, dest, scratch, stem, record)
    block: dict[str, Any] = {
        **file_block(path, data), "width": big.width, "height": big.height, "scale": factor,
        "indexed": raster.palette is not None,
        "inline": attach and within_ceiling(big.width, big.height),
    }
    if border:
        block["border"] = border
    if not attach:
        block["not_inlined"] = NOT_ASKED
    elif not block["inline"]:
        block["not_inlined"] = (
            f"{big.width}x{big.height} is past the inline ceiling (a side of "
            f"{INLINE_SIDE_MAX} px, {INLINE_TOKENS_MAX} tiles of {TOKEN_SIDE} px), where the API "
            "would resample it: the file is written; ask for a smaller `scale`, or a `crop` where "
            "the tool takes one")
    return block


def data_file(raster: png.Raster, scratch: Path, stem: str,
              record: Record | None = None) -> dict[str, Any]:
    """Write `raster` unscaled as the DATA beside a picture that is a view of it (a view dims or
    marks, and an indexed data PNG cannot), and answer its block. Never attached: the view is."""
    data = png.encode(raster)
    path = written(data, None, scratch, stem, record)
    return {**file_block(path, data), "width": raster.width, "height": raster.height,
            "indexed": raster.palette is not None}


def written(data: bytes, dest: Path | None, scratch: Path, stem: str,
            record: Record | None = None) -> Path:
    """`data` at `dest`, or at the first free `stem-<n>.png` of the scratch's `gfx` (`fresh`'s
    rules), then recorded when the server records its files (`record`; None, it does not)."""
    if dest is None:
        path = fresh.numbered(scratch / "gfx", lambda n: f"{stem}-{n}.png", data, "the picture")
    else:
        fresh.create(dest, data, "the picture", named_by_caller=True)
        path = dest
    if record is not None:
        record(path)
    return path


def file_block(path: Path, data: bytes) -> dict[str, Any]:
    """A written file's half of an `image` block: where it is, how big, and its sha256."""
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def bordered(raster: png.Raster, border: int) -> png.Raster:
    """`raster` (RGB) framed by `border` output pixels of `BORDER_COLOUR` on every side."""
    if raster.palette is not None:
        raise ValueError("a border is drawn round an RGB picture: an indexed one is data")
    width = raster.width + 2 * border
    edge = bytes(BORDER_COLOUR) * width
    side = bytes(BORDER_COLOUR) * border
    rows = [side + raster.pixels[y * raster.width * 3:(y + 1) * raster.width * 3] + side
            for y in range(raster.height)]
    return png.Raster(width, raster.height + 2 * border,
                      edge * border + b"".join(rows) + edge * border)


def outlined(raster: png.Raster, marks: list[Mark], rings: list[Ring],
             factor: int, origin: int = 0) -> png.Raster:
    """`raster` (RGB, already enlarged by `factor`, its source's pixel (0, 0) at output pixel
    (`origin`, `origin`)) with each mark's outline, then each ring, drawn in, in order."""
    if raster.palette is not None:
        raise ValueError("marks are drawn over an RGB picture: an indexed one is data")
    px = bytearray(raster.pixels)
    width = raster.width

    def put(x: int, y: int, rgb: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < raster.height:
            at = (y * width + x) * 3
            px[at:at + 3] = bytes(rgb)

    def square(left: int, top: int, right: int, bottom: int, rgb: tuple[int, int, int]) -> None:
        for xx in range(left, right + 1):
            put(xx, top, rgb)
            put(xx, bottom, rgb)
        for yy in range(top, bottom + 1):
            put(left, yy, rgb)
            put(right, yy, rgb)

    o = origin
    for x, y, w, h, rgb in marks:
        square(o + x * factor, o + y * factor, o + (x + w) * factor - 1,
               o + (y + h) * factor - 1, rgb)
    for x, y, w, h, rgb, gap in rings:
        square(o + x * factor - gap, o + y * factor - gap, o + (x + w) * factor - 1 + gap,
               o + (y + h) * factor - 1 + gap, rgb)
    return png.Raster(raster.width, raster.height, bytes(px))


def unattached_below(value: Any, top: bool = True) -> Any:
    """`value` with every attached picture block (`image`, naming its file) below the reply's
    top level marked `inline: false`, `not_inlined: "nested"`, and the top level's too when `top`
    is false (a step's own reply): only a reply's own picture is attached, so a step's picture
    inside a sequence is a file the reply names, and saying `inline: true` there would be a
    promise nobody keeps (and a cost `traffic` would charge)."""
    if isinstance(value, list):
        return [unattached_below(v, False) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, v in value.items():
        if (key == "image" and not top and isinstance(v, dict) and v.get("inline") is True
                and "path" in v):
            out[key] = {**v, "inline": False, "not_inlined": NESTED}
        else:
            out[key] = unattached_below(v, False) if key != "image" or not top else v
    return out


def attached(result: Any) -> Any:
    """`result` with its picture beside the JSON, when its body's `image` says `inline`: the
    one place a reply gains an `ImageContent`, at the MCP boundary, so a tool body and a test
    handle a plain dict. A picture below the top level is marked unattached first
    (`unattached_below`). The file is hashed again; a file that no longer matches its `sha256`
    is not attached, and the body says so."""
    if not isinstance(result, CallToolResult) or not isinstance(result.structured_content, dict):
        return result
    marked = unattached_below(result.structured_content)
    if marked != result.structured_content:
        result = CallToolResult(content=[_text(marked)], structured_content=marked,
                                is_error=result.is_error)
    body = marked
    image = body.get("image")
    if (not isinstance(image, dict) or image.get("inline") is not True
            or not isinstance(image.get("path"), str) or not isinstance(image.get("sha256"), str)):
        return result                  # nothing named to attach: the body stands as written
    try:
        data = Path(image["path"]).read_bytes()
    except (OSError, ValueError):
        data = b""                     # gone or unreadable: it cannot match, and is said so
    if hashlib.sha256(data).hexdigest() != image["sha256"]:
        body = {**body, "image": {**image, "inline": False,
                                  "not_inlined": "the file no longer matches its sha256, so the "
                                                 "picture it holds is not the one this reply "
                                                 "describes"}}
        return CallToolResult(content=[_text(body)], structured_content=body,
                              is_error=result.is_error)
    picture = ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                           mime_type="image/png")
    return CallToolResult(content=[*result.content, picture], structured_content=body,
                          is_error=result.is_error)


def _text(body: dict[str, Any]) -> TextContent:
    """The text half as the SDK writes it for a structured reply, so a rebuilt reply reads the
    same as one that was not."""
    return TextContent(type="text", text=pydantic_core.to_json(body, indent=2).decode())
