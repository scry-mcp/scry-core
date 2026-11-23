"""What a demo run did, call by call, in the emulator's frames: the file the demo decorator
reads. The format is in docs/modules.md, under *A demo run's timeline*; `Builder` writes it and
`loads` reads it back, refusing what the writer never writes.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from scry_core import abbreviation, naming
from scry_core.naming import Named
from scry_core.verdict import Invalid

VERSION = 2
Kind = Literal["key", "button", "pointer"]
KINDS: tuple[Kind, ...] = ("key", "button", "pointer")
Tint = Literal["write", "read", "refused"]
TINTS: tuple[Tint, ...] = ("write", "read", "refused")
DOCUMENT_KEYS = {"version", "demo", "calls"}
CALL_KEYS = {"n", "step", "tool", "args", "status", "caption", "before", "after", "events"}
CAPTION_KEYS = {"text", "tint"}


@dataclass(frozen=True)
class Event:
    """One input event. A key or a button has a `name` and `down`; a pointer an `x` and a `y`."""

    kind: Kind
    frame: int | None = None
    name: str = ""
    down: bool = True
    x: int = 0
    y: int = 0

    def fields(self, default: int | None) -> dict[str, Any]:
        frame = self.frame if self.frame is not None else default
        if self.kind == "pointer":
            return {"kind": self.kind, "x": self.x, "y": self.y, "frame": frame}
        return {"kind": self.kind, "name": self.name, "down": self.down, "frame": frame}


def key(name: str, down: bool, frame: int | None = None) -> Event:
    return Event("key", frame, name=name, down=down)


def button(name: str, down: bool, frame: int | None = None) -> Event:
    return Event("button", frame, name=name, down=down)


def pointer(x: int, y: int, frame: int | None = None) -> Event:
    return Event("pointer", frame, x=x, y=y)


@dataclass
class Builder:
    """The document of one run, call by call."""

    demo: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    _frame: int | None = None

    def add(self, step: str, tool: str, args: Mapping[str, Any], status: str,
            counted: tuple[int | None, int | None], events: Sequence[Event] = (),
            read_only: bool = False, named: Mapping[str, Named] | None = None,
            rows: Sequence[Mapping[str, Any]] = (),
            readers: Collection[str] = ()) -> None:
        """A call made: `counted` is the frames its reply said it began and ended at, or None;
        `read_only` is the tool's `readOnlyHint`, which tints its caption; `named` is what its
        arguments are called, as its reply's `names` says (`naming.arguments_of`).

        `rows` are the calls a wrapper ran, as its reply names them (`ran`): the timeline holds
        one entry per row, in order, at the frames that row ran for, and none for the wrapper,
        because a wrapper is not what a viewer follows. A row that counted no frame stays where
        the machine was. `readers` are the tools its server marks `readOnlyHint`, which tint a
        step's caption as a read. A reply that names no row stays one entry, so a server that
        cannot report the calls a wrapper ran is not invented."""
        if rows:
            self._ran(step, tool, args, list(rows), list(events), readers)
            return
        self._one(step, tool, args, status, counted, events, read_only, named)

    def _one(self, step: str, tool: str, args: Mapping[str, Any], status: str,
             counted: tuple[int | None, int | None], events: Sequence[Event], read_only: bool,
             named: Mapping[str, Named] | None) -> None:
        """One call as one entry."""
        before = counted[0] if counted[0] is not None else self._frame
        after = counted[1] if counted[1] is not None else before
        if after is not None:
            self._frame = after
        tint: Tint = "refused" if status != "ok" else "read" if read_only else "write"
        self.calls.append({"n": len(self.calls) + 1, "step": step, "tool": tool,
                           "args": dict(args), "status": status,
                           "caption": {"text": abbreviation.caption(tool, args, named),
                                       "tint": tint},
                           "before": before, "after": after,
                           "events": [e.fields(after) for e in events]})

    def _ran(self, step: str, tool: str, args: Mapping[str, Any],
             rows: list[Mapping[str, Any]], events: list[Event], readers: Collection[str]
             ) -> None:
        """The calls a wrapper ran, each an entry of its own; the wrapper's arguments give each
        step's, its reply's own names give what they are called."""
        steps = _steps_of(args)
        bounds: list[tuple[int | None, int | None]] = []
        first = len(self.calls)
        for n, row in enumerate(rows):
            op, reply = row.get("op"), row.get("reply")
            if not isinstance(op, str) or not isinstance(reply, Mapping):
                raise Invalid(f"step {n + 1} of the `{tool}` in the run's timeline names no "
                              f"`op` and no `reply`")
            before = _number(row.get("frame_before"))
            after = _number(row.get("frame_after"))
            before = before if before is not None else self._frame
            after = after if after is not None else before
            if after is not None:
                self._frame = after
            bounds.append((before, after))
            status = str(reply.get("status", "ok"))
            tint: Tint = "refused" if status != "ok" else "read" if op in readers else "write"
            self.calls.append({"n": len(self.calls) + 1, "step": step, "tool": op,
                               "args": _step_arguments(steps, n, op), "status": status,
                               "caption": {"text": abbreviation.caption(
                                   op, _step_arguments(steps, n, op),
                                   naming.arguments_of(reply.get("names"))),
                                   "tint": tint},
                               "before": before, "after": after, "events": []})
        placed: list[list[Event]] = [[] for _ in rows]
        for event in events:
            placed[_row_of(bounds, event.frame)].append(event)
        for entry, got in zip(self.calls[first:], placed, strict=True):
            entry["events"] = [e.fields(entry["after"]) for e in got]

    def dumps(self) -> str:
        document = {"version": VERSION, "demo": self.demo, "calls": self.calls}
        _check(document)
        return json.dumps(document, indent=2) + "\n"


def _number(value: Any) -> int | None:
    """A row's frame, when it counted one."""
    return value if type(value) is int and value >= 0 else None


