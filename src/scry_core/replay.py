"""THE RUNNER of a replay document (`scry_core.recording` writes it): `python -m scry_core.replay
<document> [--binary PATH] [--rompath DIR] [--transcript PATH]`, from the server's repository,
with no model. It starts the server the document names (`entry`, a file or a module of the
repository it runs from) over stdio, calls `start` with the document's arguments and the options
given, checks that the store declares what the recorded start found declared and that every saved
state the document loads is there, plays the steps in one `perform`, and closes. It is
`scry_core.demo`'s machinery with the document as its steps, and inherits its exit codes: 0 every
step held, 1 a step failed or diverged in the server's own words, or the server said it held a
number of steps the document does not record, 2 usage, 3 nothing was demonstrated (a document that
is not one, that records nothing a step holds to, or whose `entry` file is gone; a start the
server refused; other declarations, or a saved state it lacks; a server that did not start, or
broke: a call that raised or timed out, an error result, a list it refused whole).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from scry_core import demo, prose
from scry_core.recording import DOCUMENT_VERSION, RECORDED
from scry_core.verdict import EXIT_INVALID, Invalid

#: The codes of a `perform` that answered in its own words about a step: a verdict (1), where any
#: other refusal of the list is the server's failure to play it (3).
STEP_CODES = frozenset({"step_failed", "diverged"})


def _entry_command(entry: str, root: Path) -> list[str]:
    """The server's argv for `entry`: a `.py` file beside the document runs as a script, a dotted
    module name runs with `-m`, so a packaged server never puts its own directory first."""
    if entry.endswith(".py") and Path(entry).name == entry:
        return [sys.executable, str(root / entry)]
    if re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", entry):
        return [sys.executable, "-m", entry]
    raise ValueError(entry)


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:              # unreadable, not UTF-8, not JSON
        raise Invalid(f"{path} is not a readable document: {e}") from None
    if not isinstance(doc, dict) or doc.get("version") != DOCUMENT_VERSION:
        raise Invalid(f"{path} is not a version {DOCUMENT_VERSION} replay document")
    entry = doc.get("entry")
    try:
        _entry_command(entry if isinstance(entry, str) else "", Path())
    except ValueError:
        raise Invalid(f"{path} names no server entry (`entry`, a `.py` file of the repository "
                           "the replay runs from or an importable module name)") from None
    steps, start, needs = doc.get("steps"), doc.get("start", {}), doc.get("needs", {})
    if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) for s in steps):
        raise Invalid(f"{path} holds no steps, or one that is not an object, so a replay "
                           "would demonstrate nothing")
    states = needs.get("states", []) if isinstance(needs, dict) else None
    declared = needs.get("declarations", {}) if isinstance(needs, dict) else None
    if not isinstance(start, dict) or not _names(states) or not isinstance(declared, dict) \
            or not all(isinstance(v, dict) and isinstance(v.get("tool"), str)
                       and _names(v.get("refs")) for v in declared.values()):
        raise Invalid(f"{path}: `start` is an object of arguments, `needs.states` a list "
                           "of names, and `needs.declarations` each list key's `tool` and `refs`")
    if not any(s.get(RECORDED) for s in steps):
        raise Invalid(f"{path}: no step carries `{RECORDED}`, so a replay would hold "
                           "nothing to anything: nothing held to")
    return doc


def _needs(states: Sequence[str]) -> Callable[[demo.Reply, demo.Run], str]:
    def check(reply: demo.Reply, run: demo.Run) -> str:
        listed = reply.get("states")
        if not isinstance(listed, list):
            raise Invalid(f"the server's `state_list` answered no list: {reply}")
        have = {s.get("name") for s in listed if isinstance(s, dict)}
        missing = [s for s in states if s not in have]
        if missing:
            raise Invalid(f"the document loads saved states the server does not have: "
                               f"{missing}")
        return f"{prose.counted(len(states), 'saved state')} the document loads, all there"
    return check


def _refused_start(reply: demo.Reply, run: demo.Run) -> str:
    raise Invalid(f"the server refused the start: {reply.get('summary') or reply}")


def _broke(reply: demo.Reply, run: demo.Run) -> str:
    """A call around the steps the server did not answer: no verdict about the steps."""
    raise Invalid(f"the server did not answer: {reply.get('summary') or reply}")


def _names(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(s, str) for s in value)


def _declarations(tool: str, key: str, recorded: Sequence[str]
                  ) -> Callable[[demo.Reply, demo.Run], str]:
    """One list's declarations as the replay starts, against the recorded start's: a replay
    armed otherwise would stop where the session did not, which is no verdict about it."""
    def check(reply: demo.Reply, run: demo.Run) -> str:
        listed = reply.get(key)
        if not isinstance(listed, list):
            raise Invalid(f"the server's `{tool}` answered no `{key}` list: {reply}")
        have = sorted(str(r["ref"]) for r in listed if isinstance(r, dict) and "ref" in r)
        want = sorted(recorded)
        if have != want:
            raise Invalid(f"`{tool}` lists {have} where the recorded session's start "
                               f"found {want}: clear or declare those first")
        return f"{prose.counted(len(want), 'declaration')}, as the recorded start found them"
    return check


def _played(steps: Sequence[Mapping[str, Any]]) -> Callable[[demo.Reply, demo.Run], str]:
    # Not "checks": the export spends that word on its reads, and an advancing step holds too.
    held = sum(bool(s.get(RECORDED)) for s in steps)

    def line(reply: demo.Reply, run: demo.Run) -> str:
        done = reply.get("steps_completed", reply.get("completed", "?"))
        if done != len(steps):         # an ok list can end early (a wait ran out): not a hold
            why = reply.get("note") or reply.get("verdict") or "no reason given"
            raise demo.StepFailed(f"{done} of {len(steps)} steps ran: {why}")
        if reply.get("held") != held:  # the server's own count, held to the document's
            raise demo.StepFailed(f"the server says {reply.get('held')!r} steps held to their "
                                  f"recorded answer and the document records {held}")
        return f"{prose.counted(int(done), 'step')}, {held} holding to a recorded answer"
    return line


def _failed(steps: Sequence[Mapping[str, Any]]) -> Callable[[demo.Reply, demo.Run], str]:
    def why(reply: demo.Reply, run: demo.Run) -> str:
        if reply.get("code") not in STEP_CODES:
            # An error result, or a list refused whole: the server did not play it.
            raise Invalid(f"the server did not play the list: "
                               f"{reply.get('message') or reply.get('summary') or reply}")
        at = reply.get("failed_at")
        op, where = "?", f"step {at}"
        if isinstance(at, int) and 0 <= at < len(steps):
            # `failed_at` counts from 0; a person reading the document counts from 1.
            op, where = steps[at].get("op", "?"), f"step {at + 1} of {len(steps)}"
        if reply.get("code") == "diverged":
            return (f"diverged at {where} ({op}): {reply.get('field')} recorded "
                    f"{reply.get('recorded')!r}, got {reply.get('got')!r}")
        return f"{where} ({op}) failed: {reply.get('message') or reply.get('summary')}"
    return why


def build(doc: dict[str, Any], root: Path, name: str) -> demo.Demo:
    """The document as a demo of its server: start, the states it needs, the steps, close."""
    entry = doc["entry"]
    if entry.endswith(".py") and not (root / entry).is_file():
        raise Invalid(f"the document's entry `{entry}` is not a file in {root}: a document "
                      f"exported before the server moved into a package names a script that is "
                      f"gone; set `entry` to the server's importable module name")
    steps = doc["steps"]
    needs = doc.get("needs") or {}
    states, declared = list(needs.get("states") or []), dict(needs.get("declarations") or {})
    plan: list[demo.Step] = [demo.Step("start", "start", dict(doc.get("start") or {}),
                                       lambda r, run: str(r.get("summary", "started")),
                                       options=True, failure=_refused_start,
                                       broken_is_invalid=True)]
    plan += [demo.Step(key, listed["tool"], {}, _declarations(listed["tool"], key,
                                                              listed["refs"]),
                       failure=_broke, broken_is_invalid=True)
             for key, listed in declared.items()]
    if states:
        plan.append(demo.Step("states", "state_list", {}, _needs(states), failure=_broke,
                              broken_is_invalid=True))
    plan += [demo.Step("perform", "perform", {"steps": steps, "summaries": True},
                       _played(steps), failure=_failed(steps), broken_is_invalid=True),
             demo.Step("close", "close", {}, lambda r, run: "closed", failure=_broke,
                       broken_is_invalid=True)]
    return demo.Demo(name=name, root=root,
                     server=_entry_command(entry, root),
                     steps=plan, offers=frozenset({"rompath"}),
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
    except Invalid as e:
        print(f"INVALID: {e}")
    except Exception as e:  # anything else before a verdict: nothing was demonstrated
        print(f"INVALID: {type(e).__name__}: {e}")
    return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(main())
