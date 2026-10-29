"""The CAPTURE STORE of the probe: one file per task holding the lines a real run answered it with
and whether each was judged right, written from a run's directory (`capture`) and judged again
against the task file and the surface as they are now (`capture_problems`), so a free check can
say a task still means what the model was asked, without asking a model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scry_core import probe
from scry_core.probe_any_of import same
from scry_core.prose import counted
from scry_core.verdict import EXIT_INVALID, EXIT_PASS, Invalid


def capture_problems(repo: probe.ProbeRepo, server: str, captured: Path,
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
    surface = probe.load_surface(repo, server)
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


def _tasks_by_id(repo: probe.ProbeRepo, tasks_file: Path
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Each task by id twice: as the file writes it, which a capture stores, and resolved to the
    repository, which is what was asked and is judged. The ids are `--check`'s to keep unique, and
    a file `--check` would refuse is `Invalid` here."""
    def by_id(tasks: list[Any]) -> dict[str, dict[str, Any]]:
        if not all(isinstance(t, dict) and isinstance(t.get("id"), str) for t in tasks):
            raise Invalid(f"{tasks_file} holds an entry that is not a task with an `id`: "
                          "`--check` names it")
        return {t["id"]: t for t in tasks}

    return (by_id(probe.read_tasks(repo, tasks_file, raw=True)),
            by_id(probe.read_tasks(repo, tasks_file)))


def rejudge(repo: probe.ProbeRepo, surface: probe.Surface, task: dict[str, Any],
            lines: list[str]) -> probe.Verdict:
    """A run's stored lines for one task, judged again as the run's whole answer was."""
    answers = probe.parse(probe.resolve_root(repo, "\n".join(lines)), [task["id"]])
    return probe.judge(surface, task, answers[task["id"]])


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


def capture(repo: probe.ProbeRepo, server: str, run_dir: Path, ids: list[str]) -> int:
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
        print(f"INVALID: {e}")
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        print(probe.broke("capture", e))
        return EXIT_INVALID
    print(f"SUMMARY {counted(len(docs), 'task')} of {server} captured from {run_dir}")
    return EXIT_PASS


def _capture_docs(repo: probe.ProbeRepo, server: str, run_dir: Path,
                  ids: list[str]) -> dict[str, dict[str, Any]]:
    """The capture of each id, built from the run and proved against the task file and surface
    as they are now."""
    raw, resolved = _tasks_by_id(repo, probe.tasks_file(repo, server))
    if unknown := [tid for tid in ids if tid not in raw]:
        raise Invalid(f"{server}'s task file holds no task {', '.join(unknown)}")
    prompt_path = probe.prompt_file(run_dir, server)
    verdicts_path = probe.verdicts_file(run_dir, server)
    if not prompt_path.is_file() or not verdicts_path.is_file():
        raise Invalid(f"{run_dir} holds no run of {server}: it needs {prompt_path.name} and "
                      f"{verdicts_path.name}")
    recorded = _recorded_verdicts(verdicts_path, ids)
    texts: list[str] = []
    for k in range(1, len(recorded) + 1):
        answer = probe.answer_file(run_dir, server, k)
        if not answer.is_file():
            raise Invalid(f"{run_dir} holds no {answer.name}, which its verdicts judged")
        texts.append(answer.read_text(encoding="utf-8"))
    said = prompt_path.read_text(encoding="utf-8")
    surface_said, _, asked = said.partition(f"{probe.TASKS_HEAD}\n")
    asked_block = "\n" + asked
    surface = probe.load_surface(repo, server)
    if surface_said != probe.prompt_for(surface, []).partition(f"{probe.TASKS_HEAD}\n")[0]:
        raise Invalid(f"the run in {run_dir} was made on another surface than the repository's "
                      "(an instructions text or a tool changed since): run the probe again")
    docs: dict[str, dict[str, Any]] = {}
    for tid in ids:
        if f"\n{probe.task_line(resolved[tid])}\n" not in asked_block:
            raise Invalid(f"{tid} was asked otherwise in {run_dir} than the task file asks now: "
                          "run the probe again")
        runs = [{"lines": [probe.mark_root(repo, line) for t, line, _ in probe.answer_lines(text)
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
