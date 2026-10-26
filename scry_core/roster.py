"""A server's tools by family: the table its instructions render the roster from."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


def listed(names: Iterable[str]) -> str:
    """Names joined plain: the client's cap counts every character."""
    return ", ".join(names)


def by_method(running_ok: Iterable[str], methods: Mapping[str, Iterable[str]]) -> set[str]:
    """Names a running machine answers; a fold answering by some methods names them."""
    return ({op for op in running_ok if op not in methods}
            | {f"{op}(method={'|'.join(ok)})" for op, ok in methods.items()})


@dataclass(frozen=True)
class RunningGate:
    """What a sequence step may run on a running machine: `ops` whole, a fold by its `methods`,
    and a gesture `needs_stop` says needs a stop. The last stop's registers answer on any server,
    since they read no cpu."""

    ops: frozenset[str]
    methods: Mapping[str, tuple[str, ...]]
    needs_stop: Mapping[str, Callable[[dict[str, Any]], bool]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if stray := sorted(set(self.methods) - self.ops):
            raise ValueError(f"methods for {', '.join(stray)}, which is not among the ops")

    def answers(self, op: str, args: dict[str, Any]) -> bool:
        if op == "registers" and args.get("from_last_stop") is True:
            return True
        if op not in self.ops:
            return False
        if op in self.methods and args.get("method") not in self.methods[op]:
            return False
        stop = self.needs_stop.get(op)
        return not (stop is not None and stop(args))

    def listed(self) -> set[str]:
        return by_method(self.ops, self.methods)

    def check_folds(self, folds: Mapping[str, Iterable[str]]) -> None:
        """Refuse a fold among `ops` with no methods named, which would answer running whole,
        and a method a fold lacks; `folds` is each fold's own method names."""
        for op, has in folds.items():
            if op in self.ops and op not in self.methods:
                raise ValueError(f"{op} answers a running machine with no methods named: "
                                 "every method of it would, the ones that need a stop too")
            for name in self.methods.get(op, ()):
                if name not in set(has):
                    raise ValueError(f"{op} names `{name}`, which it lacks")


def answers_while_running(running_ok: Iterable[str], not_steps: Iterable[str],
                          kept_out: Iterable[str]) -> list[str]:
    """What a refusal for a running machine names as answering."""
    return [*sorted(running_ok), "registers(from_last_stop=True)",
            *sorted(set(not_steps) - set(kept_out))]


@dataclass(frozen=True)
class Roster:
    """`families` as `(name, tools)` in listing order; `answering` may spell a call with
    arguments."""

    families: tuple[tuple[str, tuple[str, ...]], ...]
    answering: tuple[str, ...]

    def text(self) -> str:
        """The roster: `Family: a, b.` per family."""
        return " ".join(f"{name}: {listed(tools)}." for name, tools in self.families)

    def answering_split(self) -> tuple[list[str], list[str]]:
        """Families wholly answering a running machine, then the other names."""
        running = set(self.answering)
        whole = [name for name, tools in self.families if running >= set(tools)]
        rest = [t for name, tools in self.families if name not in whole for t in tools
                if t in running]
        held = {t for _, tools in self.families for t in tools}
        return whole, rest + [t for t in self.answering if t not in held]

    def answering_named(self) -> set[str]:
        """Every name the running sentence covers."""
        whole, rest = self.answering_split()
        return {t for name, tools in self.families if name in whole for t in tools} | set(rest)

    def running_sentence(self) -> str:
        """`these answer: A and B whole, and x, y.`, each half only when non-empty."""
        whole, rest = self.answering_split()
        parts = []
        if whole:
            head = ", ".join(whole[:-1])
            parts.append(f"{head} and {whole[-1]} whole" if head else f"{whole[-1]} whole")
        if rest:
            parts.append(listed(rest))
        return f"these answer: {', and '.join(parts)}."

    def unlisted(self, registered: Iterable[str]) -> list[str]:
        """What breaks the partition of `registered` into families; empty when it holds."""
        listed = [t for _, tools in self.families for t in tools]
        twice = sorted({t for t in listed if listed.count(t) > 1})
        return ([f"held twice: {t}" for t in twice]
                + [f"in no family: {t}" for t in sorted(set(registered) - set(listed))]
                + [f"not registered: {t}" for t in sorted(set(listed) - set(registered))])
