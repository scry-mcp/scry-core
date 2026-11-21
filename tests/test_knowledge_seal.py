"""`scry_core.knowledge.seal`: the lock of the checked entries and the command that seals a check.
The contract's own cases judge the result, so a seal that would leave a case red fails here."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from null_server import an_entry, write_dictionary
from test_knowledge_contract import LOCKED, REWORDED, Copy, entry, run

from scry_core import knowledge
from scry_core.knowledge import check, lock, seal

EXIT = "ibm-pc:call:0x21/0x4C"
GET_CODE = "ibm-pc:call:0x21/0x4D"
GET_CODE_REF = "dosbox-x:src/dos/dos.cpp DOS_21Handler case 0x4d"
GET_CODE_LINE = "        case 0x4d:                  /* Get Return code */"


def calls(copy: Copy) -> Path:
    return copy.root / "calls.json"


def write(copy: Copy, change: Any) -> None:
    """The copy's calls, edited and written the way the command writes a file."""
    doc = json.loads(calls(copy).read_text(encoding="utf-8"))
    change(doc)
    calls(copy).write_text(lock.dumps(doc), encoding="utf-8")


def checked(by: str = "second checker") -> dict[str, Any]:
    return {"by": by, "writer": "fixture writer",
            "against": [{"ref": GET_CODE_REF, "line": GET_CODE_LINE}]}


