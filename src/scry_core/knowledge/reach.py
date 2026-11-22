"""What a region owes beyond its own lines: the `state` it shares with the rest of its file and
the `lookup` tables it indexes.

A `state` item is a member the region hands out and code of the file outside the region writes:
one item for each member and function, the handler's other cases included, so a fact of the
chip's clockwork (a count that wraps after terminal count, a flag set only under its enable bit)
reaches the entry that hands it out. What a region stores owes nothing: its readers are the
chip's whole engine, not a fact about the write. A member is named by its path less any root the
function owns (a local, a parameter). An item names one thing: an element reached at an index
the region does not fix (`m_data[offset]`) owes nothing, and a fixed index (a literal, a
constant's name) matches only itself; a computed index before the last part picks an instance
(`m_chan[ch].count`) and matches any, and the member named whole matches only itself.

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
_INDEXED = re.compile(rf"(?<![\w.>])([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*{_SUBSCRIPT}")
_TABLE = r"(?m)^[^;{{}}\n]*\b(?:const|constexpr)\b[^;{{}}=\n]*\b{}\s*(?:\[[^\]]*\]\s*)+=\s*\{{"
_TRAILERS = ("const", "override", "noexcept", "final")
_HEAD = re.compile(r"(?:do )?(?:for|while) \((.*)\)", re.S)
#: A name of its own, not a field reached through `.` or `->`.
_BARE = r"(?<![\w.])(?<!->)"
#: A computed index: it picks an instance on the way to a member, never the element owed. A
#: member written whole (allocated, saved) is not one of its elements.
_ANY = "*"

Member = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Write:
    member: Member
    line: int
    text: str


@dataclass(frozen=True)
class Function:
    name: str
    start: int
    stop: int
    writes: tuple[Write, ...]


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


def _statement(text: str, line: int, owned: set[str], out: list[Write],
               declares: bool = False) -> None:
    """The members a statement writes: the path an assignment, `++` or `--` changes. The first
    assignment of a declaration gives its local a value and writes no member."""
    previous = 0
    found = _paths(text, owned)
    for k, (a, b, op) in enumerate(cover._assignments(text)):
        left = [p for p in found if previous <= p[0] < a and not p[3]]
        prefix = op in ("++", "--") and not re.search(r"[\w\]]\s*$", text[previous:a])
        if prefix or (not left and not text[previous:a].strip()):
            left = [p for p in found if p[0] >= b and not p[3]][:1]
        previous = b
        if left and not (declares and k == 0):
            _, member, shown, _ = left[-1]
            out.append(Write(member, line, shown))


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


def _writes(nodes: Iterable[cover.Node], owned: set[str]) -> list[Write]:
    out: list[Write] = []
    for n in nodes:
        if n.kind in ("simple", "exit", "if", "loop", "switch") and n.text:
            name = _declared(n.text) if n.kind in ("simple", "loop") else None
            if name is not None:
                owned.add(name)
            head = _HEAD.fullmatch(n.text) if n.kind == "loop" else None
            _statement(head.group(1) if head else n.text, n.line, owned, out, name is not None)
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
    """Every function the blanked `text` defines, with the members each writes."""
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
                              tuple(_writes(_all(tree), _parameters(text, i)))))
        i = end
    return tuple(found)


def _one_index(x: str, y: str, last: bool) -> bool:
    """Whether two indexes are one: equal, or, before the last part, either computed. A name
    and a number are two, since this reader does not know the name's value."""
    return x == y or (not last and bool(x) and bool(y) and _ANY in (x, y))


def _same(a: Member, b: Member) -> bool:
    """Whether two paths name one member: the shorter is the end of the longer, part by part."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return all(x[0] == y[0] and _one_index(x[1], y[1], k == len(short) - 1)
               for k, (x, y) in enumerate(zip(short, long_[len(long_) - len(short):],
                                              strict=True)))


def _returned(region: list[cover.Node], whole: list[cover.Node], owned: set[str]
              ) -> list[tuple[Member, str]]:
    """What the region hands out: the members read in a `return` of the region, or in the value
    it gives a guest register or a local that some `return` of the function hands back."""
    handed = owned & {name for n in _all(whole) if n.kind == "exit"
                      and n.text.startswith("return")
                      for name in re.findall(_BARE + cover._NAME.pattern, n.text[6:])}
    out: list[tuple[Member, str]] = []
    for n in region:
        if n.kind not in ("simple", "exit") or not n.text:
            continue
        value = n.text[6:] if n.kind == "exit" and n.text.startswith("return") else ""
        for a, b, _ in cover._assignments(n.text)[:1]:
            if any(re.search(rf"{_BARE}{re.escape(h)}\s*$", n.text[:a]) for h in handed) \
                    or _GUEST.fullmatch(n.text[:a].strip()):
                value = n.text[b:]
        out += [(m, shown) for _, m, shown, _ in _paths(value, owned)]
    return out


def state(text: str, start: int, region: list[cover.Node], whole: list[cover.Node],
          span: tuple[int, int]) -> list[cover.Item]:
    """The `state` items of a region of the function whose body opens at `start` in the blanked
    `text`; `region` is the statements the lister read, one by one."""
    owned = _parameters(text, start - 1) | {
        name for n in _all(whole) if n.kind in ("simple", "loop") and n.text
        and (name := _declared(n.text)) is not None}
    wanted: dict[Member, str] = {}
    for member, shown in _returned(region, whole, owned):
        if member[-1][1] != _ANY:
            wanted.setdefault(member, shown)
    out: list[cover.Item] = []
    for f in functions(text):
        for member, shown in wanted.items():
            lines = tuple(sorted({w.line for w in f.writes if _same(w.member, member)}))
            if lines and not all(span[0] <= x <= span[1] for x in lines):
                out.append(cover.Item(lines[0], "state", f"{shown} written by {f.name}", lines))
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
