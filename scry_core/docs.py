"""What a tool's description states that the code already knows, filled at registration: a number
is the constant that enforces it and a sentence is the code's own, never typed into the text.

A placeholder is `{NAME}`, capitals, digits and underscores after a first capital. Each server
passes its own values beside the modules' (`picture.DOC_VALUES`, `series.DOC_VALUES`); one left
unfilled fails at import, because a placeholder that reaches a client reads as a word, not as a
number that is missing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

PLACEHOLDER = re.compile(r"\{[A-Z][A-Z0-9_]*\}")


def filled(name: str, doc: str, values: Mapping[str, str]) -> str:
    """`doc` with every `{KEY}` of `values` filled, or a `TypeError` naming `name` and what is
    left."""
    for key, value in values.items():
        doc = doc.replace("{" + key + "}", value)
    left = PLACEHOLDER.findall(doc)
    if left:
        raise TypeError(f"{name}'s docstring names {left}, which nothing fills")
    return doc
