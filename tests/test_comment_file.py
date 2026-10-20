"""The comment file both servers read and write, judged with a policy of its own: the format's
rules, and the two columns a server's policy decides."""

from __future__ import annotations

import pytest

from scry_core import comment_file as cf

STAMP = "2026-10-02T00:30:00+00:00"
ONE_CPU = cf.Policy(ref_fault=lambda r: cf.word_fault(r) if r else "is empty",
                    cpu_fault=lambda c: "is filled" if c else None)


def text(*rows: str) -> str:
    return "\n".join([cf.HEADER, *rows]) + "\n"


def test_a_file_round_trips_sorted_and_skips_notes_and_blanks() -> None:
    rows = cf.parse(text(f"b\t\t{STAMP}\tsecond", "# a note", "  ",
                         f"a\t\t{STAMP}\tfirst with words"), "f", ONE_CPU)
    assert [(r.ref, r.text, r.line) for r in rows] == [("b", "second", 2),
                                                        ("a", "first with words", 5)]
    assert cf.render(rows, ONE_CPU) == text(f"a\t\t{STAMP}\tfirst with words",
                                            f"b\t\t{STAMP}\tsecond")
    assert cf.parse(cf.render(rows, ONE_CPU), "f", ONE_CPU) == sorted(rows, key=lambda r: r.ref)


@pytest.mark.parametrize(("body", "said"), [
    ("\ufeff" + cf.HEADER + "\n", "byte order mark"),
    ("# comments v2\n", "is '# comments v2'"),
    (text("a\tb"), "has 2 columns"),
    (text(f"a\tcpu\t{STAMP}\tx"), "the cpu is filled"),
    (text("a\t\tyesterday\tx"), "the created_at 'yesterday' is not a stamp"),
    (text(f"a\t\t{STAMP}\tx "), "the text starts or ends with whitespace"),
    (text(f"a\t\t{STAMP}\t" + "y" * (cf.TEXT_MAX_BYTES + 1)), f"past the {cf.TEXT_MAX_BYTES}"),
    (text(f"a\t\t{STAMP}\tx", f"a\t\t{STAMP}\ty"),
     "'a' again, already on line 2: one comment per ref"),
    (cf.HEADER + "\n" + f"a\t\t{STAMP}\tx\ry\n", "a carriage return"),
])
def test_what_breaks_the_format_is_refused_naming_the_line(body: str, said: str) -> None:
    with pytest.raises(cf.CommentFileError) as refused:
        cf.parse(body, "f", ONE_CPU)
    assert said in str(refused.value), refused.value


def test_crlf_reads_as_lf() -> None:
    assert cf.parse(text(f"a\t\t{STAMP}\tx").replace("\n", "\r\n"), "f", ONE_CPU)[0].text == "x"


def test_render_refuses_what_parse_would_and_names_the_place() -> None:
    with pytest.raises(cf.CommentFileError, match="'a' on m: the cpu is filled"):
        cf.render([cf.Row("a", "m", STAMP, "x")], ONE_CPU)
    with pytest.raises(cf.CommentFileError, match="'a' twice: a file holds one comment per ref$"):
        cf.render([cf.Row("a", "", STAMP, "x"), cf.Row("a", "", STAMP, "y")], ONE_CPU)


@pytest.mark.parametrize(("value", "said"), [
    ("", "is empty"), ("a\tb", "not printable"), (" a", "whitespace"), ("ok", None)])
def test_a_text_is_one_visible_line(value: str, said: str | None) -> None:
    fault = cf.text_fault(value)
    assert (fault is None) if said is None else (fault is not None and said in fault), fault
