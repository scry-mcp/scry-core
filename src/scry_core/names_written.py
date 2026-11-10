"""The names of the files a server wrote during its battery, judged case by case."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scry_core import file_names


class Names:
    """What one battery judged; `fixed` are names another program gives."""

    def __init__(self, fixed: Iterable[str] = ()) -> None:
        self.fixed = frozenset(fixed)
        self.cases = 0
        self.judged = 0
        self._seen: set[Path] = set()

    def outside(self, folders: Iterable[str | Path | None]) -> list[Path]:
        """The files new under `folders` since the last case, named outside the rule."""
        self.cases += 1
        bad: list[Path] = []
        for folder in sorted({str(f) for f in folders if f}):
            # os.walk: a case may still hold `Path`'s methods replaced
            found = {Path(root, name) for root, _, names in os.walk(folder) for name in names}
            new = sorted(p for p in found - self._seen if p.name not in self.fixed)
            self._seen |= found
            self.judged += len(new)
            bad += [p for p in new if not file_names.NAME.fullmatch(p.name)]
        return bad

    def judged_nothing(self, config: Any) -> bool:
        """Whether a whole run's cases left no file to judge: INVALID, never green."""
        narrowed = config.option.keyword or config.args != config.getini("testpaths")
        return bool(self.cases) and not self.judged and not narrowed
