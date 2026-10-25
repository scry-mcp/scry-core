"""The cap measure held on known answers; each server's suite runs it on its own servers."""

from types import SimpleNamespace
from typing import Any

import pytest

from scry_core.client_cap import CLIENT_TEXT_CAP, PAST_THE_CUT_SHOWN, margins, over_the_cap
from scry_core.verdict import Invalid


def _server(instructions: str, *descriptions: str) -> Any:
    async def list_tools() -> list[Any]:
        return [SimpleNamespace(name=f"t{i}", description=d) for i, d in enumerate(descriptions)]
    return SimpleNamespace(instructions=instructions, list_tools=list_tools)


def test_the_measure_is_the_clients_at_the_boundary() -> None:
    """The cap fits, one unit past does not, and a non-BMP character counts two units."""
    assert over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP)) == []
    over = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + "cut"))
    drops = f"> {CLIENT_TEXT_CAP}, the client drops:"
    assert over == [f's t0 {CLIENT_TEXT_CAP + 3} {drops} "cut"'], over
    blank = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + "  \n "))
    assert blank == [f"s t0 {CLIENT_TEXT_CAP + 4} > {CLIENT_TEXT_CAP}, the client drops: "
                     "whitespace only"], blank
    astral = "x" * (CLIENT_TEXT_CAP - 1) + "\U0001f600"
    assert len(astral) == CLIENT_TEXT_CAP and len(over_the_cap("s", _server(astral, "d"))) == 1
    with pytest.raises(Invalid, match="lists no tools"):
        over_the_cap("s", _server("i"))
    with pytest.raises(Invalid, match="declares no instructions"):
        over_the_cap("s", _server("", "d"))
    long = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + "y" * 200))
    assert long == [f's t0 {CLIENT_TEXT_CAP + 200} > {CLIENT_TEXT_CAP}, the client drops: '
                    f'"{"y" * PAST_THE_CUT_SHOWN}"'], long


def test_what_the_client_delivers_is_the_prefix_up_to_the_cap_in_its_unit() -> None:
    """A straddling non-BMP character is dropped whole, never left as half a surrogate pair."""
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



def test_an_empty_server_is_refused_as_the_instruments_refuse_not_by_an_assert() -> None:
    """`python -O` strips an `assert`, so the refusal is `Invalid`."""
    for server in (_server("i"), _server("", "d")):
        with pytest.raises(Invalid):
            over_the_cap("s", server)
        with pytest.raises(Invalid):
            margins("s", server)


def test_the_margins_name_the_texts_nearest_the_cap_first_on_every_run() -> None:
    """Margins are listed nearest first, whether or not anything is over."""
    server = _server("i" * 10, "x" * CLIENT_TEXT_CAP, "y" * (CLIENT_TEXT_CAP - 7),
                     "z" * (CLIENT_TEXT_CAP + 2))
    assert margins("s", server, shown=3) == [
        f"s t2 {CLIENT_TEXT_CAP + 2} units, margin -2",
        f"s t0 {CLIENT_TEXT_CAP} units, margin 0",
        f"s t1 {CLIENT_TEXT_CAP - 7} units, margin 7"]
    assert len(margins("s", server)) == 4


def test_lost_text_behind_a_run_of_blanks_is_shown_and_never_called_whitespace() -> None:
    over = over_the_cap("s", _server("i", "x" * CLIENT_TEXT_CAP + " " * 70 + "REAL TEXT"))
    assert over and over[0].endswith('the client drops: "REAL TEXT"'), over


def test_a_text_the_documented_client_carries_is_delivered_whole() -> None:
    from scry_core.client_cap import delivered

    text = "x" * 3000
    assert delivered(text) == text
    assert over_the_cap("s", _server("i", text)) == []
