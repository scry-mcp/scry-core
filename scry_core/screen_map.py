"""Screen maps: which screen of an application the machine shows, and where its controls are, so a
caller names a control instead of a coordinate and a screen is recognised without a picture
crossing the conversation. No emulator here: a server hands in one read of its screen.

THE FILE is JSON, `"format": "scry-screen-map/1"`, named `<application>.screen-map.json` and kept
beside the program in the application's own repository (a game both servers run keeps one, beside
its script in `scry_core.games`):

    {"format": "scry-screen-map/1", "application": "bricks", "mode": "verified",
     "screens": [{"name": "play", "kind": "pixel", "size": [320, 200], "anchor": "DrawPlay",
                  "match": [{"crop": [0, 0, 320, 8], "signature": "<16 hex>"}],
                  "controls": [{"name": "paddle", "rect": [140, 180, 40, 8]}]}]}

THE MODE says who answers for the map holding. `verified`: an application whose screens still
move (one under development, a driver or an emulation being touched), so every way into a screen
judges its signatures and a map gone stale is noticed by the server. `consolidated`: a finished
program whose authors keep the map current; each screen names its `anchor`, the symbol after which
it is whole, and `run_to(screen=)` takes the screen as shown there with no read. The signatures are
then a protection asked for with `screen_map_find`, not the way in, which is what lets one map
serve two ports whose pixels differ.

THE PROGRAM'S UNITS. A map is in the units the program draws in; a machine that shows the
picture larger is described at `load` by an integer `scale` and a `margin` [x, y] on each side
(Speed Fight's PC port: the arcade's 320x200 at scale 2 with a margin of [0, 40] is its 640x480).
A read is sampled through that view into the program's units before it is signed, and a control's
centre is aimed back in the machine's.

THE PROGRAM'S OWN POINTER. A program that integrates the driver's motion into a pointer of its
own and clamps it drifts from the driver's after a clamp. The map may declare, once for the
application, `"pointer": {"x": ref, "y": ref, "bytes": 2}`: where that pointer lives in the
program's memory, in the program's units. A server that moves a pointer reads it back there and
corrects until it is where it was asked to be.

Every rectangle is in the screen's own units: cells in a text mode, pixels in a graphics one, as
`screen_view` counts them. A screen MATCHES when its `kind` and `size` are the screen's and every
`match` signature is `scry-sig/1` (`raster.signature`) over its crop. A pixel screen may say
`"cells": "index"`: its regions are then signed by the palette indices drawn, not the colours
shown, so one map knows a program on two machines whose palettes show one index in different
colours (an arcade board's 5-bit palette, a VGA's 6-bit DAC); a screen that says nothing is signed
in colour, and saved saying nothing. A screen is known by declared stable regions, never the whole
screen, because a whole-screen hash changes with a cursor or a ball. Names are unique in the file
(screens) and in their screen (controls), every rectangle lies inside its screen, and a file that
breaks any of it is refused whole, naming the first fault: a map half believed would match a
screen it does not describe.

TWO LAYERS, both living for the server's session: the FILE layer (`load`) and the SESSION layer
(`add`, written from the screen in front of the caller), the session's screens tried first and
shadowing a file screen of the same name. `save` writes the two as one file, the session
winning, and that file becomes the file layer: the promotion. A successful `start` empties the
session layer (its screens were read off another run) and keeps the file layer.

ONE SCREEN READ PER IDENTIFICATION. `find` reads the screen once and cuts every candidate's
crops from that read, each distinct crop signed once, kind and size compared before any hash:
a read can be a round trip through the emulator's console, and a map of many screens must not
cost one per screen.

A CONTROL IS NAMED AGAINST THE IDENTIFICATION IT CAME FROM, the way a browser automation `ref`
is valid against the snapshot it was read from: `target` answers the centre of a control of the
screen the most recent `find` matched, with the stop that `find` read at, because a running guest
cannot be read at the moment a pointer moves.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from scry_core import fresh, judges, prose, raster
from scry_core import vocabulary as vocab
from scry_core.reply_contract import Invalid, or_unavailable

FORMAT = "scry-screen-map/1"
SUFFIX = ".screen-map.json"
KINDS = ("text", "pixel")
MODES = ("verified", "consolidated")
#: The largest scale a view declares: past any picture a machine shows enlarged.
SCALE_MAX = 8
#: What a pixel screen's regions are signed over: the colours shown, or the palette indices drawn.
CELLS = ("rgb", "index")
#: `cells` as a tool takes it, empty meaning not given (`rgb`).
CELLS_WORDS = ("", *CELLS)
#: How much one map holds: screens in a file, regions a screen is matched by, controls on one.
SCREENS_MAX, MATCH_MAX, CONTROLS_MAX = 200, 16, 100
#: The largest map file read: far past the most screens it can hold, so a file past it is not one.
FILE_BYTES_MAX = 4 * 1024 * 1024
_SIGNATURE = re.compile(r"[0-9a-f]{16}")
_NAME_MAX = 64
#: A side past any rectangle a caller can name: what a rectangle's shape is judged against before
#: a read says the screen's own size, so only the read ever refuses where a rectangle lies.
_ANY_SIDE = 1 << 62

Layer = Literal["session", "file"]

#: What a tool's description fills from here (`scry_core.docs.filled`): the methods and the tool
#: both servers describe in the same words, filled after the docstring is dedented.
DOC_VALUES = {
    "MAP_SUFFIX": SUFFIX,
    "MAP_LOAD": (f"`load`: `path` (`<application>{SUFFIX}`, absolute or `~`-led) as the file "
                 "layer, held by the\nserver; nothing is written to disk. `scale` (1..8) and "
                 "`margin` [x, y] (machine pixels on\neach side) say how the program's picture "
                 "sits on this machine's screen; maps and `add`'s\ncrops are in the program's "
                 "units. Reply: `path`, `application`, `mode`, `screens`, `controls`, `pointer`\n"
                 "(a map that declares the program's pointer)."),
    "MAP_SAVE": ("`save`: both layers as one map to `dest`, refused there without `overwrite`, "
                 "made the file\nlayer, in the loaded map's `mode` (`verified` when none was "
                 "loaded). Reply: `path`,\n`application`, `mode`, `screens`, `controls`, "
                 "`promoted`."),
    "MAP_CELLS": ("`add`'s `cells` `index` (a pixel screen; default\n`rgb`) signs the palette "
                  "indices drawn, not the colours shown, so one map knows a program\n"
                  "shown through two palettes; a screen with no palette refuses it "
                  "(`no_channel`)."),
    "MAP_ANCHOR": ("`add`'s `anchor` (a symbol or an address, as `run_to`'s `ref`) is the place "
                   "after which the screen is whole,\nwhat `run_to(screen=)` runs to: a "
                   "consolidated map refuses an `add` without one (`bad_argument`),\nsince it "
                   "enters its screens by theirs."),
    "MAP_FIND": ("Which mapped screen the machine shows. Reply: `matched`, `kind` and `size`; when "
                 "matched,\n`screen`, `layer`, `controls` (`name`, `rect`, `centre`), in the "
                 "program's units; when not,\n`screens_mapped` and, if the view fits the map, "
                 "`screens_tried` and `screens_unjudged`\n(signed by index on a screen whose pens "
                 "cannot be read), else `view_fits` false. None mapped:\n`needs_call`."),
    "MAP_RUN_TO": ("`screen`: a mapped screen's name instead of `ref` (exactly one). With an "
                   "`anchor`, run to it (`control`\nrequired): a `verified` map judges it there "
                   "(`stale_map` when it no longer holds), a\n`consolidated` one takes it as "
                   "shown. With none, a retrace (a frame, on MAME) at a time until the map "
                   "names it,\nwithin `seconds`; a `control` is refused there (`bad_argument`). "
                   "Reply: `screen` (`screen`, `layer`,\n`mode`, `judged`), `frames` run. "
                   "Refused: an unmapped screen (`unknown_ref`)."),
}


@dataclass(frozen=True)
class View:
    """How the program's picture sits on the machine's screen: each program unit `scale` machine
    units wide and high, `margin` machine units on each side."""

    scale: int = 1
    margin: tuple[int, int] = (0, 0)

    def machine_size(self, size: tuple[int, int]) -> tuple[int, int]:
        return (size[0] * self.scale + 2 * self.margin[0],
                size[1] * self.scale + 2 * self.margin[1])

    def aimed(self, point: list[int]) -> list[int]:
        """A program point as the machine unit at the middle of its block."""
        return [self.margin[i] + point[i] * self.scale + self.scale // 2 for i in (0, 1)]

    def program_size(self, grid: Grid) -> tuple[int, int] | None:
        """The program's size a read shows through this view, or None when it fits none."""
        w, h = (grid.width - 2 * self.margin[0], grid.height - 2 * self.margin[1])
        if w < 1 or h < 1 or w % self.scale or h % self.scale:
            return None
        return w // self.scale, h // self.scale

    def through(self, grid: Grid) -> Grid:
        """`grid` sampled into the program's units: the top-left machine unit of each block."""
        if self == View():
            return grid
        size = self.program_size(grid)
        assert size is not None     # judged by the caller, which names the screen
        width, height = size
        step = len(grid.cells) // (grid.width * grid.height)

        def sampled(data: bytes, unit: int) -> bytes:
            out = bytearray()
            for y in range(height):
                row = (self.margin[1] + y * self.scale) * grid.width + self.margin[0]
                for x in range(width):
                    at = (row + x * self.scale) * unit
                    out += data[at:at + unit]
            return bytes(out)
        return Grid(grid.kind, width, height, sampled(grid.cells, step),
                    None if grid.indices is None else sampled(grid.indices, 1))


