"""The shell-side twin of a watched `start`, the same on macOS and Windows:

    python -m scry_core.window_cli displays
    python -m scry_core.window_cli words mame|dosbox-x [--display N] [--fullscreen] [--size WxH]
    python -m scry_core.window_cli launch mame|dosbox-x [--display N] [--fullscreen] [--size WxH]
        -- COMMAND...
    python -m scry_core.window_cli proof PID [--display N] [--fullscreen] [--size WxH]
        [--emulator mame|dosbox-x] [--seconds S]

`words` prints the placement words, one argv entry per line (a line may hold a space). `launch`
starts COMMAND with those words appended, detached, and prints `pid: <N>`, the pid `proof` takes
(no shell quoting, the same on both hosts). `proof`
waits for the window PID itself owns (the emulator's own pid, not a launcher's) and prints
`window: display=<i> bounds=<x>,<y>,<w>x<h> onscreen=<bool>`, and with `--size` a second line
`size: asked=WxH seen=WxH compared=client|outer matches=<bool>`. Display 0 when omitted.

Exit 0 done; 2 bad usage or a refused request; 3 the window is not as asked (size included), or
`displays`, `words` and `launch` found no display online or the host refused; 4 `proof` could not
prove (no display online, or the host failed). Nothing is stopped.
"""

from __future__ import annotations

import argparse
import io
import math
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any, NoReturn, cast

from scry_core import window_words
from scry_core.reply_contract import Invalid
from scry_core.window import WindowRequest, host, prove, request
from scry_core.window_size import judge

EMULATORS: dict[str, Callable[[WindowRequest], list[str]]] = {
    "mame": window_words.mame, "dosbox-x": window_words.dosbox_x}


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _Usage(message)


def _bound(text: str) -> float:
    seconds = float(text)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a finite number of seconds, 0 or more")
    return seconds


def _parser() -> argparse.ArgumentParser:
    top = _Parser(prog="window_cli", add_help=False, allow_abbrev=False)
    sub = top.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("displays", add_help=False, allow_abbrev=False)
    for name in ("words", "launch", "proof"):
        one = sub.add_parser(name, add_help=False, allow_abbrev=False)
        if name != "proof":
            one.add_argument("emulator", choices=sorted(EMULATORS))
        if name == "proof":
            one.add_argument("pid", type=int)
            one.add_argument("--seconds", type=_bound)
            one.add_argument("--emulator", choices=sorted(EMULATORS))
        one.add_argument("--display", type=int)
        one.add_argument("--fullscreen", action="store_true")
        one.add_argument("--size")
    return top


def _asked(display: int | None, fullscreen: bool, emulator: str | None,
           size: str | None) -> WindowRequest:
    """A shell run is never halted at a debugger, so the halted-start rule does not apply."""
    asked = request(display, fullscreen, shared=True, displays=host().displays(),
                    emulator=emulator, halted=False, size=size)
    assert asked is not None    # `shared=True` always asks for a window
    return asked


def _displays() -> int:
    shown = host().displays()
    if not shown:
        print("no display is online: the displays are asleep or the host reports none",
              file=sys.stderr)
        return 3
    for d in shown:
        x, y, w, h = d.bounds
        print(f"display {d.index} bounds={x},{y},{w}x{h}")
    return 0


def _launch(command: list[str], words: list[str]) -> int:
    """`command` with `words` appended, detached from this process and its terminal."""
    if not command:
        print("window_cli: launch needs the emulator's command after `--`", file=sys.stderr)
        return 2
    argv = [*command, *words]
    detach: dict[str, Any] = {}
    if sys.platform == "win32":
        detach["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        detach["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **detach)
    except OSError as e:
        print(f"window_cli: {argv[0]} did not start: {e}", file=sys.stderr)
        return 2
    print(f"pid: {proc.pid}")
    return 0


def _refused(e: Invalid, command: str) -> int:
    """A refusal as a line and an exit code: the host failing is not the caller's to fix."""
    if e.code == "host_failed":
        proof = command == "proof"
        print(f"{e.code}: {'could not prove: ' if proof else ''}{e}", file=sys.stderr)
        return 4 if proof else 3
    print(f"{e.code}: {e}", file=sys.stderr)
    return 3 if e.code == "window_not_visible" else 2


def main(argv: Sequence[str]) -> int:
    args = list(argv)
    command: list[str] = []
    if args[:1] == ["launch"] and "--" in args:
        cut = args.index("--")
        args, command = args[:cut], args[cut + 1:]
    try:
        said = _parser().parse_args(args)
    except _Usage as e:
        print(f"window_cli: {e}", file=sys.stderr)
        return 2
    try:
        if said.command == "displays":
            return _displays()
        asked = _asked(said.display, said.fullscreen, said.emulator, said.size)
        if said.command == "launch":
            return _launch(command, EMULATORS[said.emulator](asked))
        if said.command == "words":
            cast(io.TextIOWrapper, sys.stdout).reconfigure(newline="\n")
            print("\n".join(EMULATORS[said.emulator](asked)))
            return 0
        state = prove(said.pid, asked, said.seconds, host(), shell=True)
    except Invalid as e:
        return _refused(e, said.command)
    x, y, w, h = state.bounds
    print(f"window: display={state.display} bounds={x},{y},{w}x{h} "
          f"onscreen={'true' if state.onscreen else 'false'}")
    if asked.size is None:
        return 0
    verdict = judge(asked.size, state, asked.scale, height_free=asked.height_free)
    asked_w, asked_h = asked.size
    print(f"size: asked={asked_w}x{asked_h} seen={verdict['seen']['width']}x"
          f"{verdict['seen']['height']} compared={verdict['compared']} "
          f"matches={'true' if verdict['matches'] else 'false'}")
    if verdict["matches"]:
        return 0
    print(f"window_not_visible: the window is not the size asked ({asked_w}x{asked_h}, compared "
          f"on its {verdict['compared']} rectangle, within {verdict['tolerance_px']} px); the "
          f"emulator did not take it", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
