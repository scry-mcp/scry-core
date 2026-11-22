"""The coverage lister: the items a handler's code owes rows for.

It reads C++ as text, not as a program: comments and strings are blanked, statements are split by
braces and semicolons, and nothing follows a macro, a function pointer or a value carried in a
variable. What it cannot see is named by the design and decided by a person, never hidden here;
a function or a case it cannot find is `Invalid`, never an empty list.

An item is `kind`, `line` and the statement's `text`. The committed form of an item is its
`record`: kind, file, line and the digest of the line, never source text.

Two kinds are listed for what a verdict may cite and are never owed a row: a `local` is an
assignment to something the function owns (a declared variable, a parameter taken by value), and
an `input` is a statement handing a guest register to a call or to a local. Neither is state the
guest can see, so leaving one out costs nothing; showing one is how an `in` row is proved.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from scry_core.knowledge.quote import Invalid, span, stamp

KINDS = ("path", "before", "branch", "exit", "call", "store", "key", "build", "empty", "list",
         "state", "lookup", "local", "input")
#: The kinds that show what the code does without being state a row must account for.
NOT_OWED = ("local", "input")
KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "case", "defined", "else", "do",
            "catch", "goto", "break", "continue", "static_cast", "reinterpret_cast", "const_cast",
            "new", "delete", "throw", "default", "assert"}
TYPES = {"Bitu", "Bits", "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int", "char", "unsigned",
         "long", "short", "bool", "size_t", "PhysPt", "RealPt", "int8_t", "int16_t", "int32_t",
         "int64_t", "float", "double", "void", "offs_t", "u8", "u16", "u32", "attotime"}
#: The macros that define a function MAME calls later, and so hide its name from a plain search.
DEFINERS = ("TIMER_CALLBACK_MEMBER", "DEVICE_IMAGE_LOAD_MEMBER", "DEVICE_IMAGE_UNLOAD_MEMBER",
            "INTERRUPT_GEN_MEMBER", "WRITE_LINE_MEMBER")
#: A macro that names a function to be called later: the item is a call of its argument.
DEFERRERS = ("FUNC", "TIMER_CALLBACK")
_EXITS = ("return", "break", "continue", "goto", "throw")
_ASSIGN = re.compile(r"(?<![=!<>+\-*/&|^%])(\+\+|--|(?:[+\-*/&|^%]|<<|>>)?=)(?!=)")
_CALL = re.compile(r"\b([A-Za-z_]\w*(?:(?:::|\.|->)[A-Za-z_]\w*)*)\s*(?:<[\w:,\s*&]*>)?\s*\(")
_LABEL = re.compile(r"[A-Za-z_]\w*\s*:(?!:)")
_DECL = re.compile(
    r"^(?:const\s+|static\s+|unsigned\s+)*[A-Za-z_][\w:<>]*[\s*&]+([A-Za-z_]\w*)\s*(?:=|;|\[|$)")
_NAME = re.compile(r"[A-Za-z_]\w*")
#: A register of the guest as DOSBox-X's code names it.
REGISTER = re.compile(r"(?<![\w.>])reg_(?:[abcd][xlh]|[sd]i|[sb]p|ip|flags)\b")



@dataclass(frozen=True, order=True)
class Item:
    line: int
    kind: str
    text: str
    #: Every line that holds what the item names, when it is more than `line`: a row or a
    #: closure over any of them closes it.
    lines: tuple[int, ...] = field(default=(), compare=False)

    def record(self, file: str, lines: list[str]) -> dict[str, object]:
        """What a committed coverage index keeps of an item: no text of the source."""
        return {"kind": self.kind, "file": file, "line": self.line,
                "sha": stamp([lines[self.line - 1]])}


@dataclass
class Listing:
    """The items of one region, the lines the region spans, and for a function's region the
    blanked text it was read from, where its body opens, its statements and the region's
    statements the lister read, one by one."""

    items: list[Item] = field(default_factory=list)
    first: int = 0
    last: int = 0
    text: str = ""
    start: int = 0
    tree: list[Node] = field(default_factory=list)
    region: list[Node] = field(default_factory=list)


def blank(text: str) -> str:
    """`text` with comments and string and character literals turned to spaces, lines kept."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        elif text[i] == "'" and i > 0 and text[i - 1].isdigit() and text[i + 1:i + 2].isalnum():
            out.append("'")
            i += 1
        elif text[i] in "\"'":
            q, j = text[i], i + 1
            while j < n and text[j] != q and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            closed = j < n and text[j] == q
            out.append(q + "".join(c if c == "\n" else " " for c in text[i + 1:j])
                       + (q if closed else ""))
            i = j + 1 if closed else j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


_IF = re.compile(r"\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)")


