"""The format grammar: scalars, arrays, strings and structs, decoded in the target's order."""

from __future__ import annotations

import json
import math
import struct

import pytest

from scry_core import value_format as vf


def test_scalars_arrays_strings_and_structs_parse_with_their_sizes() -> None:
    assert vf.parse("u16").size is None and vf.parse("u16").kind == "scalar"
    assert vf.parse("u16[8]").size == 16 and vf.parse("u16[8]").kind == "array"
    assert vf.parse("char[16]").size == 16 and vf.parse("char[16]").kind == "string"
    s = vf.parse("{x:i16,y:i16,flags:u8,name:char[8],pal:u8[4]}")
    assert s.kind == "struct" and s.size == 2 + 2 + 1 + 8 + 4
    assert [n for n, _f in s.fields] == ["x", "y", "flags", "name", "pal"]
    assert vf.size_of(" u32 ") is None and vf.size_of("f32[2]") == 8
    # EACH SHAPE KEEPS ITS SPEC AND ITS COUNT, which a struct field and a pointer read back.
    assert (vf.parse("u16[8]").spec, vf.parse("u16[8]").count) == ("u16[8]", 8)
    assert (vf.parse("char[16]").spec, vf.parse("char[16]").count) == ("char[16]", 16)
    assert vf.parse("ptr32").spec == "ptr32" and vf.parse("ptr32").size == 4
    one = vf.parse("u16[1]")
    assert one.kind == "array" and one.count == 1, "an array of one is still an array"
    assert one.decode(b"\x00\x07", "big") == [7], "and decodes to a list of one"


@pytest.mark.parametrize("bad, names", [
    ("u64", "not a format"), ("u16[0]", "above zero"), ("u16[", "not a format"),
    ("{x:i16,x:u8}", "appears twice"), ("{}", "at least one field"), ("{x}", "name:type"),
    ("{a:{b:u8}}", "another struct"), ("char", "not a format"), ("int", "not a format"),
    ("", "not a format"), ("ptr32ptr16{x:u8}", "pointer to a pointer"),
])
def test_a_spec_outside_the_grammar_is_refused_naming_it(bad: str, names: str) -> None:
    with pytest.raises(vf.FormatError, match=names):
        vf.parse(bad)


def test_a_scalar_with_no_width_is_one_value_and_a_width_is_a_whole_number_of_it() -> None:
    u16 = vf.parse("u16")
    assert u16.width_for(2) == 2 and u16.width_for(6) == 6
    assert u16.width_for(0) == 2, "no width: one value of the scalar"
    with pytest.raises(vf.FormatError, match="whole number"):
        u16.width_for(3)
    arr = vf.parse("u16[4]")
    assert arr.width_for(0) == 8 and arr.width_for(8) == 8
    with pytest.raises(vf.FormatError, match="does not agree"):
        arr.width_for(6)


def test_values_decode_in_the_targets_byte_order() -> None:
    assert vf.parse("u16").decode(b"\x00\x38", "big", 2) == 0x38
    assert vf.parse("u16").decode(b"\x38\x00", "little", 2) == 0x38
    assert vf.parse("u16").decode(b"\x00\x01\x00\x02", "big", 4) == [1, 2]
    assert vf.parse("i8[3]").decode(b"\xff\x01\x80", "big") == [-1, 1, -128]
    assert vf.parse("char[6]").decode(b"RE\x00\x00\x00\x00", "little") == "RE"
    assert vf.parse("char[2]").decode(b"OK", "little") == "OK", "no NUL: the whole field"
    assert vf.parse("char[4]").decode(b"\0abc", "little") == "", "a NUL first: empty"
    s = vf.parse("{x:i16,y:i16,flags:u8,name:char[3]}")
    assert s.decode(b"\xff\xfe\x00\x10\x81ab\x00", "big") == {
        "x": -2, "y": 16, "flags": 0x81, "name": "ab"}
    assert s.decode(b"\xfe\xff\x10\x00\x81ab\x00", "little") == {
        "x": -2, "y": 16, "flags": 0x81, "name": "ab"}
    assert vf.parse("{v:f32}").decode(b"\x3f\x80\x00\x00", "big") == {"v": 1.0}
    with pytest.raises(vf.FormatError, match="reads 8 bytes; got 4"):
        vf.parse("u16[4]").decode(b"\0\0\0\0", "big")


def test_a_types_file_is_name_colon_format_per_line_and_refuses_the_rest() -> None:
    assert vf.read_types("# shapes\n\nhero: {x:i16,y:i16}\nscore : u16\n") == {
        "HERO": "{x:i16,y:i16}", "SCORE": "u16"}
    with pytest.raises(vf.FormatError, match="types:2: a types line"):
        vf.read_types("hero: u8\njust words\n")
    with pytest.raises(vf.FormatError, match="my.txt:1"):
        vf.read_types("hero: u64\n", "my.txt")
    with pytest.raises(vf.FormatError, match="names no type"):
        vf.read_types("# nothing\n")
    with pytest.raises(vf.FormatError, match="a types line"):
        vf.read_types(": u8\n")
    with pytest.raises(vf.FormatError, match="a types line"):
        vf.read_types("hero:\n")


