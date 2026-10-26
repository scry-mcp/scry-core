"""The comment file, version 1: one file both servers read and write.

    # comments v1: ref<TAB>cpu<TAB>created_at<TAB>text
    <ref><TAB><cpu><TAB><created_at><TAB><text>

The text is the rest of the line, so never escaped. Rows are sorted by cpu, then ref, so a diff
shows only what changed. No build column: a comment meant to survive a rebuild is made by symbol.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from scry_core import prose

HEADER = "# comments v1: ref\tcpu\tcreated_at\ttext"
# What one line of MAME's `comlist` holds unbroken (250 - 1 - 12 prefix); bytes, not characters.
TEXT_MAX_BYTES = 237
#: What a tool's description fills from here (`scry_core.docs.filled`), as both servers say it.
DOC_VALUES = {
    "COMMENT_TEXT_MAX": str(TEXT_MAX_BYTES),
    "COMMENT_SAVE": ("`save`: every comment to `dest`, an absolute or `~`-led path, replacing a "
                     "comment file\nthere (rows only it held in `dropped_comments`); any other "
                     "file is refused; answers on a\nrunning machine. Reply: `path`, "
                     "`comments_total`, `dropped_comments`, `dropped_total`,\n`truncated`, "
                     "`note`."),
    "COMMENT_LOAD": ("`load`: the comment file at `path`, all or nothing, the file winning. "
                     "Reply: `path`,\n`parsed`, `added`, `replaced_comments`, "
                     "`replaced_total`, `truncated`, `unchanged`,\n`comments_total`, "
                     "`declarations`, `note`."),
}
_BOM = "\ufeff"


@dataclass(frozen=True)
class Row:

    ref: str
    cpu: str
    created_at: str
    text: str
    #: The file line it was read from; 0 when built in memory.
    line: int = field(default=0, compare=False)


class CommentFileError(ValueError):
    """Text that is not a comment file, or rows that would not make one."""


@dataclass(frozen=True)
class Policy:
    """What a server holds `ref` and `cpu` to; each returns a fault or None."""

    ref_fault: Callable[[str], str | None]
    cpu_fault: Callable[[str], str | None]

    def parse(self, text: str, where: str = "the comment file") -> list[Row]:
        """`parse` under this policy."""
        return parse(text, where, self)

    def render(self, rows: Iterable[Row]) -> str:
        """`render` under this policy."""
        return render(rows, self)


def text_fault(text: str) -> str | None:
    """Why `text` cannot be a comment, or None."""
    if text == "":
        return "is empty"
    if not text.isprintable():
        bad = next(c for c in text if not c.isprintable())
        return f"holds {bad!r}, which is not printable: one comment is one line of text"
    if text != text.strip():
        return "starts or ends with whitespace"
    # After the printable rule: a lone surrogate cannot be encoded.
    size = len(text.encode("utf-8"))
    if size > TEXT_MAX_BYTES:
        return f"is {size} UTF-8 bytes, past the {TEXT_MAX_BYTES} a comment file of version 1 holds"
    return None


def word_fault(word: str) -> str | None:
    """The fault of a one-column word, or None."""
    if not word.isprintable() or any(c.isspace() for c in word):
        return "holds whitespace or a character that is not printable"
    return None


def stamp_fault(stamp: str) -> str | None:
    """The fault of a `created_at`, or None; it needs a UTC offset."""
    wrong = (f"{stamp!r} is not a stamp with a date, a time and an offset from UTC, as "
             "`YYYY-MM-DDTHH:MM:SS+00:00`")
    if "T" not in stamp:
        return wrong
    try:
        return None if datetime.fromisoformat(stamp).utcoffset() is not None else wrong
    except ValueError:
        return wrong


def row_fault(r: Row, policy: Policy) -> str | None:
    """What one row breaks, column named first, or None."""
    for column, fault in (("ref", policy.ref_fault(r.ref)), ("cpu", policy.cpu_fault(r.cpu)),
                          ("created_at", stamp_fault(r.created_at)), ("text", text_fault(r.text))):
        if fault is not None:
            return f"the {column} {fault}"
    return None


def _place(r: Row) -> str:
    return f"{r.ref!r} on {r.cpu}" if r.cpu else repr(r.ref)


def _one_per(r: Row) -> str:
    """The uniqueness key as a refusal names it."""
    return "one comment per ref on a cpu" if r.cpu else "one comment per ref"


def parse(text: str, where: str, policy: Policy) -> list[Row]:
    """Every row of `text`, or a `CommentFileError` naming the first bad line in `where`.

    CRLF reads as LF, any other CR is refused; blank and `#` lines after the header are skipped."""
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
    """The file's text for `rows`; refuses what `parse` would."""
    lines = [HEADER]
    previous: tuple[str, str] | None = None
    # Sorted, so a duplicate (cpu, ref) is adjacent.
    for r in sorted(rows, key=lambda r: (r.cpu, r.ref)):
        if (fault := row_fault(r, policy)) is not None:
            raise CommentFileError(f"{_place(r)}: {fault}")
        if previous == (r.cpu, r.ref):
            raise CommentFileError(f"{_place(r)} twice: a file holds {_one_per(r)}")
        previous = (r.cpu, r.ref)
        lines.append("\t".join((r.ref, r.cpu, r.created_at, r.text)))
    return "\n".join(lines) + "\n"
