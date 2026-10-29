"""The stop's instruction, in the one shape both servers answer."""

from __future__ import annotations

from typing import NotRequired

from pydantic import ConfigDict
from typing_extensions import TypedDict

from scry_core.reply_schema import Unavailable


class StopInstruction(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid", strict=True)  # type: ignore[misc]
    address: str
    bytes: str | Unavailable
    text: str
    symbol: str | Unavailable
    delta: int | Unavailable
    comment: NotRequired[str]
