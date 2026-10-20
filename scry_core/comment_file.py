"""The comment file, version 1: how a project keeps the comments it made in a session, one file
both servers read and write, so a file written by one is one the other takes.

    # comments v1: ref<TAB>cpu<TAB>created_at<TAB>text
    <ref><TAB><cpu><TAB><created_at><TAB><text>

Four fields split on the first three tabs, the text LAST, so the text is the rest of the line and
nothing in it is ever quoted or escaped; a comment cannot hold a tab or a newline, which the text
rule refuses with every other character that is not printable. Rows are written sorted by cpu,
then ref, in code-point order, so saving again moves nothing that did not change and a `git diff`
of the file shows exactly the comments that did. There is no column for the build: a raw address
read into another build is trusted for it, which is why a comment meant to survive a rebuild is
made by symbol.

This module judges the FILE and what every server agrees on: the header, the columns, a text, a
stamp, one (ref, cpu) twice. What a ref may be and whether the cpu column is filled are each
server's (`Policy`): one spells an address as `SEG:OFF` and drives one processor, the other as
`0x` and names its cpus. What a ref names and where it lands are the server's too, which holds
the table and the machine.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from scry_core import prose

#: Line 1, exactly: the version mark a reader checks before anything else.
HEADER = "# comments v1: ref\tcpu\tcreated_at\ttext"
# THE LONGEST TEXT, IN UTF-8 BYTES, is version 1's, so a file written by one server is one every
# reader takes: what one line of MAME's `comlist` holds unbroken (it prints a comment after a
# 12-character prefix, and its console cuts a line at 250 columns: 250 - 1 - 12). Bytes and not
# characters, because a file is bytes and the bound has to mean the same to every reader.
TEXT_MAX_BYTES = 237
_BOM = "\ufeff"


@dataclass(frozen=True)
class Row:
    """The four columns of one comment line, in file order, plus where it was read."""

    ref: str
    cpu: str
    created_at: str
    text: str
    #: Which line of the file held it (2 is the first after the header), so a refusal of the row
    #: can point at it; 0 when the row was built in memory and never read.
    line: int = field(default=0, compare=False)


class CommentFileError(ValueError):
    """Raised by `parse` for text that is not a comment file and by `render` for rows that would
    not make one; the message says which line, or which ref, and why."""


@dataclass(frozen=True)
class Policy:
    """What a server holds a row's `ref` and `cpu` columns to, each answering what the column
    breaks or None."""

    ref_fault: Callable[[str], str | None]
    cpu_fault: Callable[[str], str | None]


def text_fault(text: str) -> str | None:
    """Why `text` cannot be a comment, or None when it can. A comment is one visible line: not
    empty, every character printable (so no tab or line break), no blank at either end, and no
    longer than `TEXT_MAX_BYTES` once encoded. A call, the store and a file all ask this."""
    if text == "":
        return "is empty"
    if not text.isprintable():
        bad = next(c for c in text if not c.isprintable())
        return f"holds {bad!r}, which is not printable: one comment is one line of text"
    if text != text.strip():
        return "starts or ends with whitespace"
    # MEASURED LAST: a lone surrogate cannot be encoded at all, and the printable rule has
    # already refused it by name.
    size = len(text.encode("utf-8"))
    if size > TEXT_MAX_BYTES:
        return f"is {size} UTF-8 bytes, past the {TEXT_MAX_BYTES} a comment file of version 1 holds"
    return None


def word_fault(word: str) -> str | None:
    """What a word a file holds in one column breaks, or None: whitespace, or a character that is
    not printable."""
    if not word.isprintable() or any(c.isspace() for c in word):
        return "holds whitespace or a character that is not printable"
    return None


def stamp_fault(stamp: str) -> str | None:
    """What a `created_at` breaks, or None: a date AND a time with its offset from UTC, the
    store's own stamp, so a file read on another machine means the same instant."""
    wrong = (f"{stamp!r} is not a stamp with a date, a time and an offset from UTC, as "
             "`YYYY-MM-DDTHH:MM:SS+00:00`")
    if "T" not in stamp:
        return wrong
    try:
        return None if datetime.fromisoformat(stamp).utcoffset() is not None else wrong
    except ValueError:
        return wrong


