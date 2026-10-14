"""Scans over the core's own sources: the rules each server's suite also holds its own modules to.

A scan that reads only core sources lives here; one over a server's sources stays in that server.
Each is fired first on a planted case, so an empty finding is a finding and not a scan that read
nothing.
"""

import ast
import collections
import re
from pathlib import Path

import scry_core

SOURCES = sorted(Path(scry_core.__file__).resolve().parent.glob("*.py"))


def _prose_matched_for_a_code(path: Path) -> list[int]:
    """The lines of `path` that test a string literal against `why`, `message` or `str(e)`: the
    shape of a refusal's CODE chosen by reading its own prose."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], ast.In | ast.NotIn)
                and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)):
            continue
        right = node.comparators[0]
        prose = (isinstance(right, ast.Name) and right.id in ("why", "message")) or (
            isinstance(right, ast.Call) and isinstance(right.func, ast.Name)
            and right.func.id == "str" and len(right.args) == 1)
        if prose:
            lines.append(node.lineno)
    return sorted(lines)


def test_no_refusal_code_is_chosen_by_matching_its_own_prose(tmp_path: Path) -> None:
    """A code decided by `"already armed under" in why` changes in silence the day the sentence is
    reworded: the helper that knows why a call is refused answers the code beside the text."""
    planted = tmp_path / "planted.py"
    planted.write_text('code = "ambiguous_ref" if "already" in why else "bad_argument"\n'
                       'if "armed" in str(e):\n    pass\nif "x" in message:\n    pass\n'
                       'if "unknown symbol" in refusal:\n    pass\n')
    assert _prose_matched_for_a_code(planted) == [1, 2, 4], "the control did not fire"
    assert len(SOURCES) > 5, "the scan found almost no module, so it examined nothing"
    found = [(src.name, line) for src in SOURCES for line in _prose_matched_for_a_code(src)]
    assert not found, f"a refusal's code is chosen by matching prose at {found}"


def _refusal_sentences(path: Path) -> list[tuple[str, int]]:
    """The sentence of every refusal `path` raises, `raise <Exception>(<message>, ...)`, folded
    to its words of three letters or more, with the line it is raised at. The core's refusals
    carry their message first (`Invalid`, `FormatError`), where a server's carry a code first."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and node.exc.args):
            continue
        parts = [sub.value for sub in ast.walk(node.exc.args[0])
                 if isinstance(sub, ast.Constant) and isinstance(sub.value, str)]
        key = " ".join(w for w in re.sub(r"[^a-z ]+", " ", " ".join(parts).lower()).split()
                       if len(w) > 2)
        if len(key.split()) >= 3:
            found.append((key, node.lineno))
    return found


def test_no_refusal_sentence_is_written_at_more_than_one_site(tmp_path: Path) -> None:
    """The same refusal sentence raised at two SITES, in one module or two, is a copy that will
    drift by a word. It sees verbatim copies and nothing else; nothing is exempt and there is no
    baseline, since a baseline is the only thing that can grow."""
    planted = tmp_path / "planted.py"
    planted.write_text('raise Invalid(f"{p} names no file, so there is nothing to examine")\n'
                       'raise FormatError(f"{q} names no file, so there is nothing to examine")\n'
                       'raise Invalid("a different refusal entirely")\n')
    keys = collections.Counter(k for k, _ in _refusal_sentences(planted))
    assert sorted(keys.values()) == [1, 2], "the control did not fire"
    seen: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    for path in SOURCES:
        for key, line in _refusal_sentences(path):
            seen[key].add(f"{path.name}:{line}")
    assert len(seen) > 20, "the scan found almost no refusal, so it examined nothing"
    shared = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    assert not shared, ("these refusal sentences are written at more than one site:\n"
                        + "\n".join(f"  {v}: {k[:70]}" for k, v in sorted(shared.items())))