_BIT_VALUE = re.compile(r"\(\s*([01])\s*\)|([01])")
_DEFINE_BIT = re.compile(r"\s*#\s*define\s+(\w+)\s+(\(\s*[01]\s*\)|[01])\s*")
_UNDEF = re.compile(r"\s*#\s*undef\s+(\w+)\s*")


def _bit(text: str) -> bool | None:
    m = _BIT_VALUE.fullmatch(text.strip())
    return None if m is None else (m.group(1) or m.group(2)) == "1"


def decide(directive: str, rest: str, defined: set[str],
           values: Mapping[str, bool] | None = None) -> bool | None:
    """Whether the arm a directive opens is compiled, or None when this reader cannot tell;
    `values` are the names the file itself defines as `0` or `1`, `(0)` or `(1)`."""
    rest = rest.strip()
    known = set(defined) | set(values or {})
    if directive == "ifdef":
        return rest in known
    if directive == "ifndef":
        return rest not in known
    if (bit := _bit(rest)) is not None:
        return bit
    m = re.fullmatch(r"(!?)\s*defined\s*\(?\s*(\w+)\s*\)?", rest)
    if m:
        return (m.group(2) in known) != bool(m.group(1))
    m = re.fullmatch(r"(!?)\s*(\w+)", rest)
    if m and values and m.group(2) in values:
        return values[m.group(2)] != bool(m.group(1))
    if m and m.group(2) in defined:
        return not m.group(1)
    return None


def one_build(text: str, defined: set[str]) -> tuple[str, list[tuple[int, str]]]:
    """`text` with the preprocessor arms that are not compiled blanked, so braces balance, and
    what was decided at each conditional: `(line, what)`. An arm this reader cannot decide is
    taken when it is the first of its conditional, and said."""
    notes: list[tuple[int, str]] = []
    stack: list[dict[str, bool]] = []
    out: list[str] = []
    values: dict[str, bool] = {}
    for n, line in enumerate(text.split("\n"), 1):
        m = _IF.match(line)
        keep = all(s["live"] for s in stack)
        if not m:
            if keep and (d := _DEFINE_BIT.fullmatch(line)):
                values[d.group(1)] = _bit(d.group(2)) is True
            elif keep and (u := _UNDEF.fullmatch(line)):
                values.pop(u.group(1), None)
            out.append(line if keep else "")
            continue
        directive, rest = m.group(1), m.group(2)
        if directive in ("if", "ifdef", "ifndef"):
            got = decide(directive, rest, defined, values)
            live = True if got is None else got
            if keep:
                notes.append((n, f"#{directive} {rest.strip()}: " + (
                    "UNDECIDED, first arm read" if got is None else
                    "compiled" if got else "not compiled")))
            stack.append({"taken": live, "live": live, "outer": keep})
        elif directive in ("elif", "else") and stack:
            top = stack[-1]
            got = None if directive == "else" else decide("if", rest, defined, values)
            live = not top["taken"] and (True if got is None else got)
            if top["outer"]:
                notes.append((n, f"#{directive} {rest.strip()}: "
                              + ("compiled" if live else "not compiled, not read")))
            top["live"] = live
            top["taken"] = top["taken"] or live
        elif directive == "endif" and stack:
            stack.pop()
        out.append("")
    return "\n".join(out), notes


@dataclass
class Node:
    kind: str          # block if loop switch case exit simple pre
    line: int
    text: str = ""
    body: list[Node] = field(default_factory=list)
    orelse: list[Node] = field(default_factory=list)
    end: int = 0


