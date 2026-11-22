"""A quote: where a row's evidence sits in a pinned source, and the digest that says it is still
there.

A quote is `ref` (`<scheme>:<file>`), `lines` (`322-328`, or `259`) and `sha`, the SHA-256 of
those lines with every run of white space folded to one space. The committed files hold no
source text: a reader opens the lines through `Sources`, which reads each scheme at its pin.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from scry_core.knowledge.shared import PINS

PARTY = {"mame": "mame", "dosbox-x": "dosbox-x", "rbil61": "doc", "datasheet": "doc"}
QUOTE_LINES = 12
DATASHEETS_FORMAT = "scry-knowledge-datasheets/1"
_SPAN = re.compile(r"([1-9][0-9]*)(?:-([1-9][0-9]*))?")
_SHA = re.compile(r"[0-9a-f]{64}")


class Invalid(Exception):
    """A source, a function or a rule that cannot give what a check needs: exit 3."""


class Outside(Invalid):
    """Lines the file does not have: a fault of the row that names them, not of the source."""


def split_ref(ref: str) -> tuple[str, str]:
    """The scheme and the file of a `ref`, or `ValueError`."""
    scheme, colon, file = ref.partition(":")
    if not colon or scheme not in PARTY or not file or file != file.strip():
        raise ValueError(f"{ref!r} is `<scheme>:<file>` with a scheme of {', '.join(PARTY)}")
    return scheme, file


def span(lines: str) -> tuple[int, int]:
    """The first and the last line of a `lines` text (`a-b`, or `a`), or `ValueError`."""
    found = _SPAN.fullmatch(lines) if isinstance(lines, str) else None
    if not found:
        raise ValueError(f"`lines` is `a-b` or `a`, from line 1; got {lines!r}")
    first = int(found.group(1))
    last = int(found.group(2) or first)
    if last < first:
        raise ValueError(f"`lines` runs downward: {lines!r}")
    return first, last


def spelled(first: int, last: int) -> str:
    """The one spelling of a span."""
    return str(first) if first == last else f"{first}-{last}"


def stamp(lines: list[str]) -> str:
    """The digest of `lines`: their text with runs of white space folded."""
    return hashlib.sha256(" ".join(" ".join(lines).split()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Quote:
    ref: str
    lines: str
    sha: str = ""

    @property
    def scheme(self) -> str:
        return split_ref(self.ref)[0]

    @property
    def party(self) -> str:
        return PARTY[self.scheme]

    @property
    def first(self) -> int:
        return span(self.lines)[0]

    @property
    def last(self) -> int:
        return span(self.lines)[1]

    def as_json(self) -> dict[str, str]:
        return {"ref": self.ref, "lines": self.lines, "sha": self.sha}


@dataclass(frozen=True)
class Datasheet:
    """A datasheet held by identity: where it is, and the digest of the PDF and of the one text
    capture a quote's lines are numbered in (`pdftotext -raw`, which keeps a two-column page in
    reading order where `-layout` puts both columns on one line)."""

    title: str
    url: str
    pdf: str
    capture: str


def parse_datasheets(text: str, where: str = "datasheets") -> dict[str, Datasheet]:
    """The datasheet table, by capture file name, or `ValueError` naming what is wrong."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as bad:
        raise ValueError(f"{where} is not JSON: {bad}") from bad
    if not isinstance(doc, dict) or doc.get("format") != DATASHEETS_FORMAT:
        raise ValueError(f"{where} is not a `{DATASHEETS_FORMAT}` document")
    table = doc.get("datasheets")
    if not isinstance(table, dict) or not table:
        raise ValueError(f"{where}: `datasheets` is a non-empty object")
    made: dict[str, Datasheet] = {}
    for name, raw in table.items():
        if not (isinstance(raw, dict) and set(raw) == {"title", "url", "pdf", "capture"}
                and all(isinstance(v, str) for v in raw.values())
                and _SHA.fullmatch(raw["pdf"]) and _SHA.fullmatch(raw["capture"])):
            raise ValueError(f"{where}: {name!r} is `title`, `url`, and the 64-digit `pdf` and "
                             "`capture` digests")
        made[name] = Datasheet(raw["title"], raw["url"], raw["pdf"], raw["capture"])
    return made


def default_datasheets() -> dict[str, Datasheet]:
    """The datasheets this package's index holds."""
    name = "datasheets.json"
    return parse_datasheets(
        (resources.files("scry_core") / "knowledge_index" / name).read_text(encoding="utf-8"),
        name)


def _split(text: str) -> list[str]:
    held = text.replace("\r\n", "\n").split("\n")
    return held[:-1] if held and held[-1] == "" else held


