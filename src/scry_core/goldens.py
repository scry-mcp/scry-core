"""Files against `shasum -a 256` goldens, matched by file name. No name in common is
`control_silent`."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scry_core.prose import counted
from scry_core.reply_contract import Invalid

CHECKSUM_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *](.+)")
LINE_QUOTED = 80


def read_checksums(name: str, path: Path) -> dict[str, str]:
    """A `shasum -a 256` file as `{file name: digest}`, keyed by the name's last part."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}") from None
    sums: dict[str, str] = {}
    # not `splitlines`: it would cut a file name at a U+2028
    for n, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if not line.strip():
            continue
        m = CHECKSUM_LINE.fullmatch(line)
        if m is None:
            raise Invalid("bad_argument", f"{name}: {path}:{n} is not `<sha256>  <name>`, the "
                          f"`shasum -a 256` format: {line[:LINE_QUOTED]!r}")
        key = Path(m.group(2)).name
        if key in sums:
            raise Invalid("bad_argument", f"{name}: {path}:{n} names {key} a second time")
        sums[key] = m.group(1).lower()
    if not sums:
        raise Invalid("bad_argument", f"{name}: {path} holds no checksum line")
    return sums


def in_dir(name: str, folder: Path) -> dict[str, Path]:
    """The `*.png` files of `folder`, by name."""
    if not folder.is_dir():
        raise Invalid("bad_argument", f"{name}: {folder} is not a directory")
    return {p.name: p for p in sorted(folder.glob("*.png")) if p.is_file()}


def compare(files: dict[str, Path], sums: dict[str, str]) -> dict[str, Any]:
    """Each file against its golden digest: `matched` (a count), `differing`, `missing` (no file),
    `extra` (no golden)."""
    examined = sorted(files.keys() & sums.keys())
    if not examined:
        raise Invalid("control_silent", f"none of the {counted(len(files), 'file')} has a line "
                      f"in the checksums and none of the {counted(len(sums), 'line')} has a file: "
                      "nothing was compared, which is no verdict")
    differing = []
    for n in examined:
        try:
            digest = hashlib.sha256(files[n].read_bytes()).hexdigest()
        except OSError as e:
            raise Invalid("bad_argument", f"{n}: {files[n]} cannot be read: {e}") from None
        if digest != sums[n]:
            differing.append(n)
    return {"matched": len(examined) - len(differing), "differing": differing,
            "missing": sorted(sums.keys() - files.keys()),
            "extra": sorted(files.keys() - sums.keys())}