def test_a_check_is_sealed_into_its_file_and_the_lock_and_the_contract_passes(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    assert run(copy.subject()), "an unsealed check is not a whole entry"
    assert seal.seal(calls(copy), [GET_CODE], copy.lock_path) == []
    assert run(copy.subject()) == set()
    sealed = knowledge.read_lock(copy.lock_path).checked
    assert set(sealed) == {EXIT, GET_CODE}
    got = copy.subject().base().by_id(GET_CODE)
    assert got is not None and got.checked is not None
    assert got.checked.digest == got.digest == sealed[GET_CODE].digest
    assert sealed[GET_CODE] == lock.Locked(got.digest, "second checker",
                                           ((GET_CODE_REF, GET_CODE_LINE),))


def test_a_correction_checked_anew_updates_the_entry_and_its_lock_with_one_command(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    before = knowledge.read_lock(copy.lock_path).checked[EXIT]
    assert before.by == "fixture checker" and before.against[0][0].endswith("case 0x4c")

    def reword(d: dict[str, Any]) -> None:
        raw = entry(d, "0x21/0x4C")
        raw["behaviour"] = "AL is the return code, and the program ends."
        raw["checked"]["by"] = "second checker"
    write(copy, reword)
    assert {REWORDED, LOCKED} <= run(copy.subject())
    assert seal.seal(calls(copy), [EXIT], copy.lock_path) == []
    assert run(copy.subject()) == set()
    after = knowledge.read_lock(copy.lock_path).checked[EXIT]
    assert after.digest != before.digest and after.by == "second checker"
    assert after.against == before.against


def reworded(copy: Copy, by: str = "fixture checker", line: str = "") -> None:
    """The locked call reworded, checked by `by`, against `line` of its source when given."""
    def change(d: dict[str, Any]) -> None:
        raw = entry(d, "0x21/0x4C")
        raw["behaviour"] = "AL is the return code, and the program ends."
        raw["checked"]["by"] = by
        if line:
            raw["checked"]["against"][0]["line"] = line
    write(copy, change)


def test_a_re_check_by_the_same_checker_against_the_same_lines_of_a_changed_text_is_refused(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    reworded(copy)
    wrote, locked = calls(copy).read_bytes(), copy.lock_path.read_bytes()
    [fault] = seal.seal(calls(copy), [EXIT], copy.lock_path)
    assert EXIT in fault and "'fixture checker'" in fault and "changed" in fault
    assert "another session" in fault and "other lines" in fault
    assert calls(copy).read_bytes() == wrote and copy.lock_path.read_bytes() == locked


def test_the_order_of_the_lines_compared_is_no_new_check(tmp_path: Path) -> None:
    ref = "datasheet:Fixture sheet 1, table 2"
    two = [{"role": "documentation", "ref": ref, "cites": "Bit 7 selects the bank."},
           {"role": "emulator", "ref": GET_CODE_REF, "cites": GET_CODE_LINE}]
    raw = an_entry("0x10", "bank", sources=two)
    raw["checked"] = {"by": "second checker", "writer": "fixture writer", "digest": "",
                      "against": [{"ref": s["ref"], "line": s["cites"]} for s in two]}
    path = write_dictionary(tmp_path / "d", "ports", "port", "ibm-pc", [raw])
    path.write_text(lock.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")
    where = tmp_path / "lock.json"
    assert seal.seal(path, ["ibm-pc:port:0x10"], where) == []
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["entries"][0]["behaviour"] = "Reworded."
    doc["entries"][0]["checked"]["against"].reverse()
    path.write_text(lock.dumps(doc), encoding="utf-8")
    assert len(seal.seal(path, ["ibm-pc:port:0x10"], where)) == 1


def test_a_re_check_is_accepted_when_the_checker_or_the_lines_are_not_the_locked_ones(
        tmp_path: Path) -> None:
    for by, line in (("second checker", ""), ("fixture checker", "case 0x4c:")):
        copy = Copy(tmp_path / by.split()[0] / (line or "none"))
        reworded(copy, by, line)
        assert seal.seal(calls(copy), [EXIT], copy.lock_path) == []
        assert run(copy.subject()) == set()


def test_sealing_an_entry_that_has_not_changed_is_not_a_re_check(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    locked = copy.lock_path.read_bytes()
    assert seal.seal(calls(copy), [EXIT], copy.lock_path) == []
    assert copy.lock_path.read_bytes() == locked


def test_a_register_that_differs_by_direction_is_locked_under_its_own_id(
        tmp_path: Path) -> None:
    def raw(access: str) -> dict[str, Any]:
        one = an_entry("0x0F", f"{access} side", access=access)
        one["checked"] = {"by": "second checker", "writer": "fixture writer", "digest": "",
                          "against": [{"ref": s["ref"], "line": s["cites"]}
                                      for s in one["sources"]]}
        return one
    path = write_dictionary(tmp_path / "d", "vga-seq", "register", "vga-seq",
                            [raw("read"), raw("write")])
    path.write_text(lock.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")
    where = tmp_path / "lock.json"
    assert seal.seal(path, ["vga-seq:register:0x0F:write"], where) == []
    assert set(knowledge.read_lock(where).checked) == {"vga-seq:register:0x0F:write"}


def test_what_is_refused_writes_nothing(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    wrote, locked = calls(copy).read_bytes(), copy.lock_path.read_bytes()
    for ids, says in ((["ibm-pc:call:0x21/0x99"], "is no entry"),
                      ([GET_CODE, "ibm-pc:port:0x3C4"], "is no entry")):
        assert any(says in f for f in seal.seal(calls(copy), ids, copy.lock_path))
        assert calls(copy).read_bytes() == wrote and copy.lock_path.read_bytes() == locked
    write(copy, lambda d: entry(d, "0x21/0x4D")["checked"].update(by="fixture writer"))
    assert any("cannot check it" in f for f in seal.seal(calls(copy), [GET_CODE], copy.lock_path))


def test_an_entry_with_no_check_to_seal_is_refused(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    faults = seal.seal(calls(copy), [GET_CODE], copy.lock_path)
    assert len(faults) == 1 and "has no `checked` record" in faults[0]


def test_a_file_the_command_would_reformat_is_refused_untouched(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    doc = json.loads(calls(copy).read_text(encoding="utf-8"))
    entry(doc, "0x21/0x4D")["checked"] = checked()
    calls(copy).write_text(json.dumps(doc), encoding="utf-8")
    wrote = calls(copy).read_bytes()
    faults = seal.seal(calls(copy), [GET_CODE], copy.lock_path)
    assert len(faults) == 1 and "is not written the way this command writes it" in faults[0]
    assert calls(copy).read_bytes() == wrote


def test_a_lock_that_is_no_lock_is_refused_by_name(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    copy.lock_path.write_text('{"format": "other"}', encoding="utf-8")
    assert any("is not a `scry-knowledge-lock/2` document" in f
               for f in seal.seal(calls(copy), [GET_CODE], copy.lock_path))
    held = {"digest": "d", "by": "b", "against": [{"ref": "r", "line": "l"}]}
    for text in ("{", "[]", '{"format": "scry-knowledge-lock/1", "checked": {}}',
                 '{"format": "scry-knowledge-lock/2", "checked": {"a": "1"}}',
                 json.dumps({"format": "scry-knowledge-lock/2",
                             "checked": {"a": {**held, "by": 1}}}),
                 json.dumps({"format": "scry-knowledge-lock/2",
                             "checked": {"a": {**held, "against": [{"ref": "r"}]}}}),
                 json.dumps({"format": "scry-knowledge-lock/2",
                             "checked": {"a": {**held, "extra": 1}}})):
        with pytest.raises(ValueError, match="lock"):
            lock.parse_lock(text)
    got = lock.parse_lock(json.dumps({"format": "scry-knowledge-lock/2", "checked": {"a": held}}))
    assert got.checked == {"a": lock.Locked("d", "b", (("r", "l"),))}


def test_a_check_may_quote_a_part_of_the_indexed_line_and_nothing_else(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    for line, passes in (("case 0x4c:", True), ("case 0x4d:", False)):
        write(copy, lambda d, line=line: entry(d, "0x21/0x4C")["checked"]["against"][0].update(
            line=line))
        assert seal.seal(calls(copy), [EXIT], copy.lock_path) == []
        assert (check.against_sources(copy.subject().base(), copy.subject().sources())
                == []) is passes


def test_a_source_no_machine_opens_is_checked_against_the_line_the_entry_cites(
        tmp_path: Path) -> None:
    ref = "datasheet:Fixture sheet 1, table 2, page 3"
    cites = "Bit 7 selects the bank."
    raw = an_entry("0x10", "bank", sources=[{"role": "documentation", "ref": ref,
                                            "cites": cites}])
    raw["checked"] = {"by": "second checker", "writer": "fixture writer", "digest": "",
                      "against": [{"ref": ref, "line": cites}]}
    path = write_dictionary(tmp_path / "dictionaries", "ports", "port", "ibm-pc", [raw])
    path.write_text(lock.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")
    where = tmp_path / "lock.json"
    for line, faults in ((cites, 0), ("Bit 7 selects another bank.", 1)):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["entries"][0]["checked"]["against"][0]["line"] = line
        path.write_text(lock.dumps(doc), encoding="utf-8")
        assert seal.seal(path, ["ibm-pc:port:0x10"], where) == []
        assert len(check.against_sources(knowledge.Base.load(path.parent),
                                         knowledge.SourceIndex())) == faults


def test_what_cannot_be_read_or_written_is_refused_and_not_a_traceback(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    wrote = calls(copy).read_bytes()
    assert seal.main([str(tmp_path / "none.json"), GET_CODE, "--lock", str(copy.lock_path)]) == 2
    assert seal.main([str(calls(copy)), GET_CODE, "--lock", str(tmp_path / "gone" / "l.json")]) == 2
    assert "no directory" in capsys.readouterr().err and calls(copy).read_bytes() == wrote


def test_a_file_with_windows_line_ends_is_sealed_with_the_line_ends_the_command_writes(
        tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    calls(copy).write_bytes(calls(copy).read_bytes().replace(b"\n", b"\r\n"))
    assert seal.seal(calls(copy), [GET_CODE], copy.lock_path) == []
    assert b"\r" not in calls(copy).read_bytes() + copy.lock_path.read_bytes()


def test_the_command_runs_as_a_module_without_the_package_having_loaded_it() -> None:
    ran = subprocess.run([sys.executable, "-W", "error", "-m", "scry_core.knowledge.seal",
                          "--help"], capture_output=True, text=True, check=False)
    assert ran.returncode == 0 and ran.stderr == "" and "--lock" in ran.stdout


def test_the_ports_a_register_goes_by_are_part_of_what_its_seal_covers(tmp_path: Path) -> None:
    raw = an_entry("0x04", "memory mode")
    raw["checked"] = {"by": "second checker", "writer": "fixture writer", "digest": "",
                      "against": [{"ref": s["ref"], "line": s["cites"]} for s in raw["sources"]]}
    path = write_dictionary(tmp_path / "dictionaries", "vga-seq", "register", "vga-seq", [raw],
                            reached={"index": "0x3C4", "data": "0x3C5"})
    path.write_text(lock.dumps(json.loads(path.read_text(encoding="utf-8"))), encoding="utf-8")
    where = tmp_path / "lock.json"
    assert seal.seal(path, ["vga-seq:register:0x04"], where) == []
    assert check.reworded(knowledge.Base.load(path.parent)) == []
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["reached"] = {"index": "0x3C6", "data": "0x3C7"}
    path.write_text(lock.dumps(doc), encoding="utf-8")
    base = knowledge.Base.load(path.parent)
    assert len(check.reworded(base)) == 1
    assert len(check.locked(base, knowledge.read_lock(where))) == 1


def test_a_first_seal_creates_the_lock(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    copy.lock_path.unlink()
    assert seal.seal(calls(copy), [EXIT], copy.lock_path) == []
    assert set(knowledge.read_lock(copy.lock_path).checked) == {EXIT}


def test_the_lock_says_what_became_of_each_entry(tmp_path: Path) -> None:
    copy = Copy(tmp_path)
    copy.edit("calls", lambda d: entry(d, "0x21/0x4C").pop("checked"))
    [gone] = check.locked(copy.subject().base(), copy.subject().lock())
    assert "no longer checked" in gone and lock.COMMAND in gone
    copy.edit("calls", lambda d: d["entries"].remove(entry(d, "0x21/0x4C")))
    [removed] = check.locked(copy.subject().base(), copy.subject().lock())
    assert "no entry any more" in removed


def test_the_command_exits_zero_sealed_and_two_refused_and_knows_its_options(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    copy = Copy(tmp_path)
    write(copy, lambda d: entry(d, "0x21/0x4D").update(checked=checked()))
    assert seal.main([str(calls(copy)), GET_CODE, "--lock", str(copy.lock_path)]) == 0
    assert "sealed 1 in calls.json and lock.json" in capsys.readouterr().out
    assert seal.main([str(calls(copy)), "ibm-pc:call:0x21/0x99", "--lock",
                      str(copy.lock_path)]) == 2
    assert "is no entry" in capsys.readouterr().err
    with pytest.raises(SystemExit) as unknown:
        seal.main([str(calls(copy)), GET_CODE, "--lock", str(copy.lock_path), "--nope"])
    assert unknown.value.code == 2
