"""A promotion on `scry_core.promote` alone, and three that each break one rule."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scry_core import project_store, promote
from scry_core.reply_contract import Invalid


class NullPromoter:
    """Its recipe names the program's directory, `cwd`."""

    def __init__(self) -> None:
        self.drafts = promote.Drafts()

    def anchor(self, project: Path) -> str:
        return str(project)

    def start(self, project: Path, name: str) -> dict[str, Any]:
        recipe = {"format": project_store.FORMAT, "system": name, "cwd": str(project)}
        with self.drafts.starting(anchor=self.anchor(project)):
            reply: dict[str, Any] = {"status": "ok"}
        if self.drafts.keep("start", name, recipe, needs=("system",), path_keys=("cwd",)):
            reply["kept"] = self.kept()
        return reply

    def kept(self) -> str:
        return promote.kept_line(self.drafts)

    def promote(self, **arguments: Any) -> dict[str, Any]:
        try:
            return {"status": "ok", **promote.promote(self.drafts, server="mame", **arguments)}
        except Invalid as refused:
            return refused.reply()

    def close(self) -> dict[str, Any]:
        return promote.after_close(self.drafts, {"status": "ok", "closed": False})


class BorrowsAStore(NullPromoter):
    """Without `root`, writes into the first store an entry's project holds."""

    def promote(self, **arguments: Any) -> dict[str, Any]:
        if not arguments.get("root"):
            held = [c.project for c in self.drafts.kept.values() if promote.own_store(c.project)]
            arguments["root"] = held[0] if held else ""
        return super().promote(**arguments)


class LendsItsOwnDirectory(NullPromoter):
    def anchor(self, project: Path) -> str:
        return os.getcwd()


class ForgetsTheStart(NullPromoter):
    """Keeps what a start learns without saying where the start runs."""

    def anchor(self, project: Path) -> str:
        return ""


class SilentKeptLine(NullPromoter):
    def kept(self) -> str:
        return f"kept {len(self.drafts)} (promote to review)"
