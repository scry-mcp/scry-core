"""What a server declares it supports: the only place a cpu, system, device or chip is added."""

from __future__ import annotations

from dataclasses import dataclass, field

from scry_core.knowledge import keys

SUPPORTED = "supported"
#: Named in the base; the server claims nothing about running it.
NAMED = "named"
SUPPORT_CLASSES = (SUPPORTED, NAMED)


@dataclass(frozen=True)
class Scope:
    """A system or a cpu, the kinds it owes dictionaries of, and whether the server runs it."""

    name: str
    written: tuple[str, ...] = ()
    generated: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    support: str = SUPPORTED


@dataclass(frozen=True)
class Device:
    """A device: its entry, its dictionaries, the devices inside it."""

    name: str
    written: tuple[str, ...] = ()
    inside: tuple[str, ...] = ()
    placed_only: str = ""


@dataclass(frozen=True)
class Chip:
    """A chip described once for every board: its entry in scope `chip` and its dictionaries."""

    name: str
    written: tuple[str, ...] = ()
    types: tuple[str, ...] = ()


@dataclass(frozen=True)
class Support:
    """The declaration, and the kinds read from any machine, which owe no dictionary."""

    scopes: tuple[Scope, ...] = ()
    devices: tuple[Device, ...] = ()
    chips: tuple[Chip, ...] = ()
    live: tuple[str, ...] = field(default_factory=tuple)

    def held(self) -> list[str]:
        """Every scope answered for."""
        return [s.name for s in self.scopes]

    def claims(self, scope: str) -> bool:
        """Declared, and not only named."""
        return any(s.name == scope and s.support == SUPPORTED for s in self.scopes)

    def names(self) -> set[str]:
        """What a dictionary may take as its scope."""
        return ({s.name for s in self.scopes} | {d.name for d in self.devices}
                | {c.name for c in self.chips} | ({"chip"} if self.chips else set()))

    def faults(self) -> list[str]:
        """What is wrong in the declaration, one line each."""
        out: list[str] = []
        taken: list[str] = [*(s.name for s in self.scopes), *(d.name for d in self.devices),
                            *(c.name for c in self.chips)]
        out += [f"{n} is declared twice" for n in sorted({n for n in taken if taken.count(n) > 1})]
        for s in self.scopes:
            if s.support not in SUPPORT_CLASSES:
                out.append(f"scope {s.name}: support is {' or '.join(SUPPORT_CLASSES)}, "
                           f"not {s.support!r}")
        owing: list[tuple[str, tuple[str, ...]]] = [
            (s.name, s.written + s.generated) for s in self.scopes]
        owing += [(d.name, d.written) for d in self.devices]
        owing += [(c.name, c.written) for c in self.chips]
        owing.append(("live", self.live))
        for who, kinds in owing:
            out += [f"{who}: {k!r} is not a kind ({', '.join(keys.KINDS)})"
                    for k in kinds if k not in keys.KINDS]
        return out
