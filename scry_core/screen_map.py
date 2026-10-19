"""Screen maps: which screen of an application the machine shows, and where its controls are, so a
caller names a control instead of a coordinate and a screen is recognised without a picture
crossing the conversation. No emulator here: a server hands in one read of its screen.

THE FILE is JSON, `"format": "scry-map/1"`, named `<application>.scry-map.json` and kept beside
the program in the application's own repository:

    {"format": "scry-map/1", "application": "bricks",
     "screens": [{"name": "play", "kind": "pixel", "size": [320, 200],
                  "match": [{"crop": [0, 0, 320, 8], "signature": "<16 hex>"}],
                  "controls": [{"name": "paddle", "rect": [140, 180, 40, 8]}]}]}

in the screen's own units: cells in a text mode, pixels in a graphics one, as `screen_view`
counts them. A screen MATCHES when its `kind` and `size` are the screen's and every `match`
signature is `scry-sig/1` (`raster.signature`) over its crop. The key is a set of declared
stable regions, never the whole screen, because a whole-screen hash changes with a cursor or a
ball. Names are unique in the file (screens) and in their screen (controls), every rectangle
lies inside its screen, and a file that breaks any of it is refused whole, naming the first
fault: a map half believed would match a screen it does not describe.

TWO LAYERS, both living for the server's session: the FILE layer (`load`) and the SESSION layer
(`add`, written from the screen in front of the caller), the session's screens tried first and
shadowing a file screen of the same name. `save` writes the two as one file, the session
winning, and that file becomes the file layer: the promotion. A successful `start` empties the
session layer (its screens were read off another run) and keeps the file layer.

ONE SCREEN READ PER IDENTIFICATION. `find` reads the screen once and cuts every candidate's
crops from that read, each distinct crop signed once, kind and size compared before any hash:
on MAME each read is a Lua call, and a map of many screens must not cost one per screen.

A CONTROL IS NAMED AGAINST THE IDENTIFICATION IT CAME FROM, the way a browser automation `ref`
is valid against the snapshot it was read from: `target` answers the centre of a control of the
screen the most recent `find` matched, with the stop that `find` read at, because a running guest
cannot be read at the moment a pointer moves.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from scry_core import fresh, judges, raster
from scry_core.reply_contract import Invalid

FORMAT = "scry-map/1"
SUFFIX = ".scry-map.json"
KINDS = ("text", "pixel")
#: How much one map holds: screens in a file, regions a screen is matched by, controls on one.
SCREENS_MAX, MATCH_MAX, CONTROLS_MAX = 200, 16, 100
#: The largest map file read: far past the most screens it can hold, so a file past it is not one.
FILE_BYTES_MAX = 4 * 1024 * 1024
_SIGNATURE = re.compile(r"[0-9a-f]{16}")
_NAME_MAX = 64

Layer = Literal["session", "file"]


@dataclass(frozen=True)
class Grid:
    """One read of the screen: its kind, its size in its own units, and its resolved cells as
    `raster.signature` takes them."""

    kind: raster.Kind
    width: int
    height: int
    cells: bytes


#: How a server reads its screen once, at a stopped machine.
Read = Callable[[], Grid]


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

    def doc(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "size": list(self.size),
                "match": [{"crop": list(c), "signature": s} for c, s in self.match],
                "controls": [c.doc() for c in self.controls]}


@dataclass(frozen=True)
class Found:
    """The most recent identification: the screen, its layer, and the stop it was read at."""

    screen: Screen
    layer: Layer
    stop: int


@dataclass
class Maps:
    """A server's two layers and its last identification, for the life of the server."""

    file: dict[str, Screen] = field(default_factory=dict)
    application: str = ""
    path: Path | None = None
    session: dict[str, Screen] = field(default_factory=dict)
    found: Found | None = None

    def started(self) -> None:
        """A `start` succeeded: the session layer and the last identification were the old
        run's, the file layer stays."""
        self.session.clear()
        self.found = None

    def load(self, path_arg: object) -> dict[str, Any]:
        """The file at `path_arg` as the file layer, replacing any loaded one."""
        path = _map_path("path", path_arg)
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
        application, screens = parse(doc, str(path))
        if application != _application(path):
            raise Invalid("bad_argument", f"path: {path} names application "
                          f"{_application(path)!r} and the file says {application!r}: a map is "
                          "named by the application it maps")
        self.file, self.application, self.path = screens, application, path
        self.found = None
        return {"path": str(path), "application": application, "screens": len(screens),
                "controls": sum(len(s.controls) for s in screens.values())}

    def add(self, name: object, match: object, controls: object, read: Read) -> dict[str, Any]:
        """A screen written from the screen in front of the caller: each `match` crop signed
        off one read, kept in the session layer."""
        if not (isinstance(match, list) and match):
            raise Invalid("bad_argument", "match is a list of at least one crop [x, y, width, "
                          "height]: the stable regions the screen is known by")
        grid = read()
        if grid.width < 1 or grid.height < 1:
            raise Invalid("unexpected_answer", f"the screen read is {grid.width}x{grid.height}: "
                          "there is nothing to map on it")
        doc = {"name": name, "kind": grid.kind, "size": [grid.width, grid.height],
               "match": [{"crop": c, "signature": "0" * 16} for c in match],
               "controls": controls if controls is not None else []}
        screen = _screen(doc, "the screen", 0, "match")
        signed = tuple((crop, raster.signature(grid.kind, grid.width, grid.height, grid.cells,
                                               crop)) for crop, _ in screen.match)
        screen = Screen(screen.name, screen.kind, screen.size, signed, screen.controls)
        replaced = screen.name in self.session
        if len(self.session.keys() | self.file.keys() | {screen.name}) > SCREENS_MAX:
            raise Invalid("bad_argument", f"the map holds {SCREENS_MAX} screens, the most one "
                          "holds")
        self.session[screen.name] = screen
        return {"screen": screen.name, "kind": screen.kind, "size": list(screen.size),
                "match": [{"crop": list(c), "signature": s} for c, s in screen.match],
                "controls": len(screen.controls), "replaced": replaced,
                "shadows_file": screen.name in self.file}

    def find(self, read: Read, stop: int) -> dict[str, Any]:
        """Which screen the machine shows, off ONE read: the session layer first, then the
        file's, each in its order; the first whose every region matches."""
        candidates: list[tuple[Layer, Screen]] = [
            *(("session", s) for s in self.session.values()),
            *(("file", s) for name, s in self.file.items() if name not in self.session)]
        if not candidates:
            raise Invalid("needs_call", "no screen is mapped: `map_load` a map, or `map_add` the "
                          "screen in front of you")
        grid = read()
        signed: dict[judges.Rect, str] = {}
        tried = 0
        for layer, screen in candidates:
            if screen.kind != grid.kind or screen.size != (grid.width, grid.height):
                continue
            tried += 1
            if all(_signed(signed, grid, crop) == want for crop, want in screen.match):
                self.found = Found(screen, layer, stop)
                return {"matched": True, "screen": screen.name, "layer": layer,
                        "kind": screen.kind, "size": list(screen.size),
                        "controls": [{"name": c.name, "rect": list(c.rect),
                                      "centre": c.centre()} for c in screen.controls]}
        self.found = None
        return {"matched": False, "kind": grid.kind, "size": [grid.width, grid.height],
                "screens_tried": tried, "screens_mapped": len(candidates)}

    def save(self, path_arg: object, overwrite: bool) -> dict[str, Any]:
        """The file layer and the session layer written as one map, the session winning, and
        made the file layer."""
        path = _map_path("path", path_arg)
        if not isinstance(overwrite, bool):
            raise Invalid("bad_argument", f"overwrite={overwrite!r} is true or false")
        merged = {**self.file, **self.session}
        if not merged:
            raise Invalid("needs_call", "no screen is mapped: `map_add` the screen in front of "
                          "you, or `map_load` a map, before saving one")
        application = _application(path)
        doc = {"format": FORMAT, "application": application,
               "screens": [s.doc() for s in merged.values()]}
        data = (json.dumps(doc, indent=1) + "\n").encode()
        if overwrite:
            _replace(path, data)
        else:
            fresh.create(path, data, "the map", named_by_caller=True)
        promoted = sorted(self.session)
        self.file, self.application, self.path = merged, application, path
        self.session.clear()
        if self.found is not None and self.found.layer == "session":
            self.found = Found(self.found.screen, "file", self.found.stop)
        return {"path": str(path), "application": application, "screens": len(merged),
                "controls": sum(len(s.controls) for s in merged.values()),
                "promoted": promoted}

    def target(self, control: str) -> dict[str, Any]:
        """The centre of `control` on the screen the most recent `find` matched, with that
        screen and the stop it was read at."""
        if self.found is None:
            raise Invalid("needs_call", "no screen is identified: `map_find` at a stop first, "
                          "and act on the screen it matched")
        screen = self.found.screen
        for c in screen.controls:
            if c.name == control:
                return {"target": c.name, "centre": c.centre(), "screen": screen.name,
                        "identified_at_stop": self.found.stop}
        names = ", ".join(c.name for c in screen.controls) or "none"
        raise Invalid("unknown_ref", f"target={control!r}: screen {screen.name!r} has no such "
                      f"control; its controls: {names}")


