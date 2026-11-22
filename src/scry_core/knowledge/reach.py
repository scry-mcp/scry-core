"""What a region owes beyond its own lines: the `state` it shares with the rest of its file and
the `lookup` tables it indexes.

A `state` item is a member the region stores and code of the file outside the region reads, or
a member the region returns and code outside it writes: one item for each member and function,
the handler's own other cases included, whatever the number of lines, so a fact that lives in
the chip's own clockwork (a count that wraps after terminal count, a flag set only under its
enable bit) reaches the entry whose handler touches the member. A member is named by its path
less any root the function owns (a local, a parameter), so `chan->currcnt` and a method's bare
`currcnt` are one; an index that is a literal or a constant's name is part of the member (a
number and a name may be one), any other matches every index, and the member named whole
matches only itself. A member inside a subscript is read, and `++`, `--` or `op=` read what
they write.

A `lookup` item is a table the file defines (`name[] = {`) that the region reads at an index
that is not a constant, owed at the table's own lines. A row or a closure over any line of
either closes it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache

from scry_core.knowledge import cover

_SUBSCRIPT = r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]"
_PATH = re.compile(
    r"(?<![\w.>:])(?:this\s*->\s*)?([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)"
    rf"((?:\s*{_SUBSCRIPT.replace('(', '(?:', 1)}|\s*(?:\.|->)\s*[A-Za-z_]\w*)*)")
_PART = re.compile(rf"\s*{_SUBSCRIPT}|\s*(?:\.|->)\s*([A-Za-z_]\w*)")
_CONSTANT = re.compile(r"[A-Z_][A-Z0-9_]*")
#: A register of the guest is what a call hands in and out, owed by the call's own items, never
#: state another call shares.
_GUEST = re.compile(r"reg_e?(?:[abcd][xlh]|[sd]i|[sb]p|ip|flags)")
_WORDS = {"const", "constexpr", "static", "auto", "volatile", "extern", "inline", "struct",
          "class", "enum", "union", "typename", "template", "using", "namespace", "this",
          "nullptr", "true", "false", "NULL"}
#: The calls that register or copy a member for a saved state: no behaviour a program sees.
SAVES = ("save_item", "save_pointer", "WRITE_POD", "READ_POD", "WRITE_POD_SIZE",
         "READ_POD_SIZE")
_SAVE = re.compile(rf"\b(?:{'|'.join(SAVES)})\s*\(")
_INDEXED = re.compile(rf"(?<![\w.>])([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*{_SUBSCRIPT}")
_TABLE = r"(?m)^[^;{{}}\n]*\b(?:const|constexpr)\b[^;{{}}=\n]*\b{}\s*(?:\[[^\]]*\]\s*)+=\s*\{{"
_TRAILERS = ("const", "override", "noexcept", "final")
#: A computed index: it may be the one another function names. A member written whole
#: (allocated, saved) is not one of its elements.
_ANY = "*"

Member = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Touch:
    member: Member
    line: int
    writes: bool
    text: str


@dataclass(frozen=True)
class Function:
    name: str
    start: int
    stop: int
    touches: tuple[Touch, ...]


def _index(text: str) -> str:
    text = cover._SUFFIX.sub(r"\1", text.strip())
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", text):
        return str(int(text, 16))
    if re.fullmatch(r"0[0-7]+", text):
        return str(int(text, 8))
    if re.fullmatch(r"[0-9]+", text):
        return str(int(text))
    return text if _CONSTANT.fullmatch(text) else "*"


def _paths(text: str, owned: set[str], at: int = 0) -> list[tuple[int, Member, str, bool]]:
    """The members a statement names, with where each starts and whether it sits inside another's
    subscript: not a call, a local, a constant, a register of the guest or a word of the
    language."""
    out: list[tuple[int, Member, str, bool]] = []
    for m in _PATH.finditer(text):
        for p in _PART.finditer(m.group(2)):
            if p.group(1) is not None:
                start = m.start(2) + p.start(1)
                out += [(at + x, mem, shown, True)
                        for x, mem, shown, _ in _paths(p.group(1), owned, start)]
        root = m.group(1)
        if text[m.end():].lstrip().startswith("(") or root in cover.KEYWORDS or root in _WORDS \
                or root in cover.TYPES or (_CONSTANT.fullmatch(root) and not m.group(2)) \
                or _GUEST.fullmatch(root):
            continue
        parts: list[tuple[str, str]] = [(root.rsplit("::", 1)[-1], "")]
        for p in _PART.finditer(m.group(2)):
            if p.group(2) is not None:
                parts.append((p.group(2), ""))
            else:
                parts[-1] = (parts[-1][0], _index(p.group(1)))
        if root in owned:
            parts = parts[1:]
        if parts:
            out.append((at + m.start(), tuple(parts), " ".join(m.group(0).split()), False))
    return out


def _statement(text: str, line: int, owned: set[str], out: list[Touch],
               declares: bool = False) -> None:
    """The members a statement writes (the path an assignment, `++` or `--` changes) and the
    members it reads (every other one, and the one `++`, `--` or `op=` changes); the first
    assignment of a declaration gives its local a value and writes no member. A statement that
    saves state touches nothing."""
    if _SAVE.search(text):
        return
    written: set[int] = set()
    previous = 0
    found = _paths(text, owned)
    for k, (a, b, op) in enumerate(cover._assignments(text)):
        left = [p for p in found if previous <= p[0] < a and not p[3]]
        if not left and not text[previous:a].strip():
            left = [p for p in found if p[0] >= b and not p[3]][:1]
        previous = b
        if declares and k == 0:
            written.update(p[0] for p in left)
        elif left:
            at, member, shown, _ = left[-1]
            written.add(at)
            out.append(Touch(member, line, True, shown))
            if op != "=":
                out.append(Touch(member, line, False, shown))
    out += [Touch(member, line, False, shown) for at, member, shown, _ in found
            if at not in written]


def _declared(text: str) -> str | None:
    """The local a statement, or a loop's head, declares: a condition declares none."""
    head = re.split(r";|(?<!:):(?!:)", re.sub(r"^(?:for|while) \(", "", text), maxsplit=1)[0]
    m = cover._DECL.match(head.strip() + ";")
    if m is None or m.group(1) in cover.KEYWORDS or head.split()[0] in cover.KEYWORDS:
        return None
    return m.group(1)


