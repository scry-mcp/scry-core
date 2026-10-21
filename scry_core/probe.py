"""`probe` -- what a model calls when all it holds is what the client delivers.

Run as `python -m scry_core.probe <server> --servers <file> --tasks <dir> [--runs N]`, where
<server> is a server the servers file loads, or `all`, and N (default 3) is how many independent
model runs judge each task. `--check` asks no model: see CHECK below; `--capture` keeps a run:
see CAPTURE.

THE REPOSITORY IS NAMED, NEVER FOUND. `--servers` is a Python file whose `load()` returns each
server's MODULE by its registered name (`.mcp` is the server, each tool the module attribute of
the same name), and which defines `ROOT`, the repository's root, which `{root}` in a task stands
for. It may
define `CHECKS`, each server's own pre-gate judge by name, and `CAPTURED`, the servers whose real
runs the repository keeps. `--tasks` is the directory of `<server>.json`. Both are required: this
module belongs to no repository, and a default would read another one's.

TWO DIRECTORIES ARE DERIVED FROM `ROOT`, and the derivation is the contract (no option moves
them): a run writes its directory under `ROOT/tmp/mcp_probe/`, and the captures live under
`ROOT/tests/fixtures/mcp_probe/captured/<server>/`.

WHAT IT ASKS. Per server, ONE prompt: the server's `instructions` and every tool as `list_tools()`
delivers it (name, description, input schema), each text cut where the client cuts it
(`client_cap.delivered`), then the tasks of `<tasks>/<server>.json`.
A fresh `claude --print` on haiku at low effort, with no tool, no MCP server, no settings and so no
project instructions, answers one line per task:

    <id>: {"tool": "<name>", "args": {...}}      or      <id>: CANNOT <reason>

WHAT IS RIGHT. The expected tool; every argument equal to the expected one, where an argument
passed at its default counts as absent; a call that binds to the tool's signature; and, on a
server the servers file gives a `CHECKS` entry, one the server's own judge accepts. A line that
does not parse is WRONG, never skipped. A tool PASSES only when every task on it is right in
every run.

THE TASK FILE is {"tasks": [...]}, and a task is:
  id       unique; the model writes it at the head of its line
  prompt   what is asked, in the words a caller would use
  tool     the expected tool, with `args`: name -> value, or {"any_of": [value, ...]} at any
           depth; `args` itself may be {"any_of": [{...}, {...}]}, equivalent whole calls
  allow    argument names that may carry any value
  grammar  values the description HAS to hold (an enum word, a lane), exempt from contamination
  expect   "CANNOT" in place of `tool` and `args`, with `about`: the tool whose limit it probes

REFUSED BEFORE ANY MODEL IS ASKED, each naming what it found (INVALID, exit 3):
  - a coverage hole: a tool with no task, a schema property no task's `args` or `allow` names,
    a server with no CANNOT task;
  - contamination: a task value (an expected argument, a hex literal in the prompt) that the
    tool's own description holds as a whole word, unless the task lists it under `grammar`;
  - a task naming a tool or an argument the server does not have;
  - a task file that is malformed (an id, a key, a shape the list above does not take), or a
    task whose own expected call the server's judge refuses.

OUTPUT. One line per tool, `PASS <server> <tool> N/N` or `FAIL <server> <tool> k/N (<task ids>)`,
k being the runs in which every task on it was right; one summary line; and LAST, the directory
under `ROOT/tmp/mcp_probe/` that holds the prompts, the raw answers and every per-task verdict.

EXIT: 0 every tool passes; 1 any FAIL; 2 usage; 3 INVALID: nothing to examine, a refusal above,
a model call that failed or answered no line for any task, or the probe itself breaking.

CHECK. `--check` runs only the refusals above, which cost nothing and need no network, and
prints `OK <server>: <n> tasks cover <m> tools` or one `REFUSED <problem>` line each; it writes no
directory. Exit 0 covered, 1 a refusal found, 2 usage (`--runs` beside it), 3 INVALID (it could
not examine). A repository's pre-commit can run it, so a task set that no longer fits its servers
cannot be committed. It cannot see a CHANGED description: running the probe is for that.

THE MODEL RUN IS NOT A GATE. Every run costs money and needs the network, and at haiku a miss
moves between tools from run to run, so a gate on it would block by chance: it is run by hand
after a description changes.

THE SEAM. `MCP_PROBE_ANSWERS=<dir>` replays `<server>-run<k>.txt` from that directory instead of
calling `claude`. An output directory is such a directory, which is how the probe's own tests run
free and offline; a real run is kept in the tree through CAPTURE, below.

CAPTURE. `<server> --capture <run directory> --ids <id>[,<id>...]` keeps the named tasks of a
real run as `ROOT/tests/fixtures/mcp_probe/captured/<server>/<id>.json`, `{"task": <as its file
writes it>, "runs": [{"lines": [<every line that answered it, the root's path as {root}>],
"right": <the run's verdict>}]}`; the suite re-judges each one and names a task with none. It asks
no model and makes no output directory. Exit 0 written; 2 usage (a server of `CAPTURED`,
both options, no `--runs` or `--check`, no empty or repeated id); 3 INVALID: anything it cannot
prove (a run on another surface, a task asked or judged otherwise now) writes nothing, and a write
that fails part-way names the files it wrote.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import datetime as dt
import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any

from scry_core.client_cap import delivered

# Re-exported: callers spell these `probe.<name>`.
from scry_core.verdict import EXIT_FAIL as EXIT_FAIL
from scry_core.verdict import EXIT_INVALID as EXIT_INVALID
from scry_core.verdict import EXIT_PASS as EXIT_PASS
from scry_core.verdict import Invalid as Invalid

#: Where a run writes and where the captures live, under the repository's root: the contract
#: `--help` states, so no option moves them.
RUNS_UNDER_ROOT = Path("tmp") / "mcp_probe"
CAPTURED_UNDER_ROOT = Path("tests") / "fixtures" / "mcp_probe" / "captured"
ANSWERS_ENV = "MCP_PROBE_ANSWERS"
#: Written in a task file where a path has to EXIST for the server's check (a reference image):
#: it becomes the repository's root, so the file stays true in any clone.
ROOT_MARK = "{root}"
CLAUDE_TIMEOUT_S = 600
DEFAULT_RUNS = 3

#: THE MODEL SEES WHAT THE PROMPT CARRIES AND NOTHING ELSE. `--setting-sources ""` is what keeps
#: project instructions and hooks out (without it the child answers from instructions the prompt
#: never carried),
#: `--strict-mcp-config` with no config keeps every MCP server out, and `--tools ""` the built-ins.
CLAUDE = ["claude", "--print", "--model", "haiku", "--effort", "low", "--max-budget-usd", "1",
          "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config"]
STATIC = [*CLAUDE, "--tools", "", "--output-format", "json"]

#: How `--check` begins each line: a server covered, or one problem it refuses. A caller reading
#: the check's output (a pre-commit) matches these, never its own spelling of them.
CHECK_OK, CHECK_REFUSED = "OK ", "REFUSED "
CANNOT = "CANNOT"
NO_LINE = "no answer line"

#: A number this small is in every description as a count or a width, so finding it there says
#: nothing about a copied example; contamination looks only at numbers from here up.
SMALL_NUMBER = 16

TASK_KEYS = frozenset({"id", "prompt", "tool", "args", "allow", "grammar", "expect", "about"})
TASK_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
#: One answer line: an id, a colon, the rest. Markdown a model adds around it (a bullet, bold,
#: backticks) is tolerated; anything else about the line is the rest's to parse.
ANSWER_LINE = re.compile(
    r"^[\s>*`-]*(?P<id>[A-Za-z][A-Za-z0-9_-]*)[`*]*\s*:[\s`]*(?P<rest>.*?)[\s`]*$")
HEX_LITERAL = re.compile(r"\b0x[0-9A-Fa-f]+\b")

PROMPT_HEAD = """\
Below are the instructions and the tools of the MCP server `{server}`, exactly as an MCP client \
delivers them. You cannot call any tool here. For each task, write the ONE call you would make \
to do it with this server.