def _signed(signed: dict[judges.Rect, str], grid: Grid, crop: judges.Rect) -> str:
    if crop not in signed:
        signed[crop] = raster.signature(grid.kind, grid.width, grid.height, grid.cells, crop)
    return signed[crop]


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


def _replace(path: Path, data: bytes) -> None:
    """`data` at `path`, over what is there, whole or not at all: written beside it, then
    renamed over it, so a reader never meets half a map."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        if path.is_dir():
            raise Invalid("bad_argument", f"path: {path} is a directory")
        fresh.create(tmp, data, "the map", named_by_caller=True)
        os.replace(tmp, path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise Invalid("bad_argument", f"path: {path} cannot be written: {e}") from None


def parse(doc: object, where: str) -> tuple[str, dict[str, Screen]]:
    """A `scry-map/1` document's application and screens, in order, or the refusal naming the
    first fault."""
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise Invalid("bad_argument", f"{where} is not a {FORMAT} map")
    _keys(doc, {"format", "application", "screens"}, where)
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
    return cast(str, application), out


def _screen(s: object, where: str, i: int, crop_name: str = "crop") -> Screen:
    """Screen `i` of a document, judged; `crop_name` is what a refusal calls a region's crop."""
    at = f"{where}: screen {i}"
    if not isinstance(s, dict):
        raise Invalid("bad_argument", f"{at} is not an object")
    _keys(s, {"name", "kind", "size", "match", "controls"}, at)
    name = s.get("name")
    if not _name(name):
        raise Invalid("bad_argument", f"{at}: `name` is a name of 1..{_NAME_MAX} characters")
    at = f"{where}: screen {name!r}"
    kind = s.get("kind")
    if kind not in KINDS:
        raise Invalid("bad_argument", f"{at}: `kind` is `text` or `pixel`, got {kind!r}")
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
                  tuple(kept))


