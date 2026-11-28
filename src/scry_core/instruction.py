"""The stop's instruction, in the one shape both servers answer."""

from __future__ import annotations

from typing import Annotated, NotRequired

from pydantic import ConfigDict
from typing_extensions import TypedDict

from scry_core.reply_contract import When
from scry_core.reply_schema import Unavailable


class StopInstruction(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    address: str
    bytes: str | Unavailable
    text: str
    symbol: str | Unavailable
    delta: int | Unavailable
    comment: NotRequired[str]
    note: NotRequired[str]
    note_live: NotRequired[Annotated[bool, When("a register named the note")]]
    # What a platform that decodes the instruction itself adds.
    bytes_from: NotRequired[Annotated[str, When("the platform says where it read the bytes")]]
    code_bits: NotRequired[Annotated[int, When("the platform decodes at one width")]]
    flow: NotRequired[Annotated[str, When("the platform classifies the flow")]]
