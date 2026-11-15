"""Wait for a log line, the engine both servers drive. The log's existing lines are answered
first (`already`), so a line written before the call is still found. Before a STOPPED or GONE
ending it reads once more, since the loop reads last.

The engine is handed `fresh` (the whole lines gained since its last call) and returns what it
found or how it ended; the server composes the reply.
"""

from __future__ import annotations

import codecs
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from scry_core import progress as mprogress
from scry_core import prose

#: How often the wait reads the log again.
POLL_S = 0.1
#: How much of the newest line the progress line quotes.
LAST_LINE_SHOWN = 40


def lines_since(log: Path, mark: int) -> tuple[list[str], int]:
    """The whole lines a log gained since byte `mark`, and the next mark.

    A half-written line is cut at the last newline, so a line is seen whole and once. A missing
    or shorter-than-mark (rewritten) log is read from its start. A mark inside a line skips that
    line's rest. The returned mark counts a byte-order mark's bytes.
    """
    if not log.exists():
        return [], 0
    if mark > log.stat().st_size:
        mark = 0
    with open(log, "rb") as fh:
        fh.seek(max(mark - 1, 0))
        before = fh.read(1) if mark else b"\n"
        raw = fh.read()
    if before != b"\n":
        head = raw.find(b"\n") + 1           # 0: line not ended
        mark, raw = mark + head, raw[head:]
    bom = len(codecs.BOM_UTF8) if mark == 0 and raw.startswith(codecs.BOM_UTF8) else 0
    raw = raw[bom:]
    cut = raw.rfind(b"\n") + 1
    text = raw[:cut].decode("utf-8", errors="replace")
    return [line.rstrip("\r") for line in text.split("\n")[:-1]], mark + bom + cut


@dataclass(frozen=True)
class Found:
    """The first matching line; `already` it was in the log at the first look, `lines_total` the
    matches in the read that found it, `arrived_during` the lines written while waiting."""
    line: str
    already: bool
    lines_total: int
    lines_before: int
    arrived_during: int
    waited_s: float
    lines_examined: int

    def fields(self) -> dict[str, Any]:
        return asdict(self)


#: How a wait that found nothing ended.
Ending = Literal["TIMEOUT", "STOPPED", "GONE"]


@dataclass(frozen=True)
class Ended:
    """A wait that found nothing; `at_bound` a stop found as the bound ran out, not by a poll."""
    ending: Ending
    arrived_during: int
    lines_examined: int
    waited_s: float
    at_bound: bool = False


def wait(rx: re.Pattern[str], fresh: Callable[[], list[str]], *, seconds: float,
         stopped: Callable[[], bool], alive: Callable[[], bool],
         progress: mprogress.Progress = mprogress.no_progress,
         label: str = "log_wait") -> Found | Ended:
    """Wait up to `seconds` for a line `rx` matches among what `fresh` hands back."""
    clock = mprogress.Ticker(seconds, progress)
    first = fresh()
    total = len(first)

    def found(hits: list[str], new: list[str], already: bool) -> Found:
        return Found(line=hits[0], already=already, lines_total=len(hits),
                     lines_before=total - len(new) + new.index(hits[0]),
                     arrived_during=total - len(first),
                     waited_s=0.0 if already else round(clock.seconds(), 1),
                     lines_examined=total)

    def look() -> tuple[list[str], list[str]]:
        nonlocal total
        new = fresh()
        total += len(new)
        return new, [ln for ln in new if rx.search(ln)]

    def ended(ending: Ending) -> Found | Ended:
        new, hits = look()
        if hits:
            return found(hits, new, False)
        return Ended(ending, total - len(first), total, round(clock.seconds(), 1))

    hits = [ln for ln in first if rx.search(ln)]
    if hits:
        return found(hits, first, True)
    last = ""
    while not clock.expired():
        if stopped():
            return ended("STOPPED")
        if not alive():
            return ended("GONE")
        time.sleep(POLL_S)
        new, hits = look()
        if hits:
            return found(hits, new, False)
        last = new[-1].strip() if new else last
        clock.tick("{label}: {elapsed:.0f}s of {seconds:g}s, {arrived} lines arrived{last}",
                   label=label, seconds=seconds, arrived=total - len(first),
                   last=f", last: {last[:LAST_LINE_SHOWN]}" if last else "")
    out = ended("TIMEOUT")
    if isinstance(out, Ended) and stopped():
        return Ended("STOPPED", out.arrived_during, out.lines_examined, out.waited_s,
                     at_bound=True)
    if isinstance(out, Ended) and not alive():
        return Ended("GONE", out.arrived_during, out.lines_examined, out.waited_s,
                     at_bound=True)
    return out


#: What a wait that ran out says of the machine when nothing told its caller otherwise.
STILL_RUNNING = "The machine is still running"


def timeout_note(pattern: str, ended: Ended, where: str, writer: str, *,
                 run_state: str = STILL_RUNNING) -> str:
    """The `note` of a wait whose bound ran out; `where` names the span of log examined, and
    `run_state` closes it."""
    silent = ("" if ended.arrived_during else
              f" The {writer} wrote NOTHING at all in this window, so the question may be "
              "whether it is still writing rather than what it wrote.")
    return (f"nothing matched /{pattern}/ in {ended.waited_s} s: "
            f"{prose.counted(ended.arrived_during, 'line')} arrived DURING the wait "
            f"({ended.lines_examined} {where}), so this is a bound that expired and not 'there "
            f"was nothing to match against'.{silent} {run_state}")


def stopped_message(pattern: str, arrived: int, waited_s: float, *, parked: bool,
                    at_bound: bool) -> str:
    """The refusal of a wait the machine stopped under: `parked` when it was already stopped."""
    reason = ("the machine is STOPPED at the debugger" if parked else
              "the machine STOPPED as the bound expired" if at_bound else
              "the machine STOPPED during the wait")
    return (f"{reason}: a stopped machine logs nothing, so the wait for /{pattern}/ cannot end. "
            f"{prose.counted(arrived, 'line')} arrived during {waited_s} s of it and none "
            "matched: `resume` lets it run, then `log_wait` again")


def gone_message(pattern: str, ended: Ended, seconds: float) -> str:
    """The refusal of a wait whose emulator went away."""
    return (f"the emulator is GONE, {ended.waited_s} s into a {seconds:g} s wait for /{pattern}/, "
            "and a final read of the log after it died found nothing matching either. Nothing "
            "more will be written, so this needs a new session, not a bigger bound")
