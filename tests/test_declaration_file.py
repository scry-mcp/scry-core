"""The declarations file's three moves: read whole, a key's rows judged by shape, one key
written."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scry_core import declaration_file as df


class Refused(Exception):
    pass


def test_no_file_reads_empty_and_a_written_key_leaves_the_others(tmp_path: Path) -> None:
    path = tmp_path / "d" / "decl.json"
    assert df.read(path, Refused) == {}
    df.write(path, "a", [{"ref": "x"}], Refused)
    df.write(path, "b", [{"ref": "y"}], Refused)
    def drop_b(raw: dict[str, object]) -> None:
        raw.pop("b")
    df.write(path, "a", [], Refused, prune=drop_b)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": []}


@pytest.mark.parametrize(("text", "said"), [
    ("{", "could not be read"), ("[]", "holds a list"),
    ('{"a": {}}', "maps to a dict"), ('{"a": [1]}', "is a int, not an object")])
def test_a_file_of_another_shape_is_refused_ending_with_what_comes_next(
        tmp_path: Path, text: str, said: str) -> None:
    path = tmp_path / "decl.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(Refused, match=said) as e:
        df.rows(df.read(path, Refused, "; start again"), "a", Refused, "; start again")
    assert str(e.value).endswith("; start again")
    assert path.read_text(encoding="utf-8") == text, "a refused file is never discarded"
