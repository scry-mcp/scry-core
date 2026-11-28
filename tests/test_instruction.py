"""`scry_core.instruction`: the one shape of a stop's instruction, and what a platform may add."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from scry_core.instruction import StopInstruction

_PLACED: dict[str, Any] = {"address": "0814:00000130", "bytes": "E2FE", "text": "loop 0x130",
                           "symbol": "main", "delta": 4}


def test_an_instruction_is_judged_whole_with_symbol_and_delta_unavailable_together() -> None:
    judge = TypeAdapter(StopInstruction)
    judge.validate_python(_PLACED)
    gone = {"available": False, "why": "no symbol table is loaded"}
    judge.validate_python({**_PLACED, "symbol": gone, "delta": gone, "bytes": gone})
    for bad in ({k: v for k, v in _PLACED.items() if k != "delta"}, {**_PLACED, "seg_off": "x"},
                {**_PLACED, "delta": "4"}):
        with pytest.raises(ValidationError):
            judge.validate_python(bad)


def test_a_comment_beside_an_instruction_is_its_own_key() -> None:
    TypeAdapter(StopInstruction).validate_python({**_PLACED, "comment": "the loop's top"})


def test_a_note_from_the_base_is_its_own_key_beside_the_comment() -> None:
    both = {**_PLACED, "comment": "the loop's top", "note": "DAC write address (0x3C8)"}
    TypeAdapter(StopInstruction).validate_python(both)
    with pytest.raises(ValidationError):
        TypeAdapter(StopInstruction).validate_python({**_PLACED, "note": 5})


def test_a_note_from_the_registers_says_so_apart_from_the_note() -> None:
    TypeAdapter(StopInstruction).validate_python(
        {**_PLACED, "note": "port 0x3C8", "note_live": True})
    with pytest.raises(ValidationError):
        TypeAdapter(StopInstruction).validate_python({**_PLACED, "note_live": "yes"})


def test_a_platform_adds_its_own_keys_beside_the_common_ones() -> None:
    class Extended(StopInstruction):  # a platform's own subclass
        platform_key: str

    TypeAdapter(Extended).validate_python({**_PLACED, "platform_key": "x"})
    with pytest.raises(ValidationError):
        TypeAdapter(Extended).validate_python(_PLACED)
