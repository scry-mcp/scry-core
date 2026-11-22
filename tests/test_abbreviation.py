"""`scry_core.abbreviation`: a call's caption, its values in order, each cut to its width, a path
by its last name and a home by `~`, bytes by their first few and a count, printable ASCII."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import abbreviation as ab
from scry_core.naming import Named


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
    ("cd C:\\Users\\someone", "~"),
    ("C:\\GAMES\\X.EXE", "X.EXE"),
    ("UFODATA/CITYMAP1\\.BLD", "CITYMAP1\\.BLD"),
    ("GAME\\.EXE", "GAME\\.EXE"),
    ("CITYMAP\\d+\\.BLD", "CITYMAP\\d+\\.BLD"),
    ("ERR:\\d+", "ERR:\\d+"),
    ("\\Users\\someone", "~"),
    ("Users\\someone\\Desktop\\a.txt", "a.txt"),
    ("shots\\title.png", "title.png"),
    ("%USERPROFILE%\\Documents\\a.txt", "a.txt"),
    ("~\\notes.txt", "notes.txt"),
])
def test_a_path_reaches_the_caption_by_its_last_name_and_a_home_as_a_tilde(
        given: str, said: str) -> None:
    assert ab.value(given) == said


def test_a_pattern_with_an_escaped_dot_is_read_whole_not_cut_at_its_backslash() -> None:
    assert ab.caption("log_wait", {"channel": "dos", "pattern": "UFODATA/CITYMAP1\\.BLD",
                                   "seconds": 120}) == "log_wait dos CITYMAP1\\.BLD 120"
    assert ab.caption("log_wait", {"pattern": "GAME\\.EXE"}) == "log_wait GAME\\.EXE"


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
    assert ab.caption("write", {"data_hex": 4096}) == "write 4096"
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


def _n(name: str, number: str, **fields: Any) -> Named:
    return Named("port", name, number, **fields)


def test_a_named_value_reads_its_name_then_its_number() -> None:
    assert ab.caption("port", {"port": 968, "method": "write"},
                      {"port": _n("DAC write address", "0x3C8")}) == \
        "port DAC write address (0x3C8) write"


def test_two_values_that_select_one_thing_are_named_each() -> None:
    assert ab.caption("log", {"number": "0x21", "ah": "0x4C"},
                      {"number": Named("vector", "DOS", "0x21"),
                       "ah": Named("call", "exit", "0x4C")}) == "log DOS (0x21) exit (0x4C)"


def test_a_symbol_the_agent_typed_is_kept_as_typed_with_its_address_beside_it() -> None:
    assert ab.caption("read_memory", {"ref": "score", "length": 2},
                      {"ref": Named("symbol", "score", "0x9405")}) == \
        "read_memory score (0x9405) 2"


def test_an_address_inside_a_symbol_says_how_far_in() -> None:
    assert ab.caption("find", {"ref": "0xb58c"},
                      {"ref": Named("symbol", "count_coin", "0xb58c", delta=9)}) == \
        "find count_coin+0x9 (0xb58c)"


def test_a_name_is_cut_at_24_and_its_number_never() -> None:
    long = "a_function_name_that_is_far_too_long_for_a_caption"
    text = ab.caption("run_to", {"ref": "0x123456789ABCDEF0123456"},
                      {"ref": Named("symbol", long, "0x123456789ABCDEF0123456")})
    assert text == f"run_to {long[:22]}.. (0x123456789ABCDEF0123456)"
    assert len(text.split(" (")[0].split()[1]) == ab.NAME_WIDTH


def test_a_name_with_no_printable_ascii_is_written_as_a_caption_writes_text() -> None:
    assert ab.caption("t", {"a": 1}, {"a": Named("symbol", "café\tx", "1")}) == "t caf? x (1)"


def test_a_name_for_an_argument_not_given_or_empty_shows_nothing() -> None:
    assert ab.caption("t", {"a": None, "b": ""}, {"a": _n("x", "1"), "b": _n("y", "2")}) == "t"


def test_a_caption_with_no_names_is_the_caption_it_always_was() -> None:
    given = {"port": 968, "dest": "/Users/someone/x/y.png", "data_hex": "3E00C921"}
    assert ab.caption("t", given, {}) == ab.caption("t", given, None) == \
        "t 968 y.png 3E 00 C9 21"


def _wide(n: int, name: str = "n" * 24) -> tuple[dict[str, Any], dict[str, Named]]:
    given = {f"a{i}": i for i in range(n)}
    return given, {k: Named("port", name, f"0x{v:04X}") for k, v in given.items()}


def _line(names_kept: int, n: int) -> str:
    """The caption of `_wide(n)` in which only the first `names_kept` values keep their name."""
    return " ".join(["t", *(f"{'n' * 24} (0x{v:04X})" if v < names_kept else str(v)
                            for v in range(n))])


def test_a_caption_within_160_bytes_keeps_every_name() -> None:
    given, named = _wide(4)
    assert ab.caption("t", given, named) == _line(4, 4) and len(_line(4, 4)) <= ab.MAX_BYTES


def test_over_160_bytes_the_names_fall_back_to_their_bare_values_last_first() -> None:
    given, named = _wide(6)
    assert len(_line(6, 6)) > ab.MAX_BYTES
    fits = [k for k in range(7) if len(_line(k, 6)) <= ab.MAX_BYTES]
    assert fits and max(fits) < 6
    assert ab.caption("t", given, named) == _line(max(fits), 6), \
        "the first value keeps its name longest, and no name is dropped that still fitted"


def test_when_the_bare_values_do_not_fit_either_the_tail_is_cut() -> None:
    given = {f"a{i}": "v" * 20 for i in range(12)}
    text = ab.caption("t", given, {"a0": _n("x", "1")})
    assert len(text) == ab.MAX_BYTES and text.endswith("v..")


def test_a_number_is_never_cut_even_when_it_alone_is_wide() -> None:
    number = "0x" + "AB" * 30
    text = ab.caption("t", {"ref": 1}, {"ref": Named("symbol", "x", number)})
    assert text == f"t x ({number})" and number in text


def test_a_caption_is_cut_to_the_room_a_suffix_leaves() -> None:
    assert ab.fit("x" * 100, 160) == "x" * 100
    assert ab.fit("x" * 100, 10) == "x" * 8 + ".."
    assert ab.fit("x" * 100, 1) == ".."
