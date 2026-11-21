"""`scry_core.abbreviation`: a call's caption, its values in order, each cut to its width, a path
by its last name and a home by `~`, bytes by their first few and a count, printable ASCII."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import abbreviation as ab


@pytest.mark.parametrize(("given", "said"), [
    ("/Users/someone/Code/game/shots/title.png", "title.png"),
    ("/home/someone/scratch/run.wav", "run.wav"),
    ("C:\\Users\\someone\\scratch\\capture.avi", "capture.avi"),
    ("~/Code/game/plan.json", "plan.json"),
    ("relative/dir/", "dir"),
    ("/Users/someone", "~"),
    ("/Users/someone/", "~"),
    ("C:\\Users\\someone", "~"),
    ("/home/someone", "~"),
    ("~/", "~"),
    ("/", "/"),
    ("/var/home/someone", "~"),
    ("/mnt/c/Users/someone", "~"),
    ("/Volumes/Disk/Users/someone/", "~"),
    ("\\\\server\\share\\Users\\someone", "~"),
    ("\\\\?\\C:\\Users\\someone", "~"),
    ("file:///Users/someone", "~"),
    ("C:\\Documents and Settings\\someone", "~"),
    ("~someone", "~"),
    ("~someone/notes.txt", "notes.txt"),
    ("cd /Users/someone", "~"),
    ("cd /home/someone extra", "~"),
])
def test_a_path_reaches_the_caption_by_its_last_name_and_a_home_as_a_tilde(
        given: str, said: str) -> None:
    assert ab.value(given) == said


def test_no_folder_of_a_path_under_a_home_reaches_the_caption() -> None:
    text = ab.caption("snapshot", {"dest": "/Users/someone/Code/game/shots/title.png",
                                   "nested": {"to": "/home/someone/x/y.bin"},
                                   "many": ["/Users/someone/a/b.txt"],
                                   "keyed": {"/Users/someone/k": 1}})
    assert text == "snapshot title.png {to=y.bin} [b.txt] {k=1}"
    assert not any(w in text for w in ("someone", "Users", "home", "Code", "shots", "/"))


@pytest.mark.parametrize(("given", "said"), [
    (True, "true"), (False, "false"), (16, "16"), (-3, "-3"), (2.5, "2.5"), (0.1, "0.1"),
    ("0x1F00", "0x1F00"), ("DIR\r", "DIR\\r"), ("a\tb\nc", "a\\tb\\nc"), ("caf\u00e9", "caf?"),
    (b"\x3e\x00\xc9\x21", "3E 00 C9 21"), (b"\x3e\x00\xc9\x21\x00\x01", "3E 00 C9 21 +2"),
    ([1, 2], "[1,2]"), (["a", "b", "c", "d", "e", "f"], "[a,b,c,d,+2]"), ([], "[]"),
    ({"calls": False}, "{calls=false}"),
])
def test_each_kind_of_value_is_written_its_own_way(given: Any, said: str) -> None:
    assert ab.value(given) == said


def test_a_value_is_cut_to_its_width_with_the_cut_marked() -> None:
    long = "x" * (ab.VALUE_WIDTH + 5)
    said = ab.value(long)
    assert len(said) == ab.VALUE_WIDTH and said.endswith(ab.CUT)
    assert ab.value("x" * ab.VALUE_WIDTH) == "x" * ab.VALUE_WIDTH


def test_a_caption_is_the_tool_then_its_values_in_order_without_the_empty_ones() -> None:
    assert ab.caption("read_memory", {"ref": "0x0400", "length": 16}) == "read_memory 0x0400 16"
    assert ab.caption("run_for", {"seconds": 2.0, "cpu": None, "label": ""}) == "run_for 2"
    assert ab.caption("status", {}) == "status"


def test_an_argument_named_hex_is_bytes_and_any_other_hex_text_is_text() -> None:
    assert ab.caption("write", {"ref": "0x1F00", "data_hex": "3E00C9210000FF"}) == \
        "write 0x1F00 3E 00 C9 21 +3"
    assert ab.caption("write", {"data_hex": "not hex"}) == "write not hex"
    assert ab.caption("find", {"pattern": "3E00C9210000FF"}) == "find 3E00C9210000FF"


def test_every_caption_is_printable_ascii() -> None:
    text = ab.caption("send_keys", {"keys": ["\u00f1", "\x1b", "F1"], "data_hex": "00"})
    assert all(" " <= c <= "~" for c in text), text


def test_a_value_that_cannot_be_written_is_a_question_mark_never_a_failure() -> None:
    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("no text")

    deep: list[Any] = []
    for _ in range(2000):
        deep = [deep]
    assert ab.caption("x", {"big": 10 ** 5000, "odd": Unprintable(), "deep": deep}) == \
        "x ? ? " + ab.value(deep)
    wide = {f"k{i}": i for i in range(1000)}
    assert ab.value(wide).startswith("{k0=0 k1=1")
