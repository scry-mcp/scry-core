"""The names of the files a server writes: an outside value normalised into the rule or refused,
a made-up name built inside it or a defect, and a caller's path changed in its last component
only."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scry_core import file_names
from scry_core.reply_contract import Invalid


@pytest.mark.parametrize(("value", "word"), [
    ("mame", "mame"),
    ("Speed Fight", "speed-fight"),
    ("m68k_dual", "m68k-dual"),
    ("sub:cpu", "sub-cpu"),
    ("  --A__b.C  ", "a-b-c"),
    ("M01", "m01"),
    ("Café", "caf"),
    ("20261110T120000Z", "20261110t120000z"),
    ("x" * file_names.WORD_MAX, "x" * file_names.WORD_MAX),
])
def test_an_outside_value_becomes_words_of_the_rule(value: str, word: str) -> None:
    assert file_names.word(value, "system") == word
    assert file_names.NAME.fullmatch(f"{word}.bin")


@pytest.mark.parametrize(("value", "what"), [
    ("", "system"), ("___", "system"), (" . ", "name"), ("é", "name"), ("٣", "name"),
])
def test_an_outside_value_with_no_letter_or_digit_is_refused_by_its_argument(
        value: str, what: str) -> None:
    with pytest.raises(Invalid, match=f"^{what}: ") as e:
        file_names.word(value, what)
    assert e.value.code == "bad_argument" and repr(value) in str(e.value)


@pytest.mark.parametrize("value", ["x" * (file_names.WORD_MAX + 1),
                                   "A_" * file_names.WORD_MAX])
def test_an_outside_value_past_the_bound_is_refused_by_its_argument(value: str) -> None:
    with pytest.raises(Invalid, match=f"^name: .*at most {file_names.WORD_MAX}") as e:
        file_names.word(value, "name")
    assert e.value.code == "bad_argument"


def test_a_stamp_is_one_word_that_keeps_the_microsecond() -> None:
    when = dt.datetime(2026, 11, 10, 12, 0, 5, 42, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    assert file_names.stamp(when) == "20261110t110005000042z"
    assert file_names.name(file_names.stamp(when), "mame", extension="log")


@pytest.mark.parametrize(("words", "extension", "name"), [
    (("snapshot", 3), "png", "snapshot-3.png"),
    (("f000012",), "png", "f000012.png"),
    (("20261110t120000z", "m68k-dual"), "log", "20261110t120000z-m68k-dual.log"),
    (("batch", 1, "ran"), "jsonl", "batch-1-ran.jsonl"),
])
def test_a_made_up_name_is_its_words_and_one_extension(
        words: tuple[str | int, ...], extension: str, name: str) -> None:
    assert file_names.name(*words, extension=extension) == name
    assert file_names.NAME.fullmatch(name)


@pytest.mark.parametrize(("words", "extension"), [
    (("Snapshot", 3), "png"),
    (("tally", "a000_2"), "txt"),
    (("batch", 1), "ran.jsonl"),
    (("dasm.bare",), "txt"),
    (("snapshot", -1), "png"),
    (("snapshot", ""), "png"),
    (("snapshot-",), "png"),
    (("", "snapshot"), "png"),
    (("snapshot", "", 3), "png"),
    (("café",), "png"),
    (("snapshot", "٣"), "png"),
    (("snapshot",), "p-ng"),
    (("snapshot",), "pn٣"),
    (("snapshot",), "PNG"),
    (("snapshot",), "png\n"),
    (("snapshot",), ""),
    ((), "png"),
])
def test_a_made_up_name_outside_the_rule_is_the_builders_defect(
        words: tuple[str | int, ...], extension: str) -> None:
    with pytest.raises(ValueError, match="outside the rule"):
        file_names.name(*words, extension=extension)


@pytest.mark.parametrize(("given", "written"), [
    ("/d/dump.bin", "/d/dump.bin"),
    ("/d/My Dump.V2.BIN", "/d/my-dump-v2.bin"),
    ("/D ir/Sub_Dir/MIXEDCASE.BIN", "/D ir/Sub_Dir/mixedcase.bin"),
    ("/d/run_1.trace", "/d/run-1.trace"),
    ("/d/" + "X" * 200 + ".bin", "/d/" + "x" * 200 + ".bin"),
])
def test_a_callers_path_changes_in_its_last_component_only(given: str, written: str) -> None:
    path = file_names.caller_file(Path(given), "dest")
    assert path == Path(written) and file_names.NAME.fullmatch(path.name)


@pytest.mark.parametrize(("given", "what", "why"), [
    ("/d/dump", "dest", "no extension"),
    ("/d/dump.", "dest", "no extension"),
    ("/d/dump.b c", "path", "no extension"),
    ("/d/dump.٣", "path", "no extension"),
    ("/d/.bin", "dest", "no letter or digit"),
    ("/d/___.bin", "path", "no letter or digit"),
])
def test_a_callers_name_the_rule_cannot_hold_is_refused_by_its_argument(
        given: str, what: str, why: str) -> None:
    with pytest.raises(Invalid, match=f"^{what}: .*{why}") as e:
        file_names.caller_file(Path(given), what)
    assert e.value.code == "bad_argument" and repr(Path(given).name) in str(e.value)


def test_a_folder_is_walked_for_the_files_named_outside_the_rule(tmp_path: Path) -> None:
    (tmp_path / "Sub_Dir" / "snap").mkdir(parents=True)
    for name in ("snapshot-1.png", "Sub_Dir/f000012.png", "Sub_Dir/snap/manifest.json",
                 "Snapshot_2.png", "Sub_Dir/batch-1.ran.jsonl", "Sub_Dir/snap/dump"):
        (tmp_path / name).write_bytes(b"")
    assert file_names.outside(tmp_path) == [
        tmp_path / "Snapshot_2.png", tmp_path / "Sub_Dir" / "batch-1.ran.jsonl",
        tmp_path / "Sub_Dir" / "snap" / "dump"]
    for bad in file_names.outside(tmp_path):
        bad.unlink()
    assert file_names.outside(tmp_path) == []


def test_a_walk_that_met_no_file_judged_nothing(tmp_path: Path) -> None:
    (tmp_path / "snap").mkdir()
    with pytest.raises(ValueError, match="no file"):
        file_names.outside(tmp_path)
    with pytest.raises(ValueError, match="no file"):
        file_names.outside(tmp_path / "gone")
