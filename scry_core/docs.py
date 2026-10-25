from __future__ import annotations

import re
from collections.abc import Mapping

PLACEHOLDER = re.compile(r"\{[A-Z][A-Z0-9_]*\}")


def filled(name: str, doc: str, values: Mapping[str, str]) -> str:
    """`doc` with `values` filled; `TypeError` naming `name` if a placeholder is left."""
    for key, value in values.items():
        doc = doc.replace("{" + key + "}", value)
    left = PLACEHOLDER.findall(doc)
    if left:
        raise TypeError(f"{name}'s docstring names {left}, which nothing fills")
    return doc