class Parser:
    def __init__(self, text: str, start: int, stop: int) -> None:
        self.t, self.i, self.stop = text, start, stop

    def line(self, at: int) -> int:
        return self.t.count("\n", 0, at) + 1

    def skip(self) -> None:
        while self.i < self.stop and self.t[self.i].isspace():
            self.i += 1

    def paren(self) -> str:
        depth, j = 0, self.i
        while j < self.stop:
            depth += self.t[j] == "("
            depth -= self.t[j] == ")"
            j += 1
            if depth == 0:
                break
        got = self.t[self.i + 1:j - 1]
        self.i = j
        return " ".join(got.split())

    def word(self) -> str:
        m = _NAME.match(self.t, self.i)
        return m.group(0) if m else ""

    def statements(self) -> list[Node]:
        out: list[Node] = []
        while True:
            self.skip()
            if self.i >= self.stop or self.t[self.i] == "}":
                return out
            out.append(self.statement())

    def statement(self) -> Node:
        self.skip()
        at, here = self.i, self.line(self.i)
        if self.t[self.i] == "#":
            j = self.t.find("\n", self.i)
            j = self.stop if j < 0 else j
            self.i = j
            return Node("pre", here, " ".join(self.t[at:j].split()), end=here)
        if self.t[self.i] == "{":
            self.i += 1
            body = self.statements()
            self.i += 1
            return Node("block", here, body=body, end=self.line(self.i - 1))
        if self.t.startswith("[[", self.i):
            self.i = self.t.find("]]", self.i) + 2
            return self.statement()
        w = self.word()
        if w == "if":
            self.i += 2
            self.skip()
            if self.word() == "constexpr":
                self.i += len("constexpr")
                self.skip()
            node = Node("if", here, self.paren(), body=[self.statement()])
            save = self.i
            self.skip()
            if self.word() == "else":
                self.i += 4
                node.orelse = [self.statement()]
            else:
                self.i = save
            node.end = self.line(self.i - 1)
            return node
        if w in ("for", "while"):
            self.i += len(w)
            self.skip()
            cond = self.paren()
            node = Node("loop", here, f"{w} ({cond})", body=[self.statement()])
            node.end = self.line(self.i - 1)
            return node
        if w == "do":
            self.i += 2
            body = [self.statement()]
            self.skip()
            self.i += len("while")
            self.skip()
            cond = self.paren()
            self.semi()
            return Node("loop", here, f"do while ({cond})", body=body, end=self.line(self.i - 1))
        if w == "switch":
            self.i += 6
            self.skip()
            cond = self.paren()
            self.skip()
            self.i += 1
            body = self.statements()
            self.i += 1
            return Node("switch", here, cond, body=body, end=self.line(self.i - 1))
        if w in ("case", "default"):
            return self.label(at, here)
        if w not in KEYWORDS and (label := _LABEL.match(self.t, self.i)):
            self.i = label.end()
            return self.statement()
        j = self.semi()
        text = " ".join(self.t[at:j].split())
        return Node("exit" if w in _EXITS else "simple", here, text, end=self.line(j))

    def label(self, at: int, here: int) -> Node:
        j, depth = self.i, 0
        while j < self.stop:
            ch = self.t[j]
            depth += ch in "(["
            depth -= ch in ")]"
            if ch == ":" and depth == 0 and self.t[j:j + 2] != "::" and self.t[j - 1] != ":":
                break
            j += 1
        text = " ".join(self.t[at:j].split())
        self.i = j + 1
        return Node("case", here, text, end=here)

    def semi(self) -> int:
        """Moves past the `;` that ends the statement at `i`, skipping brackets; returns its
        place."""
        depth, j = 0, self.i
        while j < self.stop:
            ch = self.t[j]
            depth += ch in "([{"
            depth -= ch in ")]}"
            if ch == ";" and depth == 0:
                break
            j += 1
        self.i = j + 1
        return j


def _matching(text: str, at: int, opener: str, closer: str) -> int:
    """The index just past the bracket that closes the one at `at`, or -1."""
    depth = 0
    for j in range(at, len(text)):
        depth += text[j] == opener
        depth -= text[j] == closer
        if depth == 0:
            return j + 1
    return -1


def _definitions(text: str, name: str, within: tuple[int, int] | None = None
                 ) -> list[tuple[int, int]]:
    """The bodies of every definition of `name` in `text`, or in the part `within` it."""
    lo, hi = within or (0, len(text))
    found = []
    for m in re.finditer(rf"\b{re.escape(name)}\s*\(", text):
        if not lo <= m.start() < hi:
            continue
        k = _matching(text, m.end() - 1, "(", ")")
        while 0 <= k < len(text) and (text[k].isspace() or text[k:k + 5] == "const"):
            k += 5 if text[k:k + 5] == "const" else 1
        if 0 <= k < len(text) and text[k] == "{":
            end = _matching(text, k, "{", "}")
            if end > 0:
                found.append((k + 1, end - 1))
    return sorted(set(found))


def _members(text: str, name: str) -> list[tuple[int, int]]:
    """The bodies of `Class::name` written inside the braces of `class`, `struct` or `union`
    `Class`, the way a header holds a nested class's methods."""
    owner, _, method = name.rpartition("::")
    inner = owner.rsplit("::", 1)[-1]
    found = []
    for m in re.finditer(rf"\b(?:class|struct|union)\s+{re.escape(inner)}\b[^;{{()]*\{{", text):
        end = _matching(text, m.end() - 1, "{", "}")
        if end > 0:
            found += _definitions(text, method, (m.end(), end))
    return found


