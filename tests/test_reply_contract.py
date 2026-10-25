from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scry_core import reply_contract as contract


def test_the_class_refuses_what_the_contract_forbids() -> None:
    """A bad code, an empty message and a reserved field are programmer errors, not replies."""
    with pytest.raises(TypeError, match="not a code"):
        contract.Invalid("nonsense", "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="message"):
        contract.Invalid("bad_argument", "  ")
    for word in ("summary", "status", "session", "verdict", "why", "reason"):
        with pytest.raises(TypeError, match="reserved"):
            contract.Invalid("bad_argument", "x", **{word: "x"})
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
    """Each forbidden defect is refused by name and the good reply passes."""
    contract.check_refusal("x", _GOOD, "bad_argument")
    with pytest.raises(AssertionError, match=names):
        contract.check_refusal("x", broken)
    with pytest.raises(AssertionError, match="expected 'no_session'"):
        contract.check_refusal("x", _GOOD, "no_session")


def test_the_source_scan_refuses_a_refusal_it_cannot_read(tmp_path: Path) -> None:
    """An unreadable refusal is refused naming the file; a readable one is listed with its code."""
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
    """A call-valued callee, a non-refusal keyword and a `code=`-only refusal are all handled."""
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
    """An unavailable datum has one shape, and a blank reason is refused."""
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
    """Only the table's four words are a verdict."""
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
