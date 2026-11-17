"""An example's one shape: the call cut to its lines, the reply's excerpt, and the limits the
hand-written parts are held to."""

from __future__ import annotations

import json

import pytest

from scry_core import example


def test_a_long_value_is_abridged_to_its_shape() -> None:
    shown = example.abridged({"rows": list(range(20)), "text": "x" * 1000, "n": 3})
    assert shown["rows"][-1] == f"... {20 - example.ABRIDGED_ITEMS} more"
    assert shown["text"].endswith(" ... (1000 characters)") and shown["n"] == 3


def test_a_small_flat_object_inside_a_reply_is_one_line_and_the_reply_itself_is_not() -> None:
    """A control is a name, a rect and a point: one row, not eight; the top level stays a
    column so the reply reads as fields."""
    block = example.fenced({"matched": True, "controls": [
        {"name": "pict", "rect": [103, 0, 33, 11], "centre": [119, 5]}]})
    assert '{"name": "pict", "rect": [103, 0, 33, 11], "centre": [119, 5]}' in block, block
    assert block.startswith('```json\n{\n  "matched": true,'), block
    wide = {"controls": [{"name": "x" * 90, "rect": [1, 2, 3, 4]}]}
    assert '"name": "' + "x" * 90 + '",\n' in example.fenced(wide), "a long one stays a column"
    assert json.loads(example.fenced(wide).removeprefix("```json\n").removesuffix("\n```")) == wide


def test_a_list_of_scalars_is_one_line_in_a_block() -> None:
    """A rect or a pixel pair is one thought, not four lines: the page's size is its cost."""
    value = {"size": [640, 480], "controls": [{"name": "pict", "rect": [103, 0, 33, 11]}],
             "names": ["a", "b"], "none": [], "mixed": [1, [2, 3]]}
    block = example.fenced(value)
    assert '"size": [640, 480],' in block, block
    assert '"rect": [103, 0, 33, 11]' in block, block
    assert '"names": ["a", "b"]' in block and '"none": []' in block, block
    assert '"mixed": [\n' in block, block
    assert json.loads(block.removeprefix("```json\n").removesuffix("\n```")) == value


def test_a_call_that_fits_is_written_whole() -> None:
    assert example.call_text("close", {}) == "close()"
    assert example.call_text("read_memory", {"ref": "0x42b", "length": 2}) == \
        'read_memory(ref="0x42b", length=2)'
    wide = example.call_text("start", {"system": "gridlee", "rompath": "/" + "r" * 60,
                                       "reference_rom": "/" + "f" * 60, "boot_seconds": 60})
    assert wide.splitlines()[0] == 'start(system="gridlee", rompath="/' + "r" * 60 + '",'
    assert wide.splitlines()[1].startswith('    reference_rom="/'), wide
    assert len(wide.splitlines()) == 2, "a call breaks between arguments, where a line fills"


def test_a_call_too_long_for_its_lines_has_its_long_values_cut_and_says_what_it_left_out() -> None:
    steps = [{"op": "input", "port": ":IN1", "field": "Coin 1", "frames": 4},
             {"op": "run_for", "milliseconds": 2000}, {"op": "scan", "method": "filter"}]
    cut = example.call_text("perform", {"steps": steps * 4, "settle_seconds": 300})
    assert cut == ('perform(steps=[{"op": "input", "port": ":IN1", "field": "Coin 1", '
                   '"frames": 4}, "… 11 more"],\n    settle_seconds=300)'), cut
    hexed = example.call_text("write", {"ref": "82DD:000C", "data_hex": "ab" * 400})
    assert hexed == f'write(ref="82DD:000C", data_hex="{"ab" * 8}…{"ab" * 8}")', hexed
    many = example.call_text("start", {f"argument_{n}": "v" * 30 for n in range(12)})
    lines = many.splitlines()
    assert len(lines) == example.CALL_LINES and lines[-1].endswith(' more)'), many
    assert all(len(line) <= example.COLUMNS for line in lines), many
    shown = many.count("argument_")
    assert f"… {12 - shown} more)" in many and 0 < shown < 12, many


def test_an_excerpt_shows_the_named_fields_in_their_order_and_cuts_a_long_string() -> None:
    reply = {"summary": "s" * 300, "status": "ok", "hits": ["82DD:0000000F"], "hits_total": 1}
    text = example.excerpt(reply, ("hits_total", "summary"))
    lines = text.splitlines()
    assert lines[1] == '  "hits_total": 1,' and lines[2].startswith('  "summary": "sss'), text
    assert all(len(line) <= example.COLUMNS for line in lines), text
    assert "(300 characters)" in lines[2], "a cut string says how long it was"
    with pytest.raises(ValueError, match=r"shows \['gone'\], which the reply does not carry"):
        example.excerpt(reply, ("gone",))