def _given(obj: dict[str, Any], key: str, at: str) -> Any:
    """`obj[key]`, which a region or a control must give: absent, `inside` would read the whole
    screen, and a map is never matched or aimed by the whole screen."""
    if obj.get(key) is None:
        raise Invalid("bad_argument", f"{at} has no `{key}` [x, y, width, height]")
    return obj[key]


def _name(value: object) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= _NAME_MAX
            and value == value.strip() and value.isprintable())


def _keys(obj: dict[str, Any], allowed: set[str], at: str) -> None:
    extra = sorted(set(obj) - allowed)
    if extra:
        raise Invalid("bad_argument", f"{at} carries {extra}, which a {FORMAT} map does not "
                      f"have (it has {sorted(allowed)})")


def counted(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def load_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"map_load: {counted(reply['screens'], 'screen')}, "
            f"{counted(reply['controls'], 'control')} of {reply['application']}")


def add_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    w, h = reply["size"]
    shadow = ", shadowing the file's" if reply["shadows_file"] else ""
    return (f"map_add: {reply['screen']} ({reply['kind']} {w}x{h}), "
            f"{counted(len(reply['match']), 'region')}, "
            f"{counted(reply['controls'], 'control')}{shadow}")


def find_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    if reply["matched"]:
        return (f"map_find: {reply['screen']} ({reply['layer']}), "
                f"{counted(len(reply['controls']), 'control')}")
    w, h = reply["size"]
    return (f"map_find: no screen matched the {reply['kind']} {w}x{h} screen "
            f"({counted(reply['screens_mapped'], 'screen')} mapped, "
            f"{reply['screens_tried']} of that kind and size)")


def save_line(args: dict[str, Any], reply: dict[str, Any]) -> str:
    return (f"map_save: {counted(reply['screens'], 'screen')} to {Path(reply['path']).name}, "
            f"{len(reply['promoted'])} promoted from the session")


def check_path(name: str, value: object) -> None:
    """A map path argument's shape, judged before the machine."""
    _map_path(name, value)


def check_add(screen: object, match: object, controls: object = None) -> None:
    """`map_add`'s machine-independent half: the name, the crops' shapes and the controls'."""
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

