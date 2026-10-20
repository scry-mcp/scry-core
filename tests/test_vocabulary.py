"""`scry_core.vocabulary`: one tuple, a judge and the schema a client reads."""

from __future__ import annotations

import re
from typing import Annotated, Any

import pytest
from pydantic import TypeAdapter

from scry_core import vocabulary
from scry_core.reply_contract import Invalid


def _schema(annotation: Any) -> dict[str, Any]:
    return TypeAdapter(annotation).json_schema()


def test_a_vocabulary_publishes_its_tuple_as_the_schemas_enum_and_ints_stay_ints() -> None:
    assert _schema(Annotated[str, vocabulary.enum(("into", "over"))]) == {
        "type": "string", "enum": ["into", "over"]}
    assert _schema(Annotated[int, vocabulary.enum((1, 2, 4))])["enum"] == [1, 2, 4]


def test_a_range_publishes_its_bounds() -> None:
    assert _schema(Annotated[int, vocabulary.bounds(1, 400)]) == {
        "type": "integer", "minimum": 1, "maximum": 400}
    assert _schema(Annotated[float, vocabulary.bounds(0, 600.0)])["maximum"] == 600.0
    assert _schema(Annotated[float, vocabulary.bounds(0, 600.0, open_lo=True)]) == {
        "type": "number", "exclusiveMinimum": 0, "maximum": 600.0}


def test_a_folded_vocabulary_matches_every_case_of_its_words_and_nothing_else() -> None:
    pattern = str(_schema(Annotated[str, vocabulary.folded(("DS", "CS", "A.B"))])["pattern"])
    for word in ("DS", "ds", "dS", "cs", "a.b", "A.B"):
        assert re.fullmatch(pattern, word), word
    for word in ("ES", "dss", "", "aXb", "d"):
        assert not re.fullmatch(pattern, word), word


def test_one_of_refuses_in_one_sentence_and_never_takes_a_bool_for_one() -> None:
    vocabulary.one_of("mode", "into", ("into", "over"))
    with pytest.raises(Invalid, match=r"^mode is one of \('into', 'over'\); got 'x'; why$"):
        vocabulary.one_of("mode", "x", ("into", "over"), "; why")
    with pytest.raises(Invalid, match="got True"):
        vocabulary.one_of("length", True, (1, 2))