Answer with one line per task, in the order given, and nothing else: no prose, no code fence.
<id>: {{"tool": "<tool name>", "args": {{"<argument>": <value>, ...}}}}
Write each value as the JSON type the tool's input schema declares. Pass only the arguments the \
task needs, and leave out every argument you would leave at its default.
When no tool of this server can do what a task asks, answer that task with:
<id>: CANNOT <one-sentence reason>
"""


TASKS_HEAD = "=== TASKS ==="


def broke(what: str, e: Exception) -> str:
    """The INVALID line for an exception nobody expected: a traceback exits 1, which reads as a
    FAIL, so every entry point catches the rest and says this instead."""
    traceback.print_exc()
    return f"INVALID the {what} broke, so nothing here is a verdict: {type(e).__name__}: {e}"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    #: The tool function's signature narrowed to what the schema offers a caller: a parameter the
    #: SDK injects (`ctx`) is not the model's to pass.
    signature: inspect.Signature


#: The server's own pre-gate judge: (tool, the arguments given, the arguments with defaults).
Check = Callable[[str, dict[str, Any], dict[str, Any]], None]


@dataclass(frozen=True)
class ProbeRepo:
    """The one repository a probe reads, built by `configure` and taken by every engine function,
    so everything a call reads is what it was handed. `modules` are the servers file's servers in
    its order; `checks` each one's own pre-gate judge; `captured_servers` the ones whose real runs
    the repository keeps. `configure` also puts the root on `sys.path`, since the repository's
    modules import each other by name."""

    root: Path
    tasks_dir: Path
    out_dir: Path
    captured_dir: Path
    modules: Mapping[str, ModuleType]
    checks: Mapping[str, Check]
    captured_servers: tuple[str, ...]

    @property
    def servers(self) -> tuple[str, ...]:
        return tuple(self.modules)


@dataclass(frozen=True)
class Surface:
    server: str
    instructions: str
    tools: dict[str, Tool]
    check: Check | None


@dataclass(frozen=True)
class Answer:
    kind: str  # "call", CANNOT, or "bad"
    text: str
    tool: str = ""
    args: dict[str, Any] | None = None
    why: str = ""  # what is wrong with a "bad" one


@dataclass(frozen=True)
class Verdict:
    right: bool
    why: str
    line: str


# ---- the servers, as the client sees them -------------------------------------------------


def configure(servers_file: Path, tasks_dir: Path) -> ProbeRepo:
    """The repository a servers file and a tasks directory name, or `Invalid` when the file is not
    one the probe can use. The servers are whatever `load()` hands back: a servers file that
    imports its server by name hands the module the suite already holds."""
    path = servers_file.resolve()
    spec = importlib.util.spec_from_file_location("mcp_probe_servers", path)
    if spec is None or spec.loader is None:
        raise Invalid(f"--servers {servers_file}: not a Python file the probe can load")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError as e:
        raise Invalid(f"--servers {servers_file}: {e}") from None
    load, root = getattr(module, "load", None), getattr(module, "ROOT", None)
    if not callable(load) or not isinstance(root, Path):
        raise Invalid(f"--servers {servers_file} defines no `load()` and `ROOT` (a Path): see "
                      "THE REPOSITORY IS NAMED in this module's help")
    # The repository's own modules import each other by name, as they do run from its root.
    if str(root.resolve()) not in sys.path:
        sys.path.insert(0, str(root.resolve()))
    modules = load()
    if not isinstance(modules, dict) or not modules:
        raise Invalid(f"--servers {servers_file} loads no server, so there is nothing to examine")
    checks, captured = getattr(module, "CHECKS", {}), getattr(module, "CAPTURED", ())
    if not isinstance(checks, dict) or not isinstance(captured, tuple):
        raise Invalid(f"--servers {servers_file}: `CHECKS` is a dict and `CAPTURED` a tuple")
    # A judge filed under a name no server answers to would leave that server judged by
    # signature alone, in silence: a misspelt key is refused like a missing file.
    if stray := sorted({*checks, *captured} - set(modules)):
        raise Invalid(f"--servers {servers_file} names {', '.join(stray)} in `CHECKS` or "
                      f"`CAPTURED`, and loads no such server ({', '.join(modules)})")
    at = root.resolve()
    return ProbeRepo(at, tasks_dir, at / RUNS_UNDER_ROOT, at / CAPTURED_UNDER_ROOT,
                     MappingProxyType(dict(modules)), MappingProxyType(dict(checks)), captured)


def load_surface(repo: ProbeRepo, server: str) -> Surface:
    module = repo.modules[server]
    tools: dict[str, Tool] = {}
    for listed in asyncio.run(module.mcp.list_tools()):
        schema = dict(listed.input_schema or {})
        offered = set(schema.get("properties") or {})
        signature = inspect.signature(getattr(module, listed.name))
        signature = signature.replace(parameters=[p for p in signature.parameters.values()
                                                  if p.name in offered])
        tools[listed.name] = Tool(listed.name, delivered(listed.description or ""), schema,
                                  signature)
    if not tools:
        raise Invalid(f"{server} lists no tools, so there is nothing to examine")
    return Surface(server, delivered(module.mcp.instructions or ""), tools,
                   repo.checks.get(server))


def tasks_file(repo: ProbeRepo, server: str) -> Path:
    return repo.tasks_dir / f"{server}.json"


def load_tasks(repo: ProbeRepo, server: str) -> list[dict[str, Any]]:
    return read_tasks(repo, tasks_file(repo, server))


def resolve_root(repo: ProbeRepo, text: str) -> str:
    return text.replace(ROOT_MARK, str(repo.root))


def mark_root(repo: ProbeRepo, text: str) -> str:
    """The inverse of `resolve_root`: what a tracked file keeps, true in any clone."""
    return text.replace(str(repo.root), ROOT_MARK)


def read_tasks(repo: ProbeRepo, path: Path, *, raw: bool = False) -> list[dict[str, Any]]:
    """The tasks, with `{root}` resolved to the repository, or kept as written with `raw`, which is
    how a capture stores the task it answered."""
    try:
        text = path.read_text(encoding="utf-8")
        doc = json.loads(text if raw else resolve_root(repo, text))
    except (OSError, json.JSONDecodeError) as e:
        raise Invalid(f"{path}: {e}") from None
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise Invalid(f"{path} holds no tasks, so there is nothing to examine")
    return tasks


# ---- what is refused before a model is asked ------------------------------------------------


def on_tool(task: dict[str, Any]) -> str:
    """The tool a task is judged under: the one it calls, or the one whose limit it probes."""
    return str(task.get("tool") or task.get("about") or "")


def task_problems(surface: Surface, tasks: list[dict[str, Any]]) -> list[str]:
    """A task file that names what the server does not have would judge nothing it claims to."""
    return [p for found in _problems_by_task(surface, tasks) for p in found]


def _problems_by_task(surface: Surface, tasks: list[dict[str, Any]]) -> list[list[str]]:
    """`task_problems`, one list per task in order, so a caller can keep the tasks with none."""
    out: list[list[str]] = []
    seen: set[str] = set()
    for i, task in enumerate(tasks):
        found: list[str] = []
        out.append(found)
        tid = task.get("id") if isinstance(task, dict) else None
        where = f"{surface.server} task {tid or f'#{i}'}"
        if not isinstance(task, dict) or not isinstance(tid, str) or not TASK_ID.fullmatch(tid):
            found.append(f"{where}: needs an `id` of letters, digits, `_` or `-`")
            continue
        if tid in seen:
            found.append(f"{where}: the id is used twice")
        seen.add(tid)
        if unknown := sorted(set(task) - TASK_KEYS):
            found.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            found.append(f"{where}: needs a `prompt`")
        grammar, allow = task.get("grammar", []), task.get("allow", [])
        if not isinstance(grammar, list) or not all(_is_scalar(g) for g in grammar):
            found.append(f"{where}: `grammar` must be a list of strings or numbers")
        if not isinstance(allow, list) or not all(isinstance(a, str) for a in allow):
            found.append(f"{where}: `allow` must be a list of argument names")
            continue
        tool = surface.tools.get(on_tool(task))
        if task.get("expect") == CANNOT:
            if tool is None:
                found.append(f"{where}: `about` names no tool of this server")
            if "tool" in task or "args" in task:
                found.append(f"{where}: a CANNOT task carries no `tool` or `args`")
            continue
        if "expect" in task:
            found.append(f"{where}: `expect` can only be {CANNOT!r}")
        if "about" in task:
            found.append(f"{where}: `about` belongs to a CANNOT task; a call names its `tool`")
        if "tool" not in task or tool is None:
            found.append(f"{where}: `tool` names no tool of this server")
            continue
        if _has_empty_any_of(task.get("args", {})):
            found.append(f"{where}: an `any_of` with no alternative accepts nothing")
            continue
        alternatives = calls(task.get("args", {}))
        if not all(isinstance(a, dict) for a in alternatives):
            found.append(f"{where}: `args` must be an object, or an `any_of` list of objects")
            continue
        for args in alternatives:
            found += _call_problems(surface, tool, where, args, allow)
    return out


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float)


def _has_empty_any_of(value: Any) -> bool:
    """Whether an `any_of` anywhere in `value` is not a list of at least one alternative."""
    if _is_any_of(value):
        held = value["any_of"]
        return not isinstance(held, list) or not held or any(_has_empty_any_of(v) for v in held)
    if isinstance(value, dict):
        return any(_has_empty_any_of(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_empty_any_of(v) for v in value)
    return False


def calls(args: Any) -> list[Any]:
    """The whole calls a task accepts: one, or each of an `any_of` of calls."""
    return list(args["any_of"]) if _is_any_of(args) else [args]


def _call_problems(surface: Surface, tool: Tool, where: str, args: dict[str, Any],
                   allow: list[str]) -> list[str]:
    params = tool.signature.parameters
    out: list[str] = []
    if bad := sorted((set(args) | set(allow)) - set(params)):
        out.append(f"{where}: {tool.name} has no argument {', '.join(bad)}")
    if both := sorted(set(args) & set(allow)):
        out.append(f"{where}: {', '.join(both)} both expected and allowed")
    required = {n for n, p in params.items() if p.default is inspect.Parameter.empty}
    if missing := sorted(required - set(args) - set(allow)):
        out.append(f"{where}: required {', '.join(missing)} neither expected nor allowed")
    # The server's judge is asked only about a call the task fixes whole: a required argument
    # left to `allow` has no value to judge.
    elif not bad and required <= set(args) and (
            refusal := _refusal(surface, tool, concrete(args))):
        out.append(f"{where}: its own expected call is refused: {refusal}")
    return out


def _refusal(surface: Surface, tool: Tool, args: dict[str, Any]) -> str:
    """Why this call would be refused before it reached the machine, or "" if it would not.
    Its arguments already bind: the caller has checked their names."""
    bound = tool.signature.bind(**args)
    if surface.check is None:
        return ""
    given = dict(bound.arguments)
    bound.apply_defaults()
    try:
        surface.check(tool.name, given, dict(bound.arguments))
    except AssertionError as e:
        raise Invalid(f"{surface.server} check does not know {tool.name}: {e}") from None
    except ImportError as e:
        # A judge that cannot be loaded refuses nothing: it is the probe that is broken.
        raise Invalid(f"{surface.server}'s check cannot be imported: {e}") from None
    except Exception as e:  # noqa: BLE001 -- any refusal of the server's own judge
        return f"the server's check refuses it: {e}"
    return ""


def coverage_holes(surface: Surface, tasks: list[dict[str, Any]]) -> list[str]:
    """Every tool probed, every argument it offers named by some task, and one refusal: an
    argument no task uses is one nobody finds out a model cannot name."""
    out: list[str] = []
    for tool in surface.tools.values():
        mine = [t for t in tasks if on_tool(t) == tool.name]
        if not mine:
            out.append(f"no task on {surface.server} {tool.name}")
            continue
        named = {n for t in mine for n in
                 [*t.get("allow", []), *(k for c in calls(t.get("args", {})) for k in c)]}
        out += [f"no task names {surface.server} {tool.name}.{p}"
                for p in (tool.schema.get("properties") or {}) if p not in named]
    if not any(t.get("expect") == CANNOT for t in tasks):
        out.append(f"{surface.server} has no CANNOT task")
    return out


def _leaves(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for v in (value["any_of"] if _is_any_of(value) else value.values()):
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


def _spellings(value: Any) -> list[str]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int):
        return [str(value), hex(value)] if abs(value) >= SMALL_NUMBER else []
    if isinstance(value, float):
        return [repr(value)] if abs(value) >= SMALL_NUMBER else []
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _folded(value: Any) -> Any:
    """A grammar entry exempts what the search would find, and the search ignores case."""
    return value.casefold() if isinstance(value, str) else value


def contamination(surface: Surface, tasks: list[dict[str, Any]]) -> list[str]:
    """A task value its tool's description already holds tests copying, not reading: the
    answer is on the page."""
    out: list[str] = []
    for task in tasks:
        tool = surface.tools.get(on_tool(task))
        if tool is None:
            continue
        grammar = {_folded(g) for g in task.get("grammar", [])}
        values = [*_leaves(task.get("args", {})), *HEX_LITERAL.findall(task.get("prompt", ""))]
        for value in values:
            if _folded(value) in grammar:
                continue
            for spelled in _spellings(value):
                pattern = rf"(?<![\w]){re.escape(spelled)}(?![\w])"
                if re.search(pattern, tool.description, re.IGNORECASE):
                    out.append(f"{surface.server} task {task['id']}: {spelled!r} is in "
                               f"{tool.name}'s own description")
                    break
    return out


# ---- asking the model --------------------------------------------------------------------


def prompt_for(surface: Surface, tasks: list[dict[str, Any]]) -> str:
    parts = [PROMPT_HEAD.format(server=surface.server), "=== SERVER INSTRUCTIONS ===",
             delivered(surface.instructions), "", "=== TOOLS ==="]
    for tool in surface.tools.values():
        parts += [f"--- tool: {tool.name}", delivered(tool.description).rstrip(),
                  f"input schema: {json.dumps(tool.schema, ensure_ascii=False)}", ""]
    parts.append(TASKS_HEAD)
    parts += [task_line(t) for t in tasks]
    return "\n".join(parts) + "\n"


def task_line(task: dict[str, Any]) -> str:
    """How the prompt asks one task, under `TASKS_HEAD`."""
    return f"{task['id']}: {task['prompt']}"


# The three files of a run directory a capture reads, named once: the run writes them and the seam
# replays the answers from such a directory.
def prompt_file(out: Path, server: str) -> Path:
    return out / f"{server}-prompt.txt"


def verdicts_file(out: Path, server: str) -> Path:
    return out / f"{server}-verdicts.json"


def answer_file(out: Path, server: str, run: int) -> Path:
    return out / f"{server}-run{run}.txt"


def ask(server: str, prompt: str, run: int, out: Path) -> str:
    """One model run: the answer text, saved under the name the seam reads."""
    answer = answer_file(out, server, run)
    replay = os.environ.get(ANSWERS_ENV)
    if replay:
        replayed = Path(replay) / answer.name
        if not replayed.is_file():
            raise Invalid(f"{ANSWERS_ENV} holds no {answer.name}")
        text = replayed.read_text(encoding="utf-8")
    else:
        text = _claude(STATIC, prompt, answer.with_suffix(".json"))
    answer.write_text(text, encoding="utf-8")
    return text


def _claude(command: list[str], prompt: str, saved: Path) -> str:
    # A cwd of its own, outside the repository: no project instructions above it.
    with tempfile.TemporaryDirectory(prefix="mcp_probe-") as cwd:
        try:
            proc = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                  errors="replace", cwd=cwd, timeout=CLAUDE_TIMEOUT_S,
                                  check=False)
        except FileNotFoundError:
            raise Invalid("`claude` is not on PATH") from None
        except subprocess.TimeoutExpired:
            raise Invalid(f"`claude` did not answer within {CLAUDE_TIMEOUT_S} s") from None
        except OSError as e:
            raise Invalid(f"`claude` could not be run: {e}") from None
    saved.write_text(proc.stdout, encoding="utf-8")
    saved.with_suffix(".stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise Invalid(f"`claude` exited {proc.returncode}; its output is in {saved}")
    try:
        doc = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise Invalid(f"`claude` printed no JSON document; see {saved}") from None
    if not isinstance(doc, dict) or doc.get("is_error") or not isinstance(doc.get("result"), str):
        raise Invalid(f"`claude` reported an error; see {saved}")
    return str(doc["result"])


# ---- judging ---------------------------------------------------------------------------


def answer_lines(text: str) -> Iterator[tuple[str, str, str]]:
    """Each line of an answer that carries a task id: the id, the line whole, what follows it."""
    for line in text.splitlines():
        if m := ANSWER_LINE.match(line):
            yield m["id"], line, m["rest"]


def parse(text: str, ids: list[str]) -> dict[str, Answer]:
    lines: dict[str, list[str]] = {}
    for tid, _, rest in answer_lines(text):
        if tid in ids:
            lines.setdefault(tid, []).append(rest)
    return {tid: _answer(lines.get(tid, [])) for tid in ids}


def _answer(rests: list[str]) -> Answer:
    if not rests:
        return Answer("bad", "", why=NO_LINE)
    if len(rests) > 1:
        return Answer("bad", " | ".join(rests), why=f"answered {len(rests)} times")
    rest = rests[0]
    if rest.startswith(CANNOT):
        return Answer(CANNOT, rest)
    try:
        doc = json.loads(rest)
    except json.JSONDecodeError:
        return Answer("bad", rest, why="the line does not parse")
    if (not isinstance(doc, dict) or not isinstance(doc.get("tool"), str)
            or not isinstance(doc.get("args", {}), dict)):
        return Answer("bad", rest, why='not {"tool": <name>, "args": {...}}')
    return Answer("call", rest, doc["tool"], dict(doc.get("args", {})))


def same(a: Any, b: Any) -> bool:
    """JSON equality that does not let `True` pass for `1`, and does let `5` pass for `5.0`."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and bool(a == b)