def function(text: str, name: str, definers: Iterable[str] = DEFINERS) -> tuple[int, int]:
    """Where the body of the definition of `name` opens and closes in the blanked `text`, or
    `Invalid`: a definition through one of the `definers` macros counts, and `Class::name` is
    also a method written inside the class. A bare name two definitions answer is refused, so a
    region never reads the wrong one."""
    found = _definitions(text, name)
    if not found and "::" in name:
        found = _members(text, name)
    if len(found) > 1:
        lines = ", ".join(str(text.count("\n", 0, a) + 1) for a, _ in found)
        way = ("overloads the lister cannot tell apart: name the region by its `lines`" if "::"
               in name else f"name the one meant as `Class::{name}`")
        raise Invalid(f"{name} has {len(found)} definitions (lines {lines}): {way}")
    if found:
        return found[0]
    for macro in definers:
        for m in re.finditer(rf"\b{macro}\s*\(\s*{re.escape(name)}\s*\)\s*\{{", text):
            end = _matching(text, m.end() - 1, "{", "}")
            if end > 0:
                return m.end(), end - 1
    raise Invalid(f"no definition of {name}")


def _exits_in(nodes: list[Node], conds: tuple[str, ...] = (),
              nested: bool = False) -> list[tuple[Node, tuple[str, ...]]]:
    """The exits under `nodes` that leave the enclosing region, each with the conditions it sits
    under: a `break` or `continue` inside a nested switch or loop leaves only that one."""
    out: list[tuple[Node, tuple[str, ...]]] = []
    for n in nodes:
        if n.kind == "exit":
            if not (nested and n.text.startswith(("break", "continue"))):
                out.append((n, conds))
        elif n.kind == "if":
            out += _exits_in(n.body, (*conds, f"{n.line}: {n.text}"), nested)
            out += _exits_in(n.orelse, (*conds, f"{n.line}: not ({n.text})"), nested)
        elif n.kind in ("switch", "loop"):
            out += _exits_in(n.body, (*conds, f"{n.line}: {n.kind} {n.text}"), True)
        else:
            out += _exits_in(n.body, conds, nested)
    return out


def _ends(n: Node) -> bool:
    """Whether control never runs past `n`: an exit, or a block whose last statement is one."""
    return n.kind == "exit" or (n.kind == "block" and bool(n.body) and _ends(n.body[-1]))


def _label_value(label: str) -> str:
    label = _SUFFIX.sub(r"\1", label.removeprefix("case").strip())
    try:
        return str(int(label, 0))
    except ValueError:
        return label


def _numeric(label: str) -> bool:
    return _label_value(label).lstrip("-").isdigit()


def _case_body(sw: Node, wanted: str) -> tuple[Node, list[Node]]:
    """The label node of `wanted` in the switch `sw` and the statements it runs: from its label
    to the first exit at the switch's own level, labels it falls into included."""
    for k, n in enumerate(sw.body):
        if n.kind == "case" and _label_value(n.text) == _label_value(wanted):
            body: list[Node] = []
            for later in sw.body[k + 1:]:
                body.append(later)
                if _ends(later):
                    break
            return n, body
    raise Invalid(f"no case {wanted} in the switch at line {sw.line}")


@dataclass
class _Found:
    switch: Node
    path: list[str]
    before: list[tuple[Node, tuple[str, ...]]]
    lead: list[Node]


def _find_switch(nodes: list[Node], wanted: str, path: list[str],
                 before: list[tuple[Node, tuple[str, ...]]], lead: list[Node]) -> _Found | None:
    """The first switch under `nodes` that has the case `wanted`, with the conditions that
    enclose it, the conditional exits that come before it and the statements that run before
    it."""
    for k, n in enumerate(nodes):
        early = before + _exits_in([p for p in nodes[:k] if p.kind == "if"])
        ahead = lead + nodes[:k]
        if n.kind == "switch" and any(c.kind == "case" and _label_value(c.text)
                                      == _label_value(wanted) for c in n.body):
            return _Found(n, path, early, ahead)
        for arm, label in ((n.body, n.text), (n.orelse, f"not ({n.text})")):
            if n.kind in ("if", "block", "loop", "switch") and arm:
                where = path + ([f"{n.line}: {'if' if n.kind == 'if' else n.kind} {label}"]
                                if n.kind in ("if", "loop") else [])
                got = _find_switch(arm, wanted, where, early, ahead)
                if got:
                    return got
    return None


_WRAP = re.compile(r"\b(?:GCC_UNLIKELY|GCC_LIKELY|UNLIKELY|LIKELY)\b")
_BIT = re.compile(r"\bBIT\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)")
#: The width and signedness of the casts whose result does not depend on the build.
_CASTS = {"uint8_t": (8, False), "u8": (8, False), "int8_t": (8, True),
          "uint16_t": (16, False), "u16": (16, False), "int16_t": (16, True),
          "uint32_t": (32, False), "u32": (32, False), "int32_t": (32, True), "int": (32, True),
          "unsigned": (32, False), "uint64_t": (64, False), "int64_t": (64, True)}