def row_fault(r: Row, policy: Policy) -> str | None:
    """What one row breaks, or None, its column named first: the rules `parse` holds a line to and
    `render` holds a row to, so a file a server writes is one it reads."""
    for column, fault in (("ref", policy.ref_fault(r.ref)), ("cpu", policy.cpu_fault(r.cpu)),
                          ("created_at", stamp_fault(r.created_at)), ("text", text_fault(r.text))):
        if fault is not None:
            return f"the {column} {fault}"
    return None


def _place(r: Row) -> str:
    return f"{r.ref!r} on {r.cpu}" if r.cpu else repr(r.ref)


def _one_per(r: Row) -> str:
    """The key a file holds one comment per, as a refusal names it: the ref as spelled (which
    refs alias one place is the server's question, not the file's), on its cpu when it names one."""
    return "one comment per ref on a cpu" if r.cpu else "one comment per ref"


def parse(text: str, where: str, policy: Policy) -> list[Row]:
    """Every row of a comment file's text, or the refusal naming the first line that breaks the
    format: no header (or another one, or a byte order mark before it), a row of fewer than four
    columns, a row breaking `row_fault`, one (ref, cpu) on two lines. CRLF reads as LF, and a CR
    anywhere else is refused rather than taken for a line break; lines of nothing but spaces and
    tabs, and lines starting with `#`, are skipped after the header. `where` names the file in a
    refusal."""
    first, _, body = text.replace("\r\n", "\n").partition("\n")
    if first != HEADER:
        said = ("starts with a byte order mark" if first[:1] == _BOM else f"is {first[:80]!r}")
        raise CommentFileError(f"{where}:1: the first line {said}, and a comment file's is "
                               f"exactly {HEADER!r}")
    rows: list[Row] = []
    line_of: dict[tuple[str, str], int] = {}
    for lineno, line in enumerate(body.split("\n"), 2):
        if "\r" in line:
            raise CommentFileError(f"{where}:{lineno}: a carriage return that does not end the "
                                   "line; lines end in LF, or CRLF")
        if line.strip(" \t") == "" or line[0] == "#":
            continue
        cols = line.split("\t", 3)
        if len(cols) < 4:
            raise CommentFileError(f"{where}:{lineno}: a row is ref, cpu, created_at and text "
                                   "separated by tabs; this one has "
                                   f"{prose.counted(len(cols), 'column')}")
        row = Row(cols[0], cols[1], cols[2], cols[3], line=lineno)
        if (fault := row_fault(row, policy)) is not None:
            raise CommentFileError(f"{where}:{lineno}: {fault}")
        held = line_of.setdefault((row.ref, row.cpu), lineno)
        if held != lineno:
            raise CommentFileError(f"{where}:{lineno}: {_place(row)} again, already on line "
                                   f"{held}: {_one_per(row)}")
        rows.append(row)
    return rows


def render(rows: Iterable[Row], policy: Policy) -> str:
    """The file's text for `rows`: the header, then one line per row sorted by cpu and ref in
    code-point order, every line ended by LF. A row `parse` would refuse (`row_fault`, or one
    (ref, cpu) twice) is refused here instead, so nothing is written that cannot be read back."""
    lines = [HEADER]
    previous: tuple[str, str] | None = None
    # SORTED FIRST, so one (cpu, ref) twice lands on adjacent rows and one look back finds it.
    for r in sorted(rows, key=lambda r: (r.cpu, r.ref)):
        if (fault := row_fault(r, policy)) is not None:
            raise CommentFileError(f"{_place(r)}: {fault}")
        if previous == (r.cpu, r.ref):
            raise CommentFileError(f"{_place(r)} twice: a file holds {_one_per(r)}")
        previous = (r.cpu, r.ref)
        lines.append("\t".join((r.ref, r.cpu, r.created_at, r.text)))
    return "\n".join(lines) + "\n"
