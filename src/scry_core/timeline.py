"""What a demo run did, call by call, in the emulator's frames: the file the demo decorator
reads. The format is in docs/modules.md, under *A demo run's timeline*; `Builder` writes it and
`loads` reads it back, refusing what the writer never writes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from scry_core.verdict import Invalid

VERSION = 1
Kind = Literal["key", "button", "pointer"]
KINDS: tuple[Kind, ...] = ("key", "button", "pointer")
DOCUMENT_KEYS = {"version", "demo", "calls"}
CALL_KEYS = {"n", "step", "tool", "args", "status", "before", "after", "events"}


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
            counted: tuple[int | None, int | None], events: Sequence[Event] = ()) -> None:
        """A call made: `counted` is the frames its reply said it began and ended at, or None."""
        before = counted[0] if counted[0] is not None else self._frame
        after = counted[1] if counted[1] is not None else before
        if after is not None:
            self._frame = after
        self.calls.append({"n": len(self.calls) + 1, "step": step, "tool": tool,
                           "args": dict(args), "status": status, "before": before,
                           "after": after, "events": [e.fields(after) for e in events]})

    def dumps(self) -> str:
        document = {"version": VERSION, "demo": self.demo, "calls": self.calls}
        _check(document)
        return json.dumps(document, indent=2) + "\n"


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
