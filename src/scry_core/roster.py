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
        if empty := sorted(op for op, ok in self.methods.items() if not ok):
            raise ValueError(f"{', '.join(empty)} names no method, so it answers nothing")

    def answers(self, op: str, args: dict[str, Any]) -> bool:
        if op == "registers" and args.get("from_last_stop") is True:
            return True
        if op not in self.ops:
            return False
        if op in self.methods and args.get("method") not in self.methods[op]:
            return False
        stop = self.needs_stop.get(op)
        return not (stop is not None and stop(args))

    def listed(self, folds: Mapping[str, Iterable[str]] | None = None) -> set[str]:
        """`by_method`'s names; a fold naming every one of its `folds` methods is listed whole."""
        every = {op for op, has in (folds or {}).items()
                 if op in self.methods and set(self.methods[op]) >= set(has)}
        return by_method(self.ops, {op: ok for op, ok in self.methods.items() if op not in every})

    def check_folds(self, folds: Mapping[str, Iterable[str]]) -> None:
        """Refuse a fold among `ops` with no methods named, which would answer running whole,
        a method a fold lacks, and methods for an op that is no fold; `folds` is each fold's
        own method names."""
        if stray := sorted(set(self.methods) - set(folds)):
            raise ValueError(f"methods for {', '.join(stray)}, which is no fold")
        for op, has in folds.items():
            if op in self.ops and op not in self.methods:
                raise ValueError(f"{op} answers a running machine with no methods named: "
                                 "every method of it would, the ones that need a stop too")
            lacks = [name for name in self.methods.get(op, ()) if name not in set(has)]
            if lacks:
                raise ValueError(f"{op} names `{lacks[0]}`, which it lacks")


def answers_while_running(running_ok: Iterable[str], not_steps: Iterable[str],
                          kept_out: Iterable[str]) -> list[str]:
    """What a refusal for a running machine names as answering."""
    return [*sorted(running_ok), "registers(from_last_stop=True)",
            *sorted(set(not_steps) - set(kept_out))]


#: The `record` words both servers' descriptions share: the arguments, the bound's outcome and
#: the reply fields a caller may read.
RECORD_ARGS = ("`dest`: an absolute `.avi` path not there yet; empty lands in the session's "
               "scratch, gone at `close`, and the reply names it either way. `frames` is 2 or "
               "more. `seconds` bounds the wait for the recording. The AVI is read before its "
               "path is given.")
RECORD_CUT = ("A run cut at that bound is released before the reply: when the release answers, "
              "the reply says `ended: true` and names the AVI it read back, and a file that does "
              "not read as finished is INVALID.")
RECORD_REPLY_FIELDS: tuple[str, ...] = ("verdict", "frames", "path", "began", "ended", "bytes",
                                        "avi_frames")
RECORD_REPLY = ", ".join(f"`{name}`" for name in RECORD_REPLY_FIELDS)
DOC_VALUES: Mapping[str, str] = {"RECORD_ARGS": RECORD_ARGS, "RECORD_CUT": RECORD_CUT,
                                 "RECORD_REPLY": RECORD_REPLY}


#: The family of every tool both servers have, declared once: a model reading the two rosters
#: sees one surface, and a server that files a shared name elsewhere is refused by `misfiled`.
SHARED_FAMILIES: Mapping[str, str] = {
    **dict.fromkeys(("start", "status", "window", "close"), "Session"),
    **dict.fromkeys(("machine_map", "log", "log_wait"), "Machine"),
    "symbols_find": "Names",
    **dict.fromkeys(("run_to", "run_for", "step", "resume", "stop", "trace", "screen_wait"),
                    "Advance"),
    **dict.fromkeys(("breakpoint_at", "regpoint_add", "watch_add", "declaration_list",
                     "declaration_clear"), "Declarations"),
    **dict.fromkeys(("read_memory", "registers", "disassemble", "find", "memdump",
                     "screen_map_find", "screen_map_write"), "Read"),
    **dict.fromkeys(("palette", "screen_view", "screen_signature"), "Screen"),
    **dict.fromkeys(("write", "set_register", "debug"), "Write"),
    "scan": "Scan",
    "promote": "Store",
    **dict.fromkeys(("comment_list", "comment_write"), "Comments"),
    **dict.fromkeys(("state_list", "state_write"), "States"),
    **dict.fromkeys(("record", "audio_record", "series_capture", "snapshot", "captures"),
                    "Captures"),
    **dict.fromkeys(("image_compare", "audio_compare"), "Files"),
    **dict.fromkeys(("perform", "perform_export", "drive"), "Lists"),
}


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

    def misfiled(self, shared: Mapping[str, str]) -> list[str]:
        """The tools this roster files under another family than `shared` declares."""
        return [f"{t} is in {name}, the shared declaration says {shared[t]}"
                for name, tools in self.families for t in tools
                if t in shared and shared[t] != name]