_SUFFIX = re.compile(r"\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]+\b")
_TOKEN = re.compile(
    r"\s*(0[xX][0-9a-fA-F]+|[0-9]+|[A-Za-z_]\w*|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!<>()])")
_BINARY: tuple[tuple[str, ...], ...] = (
    ("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", "<=", ">", ">="),
    ("<<", ">>"), ("+", "-"), ("*", "/", "%"))


class _Undecidable(Exception):
    pass


class _Expr:
    """A C integer expression of one variable, read with C's precedence."""

    def __init__(self, text: str, name: str, value: int) -> None:
        self.tokens: list[str] = []
        at = 0
        text = text.rstrip()
        while at < len(text):
            m = _TOKEN.match(text, at)
            if not m:
                raise _Undecidable
            self.tokens.append(m.group(1))
            at = m.end()
        self.at, self.name, self.value = 0, name, value

    def peek(self) -> str:
        return self.tokens[self.at] if self.at < len(self.tokens) else ""

    def take(self) -> str:
        tok = self.peek()
        self.at += 1
        return tok

    def parse(self) -> int:
        got = self.level(0)
        if self.at != len(self.tokens):
            raise _Undecidable
        return got

    def level(self, depth: int) -> int:
        if depth == len(_BINARY):
            return self.unary()
        left = self.level(depth + 1)
        while self.peek() in _BINARY[depth]:
            op = self.take()
            right = self.level(depth + 1)
            left = self.apply(op, left, right)
        return left

    @staticmethod
    def apply(op: str, a: int, b: int) -> int:
        if op in ("<<", ">>") and not 0 <= b < 64:
            raise _Undecidable
        if op in ("/", "%") and b == 0:
            raise _Undecidable
        table: dict[str, Callable[[int, int], int]] = {
            "||": lambda x, y: int(bool(x) or bool(y)), "&&": lambda x, y: int(bool(x) and bool(y)),
            "|": lambda x, y: x | y, "^": lambda x, y: x ^ y, "&": lambda x, y: x & y,
            "==": lambda x, y: int(x == y), "!=": lambda x, y: int(x != y),
            "<": lambda x, y: int(x < y), "<=": lambda x, y: int(x <= y),
            ">": lambda x, y: int(x > y), ">=": lambda x, y: int(x >= y),
            "<<": lambda x, y: x << y, ">>": lambda x, y: x >> y, "+": lambda x, y: x + y,
            "-": lambda x, y: x - y, "*": lambda x, y: x * y, "/": lambda x, y: x // y,
            "%": lambda x, y: x % y}
        got = table[op](a, b)
        if op == "-" and got < 0:
            raise _Undecidable
        return got

    def unary(self) -> int:
        tok = self.take()
        if tok == "(" and (self.peek() in _CASTS or self.peek() == "bool") \
                and self.tokens[self.at + 1:][:1] == [")"]:
            kind = self.take()
            self.take()
            inner = self.unary()
            if kind == "bool":
                return int(inner != 0)
            bits, signed = _CASTS[kind]
            wrapped = inner & ((1 << bits) - 1)
            return wrapped - (1 << bits) if signed and wrapped >> (bits - 1) else wrapped
        if tok == "(":
            got = self.level(0)
            if self.take() != ")":
                raise _Undecidable
            return got
        if tok in ("!", "~", "-", "+"):
            inner = self.unary()
            if tok == "-":
                raise _Undecidable
            return {"!": int(not inner), "~": ~inner, "+": inner}[tok]
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|[0-9]+", tok):
            return int(tok, 0)
        if tok == self.name:
            return self.value
        raise _Undecidable


def _simplified(cond: str) -> str:
    cond = _WRAP.sub("", cond)
    return _SUFFIX.sub(r"\1", _BIT.sub(r"((\1 >> \2) & 1)", cond))


@dataclass(frozen=True)
class Key:
    """The key's own value in the code: the variable that holds it and the numbers it takes."""

    name: str
    low: int
    high: int
    only: tuple[int, ...] | None = None

    def values(self) -> Sequence[int]:
        """The numbers the key can hold here: its range, or the set a store to it left."""
        return range(self.low, self.high + 1) if self.only is None else self.only

    def evaluate(self, cond: str) -> int | None:
        """What `cond` is for every value of the key, when it tests nothing but that value: the
        one answer, or None for a condition on anything else or one the values split."""
        if not re.search(rf"\b{re.escape(self.name)}\b", cond) or self.high - self.low > 65536:
            return None
        text = _simplified(cond)
        try:
            got = {_Expr(text, self.name, v).parse() for v in self.values()}
        except _Undecidable:
            return None
        return got.pop() if len(got) == 1 else None


