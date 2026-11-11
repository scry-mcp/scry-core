"""`screen_wait` judged at a declared stop (`on_breakpoint`, `on_watch`): the arguments, the
condition, the `changed` predicate and the reply's fields, the same on both servers.

A firing is judged at the next retrace, never at its own instant: a screen read between two
vblanks is the frame being drawn above the beam and an older one below it, a picture no frame
showed. Each server supplies its stop and its screen read; this module decides nothing about
running the machine.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from scry_core.prose import counted
from scry_core.reply_contract import Invalid

Kind = Literal["breakpoint", "watch"]
TERMS_MAX = 4
#: `b@`, `w@`, `d@`: a byte, a word, a double word read at the ref.
SIZES = {"b": 1, "w": 2, "d": 4}
_OPS: dict[str, Callable[[int, int], bool]] = {
    "==": lambda a, b: a == b, "!=": lambda a, b: a != b, "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b}
_TERM = re.compile(r"^(?:([bwd])@([^\s=!<>&|]+)|([A-Za-z][A-Za-z0-9]*))\s*(==|!=|<=|>=|<|>)\s*"
                   r"(?:0[xX])?([0-9A-Fa-f]+)$")
GRAMMAR = (f"up to {TERMS_MAX} terms joined by `&&`, each a register (`AX`, `d0`) or a memory "
           "read (`b@ref`, `w@ref`, `d@ref`), a comparison (`==`, `!=`, `<`, `<=`, `>`, `>=`) "
           "and a hex value (`0x` allowed)")


@dataclass(frozen=True)
class Term:
    """`operand` a register name or a memory ref; `size` 0 for a register, else bytes read."""

    operand: str
    size: int
    op: str
    value: int


@dataclass(frozen=True)
class StopWait:
    kind: Kind
    ref: str
    condition: tuple[Term, ...]
    condition_text: str = ""


def parse_condition(text: str) -> tuple[Term, ...]:
    """The terms of `text`; an empty text is no condition."""
    if not text.strip():
        return ()
    parts = [p.strip() for p in text.split("&&")]
    if len(parts) > TERMS_MAX:
        raise Invalid("bad_argument", f"the condition has {len(parts)} terms; it takes {GRAMMAR}")
    terms = []
    for part in parts:
        m = _TERM.match(part)
        if m is None:
            raise Invalid("bad_argument", f"the term {part!r} is not in the condition's grammar: "
                          f"{GRAMMAR}")
        size, ref, register, op, value = m.groups()
        terms.append(Term(register.upper(), 0, op, int(value, 16)) if register
                      else Term(ref, SIZES[size], op, int(value, 16)))
    return tuple(terms)


def check(on_breakpoint: str, on_watch: str, every: int, condition: str) -> StopWait | None:
    """The stop a wait is judged at, or None for a wait by retraces; what cannot go together is
    refused before anything runs."""
    named = [(k, v) for k, v in (("breakpoint", on_breakpoint), ("watch", on_watch)) if v]
    if not named:
        if condition.strip():
            raise Invalid("bad_argument", "a `condition` filters the firings of `on_breakpoint` "
                          "or `on_watch`, and neither is named")
        return None
    if len(named) > 1:
        raise Invalid("bad_argument", "a wait is judged at one of `on_breakpoint` or "
                      "`on_watch`, not both")
    kind, ref = named[0]
    if not ref.strip():
        raise Invalid("bad_argument", f"`on_{kind}` is empty: name a declared {kind} by its "
                      "`ref`, as `declaration_list` lists it")
    if every:
        raise Invalid("bad_argument", f"`every` samples retraces, and a wait on a {kind} is "
                      "judged at its firings: leave `every` at 0")
    return StopWait("breakpoint" if kind == "breakpoint" else "watch", ref.strip(),
                    parse_condition(condition), condition.strip())


def holds(terms: tuple[Term, ...], register: Callable[[str], int],
          memory: Callable[[str, int], int]) -> bool:
    """Whether every term holds, reading registers and memory through the server's readers."""
    for t in terms:
        got = register(t.operand) if t.size == 0 else memory(t.operand, t.size)
        if not _OPS[t.op](got, t.value):
            return False
    return True


class Changed:
    """`changed`: the map names a screen other than the one it named at the call's start. A frame
    it names nothing is a transition and does not end the wait; one it cannot judge is refused."""

    def __init__(self, start: Mapping[str, Any]) -> None:
        self.started_on: str | None = start["screen"] if start.get("matched") else None

    def judge(self, found: Mapping[str, Any]) -> bool:
        if found.get("matched"):
            return bool(found["screen"] != self.started_on)
        if found.get("view_fits") is False or (found.get("screens_unjudged", 0)
                                               and not found.get("screens_tried", 0)):
            raise Invalid("no_channel", "the map cannot judge this frame (no screen of its size "
                          "and kind could be read), so `changed` cannot tell a new screen from "
                          "the old one", **{k: found[k] for k in ("view_fits", "screens_unjudged")
                                            if k in found})
        return False


def _waited_on(spec: StopWait) -> dict[str, Any]:
    return {"kind": spec.kind, "ref": spec.ref,
            **({"condition": spec.condition_text} if spec.condition_text else {})}


def fields(spec: StopWait, firings: int, examined: int, fired_line: Any) -> dict[str, Any]:
    """What a reply under `on_*` carries in place of `polls` and `sampled_every`."""
    return {"waited_on": _waited_on(spec), "firings": firings, "frames_examined": examined,
            "fired_line": fired_line}


def never_fired(spec: StopWait, seconds: float, **more: Any) -> Invalid:
    """The refusal of a wait whose stop never fired: nothing was judged, so no verdict."""
    return Invalid("never_fired", f"the {spec.kind} {spec.ref!r} never fired within {seconds:g} s, "
                   "so no screen was judged: this says nothing about the screen",
                   waited_on=_waited_on(spec), **more)


def summary_after(reply: Mapping[str, Any]) -> str | None:
    """A summary's "after ..." for a reply under `on_*`, or None for a wait by retraces."""
    on = reply.get("waited_on")
    if not isinstance(on, Mapping):
        return None
    return (f"after {counted(int(reply.get('firings') or 0), 'firing')} of {on.get('kind')} "
            f"{on.get('ref')!r}")
