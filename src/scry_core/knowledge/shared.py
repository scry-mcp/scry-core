"""The chips and cpus every server that loads `chips/` and `cpus/` declares, the pins of the
sources their entries cite, and the lock and quote index of the shared dictionaries."""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from scry_core.knowledge.support import NAMED, Chip, Scope

if TYPE_CHECKING:
    from scry_core.knowledge import quote, sealed

_INDEX = "knowledge_index"

#: `rbil61` has no pin: its archives are checked by hash.
PINS = {
    "dosbox-x": "2a43c7335efd91f87bf5582245abdd5b3f18d5d4",
    "mame": "mame0289",
}

CHIPS: tuple[Chip, ...] = (
    Chip("pit8253", written=("register",), types=("pit8253", "pit8254")),
    Chip("pic8259", written=("register", "command"), types=("pic8259",)),
    Chip("am9517a", written=("register",), types=("am9517a",)),
    Chip("ins8250", written=("register",), types=("ins8250", "ns16450", "ns16550")),
    Chip("mc146818", written=("register",), types=("mc146818",)),
    Chip("mc6845", written=("register",), types=("mc6845",)),
    Chip("ym3812", written=("register",), types=("ym3812",)),
    Chip("ymf262", written=("register",), types=("ymf262",)),
    Chip(
        "sn76496",
        written=("register",),
        types=(
            "sn76496",
            "y2404",
            "sn76489",
            "sn76489a",
            "sn76494",
            "sn94624",
            "ncr8496",
            "pssj3",
            "gamegear_psg",
            "segapsg",
        ),
    ),
    Chip("saa1099", written=("register",), types=("saa1099",)),
)

CPUS: tuple[Scope, ...] = (Scope("z80", written=("vector",), types=("z80",), support=NAMED),)


def rows_lock() -> sealed.Lock:
    """The seals of the shared dictionaries of rows."""
    from scry_core.knowledge import sealed
    name = "rows-lock.json"
    return sealed.parse_lock((resources.files("scry_core") / _INDEX / name).read_text(
        encoding="utf-8"), name)


def rows_index() -> quote.Quotes:
    """The index of the shared dictionaries of rows: every quote's lines and their digest."""
    from scry_core.knowledge import quote
    name = quote.QUOTES_NAME
    return quote.parse_quotes((resources.files("scry_core") / _INDEX / name).read_text(
        encoding="utf-8"), name)
