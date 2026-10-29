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
    judge.validate_python({**_PLACED, "symbol": gone, "delta": gone})
    for bad in ({k: v for k, v in _PLACED.items() if k != "delta"}, {**_PLACED, "seg_off": "x"},
                {**_PLACED, "delta": "4"}):
        with pytest.raises(ValidationError):
            judge.validate_python(bad)


def test_a_platform_adds_its_own_keys_beside_the_common_ones() -> None:
    class Extended(StopInstruction):  # a platform's own subclass
        flow: str

    TypeAdapter(Extended).validate_python({**_PLACED, "flow": "branch"})
    with pytest.raises(ValidationError):
        TypeAdapter(Extended).validate_python(_PLACED)
