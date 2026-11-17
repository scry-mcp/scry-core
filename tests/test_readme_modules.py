"""`docs/modules.md` lists exactly the package's modules, and the README names its groups."""

from __future__ import annotations

import pkgutil
import re
from pathlib import Path

import scry_core

ROOT = Path(__file__).resolve().parent.parent


MODULES = ROOT / "docs" / "modules.md"


def test_the_module_list_names_every_module_once_and_no_other() -> None:
    rows = re.findall(r"^\| `scry_core\.([a-z_]+)` \|", MODULES.read_text(), re.MULTILINE)
    modules = {m.name for m in pkgutil.iter_modules(scry_core.__path__) if m.name != "__main__"}
    assert rows, "the module list's tables were not found"
    assert len(rows) == len(set(rows)), sorted(name for name in set(rows) if rows.count(name) > 1)
    assert set(rows) == modules, {"no row": sorted(modules - set(rows)),
                                  "no module": sorted(set(rows) - modules)}


def test_the_readme_links_every_group_of_the_module_list_and_no_other() -> None:
    groups = re.findall(r"^## (.+)$", MODULES.read_text(), re.MULTILINE)
    linked = re.findall(r"^\| \[(.+?)\]\(docs/modules\.md#([a-z-]+)\) \|",
                        (ROOT / "README.md").read_text(), re.MULTILINE)
    assert [name for name, _ in linked] == groups
    for name, anchor in linked:
        assert anchor == re.sub(r"[^a-z0-9 -]", "", name.lower()).replace(" ", "-"), name
