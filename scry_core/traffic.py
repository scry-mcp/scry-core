"""`traffic` -- what a server's replies and its tool list cost the model, per tool, in one unit.

Run as `python -m scry_core.traffic <server> --servers <file> [--transcript <jsonl> ...]
[--before <table>]`, where <server> is a server the servers file loads (the probe's servers file:
`scry_core.probe` says what it holds).

THE UNIT is the client's: UTF-16 code units (`client_cap.utf16_units`) of ONE copy of a reply in
compact JSON, non-ASCII as itself (the wire's indented twin is transport, not context). It is a
proxy for tokens, never a token count, and it follows Python's serialisation: a whole float prints
`5.0` where JavaScript prints `5`.

THE REPLIES come from live transcripts, JSON Lines with one call per line read for `tool` and
`reply`; other keys are ignored. A line counts as a reply only when its `reply` is an envelope (an
object carrying `status`): a harness's own records (an exception it caught, a call that hung, a
pseudo-tool in parentheses) never reached a client and are counted as `skipped`; a call under a
name the server does not list (a harness's own helper) is counted under `foreign`, outside every
figure. INVALID: no reply at all, which is a run that examined nothing; and no call the server
lists, which is a transcript of another server.

THE TOOL LIST is the server's `list_tools()`, uncapped: per tool its description and its
definition (name, description and input schema, compact JSON, which is what a model is handed),
and the server's `instructions` and the sum of its tool names.

PICTURES are a second column, never summed with the units: a reply's `image_tokens` is the sum,
over the `image` blocks a client is handed attached, of the API's visual tokens for the picture as
attached (`picture.tiles`): a step's picture inside a sequence is never attached, whatever a body
recorded before the MCP boundary says. A block that says `inline: true` without a whole width
and height of at least one pixel is INVALID rather than free, under any tool name, a foreign one
included.

A TOOL IS FLAGGED FOR REVIEW when its largest reply is over `REVIEW_MAX_UNITS` (`max`), or when
it is among the fewest tools whose replies make `REVIEW_SHARE` of all reply units (`share`).
A listed tool no transcript called is `unmeasured`.

OUTPUT. The full table, as JSON (`"format": "scry-traffic/1"`), goes to a new file under the
servers file's `ROOT/tmp/traffic/`. Stdout, in this order: one line per flagged tool,

    REVIEW <server> <tool> [why] calls=N max=N p50=N total=N share=P% image_tokens=N description=N

(`why` is `max`, `share` or both, `p50` the lower median, `description` its units), one
`TOTAL <server> ...` line with the replies' figures (`foreign=N` names the unlisted tools it set
apart) and the list's, and last `TABLE <path>`. With `--before`, an earlier table of the same
server, each REVIEW `max`, the replies' `units`, every `image_tokens` and each list figure carry
` (was N)`, or ` (was -)` where that table had none; a table written before `foreign` or
`image_tokens` existed is a valid one.

Exit 0 with a table, 2 for a wrong call, 3 INVALID: a transcript or a `--before` that is missing,
does not parse or does not fit, a server that lists no tools, a table that could not be written,
a servers file the probe would refuse, or anything unforeseen.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import statistics
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scry_core.client_cap import CLIENT_TEXT_CAP, utf16_units
from scry_core.judges import whole
from scry_core.picture import tiles, unattached_below
from scry_core.probe import EXIT_INVALID, Invalid, broke, configure

EXIT_TABLE = 0
TABLE_FORMAT = "scry-traffic/1"
#: What a caller reading the output matches, never its own spelling of them.
LINE_REVIEW, LINE_TOTAL, LINE_TABLE = "REVIEW ", "TOTAL ", "TABLE "
#: A reply over the most a description may hold is flagged: a description is cut there because
#: the client will not carry more for one tool, and a reply that size is paid on every call.
REVIEW_MAX_UNITS = CLIENT_TEXT_CAP
#: The Pareto cut: the fewest tools that carry this share of every reply unit measured.
REVIEW_SHARE = 0.80
#: Where tables go, under the servers file's `ROOT`; no option moves it, as with the probe's runs.
TABLES_UNDER_ROOT = Path("tmp") / "traffic"
#: The table's shape, checked on a `--before` so a drifted table is refused, not read as "-".
TABLE_KEYS = {"replies": ("calls", "units", "skipped", "unmeasured"),
              "list": ("instructions", "names", "descriptions", "definitions", "tools")}


def json_units(value: Any) -> int:
    """`value`'s size as compact JSON, non-ASCII as itself, in the client's unit."""
    return utf16_units(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def image_tokens(value: Any) -> int:
    """The visual tokens of every picture `value` attaches as a client receives it: a reply
    recorded before the MCP boundary still says `inline: true` on a step's picture inside
    `perform` or `drive`, which the boundary never attaches (`unattached_below`)."""
    return _tokens(unattached_below(value))


def _tokens(value: Any) -> int:
    if isinstance(value, list):
        return sum(_tokens(v) for v in value)
    if not isinstance(value, dict):
        return 0
    total = 0
    for key, v in value.items():
        if key == "image" and isinstance(v, dict) and v.get("inline") is True:
            w, h = v.get("width"), v.get("height")
            if not (whole(w, 1) and whole(h, 1)):
                raise Invalid(f"an attached picture states width={w!r} height={h!r}, so its "
                              "cost cannot be counted")
            total += tiles(w, h)
        else:
            total += _tokens(v)
    return total


@dataclass(frozen=True)
class Calls:
    """Every reply's units and image tokens by tool, and how many non-blank transcript lines
    were not replies."""

    units: dict[str, list[int]]
    image_tokens: dict[str, list[int]]
    skipped: int


def _read(path: Path, flag: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Invalid(f"{flag} {path}: {e}") from None


def read_transcripts(paths: Iterable[Path]) -> Calls:
    units: dict[str, list[int]] = {}
    tokens: dict[str, list[int]] = {}
    skipped = 0
    for path in paths:
        # JSON Lines ends a record at "\n" alone: `splitlines` would also cut at a U+2028 a
        # JSON string may hold raw.
        for n, line in enumerate(_read(path, "--transcript").split("\n"), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise Invalid(f"{path}:{n} is not JSON: {e}") from None
            tool, reply = (rec.get("tool"), rec.get("reply")) if isinstance(rec, dict) else (
                None, None)
            if not isinstance(tool, str) or tool.startswith("(") or not (
                    isinstance(reply, dict) and "status" in reply):
                skipped += 1
                continue
            units.setdefault(tool, []).append(json_units(reply))
            try:
                tokens.setdefault(tool, []).append(image_tokens(reply))
            except Invalid as e:
                raise Invalid(f"{path}:{n}: {e}") from None
    if not units:
        raise Invalid("the transcripts hold no reply, so there is nothing to measure "
                      f"({skipped} line(s) skipped)")
    return Calls(units, tokens, skipped)


def for_review(totals: dict[str, int], maxima: dict[str, int]) -> dict[str, list[str]]:
    """Each flagged tool and why: `max` (one reply over the ceiling), `share` (in the Pareto
    set). Ties at the cut are broken by name, so the set is the same on every run."""
    why: dict[str, list[str]] = {}
    grand = sum(totals.values())
    running = 0
    for tool in sorted(totals, key=lambda t: (-totals[t], t)):
        if running >= REVIEW_SHARE * grand:
            break
        running += totals[tool]
        why.setdefault(tool, []).append("share")
    for tool, peak in maxima.items():
        if peak > REVIEW_MAX_UNITS:
            why.setdefault(tool, []).insert(0, "max")
    return why


def tool_list(module: Any) -> dict[str, Any]:
    tools = list(asyncio.run(module.mcp.list_tools()))
    if not tools:
        raise Invalid("the server lists no tools, so there is nothing to measure")
    per_tool = {
        t.name: {"description": utf16_units(t.description or ""),
                 "definition": json_units({"name": t.name, "description": t.description or "",
                                           "inputSchema": t.input_schema or {}})}
        for t in tools}
    return {"instructions": utf16_units(module.mcp.instructions or ""),
            "names": sum(utf16_units(t.name) for t in tools),
            "descriptions": sum(v["description"] for v in per_tool.values()),
            "definitions": sum(v["definition"] for v in per_tool.values()),
            "tools": per_tool}


def table(server: str, calls: Calls | None, listed: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    replies: dict[str, Any] | None = None
    if calls is not None:
        foreign = {t: len(u) for t, u in calls.units.items() if t not in listed["tools"]}
        units = {t: u for t, u in calls.units.items() if t not in foreign}
        if not units:
            raise Invalid(f"the transcripts call {', '.join(sorted(foreign))}, none of which "
                          f"{server} lists: a transcript of another server")
        totals = {t: sum(u) for t, u in units.items()}
        maxima = {t: max(u) for t, u in units.items()}
        grand = sum(totals.values())
        why = for_review(totals, maxima)
        for tool, sizes in units.items():
            rows[tool] = {"calls": len(sizes), "max": maxima[tool],
                          "p50": int(statistics.median_low(sizes)), "total": totals[tool],
                          "share": round(totals[tool] / grand, 4), "review": why.get(tool, []),
                          "image_tokens": sum(calls.image_tokens[tool])}
        replies = {"calls": sum(len(u) for u in units.values()), "units": grand,
                   "image_tokens": sum(sum(calls.image_tokens[t]) for t in units),
                   "skipped": calls.skipped, "foreign": foreign,
                   "unmeasured": sorted(set(listed["tools"]) - set(units))}
    return {"format": TABLE_FORMAT, "server": server, "replies": replies, "per_tool": rows,
            "list": listed}


def read_before(path: Path, server: str) -> dict[str, Any]:
    try:
        doc = json.loads(_read(path, "--before"))
    except json.JSONDecodeError as e:
        raise Invalid(f"--before {path}: {e}") from None
    if not isinstance(doc, dict) or doc.get("format") != TABLE_FORMAT:
        raise Invalid(f"--before {path} is not a {TABLE_FORMAT} table")
    if doc.get("server") != server:
        raise Invalid(f"--before {path} measured {doc.get('server')!r}, not {server!r}")
    # A list-only table has `replies: null`, which is a shape, not a gap.
    missing = [f"{part}.{k}" for part, keys in TABLE_KEYS.items()
               if part != "replies" or doc.get("replies") is not None
               for k in keys if not isinstance(doc.get(part), dict) or k not in doc[part]]
    if not isinstance(doc.get("per_tool"), dict):
        missing.append("per_tool")
    if missing:
        raise Invalid(f"--before {path} lacks {', '.join(missing)}")
    return doc


def _was(before: dict[str, Any] | None, *keys: str) -> str:
    """` (was N)` for the value at `keys` in the earlier table, ` (was -)` where it had none,
    and nothing without an earlier table."""
    if before is None:
        return ""
    node: Any = before
    for k in keys:
        node = node.get(k) if isinstance(node, dict) else None
    return f" (was {node if node is not None else '-'})"


def report(doc: dict[str, Any], before: dict[str, Any] | None) -> list[str]:
    server, listed, replies = doc["server"], doc["list"], doc["replies"]
    lines = []
    for tool, row in sorted(doc["per_tool"].items(), key=lambda kv: (-kv[1]["total"], kv[0])):
        if row["review"]:
            lines.append(
                f"{LINE_REVIEW}{server} {tool} [{','.join(row['review'])}] calls={row['calls']} "
                f"max={row['max']}{_was(before, 'per_tool', tool, 'max')} p50={row['p50']} "
                f"total={row['total']} share={row['share']:.1%} "
                f"image_tokens={row['image_tokens']}"
                f"{_was(before, 'per_tool', tool, 'image_tokens')} "
                f"description={listed['tools'][tool]['description']}")
    measured = ""
    if replies is not None:
        named = f" ({', '.join(sorted(replies['foreign']))})" if replies["foreign"] else ""
        measured = (f"replies calls={replies['calls']} units={replies['units']}"
                    f"{_was(before, 'replies', 'units')} "
                    f"image_tokens={replies['image_tokens']}"
                    f"{_was(before, 'replies', 'image_tokens')} skipped={replies['skipped']} "
                    f"foreign={sum(replies['foreign'].values())}{named} "
                    f"unmeasured={len(replies['unmeasured'])}; ")
    figures = " ".join(f"{k}={listed[k]}{_was(before, 'list', k)}"
                       for k in ("instructions", "names", "descriptions", "definitions"))
    lines.append(f"{LINE_TOTAL}{server} {measured}list tools={len(listed['tools'])} {figures}")
    return lines


def write_table(doc: dict[str, Any], root: Path, server: str) -> Path:
    """The table, serialised before anything is created so a failure leaves no half file."""
    text = json.dumps(doc, indent=1)
    under = root / TABLES_UNDER_ROOT
    try:
        under.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        fd, name = tempfile.mkstemp(prefix=f"{stamp}-{server}-", suffix=".json", dir=under)
        with open(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as e:
        raise Invalid(f"the table could not be written under {under}: {e}") from None
    return Path(name)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m scry_core.traffic", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument("server", help="a server the servers file loads")
    parser.add_argument("--servers", type=Path, required=True,
                        help="the probe's servers file (`load()` and `ROOT`)")
    parser.add_argument("--transcript", type=Path, action="append", default=[],
                        help="a live transcript (JSON Lines); repeat for several")
    parser.add_argument("--before", type=Path, default=None,
                        help="an earlier table of the same server, to compare against")
    opts = parser.parse_args(argv)
    try:
        # The probe's loader, so the server measured is the one the probe asks about. It wants
        # a tasks directory; traffic reads no task, so the placeholder is never opened.
        repo = configure(opts.servers, Path())
        if opts.server not in repo.servers:
            parser.error(f"argument server: invalid choice: {opts.server!r} (choose from "
                         f"{', '.join(repo.servers)})")
        before = None if opts.before is None else read_before(opts.before, opts.server)
        calls = read_transcripts(opts.transcript) if opts.transcript else None
        doc = table(opts.server, calls, tool_list(repo.modules[opts.server]))
        lines = report(doc, before)
        out = write_table(doc, repo.root, opts.server)
    except Invalid as e:
        print(f"INVALID: {e}")
        return EXIT_INVALID
    except Exception as e:  # noqa: BLE001 -- see `broke`
        print(broke("traffic", e))
        return EXIT_INVALID
    for line in lines:
        print(line)
    print(f"{LINE_TABLE}{out}")
    return EXIT_TABLE


if __name__ == "__main__":  # pragma: no cover -- the entry point; `main` is what is tested
    sys.exit(main(sys.argv[1:]))