def test_an_excerpt_past_its_lines_or_its_columns_is_refused() -> None:
    with pytest.raises(ValueError, match="is 15 lines, and a reply shows at most 12"):
        example.excerpt({f"field_{n}": n for n in range(13)}, [f"field_{n}" for n in range(13)])
    key = "k" * 120
    with pytest.raises(ValueError, match="a line past 100 columns"):
        example.excerpt({key: 1}, (key,))


@pytest.mark.parametrize(("text", "words", "sentences"), [
    ("One. Two? Three!", 3, 3), ("It reads `0x42b` at 3.5 s.", 6, 1), ("", 0, 0),
])
def test_words_and_sentences_are_counted_as_a_reader_counts_them(
        text: str, words: int, sentences: int) -> None:
    assert (example.words(text), example.sentences(text)) == (words, sentences)


def test_an_example_is_rendered_in_its_one_shape() -> None:
    reply = {"summary": "find: 1 hit", "status": "ok", "hits": ["82DD:0000000F"], "hits_total": 1}
    one = example.Example("Find where the game keeps that sentence.", "find",
                          {"data_hex": "4e6f", "ref": "0000:0000"}, reply,
                          ("summary", "hits"), "One address holds it.", "Find the line")
    assert example.render(one, 2) == "\n".join([
        "**2. Find the line**", "", "Ask:", "", "> Find where the game keeps that sentence.", "",
        "Call:", "", "```text", 'find(data_hex="4e6f", ref="0000:0000")', "```", "",
        "Reply, 2 of 4 fields:", "", "```json", "{", '  "summary": "find: 1 hit",',
        '  "hits": ["82DD:0000000F"]', "}", "```", "", "One address holds it.", "",
        "<details><summary>The whole reply</summary>", "", example.fenced(reply), "",
        "</details>"])
    bare = example.render(example.Example("Ask it.", "close", {}, reply, ("status",), "Read it."),
                          whole=False)
    assert bare.startswith("Ask:\n\n> Ask it.") and "<details>" not in bare, bare


def test_a_call_no_cut_can_fit_keeps_only_its_tool() -> None:
    assert example.call_text("t" * 120, {"a": 1}) == "t" * 120 + "(…)"


def test_a_call_whose_first_value_fits_no_line_keeps_its_argument_names() -> None:
    """A list of long steps cannot be cut to a line: the call says what it was given, and how
    much of it."""
    step = {f"argument_{n}": n for n in range(30)}
    assert example.call_text("perform", {"steps": [step] * 19, "seconds": 30, "with": {"a": 1},
                                         "label": "x" * 200}) == (
        "perform(steps=[… 19 items], seconds=…, with={… 1 key}, label=…)")


def test_a_list_of_numbers_in_a_call_is_kept_whole_and_one_of_objects_is_not() -> None:
    wide = {"rect": [1, 2, 3, 4], "note": "n" * 400}
    cut = example.call_text("screen_view", wide)
    assert cut.startswith("screen_view(rect=[1, 2, 3, 4], note=") and "…" in cut, cut


def test_an_excerpt_s_list_too_long_for_one_line_is_a_column() -> None:
    lines = [f"{n:04X}: LD A,(HL) ; an instruction of the trail" for n in range(12)]
    reply = {"summary": "history: 12", "lines": lines, "regs": [1, 2, 3]}
    rows = example.excerpt(reply, ("regs", "lines")).splitlines()
    assert rows[1:4] == ['  "regs": [1, 2, 3],', '  "lines": [',
                         '    "0000: LD A,(HL) ; an instruction of the trail",'], rows
    assert rows[9] == '    "... 6 more"' and len(rows) == example.REPLY_LINES, rows
    assert all(len(row) <= example.COLUMNS for row in rows)
    assert '"lines": ["0000' in example.fenced({"lines": lines}), "a whole reply keeps one line"
    with pytest.raises(ValueError, match="is 13 lines"):
        example.excerpt(reply, ("summary", "regs", "lines"))


def test_an_excerpt_keeps_as_much_of_a_list_as_its_lines_hold() -> None:
    lines = [f"{n:04X}: an instruction" for n in range(8)]
    assert example.excerpt({"lines": lines}, ("lines",)).splitlines()[-3:] == [
        '    "0007: an instruction"', "  ]", "}"], "eight items fit in twelve lines"
    more = example.excerpt({"lines": lines + lines}, ("lines",)).splitlines()
    assert more[-3] == '    "... 9 more"' and len(more) == example.REPLY_LINES, more
