"""README's table of modules is the package's index: every module is a row, and every row a module,
so a module added or removed without its row is a failure here rather than a stale index."""

from __future__ import annotations

import pkgutil
import re
from pathlib import Path

import scry_core

ROOT = Path(__file__).resolve().parent.parent


def test_the_readme_names_every_module_and_no_other() -> None:
    listed = set(re.findall(r"^\| `scry_core\.([a-z_]+)` \|", (ROOT / "README.md").read_text(),
                            re.MULTILINE))
    modules = {m.name for m in pkgutil.iter_modules(scry_core.__path__) if m.name != "__main__"}
    assert listed, "the README's table was not found"
    assert listed == modules, {"no row": sorted(modules - listed),
                               "no module": sorted(listed - modules)}
