"""`scry_core.ends_table`: a reference's table of ends against the declarations, both ways."""

from __future__ import annotations

import pytest

from scry_core import ends_table

TABLE = """### A long wait, and a cancelled call

| End | What the cancel leaves | Tools |
|---|---|---|
| `stop` | stopped, `BREAK` typed | `run`, `trace` |
| `kill` | closed | `start` |
| `later` | not an end this contract knows, so not a row of the table | `start` |

## Next section

| `none` | not this table's | `read` |
"""
DECLARED = {"run": "stop", "trace": "stop", "start": "kill", "read": None}


def test_a_table_that_is_the_declarations_agrees() -> None:
    assert ends_table.unlike(TABLE, DECLARED) == {}  # type: ignore[arg-type]


@pytest.mark.parametrize("table, want", [
    (TABLE.replace("`run`, `trace` |", "`run` |"),
     {"stop": {"table_only": [], "declared_only": ["trace"]}}),
    (TABLE.replace("`start` |", "`start`, `read` |"),
     {"kill": {"table_only": ["read"], "declared_only": []}}),
    (TABLE.replace("| `kill` | closed | `start` |", "| `kill` | closed | `start` |   "), {}),
])
def test_each_side_of_a_disagreement_is_named(table: str, want: object) -> None:
    assert ends_table.unlike(table, DECLARED) == want  # type: ignore[arg-type]


@pytest.mark.parametrize("reference, says", [
    ("# nothing here", "no section"),
    ("### A long wait, and a cancelled call\n\nprose only\n", "no table of ends"),
    (TABLE.replace("| `kill` | closed | `start` |", "| `stop` | twice | `start` |"), "two rows"),
])
def test_a_reference_that_cannot_be_compared_is_refused(reference: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        ends_table.unlike(reference, DECLARED)  # type: ignore[arg-type]