def matches(expected: Any, got: Any) -> bool:
    """`same`, with `{"any_of": [...]}` accepted at any depth of the expected value."""
    if _is_any_of(expected):
        return any(matches(e, got) for e in expected["any_of"])
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(matches(expected[k], got[k]) for k in got)
    if isinstance(expected, list) and isinstance(got, list):
        return len(expected) == len(got) and all(
            matches(e, g) for e, g in zip(expected, got, strict=True))
    return same(expected, got)


def _is_any_of(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"any_of"}


def concrete(expected: Any) -> Any:
    """The expected value with each `any_of` taken at its first alternative: a call to test."""
    if _is_any_of(expected):
        return concrete(expected["any_of"][0])
    if isinstance(expected, dict):
        return {k: concrete(v) for k, v in expected.items()}
    if isinstance(expected, list):
        return [concrete(v) for v in expected]
    return expected


def _mismatch(tool: Tool, expected_args: dict[str, Any], allow: set[str],
              effective: dict[str, Any]) -> str:
    """The first argument that differs from one expected call, or "" when none does."""
    for name, param in tool.signature.parameters.items():
        if name in allow:
            continue
        expected = expected_args.get(name, _as_json(param.default))
        got = _as_json(effective[name])
        if not matches(expected, got):
            return f"{name}={json.dumps(got)}, expected {json.dumps(expected)}"
    return ""