class Sources:
    """Reads the lines of a quote's file at the pin: MAME from a tree of the tag's files, DOSBox-X
    with `git show` at the pin, Ralf Brown's list from a folder holding its files or its
    archives, a datasheet from its capture, whose digest must be the table's."""

    def __init__(self, *, mame: Path | None = None, dosbox: Path | None = None,
                 rbil: Path | None = None, datasheets: Path | None = None,
                 pins: Mapping[str, str] | None = None,
                 table: Mapping[str, Datasheet] | None = None) -> None:
        self.roots = {"mame": mame, "dosbox-x": dosbox, "rbil61": rbil, "datasheet": datasheets}
        self.pins = dict(PINS if pins is None else pins)
        self.table = default_datasheets() if table is None else table
        self._held: dict[str, list[str]] = {}

    def lines(self, ref: str) -> list[str]:
        """Every line of the file `ref` names, numbered from 1 as an editor does."""
        if ref not in self._held:
            scheme, file = split_ref(ref)
            root = self.roots[scheme]
            if root is None:
                raise Invalid(f"no source for {scheme}: it needs its option (--mame, --dosbox, "
                              "--rbil or --datasheets)")
            reader = {"mame": self._mame, "dosbox-x": self._dosbox, "rbil61": self._rbil,
                      "datasheet": self._datasheet}[scheme]
            self._held[ref] = _split(reader(root, file))
        return self._held[ref]

    def _mame(self, root: Path, file: str) -> str:
        path = root / file
        if not path.is_file():
            raise Invalid(f"{path} is not a file: the MAME tree holds the files of the pinned "
                          "tag at their own paths")
        return path.read_bytes().decode("utf-8", errors="replace")

    def _dosbox(self, root: Path, file: str) -> str:
        pin = self.pins["dosbox-x"]
        done = subprocess.run(["git", "-C", str(root), "show", f"{pin}:{file}"],
                              capture_output=True, check=False)
        if done.returncode != 0:
            raise Invalid(f"git show {pin}:{file} failed in {root}: "
                          f"{done.stderr.decode(errors='replace').strip()}")
        return done.stdout.decode("utf-8", errors="replace")

    def _rbil(self, root: Path, file: str) -> str:
        if (root / file).is_file():
            return (root / file).read_bytes().decode("latin-1")
        for archive in sorted(root.glob("inter61*.zip")):
            try:
                with zipfile.ZipFile(io.BytesIO(archive.read_bytes())) as z:
                    if file in z.namelist():
                        return z.read(file).decode("latin-1")
            except zipfile.BadZipFile as bad:
                raise Invalid(f"{archive} is not a zip archive: {bad}") from bad
        raise Invalid(f"{file} is neither a file in {root} nor in one of its archives")

    def _datasheet(self, root: Path, file: str) -> str:
        known = self.table.get(file)
        if known is None:
            raise Invalid(f"{file} is no datasheet of the table: it holds "
                          f"{', '.join(sorted(self.table))}")
        path = root / file
        if not path.is_file():
            raise Invalid(f"{path} is not a file: rebuild the capture with `pdftotext -raw`")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != known.capture:
            raise Invalid(f"{path} is not the capture the table records for {file} "
                          "(`pdftotext -raw` of the PDF it names)")
        return data.decode("utf-8", errors="replace")

    def read(self, quote: Quote) -> list[str]:
        """The lines a quote names; `Invalid` when the file lacks them."""
        first, last = span(quote.lines)
        held = self.lines(quote.ref)
        if last > len(held):
            raise Outside(f"{quote.ref}:{quote.lines} is outside the file, which has "
                          f"{len(held)} lines")
        return held[first - 1:last]

    def stamped(self, ref: str, lines: str) -> Quote:
        """The quote of `lines` of `ref`, with the digest of what the source holds there."""
        split_ref(ref)
        span(lines)
        draft = Quote(ref, lines)
        return Quote(ref, lines, stamp(self.read(draft)))

    def faults(self, quote: Quote) -> list[str]:
        """What is wrong with `quote`: lines the file lacks, blank or too many, or a digest that
        is not the lines'."""
        where = f"{quote.ref}:{quote.lines}"
        try:
            first, last = span(quote.lines)
            held = self.read(quote)
        except ValueError as bad:
            return [str(bad)]
        except Outside as bad:
            return [str(bad)]
        out = []
        if last - first + 1 > QUOTE_LINES:
            out.append(f"{where} is {last - first + 1} lines, over {QUOTE_LINES}")
        if not any(line.strip() for line in held):
            out.append(f"{where} is blank")
        if not _SHA.fullmatch(quote.sha):
            out.append(f"{where} has no digest: `rows quote --stamp` writes it")
        elif quote.sha != stamp(held):
            out.append(f"{where} no longer gives its digest: the source changed or the row "
                       "names other lines")
        return out
