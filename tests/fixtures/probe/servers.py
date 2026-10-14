"""The servers the probe's own suite is pointed at: real tools of the two emulator servers, frozen
in `surfaces.json` as the client delivered them (instructions, description, input schema) beside
each tool's signature, so the engine is judged against true texts with no server installed.

A frozen tool is read and never called; the servers' own pre-gate judges are not frozen, so a
case that needs one hands the surface a judge of its own.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parent
CAPTURED = ("mame",)


def _frozen(name: str) -> Any:
    def tool(**_: Any) -> NoReturn:
        raise AssertionError(f"{name} is a frozen tool: the probe reads it, never calls it")
    return tool


def _module(server: str, doc: dict[str, Any]) -> ModuleType:
    module = ModuleType(f"probe_fixture_{server}")
    listed = []
    for t in doc["tools"]:
        params = [inspect.Parameter(p["name"], inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                    default=p.get("default", inspect.Parameter.empty))
                  for p in t["parameters"]]
        fn = _frozen(t["name"])
        fn.__signature__ = inspect.Signature(params)
        setattr(module, t["name"], fn)
        listed.append(SimpleNamespace(name=t["name"], description=t["description"],
                                      input_schema=t["input_schema"]))

    async def list_tools() -> list[Any]:
        return listed

    module.mcp = SimpleNamespace(instructions=doc["instructions"],  # type: ignore[attr-defined]
                                 list_tools=list_tools)
    return module


def load() -> dict[str, ModuleType]:
    surfaces = json.loads((ROOT / "surfaces.json").read_text(encoding="utf-8"))
    return {server: _module(server, doc) for server, doc in surfaces.items()}