def _as_json(value: Any) -> Any:
    """A value as JSON carries it: a default left in place compares with what a model writes."""
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return value


def judge(surface: Surface, task: dict[str, Any], answer: Answer) -> Verdict:
    def wrong(why: str) -> Verdict:
        return Verdict(False, why, answer.text)

    if task.get("expect") == CANNOT:
        if answer.kind == CANNOT:
            return Verdict(True, "refused, as expected", answer.text)
        return wrong("expected CANNOT" if answer.kind == "call" else answer.why)
    if answer.kind == "bad":
        return wrong(answer.why)
    if answer.kind == CANNOT:
        return wrong("answered CANNOT")
    if answer.tool != task["tool"]:
        return wrong(f"called {answer.tool!r}, expected {task['tool']!r}")
    tool = surface.tools[task["tool"]]
    try:
        bound = tool.signature.bind(**(answer.args or {}))
    except TypeError as e:
        return wrong(f"it does not bind to the signature: {e}")
    bound.apply_defaults()
    allow = set(task.get("allow", []))
    mismatches = [_mismatch(tool, expected_args, allow, dict(bound.arguments))
                  for expected_args in calls(task.get("args", {}))]
    if all(mismatches):
        return wrong(mismatches[0])
    if refusal := _refusal(surface, tool, answer.args or {}):
        return wrong(refusal)
    return Verdict(True, "right", answer.text)