def view(scale: object, margin: object) -> View:
    """A view as `load` takes it, judged."""
    if not judges.whole(scale, 1) or scale > SCALE_MAX:
        raise Invalid("bad_argument", f"`scale` is a whole number 1..{SCALE_MAX}, got {scale!r}")
    if margin is None:
        margin = [0, 0]
    if not (isinstance(margin, list | tuple) and len(margin) == 2
            and all(judges.whole(v, 0) for v in margin)):
        raise Invalid("bad_argument", f"`margin` is [x, y], each 0 or more, got {margin!r}")
    return View(scale, (int(margin[0]), int(margin[1])))


@dataclass(frozen=True)
class Grid:
    """One read of the screen: its kind, its size in its own units, its resolved cells as
    `raster.signature` takes them, and its palette indices (`index` cells) when asked for and
    the screen has them."""

    kind: raster.Kind
    width: int
    height: int
    cells: bytes
    indices: bytes | None = None


class Read(Protocol):
    """How a server reads its screen once, at a stopped machine; `indices` asks for the palette
    indices as well, which only a screen signed by index needs and some machines pay for."""

    def __call__(self, indices: bool = False) -> Grid: ...


@dataclass(frozen=True)
class Control:
    name: str
    rect: judges.Rect

    def centre(self) -> list[int]:
        x, y, w, h = self.rect
        return [x + w // 2, y + h // 2]

    def doc(self) -> dict[str, Any]:
        return {"name": self.name, "rect": list(self.rect)}


@dataclass(frozen=True)
class Screen:
    name: str
    kind: str
    size: tuple[int, int]
    match: tuple[tuple[judges.Rect, str], ...]
    controls: tuple[Control, ...]
    cells: str = "rgb"
    anchor: str = ""

    def doc(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "size": list(self.size),
                **({"cells": self.cells} if self.cells != "rgb" else {}),
                **({"anchor": self.anchor} if self.anchor else {}),
                "match": [{"crop": list(c), "signature": s} for c, s in self.match],
                "controls": [c.doc() for c in self.controls]}


@dataclass(frozen=True)
class Pointer:
    """Where the program keeps its own pointer, in the program's units: a ref for each axis (a
    symbol or `SEG:OFF`, as the server reads them) and the `bytes` each holds. A program that
    integrates the driver's motion into a pointer of its own and clamps it drifts from the
    driver's, so this is what a move is judged against."""

    x: str
    y: str
    bytes: int = 2

    def doc(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "bytes": self.bytes}


@dataclass(frozen=True)
class Found:
    """The most recent identification: the screen, its layer, and the stop it was read at (None
    when the server could not name that stop)."""

    screen: Screen
    layer: Layer
    stop: int | None


@dataclass
class Maps:
    """A server's two layers and its last identification, for the life of the server."""

    file: dict[str, Screen] = field(default_factory=dict)
    application: str = ""
    path: Path | None = None
    session: dict[str, Screen] = field(default_factory=dict)
    found: Found | None = None
    mode: str = "verified"
    view: View = View()
    pointer: Pointer | None = None

    def started(self) -> None:
        """A `start` succeeded: the session layer and the last identification were the old
        run's, the file layer stays."""
        self.session.clear()
        self.found = None

    def load(self, path_arg: object, scale: object = 1,
             margin: object = None) -> dict[str, Any]:
        """The file at `path_arg` as the file layer, replacing any loaded one, seen through
        `scale` and `margin`."""
        path = _map_path("path", path_arg)
        seen = view(scale, margin)
        try:
            if not path.is_file():
                raise Invalid("bad_argument", f"path: no map file at {path}")
            if path.stat().st_size > FILE_BYTES_MAX:
                raise Invalid("bad_argument", f"path: {path} is over {FILE_BYTES_MAX} bytes, "
                              "far past the most a map holds")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise Invalid("bad_argument", f"path: {path} cannot be read: {e}") from None
        try:
            doc = json.loads(text, object_pairs_hook=_unique_keys)
        except (ValueError, RecursionError) as e:   # JSONDecodeError is a ValueError
            raise Invalid("bad_argument", f"path: {path} is not a JSON map: {e}") from None
        application, mode, screens, pointer = parse(doc, str(path))
        if pointer and (seen.scale != 1 or any(seen.margin)):
            raise Invalid("bad_argument", f"path: {path} declares the program's pointer, which is "
                          "read in the program's units: load it at scale 1 and no margin, since "
                          "a view aims in the machine's")
        if application != _application(path):
            raise Invalid("bad_argument", f"path: {path} names application "
                          f"{_application(path)!r} and the file says {application!r}: a map is "
                          "named by the application it maps")
        if len(screens.keys() | self.session.keys()) > SCREENS_MAX:
            raise Invalid("bad_argument", f"path: {path} holds {len(screens)} screens and the "
                          f"session layer {len(self.session)} more, past the {SCREENS_MAX} a map "
                          "holds: save the session's first (`screen_map_write`, `save`), or "
                          "`start` again")
        self.file, self.application, self.path = screens, application, path
        self.mode, self.view, self.pointer = mode, seen, pointer
        self.found = None
        return {"path": str(path), "application": application, "mode": mode,
                "screens": len(screens),
                "controls": sum(len(s.controls) for s in screens.values()),
                **({"pointer": pointer.doc()} if pointer else {})}

    def add(self, name: object, match: object, controls: object, read: Read,
            cells: object = "rgb", anchor: object = "") -> dict[str, Any]:
        """A screen written from the screen in front of the caller: each `match` crop signed
        off one read, in `cells`, kept in the session layer; on a consolidated map it names the
        `anchor` it is entered by."""
        if not (isinstance(match, list) and match):
            raise Invalid("bad_argument", "match is a list of at least one crop [x, y, width, "
                          "height]: the stable regions the screen is known by")
        _cells(cells, "cells")
        if self.mode == "consolidated" and not anchor:
            raise Invalid("bad_argument", "the loaded map is consolidated, whose screens are "
                          "entered by their `anchor`: pass the symbol after which this screen is "
                          "whole")
        grid = read(indices=cells == "index")
        if grid.width < 1 or grid.height < 1:
            raise Invalid("unexpected_answer", f"the screen read is {grid.width}x{grid.height}: "
                          "there is nothing to map on it")
        if self.view.program_size(grid) is None:
            raise Invalid("unexpected_answer", f"the screen read is {grid.width}x{grid.height}, "
                          f"which does not fit the view the map was loaded through (scale "
                          f"{self.view.scale}, margin {list(self.view.margin)})")
        grid = self.view.through(grid)
        doc = {"name": name, "kind": grid.kind, "size": [grid.width, grid.height],
               "cells": cells, "match": [{"crop": c, "signature": "0" * 16} for c in match],
               "controls": controls if controls is not None else [],
               **({"anchor": anchor} if anchor else {})}
        screen = _screen(doc, "the screen", 0, "match")
        screen = dataclasses.replace(screen, match=tuple(
            (crop, _signed({}, grid, crop, screen.cells)) for crop, _ in screen.match))
        replaced = screen.name in self.session
        if len(self.session.keys() | self.file.keys() | {screen.name}) > SCREENS_MAX:
            raise Invalid("bad_argument", f"the map holds {SCREENS_MAX} screens, the most one "
                          "holds")
        self.session[screen.name] = screen
        if self.found is not None and self.found.screen.name == screen.name:
            self.found = None          # its controls are another screen's now: identify again
        return {"screen": screen.name, "kind": screen.kind, "size": list(screen.size),
                "cells": screen.cells,
                "match": [{"crop": list(c), "signature": s} for c, s in screen.match],
                "controls": len(screen.controls), "replaced": replaced,
                "shadows_file": screen.name in self.file,
                **({"anchor": screen.anchor} if screen.anchor else {})}

    def find(self, read: Read, stop: int | None) -> dict[str, Any]:
        """Which screen the machine shows, off ONE read: the session layer first, then the
        file's, each in its order; the first whose every region matches."""
        candidates: list[tuple[Layer, Screen]] = [
            *(("session", s) for s in self.session.values()),
            *(("file", s) for name, s in self.file.items() if name not in self.session)]
        if not candidates:
            raise Invalid("needs_call", "no screen is mapped: `screen_map_write` a map (`load`), "
                          "or the screen in front of you (`add`)")
        # FORGOTTEN BEFORE THE READ: a read that fails is no identification, and acting on the
        # screen the last one found would act on a screen nobody has seen since.
        self.found = None
        wants_pens = any(s.cells == "index" for _, s in candidates)
        try:
            shown = read(indices=wants_pens)
        except Invalid as e:
            if e.code != "no_channel" or not any(s.cells != "index" for _, s in candidates):
                raise
            shown = read(indices=False)     # pens it cannot name: the colour screens still judge
        fits = self.view.program_size(shown) is not None
        grid = self.view.through(shown) if fits else shown
        signed: dict[tuple[judges.Rect, str], str] = {}
        tried = unjudged = 0
        for layer, screen in candidates:
            if not fits or screen.kind != grid.kind or screen.size != (grid.width, grid.height):
                continue
            if screen.cells == "index" and grid.indices is None:
                unjudged += 1       # pens the machine could not give: judged by colours alone
                continue
            tried += 1
            if all(_signed(signed, grid, crop, screen.cells) == want
                   for crop, want in screen.match):
                self.found = Found(screen, layer, stop)
                return {"matched": True, "screen": screen.name, "layer": layer,
                        "kind": screen.kind, "size": list(screen.size),
                        "controls": [{"name": c.name, "rect": list(c.rect),
                                      "centre": c.centre()} for c in screen.controls]}
        self.found = None
        if not fits:
            return {"matched": False, "kind": shown.kind, "size": [shown.width, shown.height],
                    "view_fits": False, "screens_mapped": len(candidates)}
        return {"matched": False, "kind": shown.kind, "size": [shown.width, shown.height],
                "screens_tried": tried, "screens_unjudged": unjudged,
                "screens_mapped": len(candidates)}

    def save(self, dest: object, overwrite: bool) -> dict[str, Any]:
        """The file layer and the session layer written as one map to `dest`, the session
        winning, and made the file layer."""
        check_save(dest, overwrite)
        path = _map_path("dest", dest)
        merged = {**self.file, **self.session}
        if not merged:
            raise Invalid("needs_call", "no screen is mapped: `screen_map_write` the screen in "
                          "front of you (`add`), or a map (`load`), before saving one")
        application = _application(path)
        doc = {"format": FORMAT, "application": application, "mode": self.mode,
               **({"pointer": self.pointer.doc()} if self.pointer else {}),
               "screens": [s.doc() for s in merged.values()]}
        _consolidated_anchored(self.mode, merged.values(), str(path),
                               "`add` it again with one")
        data = (json.dumps(doc, indent=1) + "\n").encode()
        if overwrite:
            fresh.replace(path, data, "dest:")
        else:
            fresh.create(path, data, "the map", named_by_caller=True)
        promoted = sorted(self.session)
        self.file, self.application, self.path = merged, application, path
        self.session.clear()
        if self.found is not None and self.found.layer == "session":
            self.found = Found(self.found.screen, "file", self.found.stop)
        return {"path": str(path), "application": application, "mode": self.mode,
                "screens": len(merged),
                "controls": sum(len(s.controls) for s in merged.values()),
                "promoted": promoted}

    def _named(self, screen: str) -> tuple[Layer, Screen]:
        if screen in self.session:
            return "session", self.session[screen]
        if screen in self.file:
            return "file", self.file[screen]
        names = ", ".join([*self.session, *(n for n in self.file if n not in self.session)])
        raise Invalid("unknown_ref", f"screen={screen!r}: no screen {screen!r}; mapped: "
                      f"{names or 'none'}")

    def anchor(self, screen: str) -> str:
        """The symbol `screen` is whole after, which `run_to(screen=)` runs to."""
        _, found = self._named(screen)
        if not found.anchor:
            raise Invalid("needs_call", f"screen {screen!r} names no `anchor`: run to the "
                          "place it is drawn with `ref`, then `screen_map_find`")
        return found.anchor

    def is_anchored(self, screen: str) -> bool:
        """Whether `screen` names an `anchor`, the place a run to it goes to."""
        return bool(self._named(screen)[1].anchor)

    def arrived(self, screen: str, read: Read, stop: int | None) -> dict[str, Any]:
        """The machine stopped at `screen`'s anchor: a consolidated map takes the screen as
        shown, a verified one judges its signatures off one read."""
        layer, found = self._named(screen)
        self.found = None
        if self.mode == "verified":
            shown = read(indices=found.cells == "index")
            grid = self.view.through(shown) if self.view.program_size(shown) else None
            if grid is None or (found.kind, found.size) != (grid.kind, (grid.width, grid.height)) \
                    or (found.cells == "index" and grid.indices is None) \
                    or not all(_signed({}, grid, crop, found.cells) == want
                               for crop, want in found.match):
                raise Invalid("stale_map", f"screen {screen!r} no longer holds at its anchor "
                              f"{found.anchor}: the machine stopped there and its regions do "
                              "not match; map it again (`screen_map_write`, `add`)")
        self.found = Found(found, layer, stop)
        return {"screen": screen, "layer": layer, "mode": self.mode,
                "judged": self.mode == "verified"}

    def target(self, control: str) -> dict[str, Any]:
        """The centre of `control` on the screen the most recent `find` matched, with that
        screen, its kind and size (what an acting server holds the screen in front to), and the
        stop it was read at."""
        if self.found is None:
            raise Invalid("needs_call", "no screen is identified: `screen_map_find` at a stop "
                          "first, and act on the screen it matched")
        screen = self.found.screen
        for c in screen.controls:
            if c.name == control:
                return {"target": c.name, "centre": self.view.aimed(c.centre()),
                        "screen": screen.name, "kind": screen.kind,
                        "size": self.view.machine_size(screen.size),
                        "identified_at_stop": or_unavailable(
                            self.found.stop, "the stop it was identified at was not numbered "
                            "(its survey came back cut)")}
        names = ", ".join(c.name for c in screen.controls) or "none"
        raise Invalid("unknown_ref", f"target={control!r}: screen {screen.name!r} has no such "
                      f"control; its controls: {names}")


def at_anchor(maps: Maps, screen: str, reply: dict[str, Any], read: Read,
              stop: int | None) -> dict[str, Any]:
    """`run_to(screen=)`'s reply: an arrival judged as the map's mode says, carried as `screen`;
    a map gone stale refused with the stop kept; any other end forgets the last screen."""
    if reply.get("status") != "ok" or reply.get("verdict") != "TARGET":
        maps.found = None
        return reply
    try:
        return {**reply, "screen": maps.arrived(screen, read, stop)}
    except Invalid as e:
        kept = {k: v for k, v in reply.items() if k not in ("verdict", "summary", "status")}
        return e.reply(**kept)


def check_frame_run(screen: str, control: object) -> None:
    """A `control` on a run to a screen with no `anchor` has nothing to count: refused."""
    if control:
        raise Invalid("bad_argument", f"screen {screen!r} names no anchor, so it is run to a "
                      "frame at a time and a `control` has nothing to count: leave it out")


#: The least a frame is given when the bound is all but spent.
MIN_STEP_S = 0.001


def run_until(maps: Maps, screen: str, step: Callable[[float], dict[str, Any]], read: Read,
              seconds: float) -> dict[str, Any]:
    """`run_to(screen=)` for a screen with no `anchor`: `step(left)` runs the machine one frame
    within the `left` seconds of the bound and answers its stop, and the map judges the screen
    after each, so the run ends where the screen is whole. A stop `step` did not make as a frame
    ends it as it is; `seconds` of wall time bound it. The reply is the last stop's with
    `verdict` and `frames`, and on arrival `screen`."""
    maps.is_anchored(screen)              # an unmapped name is refused before a frame runs
    deadline = time.monotonic() + seconds
    frames = 0
    while True:
        reply = step(max(deadline - time.monotonic(), MIN_STEP_S))
        frames += 1
        if reply.get("status") != "ok" or reply.get("verdict") != "ELAPSED":
            maps.found = None
            return reply if reply.get("status") != "ok" else {**reply, "frames": frames}
        shown = maps.find(read, reply.get("stop_seq"))
        if shown.get("matched") and shown["screen"] == screen:
            return {**reply, "verdict": "TARGET", "frames": frames,
                    "screen": {"screen": screen, "layer": shown["layer"], "mode": maps.mode,
                               "judged": True}}
        if time.monotonic() >= deadline:
            maps.found = None
            return {**reply, "verdict": "TIMEOUT", "frames": frames}


def _signed(signed: dict[tuple[judges.Rect, str], str], grid: Grid, crop: judges.Rect,
            cells: str) -> str:
    """The signature of `crop` in `cells`, each signed once per read."""
    if (crop, cells) not in signed:
        if cells == "rgb":
            signed[crop, cells] = raster.signature(grid.kind, grid.width, grid.height,
                                                   grid.cells, crop)
        elif grid.indices is None:
            raise Invalid("no_channel", "the screen was read without palette indices, so a "
                          "screen signed by index cannot be matched or signed on it: the mode "
                          "shows colours with no palette")
        else:
            signed[crop, cells] = raster.signature("index", grid.width, grid.height,
                                                   grid.indices, crop)
    return signed[crop, cells]


def _cells(value: object, at: str) -> str:
    if value not in CELLS:
        raise Invalid("bad_argument", f"{at}: `cells` is `rgb` or `index`, got {value!r}")
    return value


def _map_path(name: str, value: object) -> Path:
    path = judges.absolute(name, value)
    if not path.name.endswith(SUFFIX) or not _name(_application(path)):
        raise Invalid("bad_argument", f"{name}: {path} is not named `<application>{SUFFIX}`, "
                      f"the application a name of 1..{_NAME_MAX} characters: the name a map is "
                      "kept by beside its program")
    return path


def _application(path: Path) -> str:
    """The application a map's file name says it maps."""
    return path.name[:-len(SUFFIX)]


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object whose keys are each said once: a repeated key is two answers, refused."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"the key {key!r} is said twice in one object")
        out[key] = value
    return out


def parse(doc: object, where: str) -> tuple[str, str, dict[str, Screen], Pointer | None]:
    """A map document's application, mode, screens in order and pointer, or the refusal naming
    the first fault."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise Invalid("bad_argument", f"{where} is not a {FORMAT} map")
    _keys(doc, {"format", "application", "mode", "screens"}, where, optional={"pointer"})
    application = doc.get("application")
    if not _name(application):
        raise Invalid("bad_argument", f"{where}: `application` is a name of 1..{_NAME_MAX} "
                      "characters")
    screens = doc.get("screens")
    if not isinstance(screens, list) or not screens:
        raise Invalid("bad_argument", f"{where}: `screens` is a list of at least one screen")
    if len(screens) > SCREENS_MAX:
        raise Invalid("bad_argument", f"{where}: {len(screens)} screens; a map holds at most "
                      f"{SCREENS_MAX}")
    out: dict[str, Screen] = {}
    for i, s in enumerate(screens):
        screen = _screen(s, where, i)
        if screen.name in out:
            raise Invalid("bad_argument", f"{where}: screen {i} is named {screen.name!r} again; "
                          "a screen's name is unique in its map")
        out[screen.name] = screen
    mode = doc.get("mode")
    if mode not in MODES:
        raise Invalid("bad_argument", f"{where}: `mode` is `verified` or `consolidated`, got "
                      f"{mode!r}: who answers for the map holding")
    _consolidated_anchored(cast(str, mode), out.values(), where, "name one in the file")
    return (cast(str, application), cast(str, mode), out,
            _pointer(doc["pointer"], where) if "pointer" in doc else None)


def _pointer(value: object, where: str) -> Pointer:
    """The `pointer` declaration, judged."""
    at = f"{where}: `pointer`"
    if not isinstance(value, dict):
        raise Invalid("bad_argument", f"{at} is an object: the refs of the program's own pointer")
    _keys(value, {"x", "y"}, f"{at}", optional={"bytes"})
    if "x" not in value or "y" not in value:
        raise Invalid("bad_argument", f"{at} needs `x` and `y`: a ref for each axis")
    for axis in ("x", "y"):
        ref = value[axis]
        if not isinstance(ref, str) or not ref.strip() or len(ref) > _NAME_MAX:
            raise Invalid("bad_argument", f"{where}: `pointer.{axis}` is a ref (a symbol or "
                          f"SEG:OFF) of 1..{_NAME_MAX} characters")
    width = value.get("bytes", 2)
    if not isinstance(width, int) or isinstance(width, bool) or width not in (1, 2, 4):
        raise Invalid("bad_argument", f"{where}: `pointer.bytes` is 1, 2 or 4, got {width!r}")
    return Pointer(value["x"], value["y"], width)


def _consolidated_anchored(mode: str, screens: Any, where: str, remedy: str) -> None:
    if mode != "consolidated":
        return
    for screen in screens:
        if not screen.anchor:
            raise Invalid("bad_argument", f"{where}: screen {screen.name!r} has no `anchor`, and "
                          f"a consolidated map's screens are entered by theirs: {remedy}")


def _screen(s: object, where: str, i: int, crop_name: str = "crop") -> Screen:
    """Screen `i` of a document, judged; `crop_name` is what a refusal calls a region's crop."""
    at = f"{where}: screen {i}"
    if not isinstance(s, dict):
        raise Invalid("bad_argument", f"{at} is not an object")
    _keys(s, {"name", "kind", "size", "cells", "anchor", "match", "controls"}, at)
    name = s.get("name")
    if not _name(name):
        raise Invalid("bad_argument", f"{at}: `name` is a name of 1..{_NAME_MAX} characters")
    at = f"{where}: screen {name!r}"
    kind = s.get("kind")
    if kind not in KINDS:
        raise Invalid("bad_argument", f"{at}: `kind` is `text` or `pixel`, got {kind!r}")
    cells = _cells(s.get("cells", "rgb"), at)
    anchor = s.get("anchor", "")
    if "anchor" in s and not _name(anchor):
        raise Invalid("bad_argument", f"{at}: `anchor` is a symbol or an address of "
                      f"1..{_NAME_MAX} characters")
    if cells == "index" and kind != "pixel":
        raise Invalid("bad_argument", f"{at}: `cells` index is a pixel screen's; a text screen "
                      "is signed by its cells")
    size = s.get("size")
    if not (isinstance(size, list) and len(size) == 2 and all(judges.whole(v, 1) for v in size)):
        raise Invalid("bad_argument", f"{at}: `size` is [width, height], each above zero")
    width, height = size
    what = f"screen {name!r} ({width}x{height})"
    match = s.get("match")
    if not (isinstance(match, list) and 0 < len(match) <= MATCH_MAX):
        raise Invalid("bad_argument", f"{at}: `match` is a list of 1..{MATCH_MAX} regions")
    regions: list[tuple[judges.Rect, str]] = []
    for j, m in enumerate(match):
        if not isinstance(m, dict):
            raise Invalid("bad_argument", f"{at}: match {j} is not an object")
        _keys(m, {"crop", "signature"}, f"{at}: match {j}")
        crop = raster.inside(_given(m, "crop", f"{at}: match {j}"), width, height, what,
                             f"{crop_name} {j}" if crop_name != "crop" else f"match {j} crop")
        sig = m.get("signature")
        if not (isinstance(sig, str) and _SIGNATURE.fullmatch(sig)):
            raise Invalid("bad_argument", f"{at}: match {j} signature is 16 lowercase hex "
                          f"characters (`screen_signature`'s), got {sig!r}")
        regions.append((crop, sig))
    controls = s.get("controls", [])
    if not (isinstance(controls, list) and len(controls) <= CONTROLS_MAX):
        raise Invalid("bad_argument", f"{at}: `controls` is a list of at most {CONTROLS_MAX}")
    kept: list[Control] = []
    for j, c in enumerate(controls):
        if not isinstance(c, dict):
            raise Invalid("bad_argument", f"{at}: control {j} is not an object")
        _keys(c, {"name", "rect"}, f"{at}: control {j}")
        cname = c.get("name")
        if not _name(cname):
            raise Invalid("bad_argument", f"{at}: control {j}'s `name` is a name of "
                          f"1..{_NAME_MAX} characters")
        if any(k.name == cname for k in kept):
            raise Invalid("bad_argument", f"{at}: control {cname!r} is named twice; a control's "
                          "name is unique in its screen")
        rect = raster.inside(_given(c, "rect", f"{at}: control {cname!r}"), width, height, what,
                             f"control {cname!r} rect")
        kept.append(Control(cast(str, cname), rect))
    return Screen(cast(str, name), cast(str, kind), (width, height), tuple(regions),
                  tuple(kept), cells, cast(str, anchor))


def _given(obj: dict[str, Any], key: str, at: str) -> Any:
    """`obj[key]`, which a region or a control must give: absent, `inside` would read the whole
    screen, and a map is never matched or aimed by the whole screen."""
    if obj.get(key) is None:
        raise Invalid("bad_argument", f"{at} has no `{key}` [x, y, width, height]")
    return obj[key]


def _name(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= _NAME_MAX
            and value == value.strip() and value.isprintable())


def _keys(obj: dict[str, Any], allowed: set[str], at: str,
          optional: frozenset[str] | set[str] = frozenset()) -> None:
    extra = sorted(set(obj) - allowed - optional)
    if extra:
        raise Invalid("bad_argument", f"{at} carries {extra}, which a {FORMAT} map does not "
                      f"have (it has {sorted(allowed | optional)})")


def load_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"{prose.counted(reply['screens'], 'screen')}, "
            f"{prose.counted(reply['controls'], 'control')} of {reply['application']}")