def parse_key(text: str) -> Key:
    """`name=lo..hi` or `name=value`, or `ValueError`."""
    name, eq, rest = text.partition("=")
    low, _, high = rest.partition("..")
    try:
        key = Key(name, int(low, 0), int(high or low, 0))
    except ValueError:
        key = None
    if not eq or key is None or not _NAME.fullmatch(name) or key.high < key.low:
        raise ValueError(f"a value is `name=lo..hi` or `name=value`, in whole numbers; "
                         f"got {text!r}")
    return key


@dataclass
class _Reading:
    key: Key | None
    stores: re.Pattern[str] | None
    out: list[Item] = field(default_factory=list)
    #: The statements read, each once and apart from what it holds: an arm the key leaves out is
    #: never read.
    read: list[Node] = field(default_factory=list)

    def add(self, line: int, kind: str, text: str) -> None:
        self.out.append(Item(line, kind, text))


def _calls(text: str, line: int, reading: _Reading) -> None:
    for m in _CALL.finditer(text):
        name = m.group(1)
        last = re.split(r"::|\.|->", name)[-1]
        if last in DEFERRERS:
            inner = _matching(text, m.end() - 1, "(", ")")
            target = " ".join(text[m.end():inner - 1].split())
            if target:
                reading.add(line, "call", target)
        elif last not in KEYWORDS and last not in TYPES:
            reading.add(line, "call", name)


def _assignments(text: str) -> list[tuple[int, int, str]]:
    """The assignment operators of a statement that sit outside any bracket: `(start, end,
    operator)`."""
    found = []
    for m in _ASSIGN.finditer(text):
        depth = sum(text[i] in "([{" for i in range(m.start())) - sum(
            text[i] in ")]}" for i in range(m.start()))
        if depth == 0:
            found.append((m.start(), m.end(), m.group(1)))
    return found


def family(register: str) -> str:
    """What names the part of the machine a register is: `reg_al`, `reg_ah` and `reg_ax` are one
    family, `a`; `reg_si` and `ds` are their own."""
    name = register.removeprefix("reg_").lower()
    return name[0] if len(name) == 2 and name[0] in "abcd" and name[1] in "xlh" else name


def _address_of(before: str) -> bool:
    """Whether the text before a name ends in a unary `&`, not a bitwise or logical one."""
    return before.endswith("&") and not before.endswith("&&") and not re.search(
        r"[\w)\]]\s*&$", before)


def _read_registers(text: str) -> list[tuple[int, str]]:
    """The guest registers a statement reads, not an address taken to be written through."""
    return [(m.start(), m.group(0)) for m in REGISTER.finditer(text)
            if not _address_of(text[:m.start()].rstrip())]


def _inputs(text: str, line: int, reading: _Reading) -> None:
    """An `input` for each guest register a statement hands to a call as an argument."""
    registers = _read_registers(text)
    for m in _CALL.finditer(text) if registers else ():
        last = re.split(r"::|\.|->", m.group(1))[-1]
        if last in KEYWORDS or last in TYPES:
            continue
        end = _matching(text, m.end() - 1, "(", ")")
        for at, name in registers:
            if m.end() <= at < end:
                reading.add(line, "input", f"{name} to {m.group(1)}")


def _has_call(text: str) -> bool:
    return any(re.split(r"::|\.|->", m.group(1))[-1] not in KEYWORDS | TYPES
               for m in _CALL.finditer(text))


def _stores(text: str, line: int, locals_: set[str], reading: _Reading) -> None:
    """A store for each assignment outside the function's locals, a chained one included. An
    assignment to a local or a parameter, or the declaration of a local that gives it a value, is
    a `local` when the value is no call's result (a call is its own item, and what it does is its
    body's); the registers the value reads are `input`."""
    decl = _DECL.match(text)
    declared = decl.group(1) if decl and decl.group(1) not in KEYWORDS else None
    kept = bool(decl and declared and (re.match(r"\s*static\b", text)
                                       or "&" in text[:decl.start(1)]))
    if declared and not kept:
        locals_.add(declared)
    assigned = _assignments(text)
    previous = 0
    for k, (a, b, op) in enumerate(assigned):
        left = text[previous:a].strip() or text[b:].strip()
        previous = b
        word = left.split()[-1] if left.split() else ""
        root = re.match(r"[\w:]*?([A-Za-z_]\w*)", word)
        through = bool(re.search(r"->|\.|\[|^\(?\*", left))
        own = declared if k == 0 and declared and re.search(
            rf"\b{re.escape(declared)}$", left) else None
        if own and kept:
            continue
        mine = own or (root.group(1) if root and not through and root.group(1) in locals_
                       else None)
        if mine:
            value = text[b:]
            if not _has_call(value):
                reading.add(line, "local", f"{mine} {op}")
            for _, register in _read_registers(value):
                reading.add(line, "input", f"{register} into {mine}")
        else:
            reading.add(line, "store", f"{left} {op}")
    if reading.stores and reading.stores.search(text) and not any(
            i.line == line and i.kind == "store" for i in reading.out):
        reading.add(line, "store", text[:80])


