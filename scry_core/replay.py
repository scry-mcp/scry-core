"""THE RUNNER of a replay document (`scry_core.recording` writes it): `python -m scry_core.replay
<document> [--binary PATH] [--rompath DIR] [--transcript PATH]`, from the server's repository,
with no model. It starts the server over stdio, calls `start` with the document's arguments and
the options given, checks that every saved state the document loads is there, plays the steps in
one `perform`, and closes. It is `scry_core.demo`'s machinery with the document as its steps, and
inherits its exit codes: 0 every step held, 1 a step diverged or failed, 2 usage, 3 nothing was
demonstrated (a document that is not one, a start the server refused, a saved state it lacks, a
server that did not start).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from scry_core import demo
from scry_core.recording import DOCUMENT_VERSION, RECORDED

#: Each server's command, from its repository's root.
SERVERS: Mapping[str, str] = {"mame": "server.py", "dosbox-x": "dosbox_x_server.py"}


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:              # unreadable, not UTF-8, not JSON
        raise demo.Invalid(f"{path} is not a readable document: {e}") from None
    if not isinstance(doc, dict) or doc.get("version") != DOCUMENT_VERSION:
        raise demo.Invalid(f"{path} is not a version {DOCUMENT_VERSION} replay document")
    if doc.get("server") not in SERVERS:
        raise demo.Invalid(f"{path} names server {doc.get('server')!r}; this runner knows "
                           f"{sorted(SERVERS)}")
    steps, start, needs = doc.get("steps"), doc.get("start", {}), doc.get("needs", {})
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) for s in steps):
        raise demo.Invalid(f"{path} holds no steps, or one that is not an object, so a replay "
                           "would demonstrate nothing")
    states = needs.get("states", []) if isinstance(needs, dict) else None
    if not isinstance(start, dict) or not (
            isinstance(states, list) and all(isinstance(s, str) for s in states)):
        raise demo.Invalid(f"{path}: `start` is an object of arguments and `needs.states` a list "
                           "of state names")
    return doc


def _needs(states: Sequence[str]) -> Callable[[demo.Reply, demo.Run], str]:
    def check(reply: demo.Reply, run: demo.Run) -> str:
        have = {s.get("name") for s in reply.get("states", []) if isinstance(s, dict)}
        missing = [s for s in states if s not in have]
        if missing:
            raise demo.Invalid(f"the document loads saved states the server does not have: "
                               f"{missing}")
        return f"{len(states)} saved states the document loads, all there"
    return check


def _refused_start(reply: demo.Reply, run: demo.Run) -> str:
    raise demo.Invalid(f"the server refused the start: {reply.get('summary') or reply}")


def _played(steps: Sequence[Mapping[str, Any]]) -> Callable[[demo.Reply, demo.Run], str]:
    checks = sum(bool(s.get(RECORDED)) for s in steps)

    def line(reply: demo.Reply, run: demo.Run) -> str:
        return f"{reply.get('steps_completed', '?')} steps, {checks} checks"
    return line


def _failed(steps: Sequence[Mapping[str, Any]]) -> Callable[[demo.Reply, demo.Run], str]:
    def why(reply: demo.Reply, run: demo.Run) -> str:
        at = reply.get("failed_at")
        op = steps[at].get("op", "?") if isinstance(at, int) and 0 <= at < len(steps) else "?"
        if reply.get("code") == "diverged":
            return (f"diverged at step {at} ({op}): {reply.get('field')} recorded "
                    f"{reply.get('recorded')!r}, got {reply.get('got')!r}")
        return f"step {at} ({op}) failed: {reply.get('message') or reply.get('summary')}"
    return why


def build(doc: dict[str, Any], root: Path, name: str) -> demo.Demo:
    """The document as a demo of its server: start, the states it needs, the steps, close."""
    steps = doc["steps"]
    states = list((doc.get("needs") or {}).get("states") or [])
    plan: list[demo.Step] = [demo.Step("start", "start", dict(doc.get("start") or {}),
                                       lambda r, run: str(r.get("summary", "started")),
                                       options=True, failure=_refused_start)]
    if states:
        plan.append(demo.Step("states", "state_list", {}, _needs(states)))
    plan += [demo.Step("perform", "perform", {"steps": steps, "summaries": True},
                       _played(steps), failure=_failed(steps)),
             demo.Step("close", "close", {}, lambda r, run: "closed")]
    return demo.Demo(name=name, root=root,
                     server=[sys.executable, str(root / SERVERS[doc["server"]])],
                     readme=root / "README.md", steps=plan,
                     capture=lambda run: run.dir / "no-capture", offers=frozenset({"rompath"}),
                     verdict=lambda total, ok: f"REPLAY {name}: " + (
                         "every step held" if ok == total else "it did not hold"))


def main(argv: Sequence[str] | None = None) -> int:
    """The command line (the module docstring), its exit code."""
    p = argparse.ArgumentParser(prog="python -m scry_core.replay", allow_abbrev=False,
                                description="Replay a document `perform_export` wrote, with no "
                                "model, against the server of the repository it runs from.",
                                epilog="Exit codes: 0 every step held, 1 a step diverged or "
                                "failed, 2 a usage error, 3 nothing was demonstrated.")
    p.add_argument("document", type=Path)
    p.add_argument("--binary", help="the emulator to start; left out, the document's or the "
                   "server's own ladder")
    p.add_argument("--rompath", help="the directory holding the set's zip")
    p.add_argument("--transcript", type=Path, help="where the whole transcript goes; default "
                   "tmp/replays/<document stem>/transcript.md under the repository")
    ns = p.parse_args(argv)
    root = Path.cwd()
    name = ns.document.stem
    transcript = (ns.transcript or root / "tmp" / "replays" / name / "transcript.md").resolve()
    given = {"binary": ns.binary, "rompath": ns.rompath}
    run = demo.Run(dir=transcript.parent,
                   options={k: v for k, v in given.items() if v is not None})
    try:
        return demo.execute(build(_read(ns.document), root, name), run, transcript)
    except demo.Invalid as e:
        print(f"INVALID: {e}")
    except Exception as e:  # anything else before a verdict: nothing was demonstrated
        print(f"INVALID: {type(e).__name__}: {e}")
    return demo.EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
