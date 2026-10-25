"""The README table lists exactly the package's modules."""

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