def _parameters(text: str, body: int) -> set[str]:
    """The parameters of the function whose body opens at `body` that a write to cannot reach the
    caller's object through: not a reference."""
    at = body - 1
    while at > 0 and (text[at - 1].isspace() or text[at - 5:at] == "const"):
        at -= 5 if text[at - 5:at] == "const" else 1
    if at <= 0 or text[at - 1] != ")":
        return set()
    depth, open_ = 0, at - 1
    while open_ >= 0:
        depth += (text[open_] == ")") - (text[open_] == "(")
        if depth == 0:
            break
        open_ -= 1
    names: set[str] = set()
    for part in re.split(r",", text[open_ + 1:at - 1]):
        part = part.split("=")[0]
        got = re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*$", part)
        if got and "&" not in part and got.group(1) not in KEYWORDS | TYPES:
            names.add(got.group(1))
    return names


def _rekey(text: str, reading: _Reading, conditional: bool) -> None:
    """Follows a store to the key's own variable: the values it can hold afterwards, or nothing
    decided from here on when the store is conditional or its value cannot be worked out."""
    key = reading.key
    if key is None or not re.search(rf"(?<![\w.>]){re.escape(key.name)}\b", text):
        return
    previous, found = 0, False
    for a, b, op in _assignments(text):
        left, previous = text[previous:a].strip(), b
        if not re.search(rf"(?<![\w.>]){re.escape(key.name)}$", left):
            continue
        found = True
        rhs = re.split(_ASSIGN, text[b:], maxsplit=1)[0].strip()
        expr = rhs if op == "=" else f"{key.name} {op[:-1]} ({rhs})"
        try:
            got = {_Expr(_simplified(expr), key.name, v).parse() for v in key.values()}
        except _Undecidable:
            got = set()
        if conditional or op in ("++", "--") or not got:
            reading.key = None
            return
        reading.key = Key(key.name, min(got), max(got), tuple(sorted(got)))
    if not found and re.search(rf"(\+\+|--)\s*{re.escape(key.name)}\b", text):
        reading.key = None


def _items(nodes: list[Node], reading: _Reading, locals_: set[str],
           conditional: bool = False) -> None:
    for n in nodes:
        if n.kind == "pre":
            continue
        reading.read.append(n)
        got = reading.key.evaluate(n.text) if reading.key and n.kind == "if" else None
        if n.kind == "if" and got is not None:
            took = bool(got)
            reading.add(n.line, "key", f"if ({n.text}) is always {str(took).lower()} "
                        "for this key")
            _items(n.body if took else n.orelse, reading, locals_, conditional)
        elif n.kind == "switch" and _switched(n, reading.key) is not None:
            reading.add(n.line, "key", f"switch ({n.text}) picks one case for this key")
            _items(_switched(n, reading.key) or [], reading, locals_, conditional)
        elif n.kind == "if":
            reading.add(n.line, "branch", f"if ({n.text})")
            _calls(n.text, n.line, reading)
            _inputs(n.text, n.line, reading)
            _items(n.body, reading, locals_, True)
            if n.orelse:
                if n.orelse[0].kind != "if":
                    reading.add(n.orelse[0].line, "branch", f"else of line {n.line}")
                _items(n.orelse, reading, locals_, True)
        elif n.kind == "loop":
            reading.add(n.line, "branch", n.text)
            _calls(n.text, n.line, reading)
            _inputs(n.text, n.line, reading)
            _items(n.body, reading, locals_, True)
        elif n.kind == "switch":
            reading.add(n.line, "branch", f"switch ({n.text})")
            _calls(n.text, n.line, reading)
            _inputs(n.text, n.line, reading)
            _items(n.body, reading, locals_, True)
        elif n.kind == "case":
            reading.add(n.line, "branch", n.text)
        elif n.kind == "block":
            _items(n.body, reading, locals_, conditional)
        elif n.kind == "exit":
            if conditional or n.text.startswith(("return", "throw", "goto")):
                reading.add(n.line, "exit", n.text)
            _calls(n.text, n.line, reading)
            _inputs(n.text, n.line, reading)
        else:
            if "?" in n.text:
                reading.add(n.line, "branch", f"ternary in: {n.text[:70]}")
            _stores(n.text, n.line, locals_, reading)
            _rekey(n.text, reading, conditional)
            _calls(n.text, n.line, reading)
            _inputs(n.text, n.line, reading)


