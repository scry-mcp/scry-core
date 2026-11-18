"""A demo's normalised transcript read back as records, so a reference example is the call and
the reply a committed run already shows.

It reads what `demo._entry` writes. A call a demo makes as a step of a `perform` is a record of
its own: the step's arguments and the reply the `perform` carries for it. A `perform` asked for
summaries carries each step's reply cut down, so its steps are no records.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from scry_core import recording
from scry_core.verdict import Invalid

#: The tool whose reply carries each step's own (`ran`), its steps under `steps`.
SEQUENCE_TOOL = "perform"
_HEAD = re.compile(r"^\*\*(\d+)\. `(\w+)`\*\*: (\w+)", re.MULTILINE)
_BLOCK = re.compile(r"^```json\n(.*?)\n```$", re.MULTILINE | re.DOTALL)


def _steps(n: int, call: dict[str, Any], reply: dict[str, Any], source: str
           ) -> Iterator[dict[str, Any]]:
    steps, ran = call.get("steps"), reply.get("ran")
    if not isinstance(steps, list) or not isinstance(ran, list) or call.get("summaries"):
        return
    for k, (step, done) in enumerate(zip(steps, ran, strict=False), 1):
        if isinstance(step, dict) and isinstance(done, dict) \
                and isinstance(done.get("reply"), dict) and step.get("op") == done.get("op"):
            yield {"tool": done["op"], "args": recording.step_arguments(step),
                   "reply": done["reply"], "verdict": "OK", "section": source,
                   "label": f"call {n}, step {k} of its `{SEQUENCE_TOOL}`", "normalised": True}


def records(text: str, source: str) -> list[dict[str, Any]]:
    """Every call of the transcript `text`, in order, as a live run's records are: `tool`,
    `args`, `reply`, `verdict`, with `source` as its section and the call's number as its label.
    `Invalid` when an entry's call or reply is not the JSON the runner writes."""
    heads = list(_HEAD.finditer(text))
    found: list[dict[str, Any]] = []
    for i, head in enumerate(heads):
        body = text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        try:
            blocks = [json.loads(b) for b in _BLOCK.findall(body)]
        except ValueError as e:
            raise Invalid(f"{source}: call {head[1]} is not the JSON a run writes: {e}") from e
        if not blocks or not all(isinstance(b, dict) for b in blocks[:2]):
            raise Invalid(f"{source}: call {head[1]} carries no call object")
        n, tool, reply = int(head[1]), head[2], blocks[1] if len(blocks) > 1 else None
        found.append({"tool": tool, "args": blocks[0], "reply": reply, "verdict": head[3],
                      "section": source, "label": f"call {n}", "normalised": True})
        if tool == SEQUENCE_TOOL and reply is not None and head[3] == "OK":
            found += _steps(n, blocks[0], reply, source)
    return found
