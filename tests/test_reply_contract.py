"""The reply contract as a class and a checker, judged on their own: a code outside the table, a
malformed refusal and a refusal the source scan cannot read are each refused where they are
written. Each server's suite walks its own tools through the contract on top of this."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scry_core import reply_contract as contract


def test_the_class_refuses_what_the_contract_forbids() -> None:
    """The contract is the CLASS, not a convention: a code outside the table, an empty
    message and a reserved field are refused where they are written, as a programmer's error
    and never as a reply."""
    with pytest.raises(TypeError, match="not a code"):
        contract.Invalid("nonsense", "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="message"):
        contract.Invalid("bad_argument", "  ")
    # `code` and `message` cannot even be passed twice: they are the class's own parameters.
    for word in ("summary", "status", "session", "verdict", "why", "reason"):
        with pytest.raises(TypeError, match="reserved"):
            contract.Invalid("bad_argument", "x", **{word: "x"})
    # A refusal that met a stop carries the stop's `cause` as it carries the rest of it.
    assert contract.Invalid("bad_argument", "x", cause="target irq").fields == {
        "cause": "target irq"}
    got = contract.Invalid("bad_argument", "x", left_armed=["0x4a0"])
    assert got.code == "bad_argument" and str(got) == "x"
    assert got.fields == {"left_armed": ["0x4a0"]}



_GOOD = {"summary": "x: INVALID (bad_argument), y", "status": "INVALID", "code": "bad_argument",
         "message": "y", "session": {}}


@pytest.mark.parametrize("broken, names", [
    ({**_GOOD, "status": "ok"}, "not a refusal"),
    ({**_GOOD, "code": "nonsense"}, "not in the table"),
    ({**_GOOD, "message": " "}, "no prose"),
    ({**_GOOD, "why": "old"}, r"carries \['why'\]"),
    ({"status": "INVALID", "code": "bad_argument", "message": "y", "summary": "s", "session": {}},
     "order"),
    ({**_GOOD, "summary": "x: INVALID, y"}, "summary"),
])
def test_the_contracts_own_checker_refuses_each_defect(broken: dict[str, Any], names: str) -> None:
    """The checker the two suites share is itself checked: a reply broken in each of the ways
    the contract forbids is refused, naming the defect, and the good one passes."""
    contract.check_refusal("x", _GOOD, "bad_argument")
    with pytest.raises(AssertionError, match=names):
        contract.check_refusal("x", broken)
    with pytest.raises(AssertionError, match="expected 'no_session'"):
        contract.check_refusal("x", _GOOD, "no_session")


def test_the_source_scan_refuses_a_refusal_it_cannot_read(tmp_path: Path) -> None:
    """A refusal with no code, one whose code is computed, and a `code=` that is not a literal
    are each refused naming the line; a readable one is listed with its code."""
    cases = {
        "none.py": "Invalid()\n",
        "computed.py": 'Invalid("bad_" + "argument", "x")\n',
        "keyword.py": 'reply(status="INVALID", code=pick(), message="x")\n',
    }
    for name, text in cases.items():
        (tmp_path / name).write_text(text)
        with pytest.raises(AssertionError, match=name):
            contract.codes_written_in([tmp_path / name])
    (tmp_path / "ok.py").write_text('st.invalid("no_channel", "x")\nreply(code=e.code)\n')
    assert contract.codes_written_in([tmp_path / "ok.py"]) == [
        ("ok.py", 1, "no_channel"), ("ok.py", 2, "no_session")]



def test_the_source_scan_reads_a_keyword_code_and_leaves_other_calls_alone(tmp_path: Path) -> None:
    """Three shapes the walk meets in a real module and no case held: a call whose callee is
    itself a call, a keyword on a call that is no refusal, and a refusal written with `code=`
    and no positional argument."""
    src = tmp_path / "m.py"
    src.write_text("f()()\nfoo(x=1)\ninvalid(code='no_session', message='m')\n")
    assert contract.codes_written_in([src]) == [("m.py", 3, "no_session")]


@pytest.mark.parametrize(("reply", "said"), [
    ({"status": "INVALID", "message": "x"}, "code"),
    ({"status": "INVALID", "code": "bad_argument", "message": " "}, "message"),
    ({"code": "bad_argument"}, "status"),
    ({"status": "ok", "code": "bad_argument"}, "an `ok` reply carries"),
    ({"status": "ok", "message": "x"}, "an `ok` reply carries"),
    ({"status": "maybe"}, "status"),
    *[({"status": "INVALID", "code": "bad_argument", "message": "x", word: "x"}, word)
      for word in ("verdict", "why", "reason")],
])
def test_the_envelope_refuses_a_malformed_reply(reply: dict[str, Any], said: str) -> None:
    with pytest.raises(TypeError, match=said):
        contract.check_envelope(reply)


def test_the_envelope_passes_a_well_formed_reply_and_a_refusal_keeps_its_order() -> None:
    ok = {"status": "ok", "verdict": "TARGET", "rows": [{"why": "a row's"}]}
    assert contract.check_envelope(ok) is ok
    bad = contract.refusal("control_silent", "cold", control_hits=0)
    assert contract.check_envelope(bad) is bad
    assert list(bad) == ["status", "code", "message", "control_hits"]
    assert contract.Invalid("no_session", "m", a=1).reply(b=2) == {
        "status": "INVALID", "code": "no_session", "message": "m", "a": 1, "b": 2}


def test_an_unavailable_datum_is_one_shape_and_says_why() -> None:
    """The one spelling of a datum that could not be read or does not apply, and a blank
    reason is a programmer's error, refused as the contract refuses its other ones."""
    assert contract.unavailable("no counter") == {"available": False, "why": "no counter"}
    assert contract.or_unavailable(None, "none given") == {"available": False,
                                                            "why": "none given"}
    assert contract.or_unavailable(0, "never said") == 0
    assert contract.or_unavailable("", "never said") == ""
    with pytest.raises(TypeError, match="says why"):
        contract.unavailable("  ")
    with pytest.raises(TypeError, match="says why"):
        contract.unavailable(None)  # type: ignore[arg-type]


def test_a_verdict_is_one_word_of_the_measurements() -> None:
    """`verdict` is a measurement's word, and the four are the table's: a reply carrying
    another at its top is refused where it is built, as a refusal's code is."""
    assert frozenset({"TARGET", "TIMEOUT", "OTHER_STOP", "ELAPSED"}) == contract.VERDICTS
    assert (contract.TARGET, contract.TIMEOUT, contract.OTHER_STOP, contract.ELAPSED) == (
        "TARGET", "TIMEOUT", "OTHER_STOP", "ELAPSED")
    with pytest.raises(TypeError, match="not a verdict"):
        contract.check_envelope({"status": "ok", "verdict": "EXPIRED"})
    for word in (None, "target", "", ["TARGET"], {"available": False, "why": "x"}):
        with pytest.raises(TypeError, match="not a verdict"):
            contract.check_envelope({"status": "ok", "verdict": word})
    for word in sorted(contract.VERDICTS):
        contract.check_envelope({"status": "ok", "verdict": word})
    with pytest.raises(TypeError, match=r"carries \['verdict'\]"):
        contract.check_envelope({"status": "INVALID", "code": "wait_expired", "message": "m",
                                 "verdict": "TIMEOUT"})
