"""The world the row tools' tests read: the synthetic sources of `fixtures/knowledge/rows` copied
into the run's own folder (DOSBox-X's in a git repository, as its reader needs), and helpers that
edit a copy."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core.knowledge import callees, closure, quote, rows

FIXTURES = Path(__file__).parent / "fixtures" / "knowledge" / "rows"
DICTIONARIES = ("command", "register", "call", "family")


def git_repo(path: Path) -> str:
    """Commits everything in `path` in a new repository; returns the commit."""
    def git(*args: str) -> str:
        done = subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                               *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture")
    return git("rev-parse", "HEAD")


SEARCHED = [{"where": place, "gave": "nothing"} for place in rows.SEARCH_PLACES]


def datasheet(capture: str) -> quote.Datasheet:
    return quote.Datasheet("synthetic", "https://example.invalid/chipx.pdf",
                           "https://archive.example.invalid/chipx.pdf", "maker-datasheet", "layer",
                           "pdftotext -raw", "0.0", "0" * 64, capture)


@dataclass
class World:
    root: Path
    pin: str

    @property
    def mame(self) -> Path:
        return self.root / "mame"

    @property
    def dosbox(self) -> Path:
        return self.root / "dosbox"

    @property
    def rbil(self) -> Path:
        return self.root / "rbil"

    @property
    def datasheets(self) -> Path:
        return self.root / "datasheets"

    def sources(self) -> quote.Sources:
        capture = (FIXTURES / "datasheets" / "chipx.raw.txt").read_bytes()
        table = {"chipx.raw.txt": datasheet(hashlib.sha256(capture).hexdigest())}
        return quote.Sources(mame=self.mame, dosbox=self.dosbox, rbil=self.rbil,
                             datasheets=self.datasheets, pins={"dosbox-x": self.pin, "mame": "x"},
                             table=table)

    def options(self) -> list[str]:
        return ["--mame", str(self.mame), "--dosbox", str(self.dosbox), "--rbil", str(self.rbil),
                "--datasheets", str(self.datasheets)]

    def callees(self) -> callees.Callees:
        return callees.parse((self.root / "callees.json").read_text(encoding="utf-8"))

    def dictionary(self, name: str) -> rows.Dictionary:
        got, faults = rows.read(self.root / f"{name}.json")
        assert got is not None and not faults, faults
        return got

    def edit(self, name: str, change: Callable[[dict[str, Any]], None]) -> Path:
        path = self.root / f"{name}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        change(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def rewrite(self, tree: str, file: str, old: str, new: str) -> None:
        path = self.root / tree / file
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"{old!r} matches {text.count(old)} times in {file}"
        path.write_text(text.replace(old, new), encoding="utf-8")


def build(tmp_path: Path) -> World:
    root = tmp_path / "world"
    shutil.copytree(FIXTURES, root)
    return World(root, git_repo(root / "dosbox"))


def recommit(world: World) -> World:
    return World(world.root, git_repo_again(world.dosbox))


def git_repo_again(path: Path) -> str:
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-a", "-m", "edit"], capture_output=True, check=True)
    done = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True)
    return done.stdout.strip()


def entry_doc(doc: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = doc["entries"][0]
    return entry


def result(world: World, name: str = "command") -> closure.Report:
    dictionary = world.dictionary(name)
    return closure.check(dictionary, dictionary.entries[0], world.sources(), world.callees(),
                         {e.id: e for e in dictionary.entries})


def drop_row(n: str) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["rows"] = [r for r in entry_doc(doc)["rows"] if r["n"] != n]
    return change


def drop_subject(subject: str) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        entry_doc(doc)["rows"] = [r for r in entry_doc(doc)["rows"] if r["on"] != subject]
    return change


def set_row(which: str, **fields: Any) -> Callable[[dict[str, Any]], None]:
    def change(doc: dict[str, Any]) -> None:
        for r in entry_doc(doc)["rows"]:
            if r["n"] == which:
                r.update(fields)
    return change


def set_entry(**fields: Any) -> Callable[[dict[str, Any]], None]:
    return lambda doc: entry_doc(doc).update(fields)


def set_head(**fields: Any) -> Callable[[dict[str, Any]], None]:
    return lambda doc: doc.update(fields)
