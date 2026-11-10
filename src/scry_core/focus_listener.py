"""Every application that comes to the front of this host, heard as it happens (macOS).

    with focus_listener.Listener(record) as listener:
        ...                                   # the run
    listener.heard                            # who came to the front, and the stretch listened

The listener is `focus_listener.swift`, built with `swiftc` beside the record and run as a
process, because the notifications arrive on a run loop this process does not have.
It hears an application coming to the front, however briefly, and not a window taking the
keyboard inside the application already there. It sends no Apple event: one sent without the
Automation permission brings the system's consent prompt to the front, the theft a focus watch
exists to catch.

Its lines, which `parse` reads: `epoch_ms<TAB>LISTENING<TAB>app<TAB>pid` once, naming who is
in front, then `epoch_ms<TAB>app<TAB>pid` per activation, a pid of -1 for none. Each activation
goes to the record in that shape as it is heard. A listener that cannot run, ends early or
prints another shape raises nothing: `Heard` says it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TextIO

SOURCE = Path(__file__).with_name("focus_listener.swift")
#: The built listener's file: the name the host's process list shows, cut at 16 characters.
NAME = "scry-focus-watch"
BUILD_TIMEOUT_S = 300.0
#: How long a run waits for its listener to say it listens before going on unheard.
LISTEN_WAIT_S = 10.0
STOP_WAIT_S = 5.0
_STAMP = re.compile(r"[0-9]+")
_PID = re.compile(r"-?[0-9]+")

_MACOS = sys.platform == "darwin"


@dataclass(frozen=True)
class Activation:
    """One application in front since `epoch_ms`."""

    epoch_ms: int
    app: str
    pid: int | None = None

    def line(self) -> str:
        return f"{self.epoch_ms}\t{self.app}\t{'' if self.pid is None else self.pid}"


@dataclass(frozen=True)
class Heard:
    """What was heard and the stretch listened: `since_ms` None, it never listened; `until_ms`
    None, it still does. `front` is who was in front as it began."""

    activations: tuple[Activation, ...] = ()
    since_ms: int | None = None
    until_ms: int | None = None
    error: str = ""
    front: Activation | None = None

    def unheard(self, start_ms: int, end_ms: int) -> str:
        """Why `[start_ms, end_ms]` was not listened to whole, or ""."""
        if self.error:
            return self.error
        if self.since_ms is None:
            return "the listener never said it was listening"
        if self.since_ms > start_ms:
            return f"the listener began at {self.since_ms}, after the window opened at {start_ms}"
        if self.until_ms is not None and self.until_ms < end_ms:
            return f"the listener ended at {self.until_ms}, before the window closed at {end_ms}"
        return ""

    def front_at(self, epoch_ms: int) -> Activation | None:
        """Who was in front at `epoch_ms`, or None for a moment nobody listened to."""
        if self.front is None or self.unheard(epoch_ms, epoch_ms):
            return None
        return max((a for a in (self.front, *self.activations) if a.epoch_ms <= epoch_ms),
                   key=lambda a: a.epoch_ms)


def parse(line: str) -> tuple[bool, Activation] | None:
    """Whether the line says the listener listens, and who is in front; None in neither shape."""
    fields = line.rstrip("\n").split("\t")
    listening = len(fields) == 4 and fields[1] == "LISTENING"
    if len(fields) != 3 and not listening:
        return None
    if not _STAMP.fullmatch(fields[0]) or not _PID.fullmatch(fields[-1]):
        return None
    pid = int(fields[-1])
    return listening, Activation(int(fields[0]), fields[-2], pid if pid >= 0 else None)


def swiftc(source: Path, built: Path) -> str:
    """Build `source` into `built`, warnings refused: "" when it is there, else why not."""
    compiler = shutil.which("swiftc")
    if compiler is None:
        return f"{source.name} is built with swiftc, which this host does not have"
    try:
        run = subprocess.run([compiler, "-O", "-warnings-as-errors", str(source), "-o", str(built)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=BUILD_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"swiftc did not build {source.name}: {e}"
    if run.returncode != 0:
        return f"swiftc did not build {source.name}: {run.stderr.strip() or run.returncode}"
    return ""


def host(folder: Path) -> list[str] | str:
    """The argv of the listener built into `folder`, or why this host has none."""
    if not _MACOS:
        return f"activations are heard on macOS only, not {sys.platform}"
    built = folder / NAME
    return swiftc(SOURCE, built) or [str(built)]


class Listener:
    """Hears from `__enter__` to `__exit__`, each activation into `record` as it arrives.

    `launch(folder)`, the test seam, answers the argv or why there is none. A record that cannot
    be written re-raises at `__exit__`."""

    def __init__(self, record: Path,
                 launch: Callable[[Path], Sequence[str] | str] = host) -> None:
        self.record = record
        self._launch = launch
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._out: TextIO | None = None
        self._activations: list[Activation] = []
        self._front: Activation | None = None
        self._since_ms: int | None = None
        self._until_ms: int | None = None
        self._error = ""
        self._listening = threading.Event()
        self._failure: BaseException | None = None

    @property
    def heard(self) -> Heard:
        return Heard(tuple(self._activations), self._since_ms, self._until_ms, self._error,
                     self._front)

    @property
    def returncode(self) -> int | None:
        """The listener's exit code; None while it runs or when it never did."""
        return None if self._process is None else self._process.returncode

    def _hear(self, lines: Iterable[str], out: TextIO) -> None:
        try:
            for line in lines:
                read = parse(line)
                if read is None:
                    self._error = f"the listener printed a line of no shape it has: {line!r}"
                elif read[0]:
                    self._front = read[1]
                    self._since_ms = read[1].epoch_ms
                    self._listening.set()
                else:
                    self._activations.append(read[1])
                    out.write(read[1].line() + "\n")
                    out.flush()
        except BaseException as e:
            self._failure = e
        finally:
            self._until_ms = int(time.time() * 1000)
            self._listening.set()

    def __enter__(self) -> Listener:
        made = self._launch(self.record.parent)
        if isinstance(made, str):
            self._error = made
            return self
        self._out = self.record.open("w", encoding="utf-8")
        try:
            self._process = subprocess.Popen(
                list(made), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            self._out.close()
            self._error = f"the listener did not start: {e}"
            return self
        assert self._process.stdout is not None
        self._thread = threading.Thread(target=self._hear, args=(self._process.stdout, self._out),
                                        name="focus_listener", daemon=True)
        self._thread.start()
        try:
            self._listening.wait(LISTEN_WAIT_S)
        except BaseException:
            self._stop()
            raise
        return self

    def _stop(self) -> None:
        if self._process is None or self._thread is None or self._out is None:
            return
        assert self._process.stdin is not None and self._process.stdout is not None
        self._process.stdin.close()          # its stdin ending is what ends it
        try:
            self._process.wait(STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._thread.join()
        self._process.stdout.close()
        self._out.close()

    def __exit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self._stop()
        if self._failure is not None and exc is None:
            raise self._failure
