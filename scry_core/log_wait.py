"""A wait for a line of a log, the one engine both servers drive: what the log ALREADY holds is
answered first, and only then does it wait, so a line that went past before the call is still
found (`already`). The wait ends on a match (`TARGET`), on its bound (`TIMEOUT`), on a machine
that stopped (a stopped machine logs nothing, so the wait could not end) or on an emulator that
went away; before either of the last three it reads the log once more, since the loop checks its
condition first and reads last, and a line written in between was never looked for.

What a log is and how a server answers stay the server's: the engine is handed `fresh`, which
returns the whole lines the log gained since it was last called (`lines_since` reads one file),
and gives back what it found or how it ended, for the server to compose into its reply.
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
    """The WHOLE lines a log gained since byte `mark`, and the byte after the last of them,
    which is the next mark. A half-written line stops being a line: the read is cut at the last
    newline, so a line is only ever seen whole, and once, however the writer's flushes fall. A
    log that is not there yet, or that is SHORTER than the mark (rewritten), is read from its
    start: a mark past the end describes a file that no longer exists. A byte-order mark is the
    file's, not its first line's, and the mark returned still counts its bytes."""
    if not log.exists():
        return [], 0
    if mark > log.stat().st_size:
        mark = 0
    with open(log, "rb") as fh:
        fh.seek(mark)
        raw = fh.read()
    bom = len(codecs.BOM_UTF8) if mark == 0 and raw.startswith(codecs.BOM_UTF8) else 0
    raw = raw[bom:]
    cut = raw.rfind(b"\n") + 1
    text = raw[:cut].decode("utf-8", errors="replace")
    return [line.rstrip("\r") for line in text.split("\n")[:-1]], mark + bom + cut


@dataclass(frozen=True)
class Found:
    """The first matching line, and the counts that place it: `already` it was in the log when
    the wait first looked; `lines_before` the lines examined before it; `lines_total` how many
    matched in the read that found it; `arrived_during` the lines written while it waited."""
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
    """A wait that found nothing: how it ended, the lines that arrived while it waited and
    every line it examined, and how long it waited; `at_bound` a stop found as the bound ran
    out rather than by a poll inside it."""
    how: Ending
    arrived_during: int
    lines_examined: int
    waited_s: float
    at_bound: bool = False


def wait(rx: re.Pattern[str], fresh: Callable[[], list[str]], *, seconds: float,
         stopped: Callable[[], bool], alive: Callable[[], bool],
         progress: mprogress.Progress = mprogress.no_progress,
         label: str = "log_wait") -> Found | Ended:
    """Wait up to `seconds` for a line `rx` matches among what `fresh` hands back. `stopped`
    and `alive` are asked passively, every poll; `label` heads the progress line."""
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

    def ended(how: Ending) -> Found | Ended:
        new, hits = look()
        if hits:
            return found(hits, new, False)
        return Ended(how, total - len(first), total, round(clock.seconds(), 1))

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


def timeout_note(pattern: str, ended: Ended, where: str, writer: str) -> str:
    """The `note` of a wait whose bound ran out: what arrived and what was examined (`where` says
    over what span of the log), so an expired bound is never read as "there was nothing to match
    against", and a silent `writer` (the guest, the driver) is said as such."""
    silent = ("" if ended.arrived_during else
              f" The {writer} wrote NOTHING at all in this window, so the question may be "
              "whether it is still writing rather than what it wrote.")
    return (f"nothing matched /{pattern}/ in {ended.waited_s} s: "
            f"{prose.counted(ended.arrived_during, 'line')} arrived DURING the wait "
            f"({ended.lines_examined} {where}), so this is a bound that expired and not 'there "
            f"was nothing to match against'.{silent} The machine is still running")


def gone_message(pattern: str, ended: Ended, seconds: float) -> str:
    """The refusal of a wait whose emulator went away: nothing more will be written, so a longer
    wait cannot help."""
    return (f"the emulator is GONE, {ended.waited_s} s into a {seconds:g} s wait for /{pattern}/, "
            "and a final read of the log after it died found nothing matching either. Nothing "
            "more will be written, so this needs a new session, not a bigger bound")
