"""How a watched value is TYPED, in three grammars that serve one question: the FORMAT of its
bytes (`parse`, below), the `types` file that names a format per symbol (`read_types`), and the
pointer REF that reads through one (`parse_pointer`: `[ref]+off` or `base->field`, the field
found in the base's format). They live together because each of the other two is read through
the first.

THE FORMAT: a scalar, an array of scalars, a string or a struct. A symbol table gives
addresses, not types, so a watch declares how its bytes read, and the grammar names the shape,
so a struct reads as its fields and a name as text:

    u16              one scalar; a `length` that is a whole number of them reads a list
    u16[8]           an array, eight of them, the width implied
    char[16]         a string of up to 16 bytes, cut at the first NUL
    {x:i16,y:i16,flags:u8,name:char[8]}   a struct, fields in declaration order
    ptr32            a pointer, 4 bytes (ptr16: 2), read as the number it holds
    ptr32{x:i16,y:i16}   a pointer AND what it points at, so `base->field` knows the
                     field's offset and format; the pointer's width is part of the type
    ptr16@CODE{...}  a pointer whose TARGET lives in a named class: on a board relocated
                     by class (a linker map with `bases`) the pointer's value is an offset
                     in that class's segment, and the class decides the base it is placed
                     under; without it the base symbol's own class does. A server with no
                     classes reads the type and applies nothing.

A format that names its own size (an array, a string, a struct) needs no `length`, and a
bare scalar with none reads as one value; `length` is TOTAL bytes, a whole number of the
scalar, and more than one of them reads as a list. The
byte order is the target's, which the session knows and this module does not.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

# The grammar's version, bumped when it changes: a consumer can assert the grammar it reads.
FORMAT_VERSION = 4

SCALARS: dict[str, tuple[str, int]] = {
    "u8": ("B", 1), "i8": ("b", 1), "u16": ("H", 2), "i16": ("h", 2),
    "u32": ("I", 4), "i32": ("i", 4), "f32": ("f", 4), "f64": ("d", 8),
}
Value = int | float | str | list["Value"] | dict[str, "Value"]

# THE SCALAR NAMES ARE `SCALARS`' KEYS AND NOWHERE ELSE: the array's element is read by shape
# and then looked up there, so a scalar added to the table parses everywhere a scalar may sit.
_ARRAY = re.compile(r"^([a-z][a-z0-9]*)\[(\d+)\]$")
_FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.+)$")
_POINTER = re.compile(r"^ptr(16|32)(@[^{]*)?(.*)$", re.S)
_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FormatError(ValueError):
    """A format spec this grammar does not read; the message names what was expected."""


@dataclass(frozen=True)
class Format:
    """One parsed format: its `spec`, its `size` in bytes (None for a bare scalar, whose
    size is the caller's `length`) and the shape it decodes to. A scalar WITH a size is a
    struct field: one value, sliced by the struct's decoder."""

    spec: str
    kind: str                       # scalar | array | string | struct | pointer
    size: int | None
    elem: str | None = None         # the scalar of a scalar or an array, or of a pointer
    count: int | None = None        # of an array or a string
    fields: tuple[tuple[str, Format], ...] = ()
    target: Format | None = None    # what a pointer points at, when its type says
    target_class: str | None = None  # the class the pointer's target lives in, when named

    def width_for(self, width: int) -> int:
        """The bytes this format reads for the caller's `width`: its own size when it
        has one (a width given must agree), else one scalar with no width, and otherwise
        the width, a whole number of scalars."""
        if self.size is not None:
            if width not in (0, self.size):
                raise FormatError(f"{self.spec} is {self.size} bytes; length={width} does not "
                                  "agree with it (leave length out for a sized format)")
            return self.size
        assert self.elem is not None
        elem = SCALARS[self.elem][1]
        if width == 0:
            return elem
        if width < 0 or width % elem:
            raise FormatError(f"a length of {width} is not a positive whole number of "
                              f"{self.spec} values ({elem} bytes each): `length` is the TOTAL "
                              "bytes read as that format, one value per scalar; leave it out "
                              "for one value")
        return width

    def decode(self, raw: bytes, order: str, width: int = 0) -> Value:
        """The bytes as this format's value, in the target's byte order (`little`|`big`)."""
        n = self.width_for(width)
        if len(raw) != n:
            raise FormatError(f"{self.spec} reads {n} bytes; got {len(raw)}")
        end = ">" if order == "big" else "<"
        if self.kind in ("scalar", "array", "pointer"):
            assert self.elem is not None
            code, elem = SCALARS[self.elem]
            values: list[Value] = [struct.unpack(end + code, raw[i:i + elem])[0]
                                   for i in range(0, n, elem)]
            return values if self.kind == "array" or len(values) > 1 else values[0]
        if self.kind == "string":
            cut = raw.find(b"\0")
            return (raw if cut < 0 else raw[:cut]).decode("latin-1")
        out: dict[str, Value] = {}
        at = 0
        for name, fmt in self.fields:
            assert fmt.size is not None
            out[name] = fmt.decode(raw[at:at + fmt.size], order)
            at += fmt.size
        return out


def parse(spec: str) -> Format:
    """A `Format` from its spec, or a `FormatError` naming what the grammar takes."""
    spec = spec.strip()
    if spec in SCALARS:
        return Format(spec, "scalar", None, elem=spec)
    pm = _POINTER.match(spec)
    if pm:
        bits, at, rest = int(pm.group(1)), pm.group(2), pm.group(3).strip()
        klass: str | None = None
        if at is not None:
            klass = at[1:].strip()
            if not _CLASS.match(klass):
                raise FormatError(f"{spec}: the class after `@` is a name like CODE or DATA "
                                  f"(a letter or underscore, then letters, digits, underscore); "
                                  f"got {klass!r}")
            klass = klass.upper()      # classes are keyed upper-case
        if rest.startswith("@"):
            raise FormatError(f"{spec}: the class goes right after the width, `ptr{bits}@CODE`")
        target = parse(rest) if rest else None
        if target is not None and target.kind == "pointer":
            raise FormatError(f"{spec}: a pointer to a pointer is not a shape this reads")
        return Format(spec, "pointer", bits // 8, elem=f"u{bits}", target=target,
                      target_class=klass)
    m = _ARRAY.match(spec)
    if m and (m.group(1) in SCALARS or m.group(1) == "char"):
        elem, count = m.group(1), int(m.group(2))
        if count <= 0:
            raise FormatError(f"{spec}: an array or a string needs a count above zero")
        if elem == "char":
            return Format(spec, "string", count, count=count)
        return Format(spec, "array", count * SCALARS[elem][1], elem=elem, count=count)
    if spec.startswith("{") and spec.endswith("}"):
        fields: list[tuple[str, Format]] = []
        seen: set[str] = set()
        if not spec[1:-1].strip():
            raise FormatError(f"{spec}: a struct needs at least one field")
        for part in (p.strip() for p in _fields_of(spec)):
            if not part:
                raise FormatError(f"{spec}: an empty field (two commas, or one at an end)")
            fm = _FIELD.match(part)
            if fm is None:
                raise FormatError(f"{spec}: a struct field is `name:type`; got {part!r}")
            name, sub = fm.group(1), parse(fm.group(2))
            if sub.kind == "struct":
                raise FormatError(f"{spec}: a struct field is a scalar, an array, a "
                                  f"string or a pointer, not another struct ({name})")
            if sub.size is None:
                assert sub.elem is not None
                sub = Format(sub.spec, "scalar", SCALARS[sub.elem][1], elem=sub.elem)
            if name in seen:
                raise FormatError(f"{spec}: the field {name!r} appears twice")
            seen.add(name)
            fields.append((name, sub))
        return Format(spec, "struct", sum(f.size or 0 for _n, f in fields),
                      fields=tuple(fields))
    raise FormatError(f"{spec!r} is not a format: a scalar ({', '.join(SCALARS)}), an array "
                      "like u16[8], a string like char[16], a struct like "
                      "{x:i16,y:i16,flags:u8}, or a pointer like ptr32 or ptr32{x:i16}")


def _fields_of(spec: str) -> list[str]:
    """A struct spec's body cut at its top-level commas: a comma inside a pointed-at struct
    (`{a:ptr32{x:u8,y:u8}}`) is that struct's. Braces that do not balance are refused."""
    parts: list[str] = []
    depth, start = 0, 1
    for i, ch in enumerate(spec[1:-1], start=1):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                break
        elif ch == "," and depth == 0:
            parts.append(spec[start:i])
            start = i + 1
    if depth != 0:
        raise FormatError(f"{spec}: its braces do not balance")
    return [*parts, spec[start:-1]]


def size_of(spec: str) -> int | None:
    """The size a spec implies, or None for a bare scalar."""
    return parse(spec).size


def field_offset(struct: Format, name: str) -> tuple[int, str]:
    """Where `name` sits inside a struct format, and the field's own spec: fields lie in
    declaration order with no padding, as `decode` reads them. A pointer type names what it
    points at, so `base->field` reads the field's offset and format from here."""
    if struct.kind != "struct":
        raise FormatError(f"{struct.spec} is not a struct, so it has no field {name!r}")
    at = 0
    for field, fmt in struct.fields:
        assert fmt.size is not None
        if field == name:
            return at, fmt.spec
        at += fmt.size
    raise FormatError(f"{struct.spec} has no field {name!r}; its fields are "
                      f"{', '.join(f for f, _ in struct.fields)}")


def read_types(text: str, where: str = "types") -> dict[str, str]:
    """A `types` file's text: one `name: format` per line (`#` comments and blank lines
    skipped), each format checked against the grammar and refused by line when it is not
    one; names are upper-cased, as the tables are keyed. An empty file is refused:
    a parameter that types nothing would be honoured by nothing."""
    out: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, spec = stripped.partition(":")
        if not sep or not name.strip() or not spec.strip():
            raise FormatError(f"{where}:{lineno}: a types line is `name: format`; "
                              f"got {stripped!r}")
        try:
            parse(spec)
        except FormatError as e:
            raise FormatError(f"{where}:{lineno}: {e}") from None
        out[name.strip().upper()] = spec.strip()
    if not out:
        raise FormatError(f"{where} names no type at all")
    return out


# --------------------------------------------------------------- a place through a pointer

_DEREF = re.compile(r"^\[\s*([^\[\]\s]+)\s*\]\s*(?:([+-])\s*(0[xX][0-9a-fA-F]+|[0-9a-fA-F]+))?$")
_ARROW = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class PointerRef:
    """A pointer ref taken apart: the global holding the pointer, the byte offset past
    where it points (signed, hex in the ref; a field's offset when named), and the field,
    when `->`. The grammar is `[base]`, `[base]+0x28`, `[base]-0x4` or `base->field`, with
    `base` a symbol or an address in the server's own spelling; one shape on both."""

    base: str
    offset: int
    field: str | None


def parse_pointer(ref: str) -> PointerRef | None:
    """The pointer ref in `ref`, or None for any other shape (a symbol, an address), so the
    shape decides how a declaration is made, as it does for those two."""
    text = ref.strip()
    m = _DEREF.match(text)
    if m:
        sign, digits = m.group(2), m.group(3)
        offset = int(digits, 16) if digits else 0
        return PointerRef(m.group(1), -offset if sign == "-" else offset, None)
    m = _ARROW.match(text)
    if m:
        return PointerRef(m.group(1), 0, m.group(2))
    return None


def pointer_field_fmt(ref: str, types: dict[str, str]) -> str | None:
    """The format a pointer ref reads with when the caller names none: a `base->field`'s
    field, from the base's pointer type in `types` (keyed upper-case, as the tables
    are), or the whole target for a bare `[base]`; None when the ref is not that
    shape or the type does not say."""
    pr = parse_pointer(ref)
    if pr is None:
        return None
    spec = types.get(pr.base.strip().upper())
    if spec is None:
        return None
    fmt = parse(spec)
    if fmt.kind != "pointer" or fmt.target is None:
        return None
    if pr.field is None:
        # A bare deref of a typed pointer reads what it points at, whole, when nothing
        # else is asked: the type already names the shape. With an offset, the caller
        # names the format, since the type says nothing about what sits past the struct.
        return fmt.target.spec if pr.offset == 0 else None
    if fmt.target.kind != "struct":
        return None
    try:
        return field_offset(fmt.target, pr.field)[1]
    except FormatError:
        return None
