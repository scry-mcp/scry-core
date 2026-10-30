"""A registerpoint stop is described one way on both servers."""
from __future__ import annotations

from scry_core import regpoint


def test_a_hit_names_the_registerpoint_where_it_stopped_and_that_it_stays_armed() -> None:
    got = regpoint.hit("AX==1", "AX==1", "0814:0010")
    assert got == {"ref": "AX==1", "condition": "AX==1", "pc": "0814:0010",
                   "note": regpoint.STILL_ARMED}
    assert "next advance stops again" in got["note"]


def test_what_only_one_server_knows_rides_beside_the_common_fields() -> None:
    got = regpoint.hit("rp", "d0 == 1", "0x10", cpu=":maincpu", index=3)
    assert got["cpu"] == ":maincpu" and got["index"] == 3 and got["ref"] == "rp"