def _steps_of(args: Mapping[str, Any]) -> list[Any]:
    """The steps a wrapper was given: `steps` (`perform`) or `act` (`drive`)."""
    for key in ("steps", "act"):
        given = args.get(key)
        if isinstance(given, list):
            return given
    return []


def _step_arguments(steps: Sequence[Any], n: int, op: str) -> dict[str, Any]:
    """The arguments of step `n` (counted from 0), when the wrapper's own list names that step
    and the row names the same operation; a list that repeats gives `n` modulo its length."""
    step = steps[n % len(steps)] if steps else None
    if not isinstance(step, Mapping) or step.get("op") != op:
        return {}
    return {k: v for k, v in step.items() if k != "op"}


def _row_of(bounds: Sequence[tuple[int | None, int | None]], frame: int | None) -> int:
    """Which row of a wrapper an event belongs to: the one whose frames hold it, else the last
    row that counted frames, else the last."""
    for n, (before, after) in enumerate(bounds):
        if frame is not None and before is not None and after is not None \
                and min(before, after) <= frame <= max(before, after):
            return n
    framed = [n for n, (_, after) in enumerate(bounds) if after is not None]
    return framed[-1] if framed else len(bounds) - 1


def loads(text: str) -> dict[str, Any]:
    """A timeline document read back, as the writer wrote it; `Invalid` for anything else."""
    try:
        document = json.loads(text)
    except ValueError as e:
        raise Invalid(f"the timeline is not JSON ({e})") from e
    _check(document)
    return cast(dict[str, Any], document)


def _frame(value: Any, what: str) -> None:
    if value is not None and (type(value) is not int or value < 0):
        raise Invalid(f"the timeline's {what} is {value!r}, not a frame number or null")


def _check(document: Any) -> None:
    if not isinstance(document, dict) or type(document.get("version")) is not int \
            or document["version"] != VERSION:
        raise Invalid(f"the timeline is not a version {VERSION} document")
    calls = document.get("calls")
    if set(document) != DOCUMENT_KEYS or not isinstance(document["demo"], str) \
            or not isinstance(calls, list):
        raise Invalid(f"the timeline holds {sorted(document)}, not {sorted(DOCUMENT_KEYS)}, "
                      "with a `demo` text and a `calls` list")
    for n, call in enumerate(calls, start=1):
        if not isinstance(call, dict) or set(call) != CALL_KEYS or call["n"] != n \
                or type(call["n"]) is not int:
            raise Invalid(f"call {n} of the timeline is not numbered {n} or does not hold "
                          f"exactly {sorted(CALL_KEYS)}")
        for name in ("step", "tool", "status"):
            if not isinstance(call.get(name), str):
                raise Invalid(f"call {n} of the timeline has no `{name}` text")
        if not isinstance(call.get("args"), dict) or not isinstance(call.get("events"), list):
            raise Invalid(f"call {n} of the timeline has no `args` object or `events` list")
        caption = call["caption"]
        if not isinstance(caption, dict) or set(caption) != CAPTION_KEYS \
                or not isinstance(caption["text"], str) or caption["tint"] not in TINTS:
            raise Invalid(f"call {n}'s caption is not a `text` and a `tint` of "
                          f"{', '.join(TINTS)}")
        before, after = call.get("before"), call.get("after")
        _frame(before, f"call {n} `before`")
        _frame(after, f"call {n} `after`")
        if before is not None and after is None:
            raise Invalid(f"call {n} of the timeline began at frame {before} and names no end")
        for event in call["events"]:
            _event(n, event, before, after)


def _event(n: int, event: Any, before: int | None, after: int | None) -> None:
    kind = event.get("kind") if isinstance(event, dict) else None
    if kind not in KINDS:
        raise Invalid(f"call {n} of the timeline holds an event of kind {kind!r}, not one of "
                      f"{', '.join(KINDS)}")
    shape = ({"x", "y"} if kind == "pointer" else {"name", "down"}) | {"kind", "frame"}
    if set(event) != shape:
        raise Invalid(f"call {n}'s {kind} event holds {sorted(event)}, not {sorted(shape)}")
    typed = ({"x": int, "y": int} if kind == "pointer" else {"name": str, "down": bool})
    if wrong := [k for k, t in typed.items() if type(event[k]) is not t]:
        raise Invalid(f"call {n}'s {kind} event has a wrong type for {', '.join(wrong)}")
    _frame(event["frame"], f"call {n}'s {kind} event frame")
    at = event["frame"]
    ends = [frame for frame in (before, after) if frame is not None]
    if at is not None and not (ends and min(ends) <= at <= max(ends)):
        raise Invalid(f"call {n}'s {kind} event is at frame {at}, outside the call's {before} "
                      f"to {after}")
    if at is None and after is not None:
        raise Invalid(f"call {n}'s {kind} event has no frame in a call that counted them")