# ---- one server, N runs ------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    server: str
    lines: list[str]
    passed: int
    failed: int


def run_static(surface: Surface, tasks: list[dict[str, Any]], runs: int,
               out: Path) -> list[dict[str, Verdict]]:
    prompt = prompt_for(surface, tasks)
    prompt_file(out, surface.server).write_text(prompt, encoding="utf-8")
    ids = [t["id"] for t in tasks]
    with concurrent.futures.ThreadPoolExecutor(max_workers=runs) as pool:
        texts = list(pool.map(lambda k: ask(surface.server, prompt, k, out), range(1, runs + 1)))
    verdicts: list[dict[str, Verdict]] = []
    for k, text in enumerate(texts, start=1):
        answers = parse(text, ids)
        if all(a.why == NO_LINE for a in answers.values()):
            raise Invalid(f"{surface.server} run {k} answered no line for any task")
        verdicts.append({t["id"]: judge(surface, t, answers[t["id"]]) for t in tasks})
    return verdicts


def tally(surface: Surface, tasks: list[dict[str, Any]],
          verdicts: list[dict[str, Verdict]]) -> Outcome:
    lines: list[str] = []
    passed = failed = 0
    runs = len(verdicts)
    for tool in surface.tools:
        mine = [t["id"] for t in tasks if on_tool(t) == tool]
        good = sum(all(run[i].right for i in mine) for run in verdicts)
        if good == runs:
            passed += 1
            lines.append(f"PASS {surface.server} {tool} {good}/{runs}")
        else:
            failed += 1
            wrong = [i for i in mine if not all(run[i].right for run in verdicts)]
            lines.append(f"FAIL {surface.server} {tool} {good}/{runs} ({', '.join(wrong)})")
    return Outcome(surface.server, lines, passed, failed)