def add_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    w, h = reply["size"]
    shadow = ", shadowing the file's" if reply["shadows_file"] else ""
    return (f"{reply['screen']} ({reply['kind']} {w}x{h}), "
            f"{prose.counted(len(reply['match']), 'region')}, "
            f"{prose.counted(reply['controls'], 'control')}{shadow}")


def find_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if reply["matched"]:
        return (f"screen_map_find: {reply['screen']} ({reply['layer']}), "
                f"{prose.counted(len(reply['controls']), 'control')}")
    w, h = reply["size"]
    if reply.get("view_fits") is False:
        return (f"screen_map_find: the {reply['kind']} {w}x{h} screen does not fit the view the "
                "map was loaded through (`scale`, `margin`)")
    unjudged = reply.get("screens_unjudged", 0)
    return (f"screen_map_find: no screen matched the {reply['kind']} {w}x{h} screen "
            f"({prose.counted(reply['screens_mapped'], 'screen')} mapped, "
            f"{reply['screens_tried']} of that kind and size"
            + (f", {unjudged} more left unjudged: signed by index, on a screen whose pens "
               "cannot be read" if unjudged else "")
            + ")")


def save_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"{prose.counted(reply['screens'], 'screen')} to {Path(reply['path']).name}, "
            f"{len(reply['promoted'])} promoted from the session")


