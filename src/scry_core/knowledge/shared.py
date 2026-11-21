"""The chips and cpus every server that loads `chips/` and `cpus/` declares, and the pins of the
sources their entries cite."""

from __future__ import annotations

from scry_core.knowledge.support import NAMED, Chip, Scope

#: `rbil61` has no pin: its archives are checked by hash.
PINS = {
    "dosbox-x": "054925019180170303ee2cfef1e4aee2d82f07e4",
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
