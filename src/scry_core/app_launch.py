"""An emulator launched as an app bundle, and the handle to the process it leaves.

`open` starts the app under launchd, which is what gives it the window a host captures; nothing
here reaps it, so its exit status is not known."""

from __future__ import annotations

import contextlib
import os
import plistlib
import select
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import IO, Any, Protocol, cast

from scry_core.live_host import BACKGROUND_VAR
from scry_core.reply_contract import Invalid, unavailable

BUNDLE_SUFFIX = ".app"
#: Where a bundle's launcher reads the working directory it must change into.
CWD_VAR = "SCRY_APP_CWD"
OPEN = "/usr/bin/open"
PGREP = "/usr/bin/pgrep"

#: How long the app's pid may take to appear, and how often it is looked for.
FIND_TIMEOUT_S = 10.0
FIND_POLL_S = 0.05
WAIT_POLL_S = 0.1
CONSOLE_POLL_S = 0.05
CONSOLE_CLOSE_S = 1.0

UNKNOWN_EXIT_WHY = (
    "the emulator was launched as an app, so this server is not its parent and nothing here "
    "reaps it: its exit status is not known")

#: The route is `open`'s: launchd starts the bundle, `pgrep -f -u` finds its pid, and a FIFO
#: carries its console. Windows has none of the three, and starts an emulator as a program.
NOT_HERE_WHY = (
    "an app bundle is launched by `open`, which Windows does not have: start the emulator as a "
    "program there")


def executable_of(bundle: str | Path) -> str | None:
    """The executable inside a `.app`: its Info.plist's CFBundleExecutable, or None."""
    contents = Path(bundle) / "Contents"
    try:
        with open(contents / "Info.plist", "rb") as fh:
            info: Any = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    name = info.get("CFBundleExecutable") if isinstance(info, dict) else None
    if not isinstance(name, str) or not name:
        return None
    return str(contents / "MacOS" / name)


def is_bundle(path: str | Path) -> bool:
    """Whether `path` is a `.app` whose plist names an executable."""
    return (str(path).endswith(BUNDLE_SUFFIX) and Path(path).is_dir()
            and executable_of(path) is not None)


def _not_blocking(fd: int) -> None:
    if sys.platform == "win32":
        raise Invalid("host_failed", NOT_HERE_WHY)
    else:
        os.set_blocking(fd, False)


class QueuedConsole:
    """A FIFO's write end that never blocks its writer: a FIFO holds far less than a child's pipe,
    and an emulator stopped at its debugger reads neither, so what it cannot take yet waits."""

    def __init__(self, fd: int) -> None:
        _not_blocking(fd)
        self._fd = fd
        self._chunks: deque[bytes] = deque()
        self._ready = threading.Condition()
        self._closed = False
        self._failure: OSError | None = None
        self._thread = threading.Thread(target=self._pump, name="app-console", daemon=True)
        self._thread.start()

    def write(self, data: bytes) -> int:
        with self._ready:
            if self._closed:
                raise ValueError("write to a closed console")
            if self._failure is not None:
                raise self._failure
            self._chunks.append(bytes(data))
            self._ready.notify()
        return len(data)

    def flush(self) -> None:
        with self._ready:
            if self._failure is not None:
                raise self._failure

    def close(self) -> None:
        with self._ready:
            if self._closed:
                return
            self._closed = True
            self._ready.notify()
        self._thread.join(CONSOLE_CLOSE_S)
        os.close(self._fd)

    def _pump(self) -> None:
        while True:
            with self._ready:
                while not self._chunks and not self._closed:
                    self._ready.wait()
                if self._closed:
                    return
                chunk = self._chunks.popleft()
            if not self._send(chunk):
                return

    def _send(self, chunk: bytes) -> bool:
        """`chunk` written whole as the reader makes room; False once closed or failed."""
        while chunk:
            with self._ready:
                if self._closed:
                    return False
            if not select.select([], [self._fd], [], CONSOLE_POLL_S)[1]:
                continue
            try:
                chunk = chunk[os.write(self._fd, chunk):]
            except BlockingIOError:
                time.sleep(CONSOLE_POLL_S)
            except OSError as exc:
                with self._ready:
                    self._failure = exc
                return False
        return True


class Spawned(Protocol):
    """What a server holds of the emulator: a child it made, or an app launch's pid."""

    pid: int
    returncode: int | None

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