def check_path(name: str, value: object) -> None:
    """A map path argument's shape, judged before the machine."""
    _map_path(name, value)


def check_add(screen: object, match: object, controls: object = None,
              cells: object = "", anchor: object = "") -> None:
    """The `add` method's machine-independent half, everything but whether its rectangles lie on the
    screen, which only a read can say: the name, the crops' shapes, the controls' shapes, keys
    and names. A fault found here costs no read."""
    if not _name(screen):
        raise Invalid("bad_argument", f"screen={screen!r} is a name of 1..{_NAME_MAX} "
                      "characters")
    if not (isinstance(match, list) and 0 < len(match) <= MATCH_MAX):
        raise Invalid("bad_argument", f"match is a list of 1..{MATCH_MAX} crops [x, y, width, "
                      "height]: the stable regions the screen is known by")
    for j, crop in enumerate(match):
        judges.rect(f"match {j}", crop)
    if controls is not None and not (isinstance(controls, list)
                                     and len(controls) <= CONTROLS_MAX):
        raise Invalid("bad_argument", f"controls is a list of at most {CONTROLS_MAX} "
                      "{\"name\", \"rect\"}")
    _screen({"name": screen, "kind": "pixel", "size": [_ANY_SIDE, _ANY_SIDE],
             "cells": cells or "rgb",
             "match": [{"crop": c, "signature": "0" * 16} for c in match],
             "controls": controls if controls is not None else [],
             **({"anchor": anchor} if anchor else {})}, "the screen", 0, "match")