def _save_verdicts(out: Path, server: str, verdicts: list[dict[str, Verdict]]) -> None:
    doc = [{tid: {"right": v.right, "why": v.why, "line": v.line} for tid, v in run.items()}
           for run in verdicts]
    verdicts_file(out, server).write_text(json.dumps(doc, indent=1, ensure_ascii=False),
                                          encoding="utf-8")


# ---- the per-task capture ----------------------------------------------------------------


def capture_problems(repo: ProbeRepo, server: str, captured: Path,
                     tasks_file: Path) -> list[str]:
    """Why the captures in `captured` are not every task of `tasks_file` judged as it was, one
    line per problem: none examined at all, a task with no capture, a file that is not the
    capture of the task its name says, a capture of no task, one answered to another question, one
    the surface cannot judge any more, and a stored verdict the current surface no longer gives. A
    task file or a surface that cannot be read raises `Invalid`."""
    files = sorted(captured.glob("*.json")) if captured.is_dir() else []
    if not files:
        return [f"INVALID: no capture examined ({captured} holds none)"]
    raw, resolved = _tasks_by_id(repo, tasks_file)
    surface = load_surface(repo, server)
    out: list[str] = []
    if missing := [tid for tid in raw if not (captured / f"{tid}.json").is_file()]:
        out.append(f"{server}: no capture of task {', '.join(missing)}")
    for f in files:
        tid = f.stem
        try:
            task, runs = _read_capture(f)
        except ValueError as e:
            out.append(f"{server} {tid}: {e}")
            continue
        if tid not in raw:
            out.append(f"{server} {tid}: captured, but the task file holds no task {tid}")
            continue
        if not same(task, raw[tid]):
            out.append(f"{server} {tid}: captured for another question than the task file asks "
                       "now")
            continue
        for k, run in enumerate(runs, start=1):
            try:
                now = rejudge(repo, surface, resolved[tid], run["lines"])
            except (KeyError, Invalid) as e:
                out.append(f"{server} {tid}: cannot be judged now: {type(e).__name__} {e}")
                break
            if now.right != run["right"]:
                said = "right now" if now.right else f"wrong now ({now.why})"
                out.append(f"{server} {tid} run {k}: judged {said}, captured as "
                           f"{'right' if run['right'] else 'wrong'}")
    return out


