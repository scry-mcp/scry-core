"""Value types in three grammars: the FORMAT of a value's bytes (`parse`), the `types` file
naming a format per symbol (`read_types`), and the pointer REF that reads through one
(`parse_pointer`: `[ref]+off` or `base->field`).

    u16              one scalar; a `length` that is a whole number of them reads a list
    u16[8]           an array, eight of them
    char[16]         a string of up to 16 bytes, cut at the first NUL
    {x:i16,y:i16,flags:u8,name:char[8]}   a struct, fields in declaration order
    ptr32            a pointer, 4 bytes (ptr16: 2), read as the number it holds
    ptr32{x:i16,y:i16}   a pointer AND its target, so `base->field` knows the field's
                     offset and format
    ptr16@CODE{...}  a pointer whose target lives in a named class (an offset in that
                     class's segment); without it the base symbol's class applies.
                     A server with no classes ignores it.

A sized format needs no `length`; `length` is TOTAL bytes. A NaN or infinite float reads as
the text `nan`, `inf` or `-inf`. Byte order is the session's, not this module's.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass

# Bumped when the grammar changes, so a consumer can assert what it reads.
FORMAT_VERSION = 4

SCALARS: dict[str, tuple[str, int]] = {
    "u8": ("B", 1), "i8": ("b", 1), "u16": ("H", 2), "i16": ("h", 2),
    "u32": ("I", 4), "i32": ("i", 4), "f32": ("f", 4), "f64": ("d", 8),
}
Value = int | float | str | list["Value"] | dict[str, "Value"]

# Scalar names live only in `SCALARS`; the array element is matched by shape, then looked up.
_ARRAY = re.compile(r"^([a-z][a-z0-9]*)\[(\d+)\]$")
# `int()` refuses past 4300 digits with a plain ValueError, which no caller catches
_COUNT_DIGITS_MAX = 12
_FIELD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(.+)$")
_POINTER = re.compile(r"^ptr(16|32)(@[^{]*)?(.*)$", re.S)
_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FormatError(ValueError):
    """A format spec this grammar does not read."""


@dataclass(frozen=True)
class Format:
    """One parsed format; `size` is None for a bare scalar (the caller's `length` decides).
    A scalar WITH a size is a struct field."""

    spec: str
    kind: str                       # scalar | array | string | struct | pointer
    size: int | None
    elem: str | None = None         # the scalar of a scalar or an array, or of a pointer
    count: int | None = None        # of an array or a string
    fields: tuple[tuple[str, Format], ...] = ()
    target: Format | None = None    # what a pointer points at, when its type says
    target_class: str | None = None  # the class the pointer's target lives in, when named

    def width_for(self, width: int) -> int:
        """The bytes to read for the caller's `width`; a width given must agree with its own
        size."""
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
            values: list[Value] = [_json_number(struct.unpack(end + code, raw[i:i + elem])[0])
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


def _json_number(v: int | float) -> Value:
    """NaN and the infinities are no JSON number, so they become text."""
    if isinstance(v, float) and not math.isfinite(v):
        return "nan" if math.isnan(v) else ("inf" if v > 0 else "-inf")
    return v


def parse(spec: str) -> Format:
    """A `Format` from its spec, or a `FormatError` naming what the grammar takes."""
    try:
        return _parse(spec)
    except RecursionError:
        raise FormatError(f"{spec[:40]}...: nested deeper than this reads") from None


def _parse(spec: str) -> Format:
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
            klass = klass.upper()
        if rest.startswith("@"):
            raise FormatError(f"{spec}: the class goes right after the width, `ptr{bits}@CODE`")
        target = _parse(rest) if rest else None
        if target is not None and target.kind == "pointer":
            raise FormatError(f"{spec}: a pointer to a pointer is not a shape this reads")
        return Format(spec, "pointer", bits // 8, elem=f"u{bits}", target=target,
                      target_class=klass)
    m = _ARRAY.match(spec)
    if m and (m.group(1) in SCALARS or m.group(1) == "char"):
        if len(digits := m.group(2).lstrip("0")) > _COUNT_DIGITS_MAX:
            raise FormatError(f"{spec[:40]}...: a count of {len(digits)} digits is past any "
                              f"memory this reads")
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
            name, sub = fm.group(1), _parse(fm.group(2))
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
    """A struct body cut at its top-level commas (not those of a pointed-at struct)."""
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
    """Where `name` sits in a struct format, and its spec; fields have no padding."""
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
    """A `types` file: one `name: format` per line; an empty file is refused."""
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


_DEREF = re.compile(r"^\[\s*([^\[\]\s]+)\s*\]\s*(?:([+-])\s*(0[xX][0-9a-fA-F]+|[0-9a-fA-F]+))?$")
_ARROW = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*->\s*([A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class PointerRef:
    """A pointer ref taken apart: `[base]`, `[base]+0x28`, `[base]-0x4` or `base->field`."""

    base: str
    offset: int
    field: str | None


def parse_pointer(ref: str) -> PointerRef | None:
    """The pointer ref in `ref`, or None for any other shape (a symbol, an address)."""
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
    """The format a pointer ref reads with when the caller names none, from `types`
    (keyed upper-case); None when the ref or the type does not say."""
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
        # With an offset the type says nothing about what sits there, so the caller names it.
        return fmt.target.spec if pr.offset == 0 else None
    if fmt.target.kind != "struct":
        return None
    try:
        return field_offset(fmt.target, pr.field)[1]
    except FormatError:
        return None
