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


def test_what_the_client_delivers_is_the_prefix_up_to_the_cap_in_its_unit() -> None:
    """The cut the client makes, at the boundary: a text that fits comes back whole, one past it
    loses exactly the excess, and a character outside the BMP that straddles the cut is dropped
    whole rather than left as half a surrogate pair."""
    from scry_core.client_cap import delivered, utf16_units

    fits = "x" * CLIENT_TEXT_CAP
    assert delivered(fits) == fits
    assert delivered(fits + "cut") == fits
    straddle = "x" * (CLIENT_TEXT_CAP - 1) + "\U0001f600" + "tail"
    assert delivered(straddle) == "x" * (CLIENT_TEXT_CAP - 1)
    assert utf16_units(delivered("\U0001f600" * CLIENT_TEXT_CAP)) == CLIENT_TEXT_CAP


def test_a_lone_surrogate_counts_one_unit_as_the_client_counts_it() -> None:
    from scry_core.client_cap import delivered, utf16_units

    assert utf16_units("a\ud800b") == 3
    assert delivered("\ud800" + "x" * CLIENT_TEXT_CAP) == "x" * (CLIENT_TEXT_CAP - 1)