def open_argv(bundle: str | Path, argv: list[str], *, stdout: str | None,
              stdin_fifo: str | None = None, env: dict[str, str] | None = None,
              cwd: str | None = None) -> list[str]:
    """The `open` command: the bundle and its channels, then the emulator's own argv.

    `-n` keeps a stale instance from swallowing the launch; `-o` and `--stderr` share one path
    opened `O_APPEND`, so they interleave. `-g` when `env` asks for a launch behind, so `open`
    does not activate the app: a launch a person watches is the standard one, in front."""
    cmd = [OPEN, "-n"]
    if (env or {}).get(BACKGROUND_VAR):
        cmd += ["-g"]
    cmd += ["-a", str(bundle)]
    if stdin_fifo:
        cmd += ["-i", stdin_fifo]
    if stdout:
        cmd += ["-o", stdout, "--stderr", stdout]
    if cwd:
        cmd += ["--env", f"{CWD_VAR}={cwd}"]
    for key, value in (env or {}).items():
        cmd += ["--env", f"{key}={value}"]
    return cmd + ["--args", *argv[1:]]


def run_open(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """`open`, with its words kept for a refusal."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def find_pid(token: str, timeout: float) -> int | None:
    """The pid whose command line carries `token`, or None within `timeout` (`pgrep -f`)."""
    if sys.platform == "win32":
        raise Invalid("host_failed", NOT_HERE_WHY)
    else:
        deadline = time.monotonic() + timeout
        while True:
            # In a UTF-8 locale one process's undecodable argv makes pgrep fail for all of them.
            run = subprocess.run([PGREP, "-f", "-u", str(os.getuid()), "--", token],
                                 capture_output=True, text=True, check=False,
                                 env={**os.environ, "LC_ALL": "C"})
            said = run.stdout.split()
            if said:
                try:
                    return int(said[0])
                except ValueError:
                    pass
            if time.monotonic() >= deadline:
                return None
            time.sleep(FIND_POLL_S)


class AppProcess:
    """The emulator an app launch leaves: its pid, a console to write, and no exit status."""

    exit_code_known = False
    #: The pid was found by this session's own token, so the guardian may watch and kill it.
    pid_is_ours = True
    #: Never known here: the app is launchd's child, and nothing in this server reaps it.
    returncode: int | None = None

    def __init__(self, pid: int, stdin: IO[bytes] | None = None) -> None:
        self.pid = pid
        self.stdin = stdin
        self._gone = False

    def poll(self) -> int | None:
        """None while the pid lives; 0 once the kernel reports it gone."""
        if self._gone:
            return 0
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self._gone = True
            if self.stdin is not None:
                self.stdin.close()
            return 0
        except PermissionError:
            return None
        return None

    def wait(self, timeout: float | None = None) -> int:
        """0 once it is gone; `TimeoutExpired` if it outlives `timeout`."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.poll() is not None:
                return 0
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(f"pid {self.pid}", timeout or 0.0)
            time.sleep(WAIT_POLL_S)

    def kill(self) -> None:
        if sys.platform == "win32":
            raise Invalid("host_failed", NOT_HERE_WHY)
        else:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(self.pid, signal.SIGKILL)


def launch(bundle: str | Path, argv: list[str], *, stdout: str | None = None,
           stdin_fifo: str | None = None, env: dict[str, str] | None = None,
           cwd: str | None = None, token: str,
           timeout: float = FIND_TIMEOUT_S) -> AppProcess:
    """Start the bundle through `open` and hand back the process it left running.

    The FIFO is opened read-write first, so launchd finds a reader and a dead emulator is a
    liveness question, never an `EPIPE`."""
    if sys.platform == "win32":
        raise Invalid("host_failed", NOT_HERE_WHY)
    else:
        stdin = None
        if stdin_fifo:
            with contextlib.suppress(FileExistsError):
                os.mkfifo(stdin_fifo, 0o600)
            stdin = cast(IO[bytes], QueuedConsole(os.open(stdin_fifo, os.O_RDWR)))
        try:
            cmd = open_argv(bundle, argv, stdout=stdout, stdin_fifo=stdin_fifo, env=env,
                            cwd=cwd)
            run = run_open(cmd)
            if run.returncode != 0:
                said = (run.stderr or run.stdout).strip() or "it said nothing"
                raise Invalid("host_failed",
                              f"open refused the app bundle {bundle} (rc {run.returncode}): "
                              f"{said}")
            pid = find_pid(token, timeout)
        except BaseException:
            if stdin is not None:
                stdin.close()
            raise
        if pid is None:
            if stdin is not None:
                stdin.close()
            raise Invalid("host_failed",
                          f"open accepted {bundle} but no process carrying {token!r} appeared "
                          f"in {timeout:g} s: the app may have quit, or another user's process "
                          "holds the same command line")
        return AppProcess(pid, stdin)


def exit_status(proc: Any, code: int) -> int | dict[str, Any]:
    """`code`, or `unavailable` where nothing here reaped the process that ended with it."""
    return code if getattr(proc, "exit_code_known", True) else unavailable(UNKNOWN_EXIT_WHY)
