"""The client's cap, measured in the client's unit at the boundary: each server's suite runs
`over_the_cap` on its own servers, so the measure itself is held here, on known answers."""

from types import SimpleNamespace
from typing import Any

import pytest

from scry_core.client_cap import CLIENT_TEXT_CAP, PAST_THE_CUT_SHOWN, over_the_cap


def _server(instructions: str, *descriptions: str) -> Any:
    async def list_tools() -> list[Any]:
        return [SimpleNamespace(name=f"t{i}", description=d) for i, d in enumerate(descriptions)]
    return SimpleNamespace(instructions=instructions, list_tools=list_tools)


def test_the_measure_is_the_clients_at_the_boundary() -> None:
    """The known answers: the cap itself fits, one unit past it does not, and a character outside
    the BMP counts two units, so a text of cap characters can be over the cap."""
    assert over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP)) == []
    over = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + "cut"))
    assert over == [f's t0 {CLIENT_TEXT_CAP + 3} > {CLIENT_TEXT_CAP}: "cut"'], over
    astral = "x" * (CLIENT_TEXT_CAP - 1) + "\U0001f600"
    assert len(astral) == CLIENT_TEXT_CAP and len(over_the_cap("s", _server(astral, "d"))) == 1
    with pytest.raises(AssertionError, match="lists no tools"):
        over_the_cap("s", _server("i"))
    with pytest.raises(AssertionError, match="declares no instructions"):
        over_the_cap("s", _server("", "d"))
    long = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + "y" * 200))
    assert long == [f's t0 {CLIENT_TEXT_CAP + 200} > {CLIENT_TEXT_CAP}: '
                    f'"{"y" * PAST_THE_CUT_SHOWN}"'], long
