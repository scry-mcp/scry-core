"""`since_mark` names a position of the log as it stands: 0 and the end itself are taken, a
negative one and one past the end are refused naming the channel."""

from __future__ import annotations

import pytest

from scry_core.log_marks import check_since_mark
from scry_core.reply_contract import Invalid


@pytest.mark.parametrize("mark", [0, 1, 99, 100])
def test_a_mark_from_zero_to_the_end_is_taken(mark: int) -> None:
    check_since_mark(mark, 100, "guest")


def test_a_negative_mark_is_refused() -> None:
    with pytest.raises(Invalid) as e:
        check_since_mark(-1, 100, "guest")
    assert e.value.code == "bad_argument" and "0 or more" in str(e.value)


@pytest.mark.parametrize(("mark", "end"), [(101, 100), (1, 0)])
def test_a_mark_past_the_end_is_refused_naming_the_channel_and_its_end(mark: int,
                                                                        end: int) -> None:
    with pytest.raises(Invalid) as e:
        check_since_mark(mark, end, "emulator")
    assert e.value.code == "bad_argument"
    assert f"past where the emulator log ends now ({end} bytes)" in str(e.value)


def test_the_descriptions_both_servers_fill_name_the_argument_and_the_mark() -> None:
    from scry_core.log_marks import DOC_VALUES
    assert set(DOC_VALUES) == {"SINCE_MARK", "MARK"}
    assert "`since_mark`" in DOC_VALUES["SINCE_MARK"] and "`mark`" in DOC_VALUES["MARK"]


def test_a_bool_is_no_position() -> None:
    with pytest.raises(Invalid, match="0 or more"):
        check_since_mark(True, 100, "guest")