def _tasks_by_id(repo: ProbeRepo, tasks_file: Path
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Each task by id twice: as the file writes it, which a capture stores, and resolved to the
    repository, which is what was asked and is judged. The ids are `--check`'s to keep unique, and
    a file `--check` would refuse is `Invalid` here."""
    def by_id(tasks: list[Any]) -> dict[str, dict[str, Any]]:
        if not all(isinstance(t, dict) and isinstance(t.get("id"), str) for t in tasks):
            raise Invalid(f"{tasks_file} holds an entry that is not a task with an `id`: "
                          "`--check` names it")
        return {t["id"]: t for t in tasks}

    return by_id(read_tasks(repo, tasks_file, raw=True)), by_id(read_tasks(repo, tasks_file))


def rejudge(repo: ProbeRepo, surface: Surface, task: dict[str, Any], lines: list[str]) -> Verdict:
    """A run's stored lines for one task, judged again as the run's whole answer was."""
    answers = parse(resolve_root(repo, "\n".join(lines)), [task["id"]])
    return judge(surface, task, answers[task["id"]])


def _read_capture(f: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A capture's task and runs, or ValueError saying why the file is not the capture of the
    task its name says."""
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{f.name} is not a capture: {e}") from None
    task = doc.get("task") if isinstance(doc, dict) else None
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if (not isinstance(task, dict) or not isinstance(runs, list) or not runs
            or not all(isinstance(r, dict) and isinstance(r.get("right"), bool)
                       and isinstance(r.get("lines"), list)
                       and all(isinstance(ln, str) for ln in r["lines"]) for r in runs)):
        raise ValueError(f"{f.name} is not a capture: it needs a `task` and at least one run of "
                         "`lines` and `right`")
    if task.get("id") != f.stem:
        raise ValueError(f"{f.name} holds task {task.get('id')}")
    return task, runs


def capture(repo: ProbeRepo, server: str, run_dir: Path, ids: list[str]) -> int:
    """Write one capture per id from a real run's directory, and nothing when any id cannot be
    proved; a write that fails part-way has printed each file it wrote."""
    try:
        docs = _capture_docs(repo, server, run_dir, ids)
        dest = repo.captured_dir / server
        dest.mkdir(parents=True, exist_ok=True)
        for tid, doc in docs.items():
            path = dest / f"{tid}.json"
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            print(f"captured {path}")
    except Invalid as e:
        print(f"INVALID {e}")
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        print(broke("capture", e))
        return EXIT_INVALID
    print(f"SUMMARY {len(docs)} task(s) of {server} captured from {run_dir}")
    return EXIT_PASS


def _capture_docs(repo: ProbeRepo, server: str, run_dir: Path,
                  ids: list[str]) -> dict[str, dict[str, Any]]:
    """The capture of each id, built from the run and proved against the task file and surface
    as they are now."""
    raw, resolved = _tasks_by_id(repo, tasks_file(repo, server))
    if unknown := [tid for tid in ids if tid not in raw]:
        raise Invalid(f"{server}'s task file holds no task {', '.join(unknown)}")
    prompt_path, verdicts_path = prompt_file(run_dir, server), verdicts_file(run_dir, server)
    if not prompt_path.is_file() or not verdicts_path.is_file():
        raise Invalid(f"{run_dir} holds no run of {server}: it needs {prompt_path.name} and "
                      f"{verdicts_path.name}")
    recorded = _recorded_verdicts(verdicts_path, ids)
    texts: list[str] = []
    for k in range(1, len(recorded) + 1):
        answer = answer_file(run_dir, server, k)
        if not answer.is_file():
            raise Invalid(f"{run_dir} holds no {answer.name}, which its verdicts judged")
        texts.append(answer.read_text(encoding="utf-8"))
    surface_said, _, asked = prompt_path.read_text(encoding="utf-8").partition(f"{TASKS_HEAD}\n")
    asked_block = "\n" + asked
    surface = load_surface(repo, server)
    if surface_said != prompt_for(surface, []).partition(f"{TASKS_HEAD}\n")[0]:
        raise Invalid(f"the run in {run_dir} was made on another surface than the repository's "
                      "(an instructions text or a tool changed since): run the probe again")
    docs: dict[str, dict[str, Any]] = {}
    for tid in ids:
        if f"\n{task_line(resolved[tid])}\n" not in asked_block:
            raise Invalid(f"{tid} was asked otherwise in {run_dir} than the task file asks now: "
                          "run the probe again")
        runs = [{"lines": [mark_root(repo, line) for t, line, _ in answer_lines(text)
                           if t == tid],
                 "right": verdicts[tid]["right"]}
                for text, verdicts in zip(texts, recorded, strict=True)]
        for k, run in enumerate(runs, start=1):
            if (now := rejudge(repo, surface, resolved[tid], run["lines"]).right) != run["right"]:
                raise Invalid(f"{tid} run {k} is judged {'right' if now else 'wrong'} now and was "
                              f"{'right' if run['right'] else 'wrong'} in its run: the task or the "
                              "surface changed since; run the probe again")
        docs[tid] = {"task": raw[tid], "runs": runs}
    return docs


def _recorded_verdicts(path: Path, ids: list[str]) -> list[dict[str, Any]]:
    """A run's verdicts, one dict per run, each holding every id asked with a boolean `right`."""
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Invalid(f"{path}: {e}") from None
    if not isinstance(recorded, list) or not recorded:
        raise Invalid(f"{path} holds no run, so there is nothing to capture")
    for k, run in enumerate(recorded, start=1):
        for tid in ids:
            if not isinstance(run, dict) or tid not in run:
                raise Invalid(f"the run in {path.parent} judged no task {tid} in run {k}")
            if not isinstance(run[tid], dict) or not isinstance(run[tid].get("right"), bool):
                raise Invalid(f"{path}: run {k} holds no boolean `right` for {tid}")
    return recorded


def refusals(surface: Surface, tasks: list[dict[str, Any]]) -> list[str]:
    """Everything refused before a model is asked, for one server. The two later passes read a
    task's `args`, `allow`, `grammar` and `id` as the shapes `task_problems` holds them to, so
    they judge only the tasks it accepted: a malformed one is named once, never a traceback."""
    found = _problems_by_task(surface, tasks)
    accepted = [t for t, problems in zip(tasks, found, strict=True) if not problems]
    return [*(p for problems in found for p in problems), *coverage_holes(surface, accepted),
            *contamination(surface, accepted)]


def check(repo: ProbeRepo, names: tuple[str, ...]) -> int:
    """The refusals alone, for the commit path: no model, no network, no directory."""
    lines: list[str] = []
    rc = EXIT_PASS
    try:
        for name in names:
            surface, tasks = load_surface(repo, name), load_tasks(repo, name)
            if refused := refusals(surface, tasks):
                lines += [f"{CHECK_REFUSED}{p}" for p in refused]
                rc = EXIT_FAIL
            else:
                lines.append(f"{CHECK_OK}{name}: {len(tasks)} tasks cover "
                             f"{len(surface.tools)} tools")
    except Invalid as e:
        lines.append(f"INVALID {e}")
        rc = EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        lines.append(broke("check", e))
        rc = EXIT_INVALID
    print("\n".join(lines))
    return rc


def _positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"not a positive whole number: {text!r}")
    return n


