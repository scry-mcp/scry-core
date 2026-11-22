"""The chips and cpus every server that loads `chips/` and `cpus/` declares, and the pins of the
sources their entries cite."""

from __future__ import annotations

from importlib import resources

from scry_core.knowledge.confirmed import Confirmation, SecondCheck, parse_second_check
from scry_core.knowledge.lock import Lock, parse_lock
from scry_core.knowledge.support import NAMED, Chip, Scope

_INDEX = "knowledge_index"

#: `rbil61` has no pin: its archives are checked by hash.
PINS = {
    "dosbox-x": "2a43c7335efd91f87bf5582245abdd5b3f18d5d4",
    "mame": "ab06a77f0ffa227a481629d8a6135a786ef5cabe",
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


def locks() -> tuple[Lock, ...]:
    """The locks of the shared dictionaries: the chips' and the cpus'."""
    folder = resources.files("scry_core") / _INDEX
    return tuple(parse_lock((folder / name).read_text(encoding="utf-8"), name)
                 for name in ("shared-lock.json", "cpus-lock.json"))


def second_check() -> SecondCheck:
    """What the second check confirmed of the shared dictionaries."""
    name = "second-check.json"
    return parse_second_check((resources.files("scry_core") / _INDEX / name).read_text(
        encoding="utf-8"), name)


def confirmation() -> Confirmation:
    """The shared dictionaries' own confirmation, for a server that loads no dictionary of its
    own; one that does adds its lock and its second check to `Confirmation.of`."""
    return Confirmation.of(locks(), (second_check(),))
