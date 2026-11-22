"""Writes `src/scry_core/knowledge_index/shared.json`, the index the shared chip dictionaries are
held to, from the real sources, or compares the committed file with them.

    python tools/knowledge_sources.py --mame DIR --dosbox REPO --rbil DIR [--index PATH] [--check]

Exit 0: written, or equal under `--check`. Exit 1: `--check` and the committed index differs.
Exit 3: a source could not be read or a rule matched nothing (or more than once): an index
that examined nothing is never written. Exit 2: a bad option.

- `--mame DIR` is a tree holding the files of the MAME tag `shared.PINS["mame"]` at their own
  paths, fetched as `https://raw.githubusercontent.com/mamedev/mame/<tag>/<path>`.
- `--dosbox REPO` is a DOSBox-X checkout that holds the commit `shared.PINS["dosbox-x"]`; the
  files are read with `git show` at that commit.
- `--rbil DIR` holds the six archives of Ralf Brown's Interrupt List, release 61, from
  https://www.cs.cmu.edu/~ralf/interrupt-list/ (`inter61a.zip` to `inter61f.zip`), checked
  against `ARCHIVES`. Credit: the list is by Ralf Brown and contributors, and its licence asks for
  credit once more than 2,000 lines are used.

A row is the source's own line, tabs kept, so an entry's `cites` equals it character for
character. A rule that matches no line, or several where one was meant, is INVALID.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scry_core.knowledge import sources
from scry_core.knowledge.keys import KeyFault, canonical
from scry_core.knowledge.lock import dumps
from scry_core.knowledge.shared import PINS

ARCHIVES = {
    "inter61a.zip": "8077536135c0290ff18a4a44cf63c56339f6127f053ee673f9895837248cc947",
    "inter61b.zip": "713e9e218eda694ed2bac8d5f02378f935f3e3132b79c92c44c14101e76b88a7",
    "inter61c.zip": "d7a059a1700c765adb9d4bf9dbe6289621aca6ff09c0583192764ee47e2b690a",
    "inter61d.zip": "0d0a04e84dd6a1db312157f3365fc7ee0b539af677944ace593df5236a563241",
    "inter61e.zip": "e71ff6bc9cb4c8d04b6fd3d91399ed4b7cdad205b8186d8ddbf52c13440d31a4",
    "inter61f.zip": "8166cfb253b1b7945bb58c9aca757f772e9d3f16514327e28652920b66751b40",
}
DEFAULT_INDEX = Path(__file__).resolve().parent.parent / "src/scry_core/knowledge_index/shared.json"


class Invalid(Exception):
    """A source or a rule that cannot give what the index needs: exit 3."""


class Library:
    """The lines of each source file, read once."""

    def __init__(self, mame: Path, dosbox: Path, rbil: Path) -> None:
        self.mame, self.dosbox, self.rbil = mame, dosbox, rbil
        self._lines: dict[tuple[str, str], list[str]] = {}
        self._zips: dict[str, bytes] | None = None

    def lines(self, scheme: str, file: str) -> list[str]:
        if (scheme, file) not in self._lines:
            self._lines[scheme, file] = self._read(scheme, file).replace("\r\n", "\n").split("\n")
        return self._lines[scheme, file]

    def _read(self, scheme: str, file: str) -> str:
        if scheme == "mame":
            path = self.mame / file
            if not path.is_file():
                raise Invalid(
                    f"{path} is not a file: fetch it from "
                    f"https://raw.githubusercontent.com/mamedev/mame/{PINS['mame']}/{file}"
                )
            return path.read_text(encoding="utf-8")
        if scheme == "dosbox-x":
            done = subprocess.run(
                ["git", "-C", str(self.dosbox), "show", f"{PINS['dosbox-x']}:{file}"],
                capture_output=True,
                check=False,
            )
            if done.returncode != 0:
                raise Invalid(
                    f"git show {PINS['dosbox-x']}:{file} failed in {self.dosbox}: "
                    f"{done.stderr.decode(errors='replace').strip()}"
                )
            return done.stdout.decode("utf-8", errors="replace")
        if scheme == "rbil61":
            return self._rbil(file)
        raise Invalid(f"no reader for scheme {scheme}")

    def _rbil(self, file: str) -> str:
        if self._zips is None:
            self._zips = {}
            for name, wanted in ARCHIVES.items():
                data = (self.rbil / name).read_bytes() if (self.rbil / name).is_file() else b""
                if hashlib.sha256(data).hexdigest() != wanted:
                    raise Invalid(
                        f"{self.rbil / name} is missing or is not the archive "
                        "whose SHA-256 ARCHIVES records"
                    )
                self._zips[name] = data
        for name in sorted(ARCHIVES):
            with zipfile.ZipFile(io.BytesIO(self._zips[name])) as z:
                if file in z.namelist():
                    return z.read(file).decode("latin-1").replace("\r\n", "\n")
        raise Invalid(f"{file} is in none of the RBIL archives")


def region(lines: list[str], inside: str, after: str = "", until: str = "") -> tuple[int, int]:
    """The first and one past the last line of the function `inside` (a definition starting in
    column 0, closed by a `}` in column 0), narrowed to what follows the first line matching
    `after` and precedes the next one matching `until`. No `inside` is the whole file."""
    start, end = 0, len(lines)
    if inside:
        starts = [
            i
            for i, text in enumerate(lines)
            if text[:1] not in ("", " ", "\t", "/", "#")
            and not text.rstrip().endswith(";")
            and re.search(rf"(?<![\w:]){re.escape(inside)}\s*[()]", text)
        ]
        if len(starts) != 1:
            raise Invalid(f"{inside!r} is defined {len(starts)} times, not once")
        start = starts[0]
        closed = next((i + 1 for i in range(start + 1, len(lines)) if lines[i] == "}"), None)
        if closed is None:
            raise Invalid(f"{inside!r} has no closing `}}` in column 0")
        end = closed
    if after:
        found = [i for i in range(start, end) if re.search(after, lines[i])]
        if len(found) != 1:
            raise Invalid(
                f"{after!r} matches {len(found)} lines of {inside or 'the file'}, not one"
            )
        start = found[0]
    if until:
        found = [i for i in range(start + 1, end) if re.search(until, lines[i])]
        if not found:
            raise Invalid(f"nothing matches {until!r} after {after!r} in {inside or 'the file'}")
        end = found[0]
    return start, end


@dataclass(frozen=True)
class Line:
    """A row: the one line of `file` (inside the function `inside`, after `after`) matching
    `find`; `which` picks one of several, counted from 0."""

    ref: str
    find: str
    inside: str = ""
    after: str = ""
    until: str = ""
    which: int | None = None
    key: str = ""
    marks: str = ""

    def file(self) -> str:
        return sources.split(self.ref)[1].split(" ", 1)[0]


@dataclass
class Index:
    rows: dict[str, dict[str, str]] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)

    def put(self, ref: str, keys: list[str]) -> None:
        if ref in self.lists:
            raise Invalid(f"{ref} is a list twice")
        self.lists[ref] = keys

    def row(self, ref: str, line: str, key: str = "", marks: str = "") -> None:
        if ref in self.rows:
            raise Invalid(f"{ref} is a row twice")
        self.rows[ref] = {
            "line": line,
            **({"key": key} if key else {}),
            **({"marks": marks} if marks else {}),
        }


def hexed(label: str, symbols: dict[str, int] | None = None) -> str:
    """A case label or a number as the canonical hex key."""
    text = label.strip()
    try:
        value = int(text, 0)
    except ValueError:
        if symbols is None or text not in symbols:
            raise Invalid(f"case label {text!r} is no number and no known name") from None
        value = symbols[text]
    return canonical("register", f"0x{value:02X}")


def one_line(lib: Library, spec: Line) -> tuple[str, str]:
    scheme, locator = sources.split(spec.ref)
    lines = lib.lines(scheme, spec.file())
    lo, hi = region(lines, spec.inside, spec.after, spec.until)
    found = [lines[i] for i in range(lo, hi) if re.search(spec.find, lines[i])]
    if spec.which is None and len(found) != 1:
        raise Invalid(f"{spec.ref}: {spec.find!r} matches {len(found)} lines, not one")
    if spec.which is not None and len(found) <= spec.which:
        raise Invalid(f"{spec.ref}: {spec.find!r} matches {len(found)} lines, not {spec.which + 1}")
    return scheme, found[spec.which or 0]


@dataclass(frozen=True)
class Cases:
    """Every `case` label of a function: a row per label (`<ref> case <label>`, its key the
    label's number) and the list `<ref>` of the keys, a label that shares its body with the next
    counted as its own key. `symbols` names the enumerators a label may be."""

    ref: str
    inside: str
    after: str = ""
    until: str = ""
    symbols: tuple[tuple[str, int], ...] = ()
    enum_after: str = ""
    enum_file: str = ""
    runs: bool = False


@dataclass(frozen=True)
class Enum:
    """The enumerators of an `enum` block: a row per name (its key the number) and the list of the
    numbers. `rest` matches the line holding the size of the whole space (`return N;`): the numbers
    from the last enumerator up to that size are one more key, written as a range."""

    ref: str
    after: str
    rest: str = ""


@dataclass(frozen=True)
class OplMap:
    """The register map comment of the ymfm OPL header: a row per register line (`<ref> 20-35`, its
    key the address or the range), a second row `<ref> 20-35 +100` for the lines the comment says
    apply at address+100 on the OPL3, and the two lists: `opl2` (every line not marked OPL3 only)
    and `opl3` (every line, and the second banks)."""

    ref: str
    opl2: str
    opl3: str


@dataclass(frozen=True)
class LowHalf:
    """The registers a decode keeps below a tested address bit (`BIT(offset, 3)` leaves 0 to 7): a
    row, and the list of those numbers."""

    ref: str
    find: str
    inside: str


@dataclass(frozen=True)
class Joined:
    """A list that is two others one after the other."""

    ref: str
    parts: tuple[str, ...]


@dataclass(frozen=True)
class FromRows:
    """A list that is the keys of rows already captured, each number once, in order."""

    ref: str
    rows: tuple[str, ...]


@dataclass(frozen=True)
class Mask:
    """The `offset &= N` of a function: a row, and the list of the keys 0 to N."""

    ref: str
    find: str
    inside: str


@dataclass(frozen=True)
class DeviceTypes:
    """Every `DEFINE_DEVICE_TYPE` of a file: a row per short name and the list of the names."""

    ref: str


@dataclass(frozen=True)
class Listed:
    """A list written by hand because no `switch` gives it (the 8259's command words): each key
    is held to a row, so a key whose line is not found fails the run."""

    ref: str
    prefix: str
    keys: tuple[str, ...]


Spec = Line | Cases | Enum | OplMap | LowHalf | Joined | FromRows | Mask | DeviceTypes | Listed
PIT = "mame:src/devices/machine/pit8253.cpp"
PIC = "mame:src/devices/machine/pic8259.cpp"
Z80L = "mame:src/devices/cpu/z80/z80.lst"
Z80C = "mame:src/devices/cpu/z80/z80.cpp"
SAAM = "mame:src/devices/sound/saa1099.cpp"
SAAD = "dosbox-x:src/hardware/mame/saa1099.cpp"
SAA = "saa1099_device::data_w"
SNM = "mame:src/devices/sound/sn76496.cpp"
SND = "dosbox-x:src/hardware/mame/sn76496.cpp"
SNW = "sn76496_base_device::write"
OPLH = "mame:3rdparty/ymfm/src/ymfm_opl.h"
YMFOPL = "mame:3rdparty/ymfm/src/ymfm_opl.cpp"
DBOPL = "dosbox-x:src/hardware/dbopl.cpp"
ADLIB = "dosbox-x:src/hardware/adlib.cpp"
M68 = "mame:src/devices/video/mc6845.cpp"
VO = "dosbox-x:src/hardware/vga_other.cpp"
CRTW = "write_crtc_data_other"
CRTR = "read_crtc_data_other"
MC = "mame:src/devices/machine/mc146818.cpp"
MCH = "mame:src/devices/machine/mc146818.h"
CMOS = "dosbox-x:src/hardware/cmos.cpp"
CMOSL = "rbil61:CMOS.LST"
INS = "mame:src/devices/machine/ins8250.cpp"
SER = "dosbox-x:src/hardware/serialport/serialport.cpp"
PORTSB = "rbil61:PORTS.B"
AM = "mame:src/devices/machine/am9517a.cpp"
DDMA = "dosbox-x:src/hardware/dma.cpp"
WR = "DmaController::WriteControllerReg"
RD = "DmaController::ReadControllerReg"
DPIC = "dosbox-x:src/hardware/pic.cpp"
TIMER = "dosbox-x:src/hardware/timer.cpp"


def build(lib: Library, specs: Sequence[Spec]) -> Index:
    index = Index()
    for spec in specs:
        if isinstance(spec, Line):
            scheme, text = one_line(lib, spec)
            index.row(spec.ref, text, spec.key, spec.marks)
        elif isinstance(spec, Cases):
            _cases(lib, spec, index)
        elif isinstance(spec, Enum):
            _enum_rows(lib, spec, index)
        elif isinstance(spec, OplMap):
            _opl_map(lib, spec, index)
        elif isinstance(spec, LowHalf):
            _low_half(lib, spec, index)
        elif isinstance(spec, FromRows):
            keys = sorted({index.rows[row]["key"] for row in spec.rows}, key=lambda k: int(k, 16))
            index.put(spec.ref, keys)
        elif isinstance(spec, Joined):
            index.put(spec.ref, [k for part in spec.parts for k in index.lists[part]])
        elif isinstance(spec, Mask):
            _mask(lib, spec, index)
        elif isinstance(spec, DeviceTypes):
            _device_types(lib, spec, index)
        else:
            _listed(spec, index)
    if not index.rows or not index.lists:
        raise Invalid("the rules produced no row or no list: the index would examine nothing")
    return index


def _depths(lines: list[str], lo: int, hi: int) -> list[int]:
    """The brace depth at the start of each line of `lines[lo:hi]`, comments and strings aside."""
    depth, out = 0, []
    for text in lines[lo:hi]:
        out.append(depth)
        code = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|//.*|/\*.*?\*/', "", text)
        depth += code.count("{") - code.count("}")
    return out


def _cases(lib: Library, spec: Cases, index: Index) -> None:
    scheme, locator = sources.split(spec.ref)
    file = locator.split(" ", 1)[0]
    lines = lib.lines(scheme, file)
    lo, hi = region(lines, spec.inside, spec.after, spec.until)
    enum_lines = lib.lines(scheme, spec.enum_file) if spec.enum_file else lines
    symbols = dict(spec.symbols) | (_enum(enum_lines, spec.enum_after) if spec.enum_after else {})
    depths = _depths(lines, lo, hi)
    found = [
        (i, m.group(1))
        for i in range(lo, hi)
        if (m := re.match(r"\s*case\s+([^:]+?)\s*:(?!:)", lines[i]))
    ]
    if not found:
        raise Invalid(f"{spec.ref}: no `case` label found")
    if spec.runs:
        _case_runs(lines, lo, hi, spec, index)
        return
    outer = min(depths[i - lo] for i, _ in found)
    keys: list[str] = []
    for i, label in found:
        if depths[i - lo] == outer:
            key = hexed(label, symbols)
            index.row(f"{spec.ref} case {label}", lines[i], key)
            keys.append(key)
    index.put(spec.ref, keys)


def _enum_start(lines: list[str], first: str) -> int:
    """The line after the `{` that opens the enum whose first enumerator is the one line matching
    `first`."""
    found = [i for i, text in enumerate(lines) if re.search(first, text)]
    if len(found) != 1:
        raise Invalid(f"{first!r} matches {len(found)} lines, not the one of an enum")
    opening = next((i for i in range(found[0], max(found[0] - 5, -1), -1) if "{" in lines[i]), None)
    if opening is None:
        raise Invalid(f"no `{{` opens the enum at {first!r}")
    return opening + 1


def _enum_code(text: str) -> str:
    return re.sub(r"//.*|/\*.*?\*/", "", text).strip()


def _enum(lines: list[str], after: str) -> dict[str, int]:
    """The enumerators of the enum whose first enumerator is the line matching `after`: a name is
    its explicit number or name, or one more than the one before."""
    out: dict[str, int] = {}
    last = -1
    for text in lines[_enum_start(lines, after) :]:
        code = _enum_code(text)
        if code.startswith("}"):
            break
        if not code:
            continue
        found = re.fullmatch(r"(\w+)(?:\s*=\s*(\w+))?,?", code)
        if not found:
            raise Invalid(f"an enumerator this tool cannot read: {text!r}")
        name, value = found.groups()
        last = (out[value] if value in out else int(value, 0)) if value else last + 1
        out[name] = last
    if not out:
        raise Invalid(f"the enum at {after!r} holds no enumerator")
    return out


def _enum_rows(lib: Library, spec: Enum, index: Index) -> None:
    scheme, locator = sources.split(spec.ref)
    lines = lib.lines(scheme, locator.split(" ", 1)[0])
    values = _enum(lines, spec.after)
    keys: list[str] = []
    for text in lines[_enum_start(lines, spec.after) :]:
        code = _enum_code(text)
        if code.startswith("}"):
            break
        found = re.match(r"(\w+)", code)
        if found:
            key = hexed(str(values[found.group(1)]))
            index.row(f"{spec.ref} {found.group(1)}", text, key)
            keys.append(key)
    if spec.rest:
        _, size_line = one_line(lib, Line(spec.ref, spec.rest))
        size = re.search(r"return (\d+);", size_line)
        if size is None:
            raise Invalid(f"{spec.ref}: no size in {size_line!r}")
        first = max(values.values()) + 1
        keys.append(f"{hexed(str(first))}..{hexed(str(int(size.group(1)) - 1))}")
    index.put(spec.ref, keys)


_OPL_LINE = re.compile(r"//\s+([0-9A-F]{2,3})(?:-([0-9A-F]{2,3}))?\s+[x-]{8}\s+(.*)")


def _opl_key(low: str, high: str | None, bank: int = 0) -> str:
    lo = hexed(str(int(low, 16) + bank))
    return lo if high is None else f"{lo}..{hexed(str(int(high, 16) + bank))}"


def _opl_map(lib: Library, spec: OplMap, index: Index) -> None:
    scheme, locator = sources.split(spec.ref)
    lines = lib.lines(scheme, locator.split(" ", 1)[0])
    start = next(
        (i for i, text in enumerate(lines) if "OPL/OPL2/OPL3/OPL4 register map" in text), None
    )
    if start is None:
        raise Invalid(f"{spec.ref}: the register map comment was not found")
    opl2: list[str] = []
    opl3: list[str] = []
    banks: list[str] = []
    second = False
    for text in lines[start + 1 :]:
        if not text.startswith("//"):
            break
        if re.match(r"//\s+(System-wide|Per-channel|Per-operator) registers", text):
            second = False
        if "apply to address+100" in text:
            second = True
        found = _OPL_LINE.match(text)
        if not found:
            continue
        low, high, what = found.groups()
        name = low if high is None else f"{low}-{high}"
        key = _opl_key(low, high)
        index.row(f"{spec.ref} {name}", text, key)
        opl3.append(key)
        if "[OPL3 only]" not in what:
            opl2.append(key)
        if second:
            index.row(f"{spec.ref} {name} +100", text, _opl_key(low, high, 0x100))
            banks.append(_opl_key(low, high, 0x100))
    if not opl2 or not banks:
        raise Invalid(f"{spec.ref}: the register map held no register or no second bank")
    index.put(spec.opl2, opl2)
    index.put(spec.opl3, opl3 + banks)


def _low_half(lib: Library, spec: LowHalf, index: Index) -> None:
    scheme, text = one_line(lib, Line(spec.ref, spec.find, spec.inside))
    bit = re.search(r"!BIT\(\w+, (\d+)\)", text)
    if bit is None:
        raise Invalid(f"{spec.ref}: no `!BIT(offset, n)` test in {text!r}")
    index.row(spec.ref, text)
    index.put(spec.ref, [hexed(str(n)) for n in range(1 << int(bit.group(1)))])


def _case_runs(lines: list[str], lo: int, hi: int, spec: Cases, index: Index) -> None:
    """Labels stacked on lines that hold nothing else share one body, and a run of consecutive
    numbers in such a body is one key, `A..B`: a row per key, on the line of the run's first
    label. Only the outermost switch's labels count."""
    symbols = dict(spec.symbols)
    depths = _depths(lines, lo, hi)
    found: list[tuple[str, int, int, int]] = []
    group, stacked = 0, False
    for i in range(lo, hi):
        labels = re.findall(r"case\s+([^:]+?)\s*:(?!:)", lines[i])
        only = bool(labels) and not re.sub(r"case\s+[^:]+?\s*:|\s+|/\*.*?\*/|//.*", "", lines[i])
        if labels and not only:
            raise Invalid(f"{spec.ref}: a case label shares its line with code: {lines[i]!r}")
        if only and not stacked:
            group += 1
        found += [(label, i, depths[i - lo], group) for label in labels]
        stacked = only
    if not found:
        raise Invalid(f"{spec.ref}: no `case` label found")
    outer = min(depth for _, _, depth, _ in found)
    keys: list[str] = []
    for number in sorted({g for _, _, depth, g in found if depth == outer}):
        members = sorted(
            (
                (hexed_value(label, symbols), label, i)
                for label, i, depth, g in found
                if g == number and depth == outer
            )
        )
        runs: list[list[tuple[int, str, int]]] = []
        for member in members:
            if runs and member[0] == runs[-1][-1][0] + 1:
                runs[-1].append(member)
            else:
                runs.append([member])
        for run in runs:
            first, last = run[0], run[-1]
            key = (
                hexed(str(first[0]))
                if len(run) == 1
                else (f"{hexed(str(first[0]))}..{hexed(str(last[0]))}")
            )
            index.row(f"{spec.ref} case {first[1]}", lines[first[2]], key)
            keys.append(key)
    index.put(spec.ref, keys)


def hexed_value(label: str, symbols: dict[str, int]) -> int:
    try:
        return int(label.strip(), 0)
    except ValueError:
        if label.strip() not in symbols:
            raise Invalid(f"case label {label!r} is no number and no known name") from None
        return symbols[label.strip()]


def _mask(lib: Library, spec: Mask, index: Index) -> None:
    scheme, text = one_line(lib, Line(spec.ref, spec.find, spec.inside))
    number = re.search(r"(0x[0-9a-fA-F]+|\d+)", text.split("&=", 1)[1])
    if number is None:
        raise Invalid(f"{spec.ref}: no mask number in {text!r}")
    top = int(number.group(1), 0)
    index.row(spec.ref, text)
    index.put(spec.ref, [hexed(str(n)) for n in range(top + 1)])


def _device_types(lib: Library, spec: DeviceTypes, index: Index) -> None:
    scheme, locator = sources.split(spec.ref)
    names: list[str] = []
    for text in lib.lines(scheme, locator.split(" ", 1)[0]):
        found = re.match(r'\s*DEFINE_DEVICE_TYPE(?:_NS)?\(\s*\w+,\s*[\w:]+,\s*"([^"]+)"', text)
        if found:
            index.row(f"{spec.ref} {found.group(1)}", text)
            names.append(found.group(1))
    if not names:
        raise Invalid(f"{spec.ref}: no DEFINE_DEVICE_TYPE line")
    index.put(spec.ref, names)


def _listed(spec: Listed, index: Index) -> None:
    held = [k for k in spec.keys if f"{spec.prefix} {k}" in index.rows]
    if held != list(spec.keys):
        missing = sorted(set(spec.keys) - set(held))
        raise Invalid(f"{spec.ref}: no row for {', '.join(missing)}")
    index.put(spec.ref, list(spec.keys))


def document(index: Index) -> str:
    """The index as the committed file is written."""
    for ref in index.rows:
        sources.split(ref)
    doc = {
        "format": sources.INDEX_FORMAT,
        "pins": dict(PINS),
        "rows": dict(sorted(index.rows.items())),
        "lists": dict(sorted(index.lists.items())),
    }
    sources.parse_index(json.dumps(doc), "the index just built")
    return dumps(doc)


def rules() -> list[Spec]:
    """Every row and every list the shared dictionaries cite, one rule each, grouped by chip."""
    specs: list[Spec] = [
        # pit8253
        Mask(f"{PIT} pit8253_device::write mask", r"offset &= ", "pit8253_device::write"),
        Line(f"{PIT} pit8253_device::write count_w", r"count_w\(data\)", "pit8253_device::write"),
        Line(
            f"{PIT} pit8253_device::write control_w", r"control_w\(data\)", "pit8253_device::write"
        ),
        Line(
            f"{TIMER} TIMER_OnPowerOn write 0x40",
            r"Install\(0x40,write_latch,IO_MB\)",
            "TIMER_OnPowerOn",
        ),
        Line(
            f"{TIMER} TIMER_OnPowerOn write 0x41",
            r"Install\(0x41,write_latch,IO_MB\)",
            "TIMER_OnPowerOn",
        ),
        Line(
            f"{TIMER} TIMER_OnPowerOn write 0x42",
            r"Install\(0x42,write_latch,IO_MB\)",
            "TIMER_OnPowerOn",
        ),
        Line(
            f"{TIMER} TIMER_OnPowerOn write 0x43",
            r"Install\(0x43,write_p43,IO_MB\)",
            "TIMER_OnPowerOn",
        ),
        DeviceTypes(f"{PIT} DEFINE_DEVICE_TYPE"),
        # pic8259
        Cases(f"{PIC} pic8259_device::write", "pic8259_device::write"),
        Cases(f"{PIC} pic8259_device::read", "pic8259_device::read"),
        DeviceTypes(f"{PIC} DEFINE_DEVICE_TYPE"),
        Line(f"{PIC} pic8259_device::write OCW1", r"m_imr = data;", "pic8259_device::write"),
        Line(f"{PIC} pic8259_device::read ISR", r"data = m_isr & ~m_imr;", "pic8259_device::read"),
        Line(f"{DPIC} write_command ICW1", r"val&0x10", "write_command"),
        Line(f"{DPIC} write_command OCW3", r"val&0x08\)\) \{", "write_command"),
        Line(f"{DPIC} write_command specific EOI", r"// specific EOI", "write_command"),
        Line(f"{DPIC} write_command nonspecific EOI", r"// nonspecific EOI", "write_command"),
        Line(
            f"{DPIC} write_command rotate in auto EOI mode",
            r"// rotate in auto EOI mode",
            "write_command",
        ),
        Line(
            f"{DPIC} write_command set priority",
            r"set priority command not handled",
            "write_command",
        ),
        Line(f"{DPIC} write_command rotate mode", r"rotate mode not supported", "write_command"),
        Line(f"{DPIC} write_command no operation", r"// else NOP command", "write_command"),
        Line(f"{DPIC} read_command status", r"if \(pic->request_issr\)", "read_command"),
        Line(f"{DPIC} read_data mask", r"return pic->imr;", "read_data"),
        Line(f"{DPIC} write_data mask register", r"/\* mask register \*/", "write_data"),
    ]
    specs += [
        # am9517a
        LowHalf(f"{AM} am9517a_device::write low", r"BIT\(offset, 3\)", "am9517a_device::write"),
        Cases(
            f"{AM} am9517a_device::write high",
            "am9517a_device::write",
            after=r"switch \(offset & 0x0f\)",
            enum_after=r"REGISTER_ADDRESS = 0",
        ),
        Cases(
            f"{AM} am9517a_device::read high",
            "am9517a_device::read",
            after=r"switch \(offset & 0x0f\)",
            enum_after=r"REGISTER_ADDRESS = 0",
        ),
        Joined(
            f"{AM} am9517a_device::write",
            (f"{AM} am9517a_device::write low", f"{AM} am9517a_device::write high"),
        ),
        Line(
            f"{AM} am9517a_device::write channel address",
            r"case REGISTER_ADDRESS:",
            "am9517a_device::write",
        ),
        Line(
            f"{AM} am9517a_device::write channel count",
            r"case REGISTER_WORD_COUNT:",
            "am9517a_device::write",
        ),
        Line(
            f"{AM} am9517a_device::read channel address",
            r"case REGISTER_ADDRESS:",
            "am9517a_device::read",
        ),
        Line(
            f"{AM} am9517a_device::read channel count",
            r"case REGISTER_WORD_COUNT:",
            "am9517a_device::read",
        ),
        DeviceTypes(f"{AM} DEFINE_DEVICE_TYPE"),
        Line(f"{DDMA} {WR} channel address", r"case 0x0:case 0x2:case 0x4:case 0x6:", WR),
        Line(f"{DDMA} {WR} channel count", r"case 0x1:case 0x3:case 0x5:case 0x7:", WR),
    ]
    specs.append(Line(f"{DDMA} {RD} undefined port", r"Trying to read undefined DMA port", RD))
    for _n in range(8, 16):
        specs.append(
            Line(f"{DDMA} {WR} case 0x{_n:x}", rf"^\s*case 0x{_n:x}:", WR, key=f"0x{_n:02X}")
        )
    for _n in (8, 15):
        specs.append(
            Line(f"{DDMA} {RD} case 0x{_n:x}", rf"^\s*case 0x{_n:x}:", RD, key=f"0x{_n:02X}")
        )
    specs += [
        # ins8250
        Cases(f"{INS} ins8250_uart_device::ins8250_w", "ins8250_uart_device::ins8250_w"),
        Cases(f"{INS} ins8250_uart_device::ins8250_r", "ins8250_uart_device::ins8250_r"),
        DeviceTypes(f"{INS} DEFINE_DEVICE_TYPE"),
        Line(f"{PORTSB} 03F8-03FF serial port", r"^PORT 03F8-03FF - Serial port"),
        Line(f"{PORTSB} 03F8 receiver buffer", r"^03F8  R-  receiver buffer register \(RBR\)"),
        Line(f"{PORTSB} 03F9 interrupt enable", r"^03F9  RW  interrupt enable register \(IER\)"),
        Line(f"{PORTSB} 03FA interrupt identification", r"^03FA  R-  interrupt identification"),
        Line(f"{PORTSB} 03FB line control", r"^03FB  RW  line control register"),
        Line(f"{PORTSB} 03FC modem control", r"^03FC  RW  modem control register"),
        Line(f"{PORTSB} 03FD line status", r"^03FD  R-  line status register"),
        Line(f"{PORTSB} 03FE modem status", r"^03FE  R-  modem status register"),
        Line(f"{PORTSB} 03FF scratch", r"^03FF  RW  scratch register"),
    ]
    for _o in ("THR", "IER", "FCR", "LCR", "MCR", "MSR", "SPR"):
        specs.append(
            Line(f"{SER} SERIAL_Write case {_o}", rf"^\s*case {_o}_OFFSET:", "SERIAL_Write")
        )
    specs.append(Line(f"{SER} SERIAL_Write reserved", r"^\s*default:", "SERIAL_Write"))
    specs += [
        # mc146818
        Enum(f"{MCH} REG", r"REG_SECONDS = 0", r"virtual int data_size\(\) const \{"),
        Cases(
            f"{MC} mc146818_device::internal_read",
            "mc146818_device::internal_read",
            enum_after=r"REG_SECONDS = 0",
            enum_file="src/devices/machine/mc146818.h",
        ),
        Cases(
            f"{MC} mc146818_device::internal_write",
            "mc146818_device::internal_write",
            enum_after=r"REG_SECONDS = 0",
            enum_file="src/devices/machine/mc146818.h",
        ),
        DeviceTypes(f"{MC} DEFINE_DEVICE_TYPE"),
        Line(f"{MCH} data size", r"virtual int data_size\(\) const \{"),
        Line(
            f"{CMOSL} CMOS 00h-0Dh clock functions",
            r"^The first fourteen bytes are dedicated to the MC146818 chip clock functions",
        ),
        Line(f"{CMOS} cmos_writereg default", r"^\s*default:", "cmos_writereg"),
    ]
    for _n, _what in (
        (0, "SECONDS"),
        (1, "SECOND ALARM"),
        (2, "MINUTES"),
        (3, "MINUTE ALARM"),
        (4, "HOURS"),
        (5, "HOUR ALARM"),
        (6, "DAY OF WEEK"),
        (7, "DATE OF MONTH"),
        (8, "MONTH"),
        (9, "YEAR"),
    ):
        specs.append(Line(f"{CMOSL} CMOS {_n:02X}h {_what}", rf"^CMOS {_n:02X}h - RTC - {_what}$"))
    for _n, _what in ((0xA, "A"), (0xB, "B"), (0xC, "C"), (0xD, "D")):
        specs.append(
            Line(
                f"{CMOSL} CMOS {_n:02X}h STATUS REGISTER {_what}",
                rf"^CMOS {_n:02X}h - RTC - STATUS REGISTER {_what}",
            )
        )
    for _n in range(0xE):
        specs.append(
            Line(
                f"{CMOS} cmos_writereg case 0x{_n:02x}",
                rf"^\s*case 0x{_n:02x}:",
                "cmos_writereg",
                key=f"0x{_n:02X}",
            )
        )
    specs += [
        Line(
            f"{CMOS} cmos_readreg case 0x{_n:02x}",
            rf"^\s*case 0x{_n:02x}:",
            "cmos_readreg",
            key=f"0x{_n:02X}",
        )
        for _n in (0x0A, 0x0C)
    ]
    specs += [
        # mc6845
        Cases(f"{M68} mc6845_device::register_w", "mc6845_device::register_w"),
        Cases(f"{M68} mc6845_device::register_r", "mc6845_device::register_r"),
        DeviceTypes(f"{M68} DEFINE_DEVICE_TYPE"),
        Line(f"{PORTSB} 03B0-03BF MDA", r"^PORT 03B0-03BF - MDA"),
        Line(f"{VO} {CRTW} illegal index", r"MC6845:Write %X to illegal index", CRTW),
    ]
    for _n, _name in (
        (0x00, "horizontal total"),
        (0x01, "horizontal displayed"),
        (0x02, "horizontal sync position"),
        (0x03, "sync pulse width"),
        (0x04, "vertical total"),
        (0x05, "vertical total adjust"),
        (0x06, "vertical displayed"),
        (0x08, "interlace mode"),
        (0x09, "maximum scan lines"),
        (0x0A, "cursor start"),
        (0x0B, "cursor end"),
        (0x0C, "start address high"),
        (0x0D, "start address low"),
        (0x0E, "cursor location high"),
        (0x0F, "cursor location low"),
        (0x10, "light pen high"),
        (0x11, "light pen low"),
    ):
        specs.append(
            Line(
                f"{PORTSB} CRT register {_n:02X}h {_name}",
                rf"^ {_n:02X}h(?: [R-][W-])?\s+{_name}",
                after=r"^Values for mono video adapter CRT",
                until=r"^SeeAlso: #P0708,#P0710,#P0655",
            )
        )
        if _n != 0x08:
            specs.append(
                Line(
                    f"{VO} {CRTW} case 0x{_n:02x}",
                    rf"(?i)^\s*case 0x{_n:02x}:",
                    CRTW,
                    key=f"0x{_n:02X}",
                )
            )
    specs.append(Line(f"{VO} {CRTW} case 0x07", r"(?i)^\s*case 0x07:", CRTW, key="0x07"))
    specs += [
        # ym3812 and ymf262
        OplMap(
            f"{OPLH} opl_registers_base",
            f"{OPLH} opl_registers_base ym3812",
            f"{OPLH} opl_registers_base ymf262",
        ),
        Line(
            f"{OPLH} opl_registers_base op_waveform",
            r"op_waveform\(uint32_t opoffs\) const +\{ return waveform_enable\(\)",
        ),
        Line(
            f"{OPLH} opl_registers_base ch_feedback",
            r"ch_feedback\(uint32_t choffs\) const +\{ return byte\(0xc0",
        ),
        Line(
            f"{OPLH} opl_registers_base waveform_enable",
            r"waveform_enable\(\) const +\{ return IsOpl2",
        ),
        DeviceTypes("mame:src/devices/sound/ymopl.cpp DEFINE_DEVICE_TYPE"),
        Line(f"{DBOPL} Chip::WriteReg reg 0x01", r"reg == 0x01\b", "Chip::WriteReg"),
        Line(f"{DBOPL} Chip::WriteReg reg 0x08", r"reg == 0x08\b", "Chip::WriteReg"),
        Line(f"{DBOPL} Chip::WriteReg reg 0x104", r"reg == 0x104\b", "Chip::WriteReg"),
        Line(f"{DBOPL} Chip::WriteReg reg 0x105", r"reg == 0x105\b", "Chip::WriteReg"),
        Line(f"{DBOPL} Chip::WriteReg reg 0xbd", r"reg == 0xbd\b", "Chip::WriteReg"),
        Line(
            f"{DBOPL} Chip::WriteAddr opl3Active",
            r"opl3Active \|\| \(val == 0x05u\)",
            "Chip::WriteAddr",
        ),
        Line(
            f"{YMFOPL} ymf262::write_address_hi newflag",
            r"newflag\(\) == 0 && m_address != 0x105",
            "ymf262::write_address_hi",
        ),
        Line(
            f"{YMFOPL} ymf262::write_address_hi address",
            r"^\s*m_address = data \| 0x100;",
            "ymf262::write_address_hi",
        ),
    ]
    for _n in (0x20, 0x40, 0x60, 0x80, 0xA0, 0xB0, 0xC0, 0xE0):
        specs.append(
            Line(
                f"{DBOPL} Chip::WriteReg case 0x{_n:02x}",
                rf"^\s*case 0x{_n:02x} >> 4:",
                "Chip::WriteReg",
            )
        )
    for _n in (2, 3, 4):
        specs.append(
            Line(f"{ADLIB} Chip::Write case 0x{_n:02x}", rf"^\s*case 0x{_n:02x}:", "Chip::Write")
        )
    for _label, _regex in (
        ("01h", r"^ 01h\tEnable waveform control"),
        ("02h", r"^ 02h\tTimer #1 data"),
        ("03h", r"^ 03h\tTimer #2 data"),
        ("04h", r"^ 04h\tTimer control flags"),
        ("04h OPL3", r"^ 04h\t\(OPL3 in OPL3 mode only\) connection select"),
        ("05h", r"^ 05h\t\(OPL3\) compatibility register"),
        ("08h", r"^ 08h\tSpeech synthesis mode"),
        ("20h-35h", r"^ 20h-35h "),
        ("40h-55h", r"^ 40h-55h "),
        ("60h-75h", r"^ 60h-75h "),
        ("80h-95h", r"^ 80h-95h "),
        ("A0h-A8h", r"^ A0h-A8h "),
        ("B0h-B8h", r"^ B0h-B8h "),
        ("BDh", r"^ BDh\tpercussion"),
        ("C0h-C8h", r"^ C0h-C8h "),
        ("E0h-F5h", r"^ E0h-F5h "),
    ):
        specs.append(
            Line(
                f"{PORTSB} AdLib index {_label}",
                _regex,
                after=r"^Values for AdLib address port index",
                until=r"^SeeAlso: #P0646",
            )
        )
    specs += [
        # sn76496
        Cases(f"{SNM} {SNW}", SNW),
        Cases(f"{SND} {SNW}", f"void {SNW}"),
        DeviceTypes(f"{SNM} DEFINE_DEVICE_TYPE"),
    ]
    specs += [
        # saa1099
        Cases(f"{SAAM} {SAA}", SAA, runs=True),
        Cases(f"{SAAD} {SAA}", SAA, runs=True),
        DeviceTypes(f"{SAAM} DEFINE_DEVICE_TYPE"),
        Line(f"{PORTSB} 0210-0211 Game Blaster", r"^PORT 0210-0211 - Game Blaster"),
    ]
    specs += [
        # z80
        Line(f"{Z80L} NMI", r"^\tPC = 0x0066;$", which=0, key="0x66"),
        Line(f"{Z80L} interrupt mode 1", r"^\t\tPC = 0x0038;$", key="0x38"),
        Line(
            f"{Z80C} z80_device::device_reset PC",
            r"^\tPC = 0;$",
            "z80_device::device_reset",
            key="0x00",
        ),
    ]
    specs += [
        Line(f"{Z80L} @rst 0x{_n:02x}", rf"^\t@rst 0x{_n:02x}$", key=f"0x{_n:02X}")
        for _n in range(0, 0x40, 8)
    ]
    specs.append(
        FromRows(
            f"{Z80L} vectors",
            (
                f"{Z80L} NMI",
                f"{Z80L} interrupt mode 1",
                f"{Z80C} z80_device::device_reset PC",
                *(f"{Z80L} @rst 0x{_n:02x}" for _n in range(0, 0x40, 8)),
            ),
        )
    )
    for _word, _what in (
        ("0x00", "0x00..0x07"),
        ("0x20", "0x20..0x27"),
        ("0x40", "0x40..0x47"),
        ("0x60", "0x60..0x67"),
        ("0x80", "0x80..0x87"),
        ("0xa0", "0xA0..0xA7"),
        ("0xc0", "0xC0..0xC7"),
        ("0xe0", "0xE0..0xE7"),
    ):
        specs.append(
            Line(
                f"{PIC} pic8259_device::write command {_what}",
                rf"^\s*case {_word}:$",
                "pic8259_device::write",
                after=r"switch \(data & 0xe0\)",
            )
        )
    # Bytes with bit 4 set are ICW1 whatever bits 7 to 5 hold; bytes with bit 7 and bit 4 clear
    # and bit 3 set are OCW3 whatever bits 6 and 5 hold (pic8259.cpp, `data & 0x10`, `data & 0x98`).
    icw1 = [f"0x{n:02X}..0x{n + 0xF:02X}" for n in range(0x10, 0x100, 0x20)]
    ocw3 = [f"0x{n:02X}..0x{n + 0x7:02X}" for n in range(0x08, 0x80, 0x20)]
    for _key in icw1:
        specs.append(
            Line(
                f"{PIC} pic8259_device::write command {_key}",
                r"^\s*if \(data & 0x10\)$",
                "pic8259_device::write",
            )
        )
    for _key in ocw3:
        specs.append(
            Line(
                f"{PIC} pic8259_device::write command {_key}",
                r"\(data & 0x98\) == 0x08",
                "pic8259_device::write",
            )
        )
    specs.append(
        Listed(
            f"{PIC} pic8259_device::write command words",
            f"{PIC} pic8259_device::write command",
            (
                "0x00..0x07",
                *ocw3,
                *icw1,
                "0x20..0x27",
                "0x40..0x47",
                "0x60..0x67",
                "0x80..0x87",
                "0xA0..0xA7",
                "0xC0..0xC7",
                "0xE0..0xE7",
            ),
        )
    )
    return specs


def main(argv: Sequence[str] | None = None) -> int:
    ask = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        epilog="Exit 0 written or equal, 1 differs under --check, 3 a source or a rule failed.",
    )
    ask.add_argument(
        "--mame", type=Path, required=True, help="tree of MAME files at the pinned tag"
    )
    ask.add_argument("--dosbox", type=Path, required=True, help="DOSBox-X checkout with the pin")
    ask.add_argument("--rbil", type=Path, required=True, help="directory of the RBIL archives")
    ask.add_argument(
        "--index", type=Path, default=DEFAULT_INDEX, help="the index to write or check"
    )
    ask.add_argument("--check", action="store_true", help="compare the index, write nothing")
    got = ask.parse_args(argv)
    try:
        text = document(build(Library(got.mame, got.dosbox, got.rbil), rules()))
    except (Invalid, KeyFault, ValueError, OSError, KeyError, re.error) as bad:
        print(f"INVALID: {bad}", file=sys.stderr)
        return 3
    if got.check:
        have = got.index.read_text(encoding="utf-8") if got.index.is_file() else ""
        if have != text:
            print(f"{got.index} differs from what the sources give", file=sys.stderr)
            return 1
        print(f"{got.index} equals the sources")
        return 0
    got.index.parent.mkdir(parents=True, exist_ok=True)
    got.index.write_text(text, encoding="utf-8")
    print(f"wrote {got.index}: {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
