"""A server's tools BY FAMILY, the one table its `instructions` render their roster and their
"answers while it runs" sentence from: a family every member of which answers a running machine
is named once, whole, instead of tool by tool, and the table partitions what the server
registers, which each server's suite holds it to (`unlisted`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


def listed(names: Iterable[str]) -> str:
    """Names as a roster lists them: plain, since every word of the list is a tool's name and the
    client's cap is counted on every character."""
    return ", ".join(names)


@dataclass(frozen=True)
class Roster:
    """`families`, `(name, tools)` in the order the instructions list them, and `answering`,
    what a refusal for a running machine names as answering (a tool, or a call spelled with its
    argument, such as `registers(from_last_stop=True)`)."""

    families: tuple[tuple[str, tuple[str, ...]], ...]
    answering: tuple[str, ...]

    def text(self) -> str:
        """The roster: `Family: a, b.` per family."""
        return " ".join(f"{name}: {listed(tools)}." for name, tools in self.families)

    def answering_split(self) -> tuple[list[str], list[str]]:
        """The families every member of which answers a running machine, and the other names
        that do, in roster order with what no family holds last."""
        running = set(self.answering)
        whole = [name for name, tools in self.families if running >= set(tools)]
        rest = [t for name, tools in self.families if name not in whole for t in tools
                if t in running]
        held = {t for _, tools in self.families for t in tools}
        return whole, rest + [t for t in self.answering if t not in held]

    def answering_named(self) -> set[str]:
        """Every name the running sentence covers, its whole families expanded."""
        whole, rest = self.answering_split()
        return {t for name, tools in self.families if name in whole for t in tools} | set(rest)

    def running_sentence(self) -> str:
        """`these answer: A and B whole, and x, y.`, each half only when it names
        something."""
        whole, rest = self.answering_split()
        parts = []
        if whole:
            head = ", ".join(whole[:-1])
            parts.append(f"{head} and {whole[-1]} whole" if head else f"{whole[-1]} whole")
        if rest:
            parts.append(listed(rest))
        return f"these answer: {', and '.join(parts)}."

    def unlisted(self, registered: Iterable[str]) -> list[str]:
        """What breaks the partition: a registered tool no family holds, one a family holds that
        is not registered, or one two families hold. Empty when the table is the registry."""
        listed = [t for _, tools in self.families for t in tools]
        twice = sorted({t for t in listed if listed.count(t) > 1})
        return ([f"held twice: {t}" for t in twice]
                + [f"in no family: {t}" for t in sorted(set(registered) - set(listed))]
                + [f"not registered: {t}" for t in sorted(set(listed) - set(registered))])