def _switched(n: Node, key: Key | None) -> list[Node] | None:
    """The statements a switch on the key's own value runs for every value of the key, or None
    when it switches on something else or the values pick different cases."""
    if key is None or n.kind != "switch":
        return None
    picked = key.evaluate(n.text)
    if picked is None:
        return None
    wanted = str(picked)
    if not any(c.kind == "case" and _label_value(c.text) == wanted for c in n.body):
        if any(c.kind == "case" and c.text != "default" and not _numeric(c.text) for c in n.body):
            return None
        wanted = "default"
        if not any(c.kind == "case" and c.text == "default" for c in n.body):
            return []
    return _case_body(n, wanted)[1]


def _span_of(nodes: list[Node], parser: Parser, start: int) -> tuple[int, int]:
    first = min((n.line for n in nodes), default=parser.line(start))
    last = max((n.end or n.line for n in nodes), default=first)
    return first, last


def list_function(source: str, name: str, *, case: Iterable[str] = (), preamble: bool = False,
                  key: Key | None = None, defined: Iterable[str] = (),
                  stores: str = "") -> Listing:
    """The items the code of `name` owes rows for.

    With `case`, the region is the case reached by that path of switch labels, with the
    conditions that enclose it and the conditional exits that come before it; with `preamble`
    too, it is the statements that run before the dispatch instead. With neither, it is the
    whole function. `key` decides the tests of the key's own value, `defined` is what the build
    defines and `stores` names the calls that write to the guest.
    """
    text, build = one_build(blank(source), set(defined))
    start, stop = function(text, name)
    parser = Parser(text, start, stop)
    tree = parser.statements()
    reading = _Reading(key, re.compile(stores) if stores else None)
    region, before, path = tree, [], []
    lead: list[Node] = []
    opens = parser.line(start)
    paths = list(case)
    for wanted in paths:
        found = _find_switch(region, wanted, [], [], [])
        if not found:
            raise Invalid(f"no switch with a case {wanted} in {name}")
        label, region = _case_body(found.switch, wanted)
        opens = label.line
        path += [*found.path, f"{found.switch.line}: switch ({found.switch.text}) {label.text}"]
        before += found.before
        lead += found.lead
    if paths and preamble:
        region = lead
        path, before, opens = [], [], parser.line(start)
    first, last = _span_of(region, parser, start)
    first = min(first, opens)
    if not paths:
        first, last = parser.line(start), parser.line(stop)
    _items(region, reading, _parameters(text, start))
    if not region and not paths:
        reading.add(parser.line(start), "empty", "the function's body holds no statement")
    for node, conds in before:
        reading.add(node.line, "before", f"{node.text}  UNDER  {' AND '.join(conds)}")
    for line, what in build:
        if first <= line <= last:
            reading.add(line, "build", what)
    for step in path:
        number, _, condition = step.partition(": ")
        reading.add(int(number), "path", condition)
    items = sorted(set(reading.out))
    if not items:
        raise Invalid(f"{name} lists nothing: the region holds no statement the lister reads")
    return Listing(items, first, last, text, start, tree, reading.read)


def _bodies_in(nodes: list[Node], out: list[tuple[int, int]]) -> None:
    for n in nodes:
        if n.kind in ("if", "loop", "switch", "block"):
            out.append((n.line, n.end or n.line))
        if n.kind == "switch":
            for k, label in enumerate(n.body):
                if label.kind != "case":
                    continue
                run: list[Node] = []
                for later in n.body[k + 1:]:
                    run.append(later)
                    if _ends(later):
                        break
                out.append((label.line, max((x.end or x.line for x in run), default=label.line)))
        _bodies_in(n.body, out)
        _bodies_in(n.orelse, out)


def bodies(source: str, name: str, *, defined: Iterable[str] = ()) -> list[tuple[int, int]]:
    """The first and last line of every whole body in the function `name`: the function itself
    (from its signature or from its brace), each block, branch, loop and switch, and each case
    from its label to the exit that ends it."""
    text, _ = one_build(blank(source), set(defined))
    start, stop = function(text, name)
    parser = Parser(text, start, stop)
    opens, closes = parser.line(start), parser.line(stop)
    signature = text.rfind(name.rsplit("::", 1)[-1], 0, start)
    out = [(opens, closes), (parser.line(signature), closes)]
    _bodies_in(parser.statements(), out)
    return sorted(set(out))


def list_section(lines: list[str], lines_span: str) -> Listing:
    """A section of a list: every line that is not blank is an item."""
    first, last = span(lines_span)
    if last > len(lines):
        raise Invalid(f"lines {lines_span} are outside the file, which has {len(lines)} lines")
    items = [Item(n, "list", lines[n - 1].strip()) for n in range(first, last + 1)
             if lines[n - 1].strip()]
    if not items:
        raise Invalid(f"lines {lines_span} hold no text")
    return Listing(items, first, last)