def _capture_ids(parser: argparse.ArgumentParser, opts: argparse.Namespace) -> list[str]:
    """The ids `--capture` writes, once the call is one the writer can answer; else usage."""
    if opts.capture is None or opts.ids is None:
        parser.error("--capture and --ids go together: the run directory and the tasks to take")
    if opts.runs is not None or opts.check:
        parser.error("--capture asks no model and checks nothing: pass it without --runs, --check")
    ids: list[str] = opts.ids.split(",")
    if not all(ids):
        parser.error(f"--ids holds an empty id: {opts.ids!r}")
    if len(set(ids)) != len(ids):
        parser.error(f"--ids names an id twice: {opts.ids!r}")
    return ids


def new_run_dir(repo: ProbeRepo, now: dt.datetime) -> Path:
    """A new directory under the repository's `out_dir` for one run, named by the UTC second of
    `now` (aware). Two runs can share that second; `mkdtemp`'s random tail keeps them apart."""
    repo.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.mkdtemp(prefix=f"{stamp}-", dir=repo.out_dir))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m scry_core.probe", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("server", help="a server the servers file loads, or `all`")
    parser.add_argument("--servers", type=Path, required=True,
                        help="the Python file defining `load()` and `ROOT` (and optionally "
                             "`CHECKS`, `CAPTURED`)")
    parser.add_argument("--tasks", type=Path, required=True,
                        help="the directory holding `<server>.json`")
    parser.add_argument("--runs", type=_positive, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--capture", type=Path, default=None)
    parser.add_argument("--ids", default=None)
    opts = parser.parse_args(argv)
    # USAGE FIRST, from the options alone: a wrong call is answered as one (exit 2) whatever the
    # servers file holds, and before it is run.
    capturing = opts.capture is not None or opts.ids is not None
    ids = _capture_ids(parser, opts) if capturing else []
    if opts.check and opts.runs is not None:
        parser.error("--runs asks the model and --check asks no model: pass one")
    try:
        repo = configure(opts.servers, opts.tasks)
    except Invalid as e:
        print(f"INVALID {e}")
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        print(broke("servers file", e))
        return EXIT_INVALID
    if opts.server not in (*repo.servers, "all"):
        parser.error(f"argument server: invalid choice: {opts.server!r} (choose from "
                     f"{', '.join([*repo.servers, 'all'])})")
    if capturing:
        if opts.server not in repo.captured_servers:
            parser.error(f"{opts.server} has no capture: --capture takes one of "
                         f"{', '.join(repo.captured_servers) or 'none here'}")
        return capture(repo, opts.server, opts.capture, ids)
    names = repo.servers if opts.server == "all" else (opts.server,)
    if opts.check:
        return check(repo, names)
    runs = opts.runs or DEFAULT_RUNS

    try:
        out = new_run_dir(repo, dt.datetime.now(dt.UTC))
    except OSError as e:
        print(f"INVALID no run directory under {repo.out_dir}: {e}")
        return EXIT_INVALID
    report: list[str] = []
    rc = EXIT_INVALID
    try:
        prepared = [(load_surface(repo, n), load_tasks(repo, n)) for n in names]
        refused = [p for s, tasks in prepared for p in refusals(s, tasks)]
        if refused:
            report += [f"INVALID {p}" for p in refused]
        else:
            outcomes = []
            for surface, tasks in prepared:
                verdicts = run_static(surface, tasks, runs, out)
                _save_verdicts(out, surface.server, verdicts)
                outcomes.append(tally(surface, tasks, verdicts))
            passed = sum(o.passed for o in outcomes)
            failed = sum(o.failed for o in outcomes)
            report += [line for o in outcomes for line in o.lines]
            report.append(f"SUMMARY {passed + failed} tools over {runs} run(s): "
                          f"{passed} PASS, {failed} FAIL")
            rc = EXIT_FAIL if failed else EXIT_PASS
    except Invalid as e:
        report.append(f"INVALID {e}")
        rc = EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        report.append(broke("probe", e))
        rc = EXIT_INVALID
    report.append(str(out))
    try:
        (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    except OSError as e:
        report.insert(0, f"INVALID the report could not be written to {out}: {e}")
        rc = EXIT_INVALID
    print("\n".join(report))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
