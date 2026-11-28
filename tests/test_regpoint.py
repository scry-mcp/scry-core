"""A registerpoint stop says what its own emulator does with it."""
from __future__ import annotations

import pytest

from scry_core import regpoint


def test_a_hit_names_the_registerpoint_where_it_stopped_and_carries_the_callers_note() -> None:
    got = regpoint.hit("AX==1", "AX==1", "0814:0010", note=regpoint.WAITS_WHILE_HELD)
    assert got == {"ref": "AX==1", "condition": "AX==1", "pc": "0814:0010",
                   "note": regpoint.WAITS_WHILE_HELD}
    assert "waits while it already holds" in got["note"]


def test_the_note_says_which_of_the_two_emulators_the_caller_runs() -> None:
    every = regpoint.hit("d0 == 1", "d0 == 1", "0x10", note=regpoint.STILL_ARMED)["note"]
    rising = regpoint.hit("AX==1", "AX==1", "0814:0010", note=regpoint.WAITS_WHILE_HELD)["note"]
    assert "every instruction where its condition holds" in every
    assert "every instruction" not in rising and "comes true" in rising


def test_what_only_one_server_knows_rides_beside_the_common_fields() -> None:
    got = regpoint.hit("rp", "d0 == 1", "0x10", note=regpoint.STILL_ARMED, cpu=":maincpu", index=3)
    assert got["cpu"] == ":maincpu" and got["index"] == 3 and got["ref"] == "rp"


def test_a_hit_without_a_note_is_refused() -> None:
    with pytest.raises(TypeError, match="note"):
        regpoint.hit("rp", "d0 == 1", "0x10")  # type: ignore[call-arg]
