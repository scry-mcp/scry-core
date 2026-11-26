"""`scry_core.knowledge.confirmed`: what makes an entry confirmed, and the one format of the
second check."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scry_core.knowledge import Check, Entry, Lock, Locked, confirmed
from scry_core.knowledge.confirmed import Confirmation, parse_second_check
from scry_core.knowledge.lock import Reopened

NOW = "a" * 64
OTHER = "b" * 64
ID = "ibm-pc:port:0x3C8"


def entry(digest: str = NOW, checked: str | None = NOW, id_: str = ID) -> Entry:
    """An entry whose seal is `digest` and whose `checked` record holds `checked`."""
    record = None if checked is None else Check("checker", "writer", (), checked)
    return Entry(id_, "ibm-pc", "port", "0x3C8", "dac index", "d", "b", (), "ports", digest,
                 checked=record)


def second(digest: str = NOW, id_: str = ID) -> str:
    return json.dumps({"format": confirmed.SECOND_FORMAT,
                       "confirmed": [{"id": id_, "by": "second reader", "digest": digest}]})


def standing(lock: Lock, text: str, e: Entry) -> str:
    return Confirmation.of([lock], [parse_second_check(text)]).standing(e)


def sealed(digest: str = NOW) -> Lock:
    return Lock({ID: Locked(digest, "checker", ())})


class TestWhatConfirmsAnEntry:
    def test_sealed_in_the_lock_and_recorded_by_the_second_check_at_the_digest_it_has_now(
            self) -> None:
        got = Confirmation.of([sealed()], [parse_second_check(second())])
        assert got.standing(entry()) == confirmed.CONFIRMED
        assert got.confirms(entry())

    def test_an_entry_the_lock_does_not_hold_is_unsealed(self) -> None:
        assert standing(Lock({}), second(), entry(checked=None)) == confirmed.UNSEALED

    def test_an_entry_whose_seal_was_lifted_is_reopened(self) -> None:
        lock = Lock({}, (Reopened(ID, OTHER, "reopener", "wrong", "checker", ()),))
        assert standing(lock, second(), entry(checked=None)) == confirmed.REOPENED

    def test_an_entry_sealed_and_never_confirmed_by_the_second_check_is_sealed_once(
            self) -> None:
        none = json.dumps({"format": confirmed.SECOND_FORMAT, "confirmed": []})
        assert standing(sealed(), none, entry()) == confirmed.SEALED_ONCE

    def test_an_entry_the_second_check_recorded_under_another_digest_is_held_back(self) -> None:
        assert standing(sealed(), second(OTHER), entry()) == confirmed.ANOTHER_DIGEST

    def test_an_entry_that_changed_after_it_was_sealed_is_held_back_whatever_the_second_check_says(
            self) -> None:
        assert standing(sealed(), second(NOW), entry(digest=OTHER, checked=OTHER)
                        ) == confirmed.CHANGED

    def test_an_entry_whose_check_record_no_longer_matches_its_text_is_held_back(self) -> None:
        assert standing(sealed(), second(), entry(checked=OTHER)) == confirmed.CHANGED
        assert standing(sealed(), second(), entry(checked=None)) == confirmed.CHANGED


class TestTheSecondCheckFile:
    def test_it_reads_the_rows_by_id(self) -> None:
        got = parse_second_check(second())
        assert got.confirmed == {ID: confirmed.Recorded("second reader", NOW)}

    @pytest.mark.parametrize(("doc", "said"), [
        ("{", "not JSON"),
        ("[]", "`scry-knowledge-second-check/1` document"),
        ('{"format": "other/1", "confirmed": []}', "`scry-knowledge-second-check/1` document"),
        ('{"format": "scry-knowledge-second-check/1", "checked": {"a:b:c": '
         f'{{"by": "x", "digest": "{NOW}"}}}}}}', "older shape"),
        ('{"format": "scry-knowledge-second-check/1"}', "`confirmed`"),
        ('{"format": "scry-knowledge-second-check/1", "confirmed": {}}', "`confirmed`"),
        ('{"format": "scry-knowledge-second-check/1", "confirmed": [{"id": "a:b:c"}]}',
         "`id`, `by` and `digest`"),
        ('{"format": "scry-knowledge-second-check/1", "confirmed": [{"id": "a:b:c", '
         '"by": "x", "digest": "short"}]}', "64 hex digits"),
    ])
    def test_a_file_that_is_not_the_one_shape_is_refused_by_name(self, doc: str,
                                                                 said: str) -> None:
        with pytest.raises(ValueError, match=said):
            parse_second_check(doc, "x.json")

    def test_an_id_recorded_twice_is_refused(self) -> None:
        row: dict[str, Any] = {"id": ID, "by": "x", "digest": NOW}
        twice = json.dumps({"format": confirmed.SECOND_FORMAT, "confirmed": [row, row]})
        with pytest.raises(ValueError, match="twice"):
            parse_second_check(twice)

    def test_the_older_shape_is_named_with_what_to_convert(self) -> None:
        old = json.dumps({"format": confirmed.SECOND_FORMAT,
                          "checked": {ID: {"by": "x", "digest": NOW}}})
        with pytest.raises(ValueError) as caught:
            parse_second_check(old, "knowledge.second-check.json")
        assert "knowledge.second-check.json" in str(caught.value)
        assert "`confirmed`" in str(caught.value)