def _all(nodes: Iterable[cover.Node]) -> Iterator[cover.Node]:
    for n in nodes:
        yield n
        yield from _all(n.body)
        yield from _all(n.orelse)


def _touches(nodes: Iterable[cover.Node], owned: set[str]) -> list[Touch]:
    out: list[Touch] = []
    for n in nodes:
        if n.kind in ("simple", "exit", "if", "loop", "switch") and n.text:
            name = _declared(n.text) if n.kind in ("simple", "loop") else None
            if name is not None:
                owned.add(name)
            _statement(n.text, n.line, owned, out, name is not None)
    return out


def _signature_end(text: str, brace: int) -> int:
    """The `)` that closes the parameters of the body opening at `brace`, or -1."""
    k = brace - 1
    while k >= 0:
        if text[k].isspace():
            k -= 1
            continue
        word = next((w for w in _TRAILERS if text[max(0, k - len(w) + 1):k + 1] == w), "")
        if not word:
            break
        k -= len(word)
    return k if k >= 0 and text[k] == ")" else -1


def _opening(text: str, close: int) -> int:
    """The bracket that opens the one closing at `close`, or -1."""
    pair = {")": "(", "}": "{"}[text[close]]
    depth = 0
    for k in range(close, -1, -1):
        depth += (text[k] == text[close]) - (text[k] == pair)
        if depth == 0:
            return k
    return -1


def _parameters(text: str, brace: int) -> set[str]:
    """Every parameter of the function whose body opens at `brace`, references included: what
    is reached through one is named by the rest of its path."""
    close = _signature_end(text, brace)
    open_ = _opening(text, close) if close >= 0 else -1
    names = set()
    for part in text[open_ + 1:close].split(",") if open_ >= 0 else ():
        got = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", part.split("=")[0])
        if got and got.group(1) not in cover.KEYWORDS | cover.TYPES:
            names.add(got.group(1))
    return names


def _function_name(text: str, brace: int) -> str:
    """The name of the function whose body opens at `brace`, or "" when the brace opens none; a
    constructor's initializer list is passed over, and a definer macro names its argument."""
    close = _signature_end(text, brace)
    while close >= 0:
        open_ = _opening(text, close)
        if open_ < 0:
            return ""
        m = re.search(r"(~?[A-Za-z_][\w:~]*)\s*$", text[:open_])
        name = m.group(1) if m else ""
        if name.rsplit("::", 1)[-1] in cover.DEFINERS:
            return " ".join(text[open_ + 1:close].split())
        lead = text[:open_ - len(name) if m is None else m.start()].rstrip()
        if name and (lead.endswith(",") or (lead.endswith(":") and not lead.endswith("::"))):
            k = len(lead) - 2
            while k >= 0 and text[k].isspace():
                k -= 1
            close = k if k >= 0 and text[k] in ")}" else -1
            continue
        return "" if not name or name in cover.KEYWORDS else name
    return ""


