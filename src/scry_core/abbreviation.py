"""A call as its overlay caption reads: the tool, then its values in signature order, each cut
to `VALUE_WIDTH`; a path by its last name, a home as `~`, so no user name reaches the window;
`*_hex` bytes by the first few and `+N`. Printable ASCII, for the VGA ROM font."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VALUE_WIDTH = 20
BYTES_SHOWN = 4
ITEMS_SHOWN = 4
DEPTH_SHOWN = 3
CUT = ".."
HEX_SUFFIX = "_hex"
_HOMES = frozenset({"users", "home", "documents and settings"})
_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def caption(tool: str, given: Mapping[str, Any]) -> str:
    """`tool` and each value given that is neither None nor empty."""
    return " ".join([tool, *(value(_hex(v) if n.endswith(HEX_SUFFIX) else v)
                             for n, v in given.items() if v is not None and v != "")])


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