def test_a_pointer_type_may_name_the_class_of_its_target() -> None:
    """`ptr16@CODE` and `ptr16@CODE{...}`: on a board relocated by `bases` a pointer's class
    is the BASE symbol's unless the type says otherwise, which is what a routine's address
    kept in DATA needs (on a V30, an offset under DATA is a different byte than the same
    offset under CODE). The class is part of the type, so it travels with the width
    and the target."""
    p = vf.parse("ptr16@CODE")
    assert p.kind == "pointer" and p.size == 2 and p.target is None
    assert p.target_class == "CODE"
    q = vf.parse("ptr32@DATA{x:i16,y:i16}")
    assert q.target_class == "DATA" and q.target is not None and q.target.size == 4
    assert vf.parse("ptr32{x:i16}").target_class is None
    assert vf.parse("ptr16@v30_jukebox").target_class == "V30_JUKEBOX", "classes are upper-cased"
    for bad in ("ptr16@", "ptr16@{x:u8}", "ptr16@1CODE", "ptr16@CO-DE", "ptr16 @CODE"):
        with pytest.raises(vf.FormatError, match="class"):
            vf.parse(bad)


def test_a_field_is_placed_by_the_sizes_before_it_and_a_pointer_ref_reads_its_type() -> None:
    """`field_offset` walks the fields in order, so the third field sits past the first two;
    a bare `[base]` of a typed pointer reads the whole target and an offset past it names
    no format, since the type says nothing about what sits there."""
    hero = vf.parse("{x:i16,y:i16,flags:u8,name:char[8]}")
    assert vf.field_offset(hero, "x") == (0, "i16")
    assert vf.field_offset(hero, "flags") == (4, "u8")
    assert vf.field_offset(hero, "name") == (5, "char[8]")
    with pytest.raises(vf.FormatError, match="has no field 'z'"):
        vf.field_offset(hero, "z")
    with pytest.raises(vf.FormatError, match="is not a struct"):
        vf.field_offset(vf.parse("u16"), "x")
    types = {"HERO": "ptr32{x:i16,y:i16}"}
    assert vf.pointer_field_fmt("[hero]", types) == "{x:i16,y:i16}"
    assert vf.pointer_field_fmt("hero->y", types) == "i16"
    assert vf.pointer_field_fmt("[hero]+0x28", types) is None
    assert vf.pointer_field_fmt("hero->z", types) is None
    assert vf.pointer_field_fmt("hero", types) is None, "not a pointer ref"
    assert vf.pointer_field_fmt("hero->x", {"HERO": "ptr32u16"}) is None, "no struct to field"


@pytest.mark.parametrize("spec, sizes", [
    ("{a:ptr32{x:u8,y:u8}}", {"a": 4}),
    ("{a:ptr16{x:u8,y:u16},b:u16[2],c:ptr32@CODE{p:i16,q:i16,r:u8}}", {"a": 2, "b": 4, "c": 4}),
])
def test_a_struct_field_may_point_at_a_struct_of_several_fields(
        spec: str, sizes: dict[str, int]) -> None:
    """The struct body is split at depth zero only: a comma inside the pointed-at struct belongs
    to it, not to the outer one, as the refusal of a nested struct already says a pointer may."""
    s = vf.parse(spec)
    assert s.kind == "struct" and {n: f.size for n, f in s.fields} == sizes
    a = dict(s.fields)["a"]
    assert a.kind == "pointer" and a.target is not None and a.target.kind == "struct"
    assert [n for n, _f in a.target.fields][:2] == ["x", "y"]


@pytest.mark.parametrize("bad", ["{a:ptr32{x:u8}", "{a:u8}}", "{a:ptr32{x:u8,y:u8}},b:u8}"])
def test_a_struct_whose_braces_do_not_balance_is_refused(bad: str) -> None:
    with pytest.raises(vf.FormatError, match="braces do not balance"):
        vf.parse(bad)


@pytest.mark.parametrize("bad", ["{x:u8,,y:u8}", "{x:u8,}", "{,x:u8}"])
def test_an_empty_struct_field_is_refused(bad: str) -> None:
    with pytest.raises(vf.FormatError, match="an empty field"):
        vf.parse(bad)


@pytest.mark.parametrize("bad", ["u64[2]", "float[3]", "{v:i64[4]}"])
def test_an_array_of_a_scalar_the_table_does_not_name_is_refused(bad: str) -> None:
    with pytest.raises(vf.FormatError, match="not a format"):
        vf.parse(bad)


def test_every_scalar_the_table_names_parses_alone_and_in_an_array(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`SCALARS` is the one list of scalar names: one added there parses as a scalar and as an
    array element with nothing else edited."""
    monkeypatch.setitem(vf.SCALARS, "u64", ("Q", 8))
    assert vf.parse("u64").kind == "scalar"
    assert vf.parse("u64[2]").size == 16
    assert vf.parse("{v:u64}").size == 8


def test_the_refusals_name_every_shape_and_a_positive_length() -> None:
    with pytest.raises(vf.FormatError, match="a pointer like ptr32"):
        vf.parse("ptr64")
    with pytest.raises(vf.FormatError, match="positive whole number"):
        vf.parse("u32").width_for(-4)


@pytest.mark.parametrize("spec, raw, want", [
    ("f32", struct.pack("<f", math.nan), "nan"),
    ("f32", struct.pack("<f", math.inf), "inf"),
    ("f64", struct.pack("<d", -math.inf), "-inf"),
    ("f32[2]", struct.pack("<ff", 1.5, math.nan), [1.5, "nan"]),
    ("{a:f64,b:u8}", struct.pack("<dB", math.inf, 7), {"a": "inf", "b": 7}),
])
def test_a_float_that_json_cannot_carry_is_rendered_as_its_text(
        spec: str, raw: bytes, want: object) -> None:
    """NaN and the infinities are not JSON numbers: rendered as `nan`, `inf`, `-inf`, a reply
    stays valid JSON and says what the bytes hold; a finite float stays a number."""
    got = vf.parse(spec).decode(raw, "little")
    assert got == want
    json.dumps(got, allow_nan=False)


def test_a_count_past_the_integer_limit_is_a_format_error() -> None:
    with pytest.raises(vf.FormatError, match="count"):
        vf.parse("u8[" + "9" * 5000 + "]")
