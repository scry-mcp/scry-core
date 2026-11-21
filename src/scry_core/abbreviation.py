"""A call as its overlay caption reads: the tool, then its values in signature order, each cut
to `VALUE_WIDTH`; a path by its last name, a home as `~`, so no user name reaches the window;
`*_hex` bytes by the first few and `+N`. Printable ASCII, for the VGA ROM font.

A value the server could name reads `name (number)`: the name cut to `NAME_WIDTH`, the number never
cut, because a cut number is a wrong number. The whole caption is at most `MAX_BYTES`, the wire's
limit: names fall back to their bare values from the last to the first, and only then is the tail
cut.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scry_core.naming import Named

VALUE_WIDTH = 20
NAME_WIDTH = 24
MAX_BYTES = 160
BYTES_SHOWN = 4
ITEMS_SHOWN = 4
DEPTH_SHOWN = 3
CUT = ".."
HEX_SUFFIX = "_hex"
_HOMES = frozenset({"users", "home", "documents and settings"})
_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def caption(tool: str, given: Mapping[str, Any],
            named: Mapping[str, Named] | None = None) -> str:
    """`tool` and each value given that is neither None nor empty, a value `named` reading
    `name (number)`; at most `MAX_BYTES`."""
    given_values = [(n, v) for n, v in given.items() if v is not None and v != ""]
    bare = [value(_hex(v) if n.endswith(HEX_SUFFIX) else v) for n, v in given_values]
    words = list(bare)
    held = [i for i, (n, _) in enumerate(given_values) if named is not None and n in named]
    for i in held:
        words[i] = _named(named[given_values[i][0]]) if named is not None else bare[i]
    text = " ".join([tool, *words])
    while len(text) > MAX_BYTES and held:
        i = held.pop()
        words[i] = bare[i]
        text = " ".join([tool, *words])
    return fit(text, MAX_BYTES)


def fit(text: str, room: int) -> str:
    """`text` cut to `room` characters, the cut marked."""
    return text if len(text) <= room else text[:max(0, room - len(CUT))] + CUT


def name_text(named: Named) -> str:
    """A name as a caption or a summary writes it: cut to `NAME_WIDTH`, then `+0x<delta>` when it
    is inside a symbol or a range."""
    name = _printable(" ".join(named.name.split()))
    name = name if len(name) <= NAME_WIDTH else name[:NAME_WIDTH - len(CUT)] + CUT
    return f"{name}+0x{named.delta:X}" if named.delta else name


def _named(named: Named) -> str:
    return f"{name_text(named)} ({_printable(named.number)})"


def value(v: object, depth: int = 0) -> str:
    """At most `VALUE_WIDTH` characters; `?` when it cannot be written."""
    try:
        return _cut(_text(v, depth))
    except Exception:  # a caption never fails the call it names
        return "?"


def _text(v: object, depth: int) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return _bytes(bytes(v))
    if isinstance(v, str):
        return _printable(_basename(v))
    if isinstance(v, (Mapping, list, tuple)) and depth >= DEPTH_SHOWN:
        return CUT
    if isinstance(v, Mapping):
        items = list(v.items())
        shown = " ".join(f"{_printable(_basename(str(k)))}={value(x, depth + 1)}"
                         for k, x in items[:ITEMS_SHOWN])
        more = f" +{len(items) - ITEMS_SHOWN}" if len(items) > ITEMS_SHOWN else ""
        return "{" + shown + more + "}"
    if isinstance(v, (list, tuple)):
        return _items(v, depth)
    return _printable(_basename(str(v)))


def _basename(s: str) -> str:
    """The last component; a home (a name after `_HOMES`, or `~name`) is `~`."""
    if s.startswith("~") and "/" not in s and "\\" not in s:
        return "~"
    if "/" not in s and "\\" not in s:
        return s
    parts = [p for p in s.replace("\\", "/").split("/") if p]
    if not parts:
        return s
    if len(parts) == 1 and parts[0].startswith("~") or (
            len(parts) > 1 and parts[-2].strip().lower() in _HOMES):
        return "~"
    return parts[-1]


def _hex(v: object) -> object:
    if not isinstance(v, str):
        return v
    try:
        return bytes.fromhex(v)
    except ValueError:
        return v


def _bytes(b: bytes) -> str:
    shown = " ".join(f"{x:02X}" for x in b[:BYTES_SHOWN])
    return shown if len(b) <= BYTES_SHOWN else f"{shown} +{len(b) - BYTES_SHOWN}"


def _items(v: list[Any] | tuple[Any, ...], depth: int) -> str:
    shown = ",".join(value(x, depth + 1) for x in v[:ITEMS_SHOWN])
    return f"[{shown}]" if len(v) <= ITEMS_SHOWN else f"[{shown},+{len(v) - ITEMS_SHOWN}]"


def _printable(s: str) -> str:
    return "".join(_ESCAPES.get(c, c if " " <= c <= "~" else "?") for c in s)


def _cut(s: str) -> str:
    return s if len(s) <= VALUE_WIDTH else s[:VALUE_WIDTH - len(CUT)] + CUT
