"""A name as a summary writes it: cut to `NAME_WIDTH`, printable ASCII, with its offset."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scry_core.naming import Named

NAME_WIDTH = 24
CUT = ".."
_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def name_text(named: Named) -> str:
    name = _printable(" ".join(named.name.split()))
    name = name if len(name) <= NAME_WIDTH else name[:NAME_WIDTH - len(CUT)] + CUT
    return f"{name}+0x{named.delta:X}" if named.delta else name


def _printable(s: str) -> str:
    return "".join(_ESCAPES.get(c, c if " " <= c <= "~" else "?") for c in s)