def check_save(dest: object, overwrite: object) -> None:
    """The `save` method's machine-independent half: `dest`, and `overwrite` a yes or a no."""
    _map_path("dest", dest)
    vocab.check_bool("overwrite", overwrite)



def check_run_to(ref: object, screen: object) -> None:
    """`run_to`'s target: a `ref` or a mapped `screen`, exactly one."""
    named = [k for k, v in (("ref", ref), ("screen", screen)) if isinstance(v, str) and v.strip()]
    if len(named) != 1:
        raise Invalid("bad_argument", "run_to needs a `ref` (a symbol or an address) or a "
                      "`screen` (a mapped screen, run to its anchor or by frames), exactly one; "
                      "got "
                      f"{' and '.join(named) or 'neither'}")
    if named == ["screen"] and not _name(screen):
        raise Invalid("bad_argument", f"screen={screen!r} is a name of 1..{_NAME_MAX} "
                      "characters")


def run_to_named(args: dict[str, Any], reply: dict[str, Any]) -> str:
    """What a `run_to` summary names: its `ref`, or the screen and how its arrival was taken."""
    if args.get("ref"):
        return str(args["ref"])
    arrived = reply.get("screen")
    how = ("" if not isinstance(arrived, dict) else
           " (judged)" if arrived.get("judged") else " (taken as shown)")
    return f"screen {args.get('screen', '')}{how}"