@lru_cache(maxsize=16)
def functions(text: str) -> tuple[Function, ...]:
    """Every function the blanked `text` defines, with the members each touches."""
    found = []
    i = 0
    while i < len(text):
        if text[i] != "{" or not (name := _function_name(text, i)):
            i += 1
            continue
        end = cover._matching(text, i, "{", "}")
        if end < 0:
            break
        tree = cover.Parser(text, i + 1, end - 1).statements()
        found.append(Function(name, i + 1, end - 1,
                              tuple(_touches(_all(tree), _parameters(text, i)))))
        i = end
    return tuple(found)


def _one_index(x: str, y: str) -> bool:
    """Whether two indexes may be one: equal, either computed, or a number and a constant's
    name, whose value this reader does not know. No index, the member whole, is only itself."""
    return x == y or (bool(x) and bool(y) and (_ANY in (x, y) or x.isdigit() != y.isdigit()))


def _same(a: Member, b: Member) -> bool:
    """Whether two paths name one member: the shorter is the end of the longer, part by part."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return all(x[0] == y[0] and _one_index(x[1], y[1])
               for x, y in zip(short, long_[len(long_) - len(short):], strict=True))


def _returned(region: list[cover.Node], whole: list[cover.Node], owned: set[str]
              ) -> list[Touch]:
    """What the region returns: the members read in a `return` of the region, or in the value
    it gives a local that some `return` of the function hands back."""
    handed = owned & {name for n in _all(whole) if n.kind == "exit"
                      and n.text.startswith("return") for name in cover._NAME.findall(n.text[6:])}
    out: list[Touch] = []
    for n in region:
        if n.kind not in ("simple", "exit") or not n.text:
            continue
        value = n.text[6:] if n.kind == "exit" and n.text.startswith("return") else ""
        for a, b, _ in cover._assignments(n.text)[:1]:
            if any(re.search(rf"\b{re.escape(h)}\s*$", n.text[:a]) for h in handed):
                value = n.text[b:]
        out += [Touch(m, n.line, False, shown) for _, m, shown, _ in _paths(value, owned)]
    return out


def state(text: str, start: int, region: list[cover.Node], whole: list[cover.Node],
          span: tuple[int, int]) -> list[cover.Item]:
    """The `state` items of a region of the function whose body opens at `start` in the blanked
    `text`; `region` is the statements the lister read, one by one."""
    owned = _parameters(text, start - 1) | {
        name for n in _all(whole) if n.kind in ("simple", "loop") and n.text
        and (name := _declared(n.text)) is not None}
    wanted: list[tuple[Touch, bool]] = []
    for t, writes in [(t, False) for t in _touches(region, set(owned)) if t.writes] + [
            (t, True) for t in _returned(region, whole, owned)]:
        if not any(w == writes and u.member == t.member for u, w in wanted):
            wanted.append((t, writes))
    out: list[cover.Item] = []
    for f in functions(text):
        for t, writes in wanted:
            lines = tuple(sorted({u.line for u in f.touches
                                  if u.writes == writes and _same(u.member, t.member)}))
            if lines and not all(span[0] <= x <= span[1] for x in lines):
                verb = "written" if writes else "read"
                out.append(cover.Item(lines[0], "state", f"{t.text} {verb} by {f.name}", lines))
    return out


def lookup(text: str, region: list[cover.Node]) -> list[cover.Item]:
    """The `lookup` items of a region, each with its table's lines."""
    out: dict[str, cover.Item] = {}
    for n in region:
        for m in _INDEXED.finditer(n.text):
            name = m.group(1).rsplit("::", 1)[-1]
            if name in out or _index(m.group(2)) != "*":
                continue
            table = re.search(_TABLE.format(re.escape(name)), text)
            if table is None:
                continue
            first = text.count("\n", 0, table.start()) + 1
            last = text.count("\n", 0, cover._matching(text, table.end() - 1, "{", "}")) + 1
            out[name] = cover.Item(first, "lookup", f"{name}[{' '.join(m.group(2).split())}]",
                                   tuple(range(first, last + 1)))
    return list(out.values())
