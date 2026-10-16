"""Files against goldens written by `shasum -a 256`: exact bytes, matched by file name, which is
how the client repositories keep theirs. A file and a golden that meet nowhere compare nothing, so
no name in common is `control_silent`, never a pass.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from scry_core.reply_contract import Invalid

#: One line of a `shasum -a 256` file: the digest, a space, then a space (text) or `*` (binary),
#: then the name.
CHECKSUM_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *](.+)")
#: How much of a line that does not parse its refusal quotes.
LINE_QUOTED = 80


def read_checksums(name: str, path: Path) -> dict[str, str]:
    """A `shasum -a 256` file as `{file name: digest}`, keyed by the name's last part, or the
    refusal naming the line that does not parse."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Invalid("bad_argument", f"{name}: {path} cannot be read: {e}") from None
    sums: dict[str, str] = {}
    # A line ends at "\n" alone: `splitlines` would also cut a file name at a U+2028.
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
    """Each file against its golden digest, by name: `matched` (a count), `differing`,
    `missing` (a golden with no file) and `extra` (a file with no golden), names sorted."""
    examined = sorted(files.keys() & sums.keys())
    if not examined:
        raise Invalid("control_silent", f"none of the {len(files)} file(s) has a line in the "
                      f"checksums and none of the {len(sums)} line(s) has a file: nothing was "
                      "compared, which is no verdict")
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
