"""`scry_core.knowledge.cover`: the items a handler's code owes rows for."""

from __future__ import annotations

from typing import Any

import pytest
from rows_world import FIXTURES

from scry_core.knowledge import cover
from scry_core.knowledge.quote import Invalid

CHIP = (FIXTURES / "mame/src/devices/machine/chipx.cpp").read_text(encoding="utf-8")
DOS = (FIXTURES / "dosbox/src/ints/call.cpp").read_text(encoding="utf-8")


def items(source: str, name: str, **kw: Any) -> list[tuple[int, str, str]]:
    return [(i.line, i.kind, i.text) for i in cover.list_function(source, name, **kw).items]


def kinds(source: str, name: str, **kw: Any) -> list[tuple[int, str]]:
    return [(line, kind) for line, kind, _ in items(source, name, **kw)]


def test_the_command_a_key_reaches_lists_what_the_key_does_not_decide() -> None:
    got = items(CHIP, "chipx_device::write", case=["0"], key=cover.parse_key("data=0xE0..0xE7"))
    assert got == [
        (10, "path", "switch (offset) case 0"),
        (13, "key", "if (data & 0x10) is always false for this key"),
        (17, "branch", "if (m_state == state_t::READY)"),
        (19, "call", "LOG_CMD"),
        (20, "key", "if ((data & 0xe0) == 0xe0) is always true for this key"),
        (22, "local", "level ="),
        (23, "local", "mask ="),
        (24, "branch", "if (m_isr & mask)"),
        (26, "store", "m_isr &="),
        (27, "store", "m_base =")]


def test_a_key_that_splits_a_test_leaves_it_a_branch() -> None:
    got = kinds(CHIP, "chipx_device::write", case=["0"], key=cover.parse_key("data=0xD0..0xE7"))
    assert (20, "branch") in got and (20, "key") not in got


def test_a_function_with_no_key_lists_every_branch() -> None:
    got = kinds(CHIP, "chipx_device::write", case=["0"])
    assert (13, "branch") in got and (20, "branch") in got and (15, "call") in got


def test_a_case_that_is_not_in_the_function_is_invalid() -> None:
    with pytest.raises(Invalid, match="no switch with a case 9"):
        cover.list_function(CHIP, "chipx_device::write", case=["9"])


def test_a_function_that_is_not_in_the_file_is_invalid() -> None:
    with pytest.raises(Invalid, match="no definition of nowhere"):
        cover.list_function(CHIP, "nowhere")


def test_a_region_that_lists_nothing_is_invalid_and_never_an_empty_list() -> None:
    with pytest.raises(Invalid, match="lists nothing"):
        cover.list_function("void f() { int a; }", "f")


def test_a_function_defined_through_a_macro_is_found() -> None:
    assert items(CHIP, "chipx_device::tick") == [
        (49, "store", "m_count ="), (49, "store", "m_reload ="), (50, "call", "chipx_irq")]


def test_a_function_named_in_a_macro_that_defers_it_is_a_call_of_that_function() -> None:
    got = items(CHIP, "chipx_device::start")
    assert (55, "call", "chipx_device::tick") in got and (55, "call", "FUNC") not in got


def test_a_function_with_no_statement_is_one_item() -> None:
    assert items(CHIP, "chipx_device::idle") == [
        (59, "empty", "the function's body holds no statement")]


def test_a_chained_assignment_is_a_store_for_each_target() -> None:
    got = items("void f() { m_a = m_b = false; }", "f")
    assert [t for _, k, t in got if k == "store"] == ["m_a =", "m_b ="]


def test_the_declaration_of_a_pointer_is_no_store_and_its_chained_assignment_is() -> None:
    src = "void f() {\n  Block *p = &blocks[n];\n  Result r = p->last = p->read();\n}\n"
    got = items(src, "f")
    assert [t for _, k, t in got if k == "store"] == ["p->last ="]


def test_a_local_or_a_parameter_assigned_is_a_local_and_no_store() -> None:
    got = items("void f(int offset) { int x; x = 1; offset &= 3; }", "f")
    assert [t for _, k, t in got if k == "store"] == []
    assert sorted(t for _, k, t in got if k == "local") == ["offset &=", "x ="]


def test_a_declaration_gives_a_local_only_when_it_gives_a_value() -> None:
    got = items("void f() { Bitu a = 1; Bitu b; int *p = &x; }", "f")
    assert [t for _, k, t in got if k == "local"] == ["a =", "p ="]


def test_an_assignment_of_what_a_call_returns_is_no_local_for_the_call_is_the_item() -> None:
    got = items("void f() {\n  Bitu a = get(1);\n  a = 2;\n  Bitu b = x ? get() : 0;\n}\n", "f")
    assert [(n, k) for n, k, _ in got if k == "local"] == [(3, "local")]
    assert [n for n, k, _ in got if k == "call"] == [2, 4]


def test_a_reference_parameter_assigned_is_a_store_for_it_reaches_the_caller() -> None:
    got = items("void f(Foo &state, Bar bar) { state = 1; bar = 2; }", "f")
    assert sorted((k, t) for _, k, t in got) == [("local", "bar ="), ("store", "state =")]


def test_an_assignment_through_a_local_is_still_a_store() -> None:
    got = items("void f(Foo *p) { Foo q; q.x = 1; p->y = 2; p[0] = 3; }", "f")
    assert sorted(t for _, k, t in got if k == "store") == ["p->y =", "p[0] =", "q.x ="]


def test_an_indexed_or_dereferenced_target_ending_in_a_local_is_still_a_store() -> None:
    src = ("void f(Bitu offset, Bitu data) {\n  Bitu n;\n  m_regs[4 + offset] = data;\n"
           "  *(p + n) = data;\n  m_regs[n] = data;\n}\n")
    assert [(n, k) for n, k, _ in items(src, "f")] == [(3, "store"), (4, "store"), (5, "store")]


def test_a_static_or_a_reference_local_is_state_the_caller_or_a_later_call_sees() -> None:
    src = "void f() {\n  static Bitu n = 0;\n  n++;\n  Bitu &r = g;\n  r = 1;\n}\n"
    got = items(src, "f")
    assert [(n, k) for n, k, _ in got] == [(3, "store"), (5, "store")]


def test_a_chain_that_ends_in_a_call_gives_no_local_for_any_target_of_it() -> None:
    got = items("void f() {\n  Bitu t = u = g();\n}\n", "f")
    assert [k for _, k, _ in got if k == "local"] == []


def test_a_register_met_after_a_bitwise_and_is_read_and_after_an_address_of_is_not() -> None:
    src = "void f() {\n  foo(mask & reg_al);\n  bar(ok && reg_dl);\n  baz(&reg_ax);\n}\n"
    got = [(n, t) for n, k, t in items(src, "f") if k == "input"]
    assert got == [(2, "reg_al to foo"), (3, "reg_dl to bar")]


def test_a_guest_register_handed_to_a_call_or_a_local_is_an_input() -> None:
    src = ("void f() {\n  uint8_t drive;\n  MEM_StrCopy(SegPhys(ds) + reg_dx, name, 9);\n"
           "  uint32_t handle = RealHandle(reg_bx);\n  drive = reg_bl;\n"
           "  if (DOS_Close(reg_cx, &reg_al)) {}\n}\n")
    got = items(src, "f")
    assert [(n, t) for n, k, t in got if k == "input"] == [
        (3, "reg_dx to MEM_StrCopy"), (4, "reg_bx into handle"), (4, "reg_bx to RealHandle"),
        (5, "reg_bl into drive"), (6, "reg_cx to DOS_Close")]
    assert (4, "local", "handle =") not in got and (5, "local", "drive =") in got


def test_a_register_stored_into_state_the_function_does_not_own_is_a_store_and_no_input() -> None:
    got = items("void f() {\n  m_latch = reg_bl;\n}\n", "f")
    assert [(k, t) for _, k, t in got] == [("store", "m_latch =")]


@pytest.mark.parametrize(("register", "kin"), [
    ("reg_al", "a"), ("reg_ax", "a"), ("reg_ah", "a"), ("reg_bl", "b"), ("reg_dx", "d"),
    ("reg_si", "si"), ("ds", "ds")])
def test_the_halves_of_a_register_are_one_family(register: str, kin: str) -> None:
    assert cover.family(register) == kin


@pytest.mark.parametrize("body", [
    "if (reg_al & 1) mode |= 8;", "if (reg_al == 3) { reg_ax = 0; }", "reg_ax = 7;",
    "x = &reg_ax;", "reg_al += 1;", "foo(&reg_ax);", "foo(reg_ax_value);", "foo(a.reg_ax);"])
def test_a_register_only_tested_or_written_is_no_input(body: str) -> None:
    got = items(f"void f() {{\n  int mode;\n  {body}\n}}\n", "f")
    assert not [i for i in got if i[1] == "input"]


def test_a_call_the_stores_pattern_names_is_a_store() -> None:
    got = kinds("void f() { real_writeb(a, b, c); }", "f", stores="real_writeb")
    assert got == [(1, "call"), (1, "store")]


def test_the_statements_before_the_dispatch_are_the_handlers_own_region() -> None:
    got = items(DOS, "Handler", case=["0x5a"], preamble=True)
    assert got == [
        (4, "branch", "if (reg_ah == 0x06 || reg_ah == 0x07)"),
        (5, "exit", "return CBRET_NONE"),
        (7, "store", "dos.breakcheck =")]


def test_a_conditional_exit_before_the_dispatch_is_listed_as_coming_before() -> None:
    got = items(DOS, "Handler", case=["0x5a"])
    assert (5, "before", "return CBRET_NONE  UNDER  4: reg_ah == 0x06 || reg_ah == 0x07") in got


def test_nested_cases_list_the_path_and_the_exits_that_come_first() -> None:
    got = kinds(DOS, "Video", case=["0x12", "0x31"])
    assert got == [(43, "before"), (44, "path"), (47, "before"), (49, "path"), (51, "branch"),
                   (52, "store"), (53, "exit"), (55, "store")]


def test_a_break_inside_a_nested_switch_leaves_only_that_switch() -> None:
    src = ("void f() {\n switch (a) {\n case 1:\n  switch (b) {\n  case 2:\n   x = 1;\n"
           "   break;\n  }\n  y = 2;\n  break;\n }\n}\n")
    assert kinds(src, "f", case=["1"]) == [(2, "path"), (4, "branch"), (5, "branch"),
                                           (6, "store"), (7, "exit"), (9, "store")]


def test_an_arm_the_build_does_not_compile_is_said_and_not_read() -> None:
    got = items(DOS, "Handler", case=["0x5a"])
    assert (19, "build", "#else : not compiled, not read") in got
    assert not any(line == 20 for line, _, _ in got)


def test_the_defines_of_the_build_choose_the_arm() -> None:
    got = items(DOS, "Handler", case=["0x5a"], defined=["NOFILES"])
    assert any(t == "#else : compiled" for _, k, t in got if k == "build")
    assert (20, "store", "reg_ax =") in got and not any(line == 11 for line, _, _ in got)


def test_a_condition_the_reader_cannot_decide_is_taken_and_said() -> None:
    src = "void f() {\n#if FEATURE(2)\n x = 1;\n#else\n x = 2;\n#endif\n}\n"
    assert (2, "build", "#if FEATURE(2): UNDECIDED, first arm read") in items(src, "f")


@pytest.mark.parametrize(("cond", "name", "values", "want"), [
    ("data & 0x10", "data", (0xE0, 0xE7), 0),
    ("(data & 0xe0) == 0xe0", "data", (0xE0, 0xE7), 1),
    ("!data & 1", "data", (2, 2), 0),            # `!` binds tighter than `&`
    ("!(data & 1)", "data", (2, 2), 1),
    ("data >> 1 == 1", "data", (2, 3), 1),
    ("BIT(data, 1)", "data", (2, 3), 1),
    ("GCC_UNLIKELY(val & 0x08)", "val", (0xE0, 0xE7), 0),
    ("(uint8_t)data < 0x80u", "data", (0, 5), 1),
    ("data == 1 || data == 2", "data", (1, 2), 1),
    ("data % 2 == 0 && data / 2 == 1", "data", (2, 2), 1),
    ("data + 1 * 2 == 4", "data", (2, 2), 1)])
def test_a_test_of_the_keys_own_value_is_decided_by_c_precedence(
        cond: str, name: str, values: tuple[int, int], want: int) -> None:
    assert cover.Key(name, *values).evaluate(cond) == want


@pytest.mark.parametrize("cond", ["data & 1", "other == 1", "data == other", "data ? 1 : 0",
                                  "data << 99", "data / 0", "f(data)"])
def test_a_test_the_values_split_or_that_names_anything_else_is_not_decided(cond: str) -> None:
    assert cover.Key("data", 0, 3).evaluate(cond) is None


def test_a_key_is_name_equals_a_value_or_a_range() -> None:
    assert cover.parse_key("data=0xE0..0xE7") == cover.Key("data", 224, 231)
    assert cover.parse_key("n=3") == cover.Key("n", 3, 3)


@pytest.mark.parametrize("text", ["", "data", "=3", "data=", "data=9..1", "data=x", "1a=3"])
def test_a_key_that_is_not_one_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="a value is"):
        cover.parse_key(text)


def test_a_switch_on_the_key_runs_the_case_every_value_picks() -> None:
    src = "void f() { switch (v & 0xe0) { case 0xe0: a = 1; break; default: b = 2; } }"
    got = items(src, "f", key=cover.parse_key("v=0xE0..0xE7"))
    assert [(k, t) for _, k, t in got] == [
        ("key", "switch (v & 0xe0) picks one case for this key"), ("store", "a =")]


def test_a_section_of_a_list_gives_each_line_that_is_not_blank() -> None:
    held = ["INT 21 - TITLE", "", "AH = 5Ah", "  Return: CF clear"]
    got = cover.list_section(held, "1-4")
    assert [(i.line, i.text) for i in got.items] == [
        (1, "INT 21 - TITLE"), (3, "AH = 5Ah"), (4, "Return: CF clear")]
    assert (got.first, got.last) == (1, 4)


def test_a_section_outside_the_file_or_with_no_text_is_invalid() -> None:
    with pytest.raises(Invalid, match="outside the file"):
        cover.list_section(["a"], "1-3")
    with pytest.raises(Invalid, match="hold no text"):
        cover.list_section(["a", " "], "2")


def test_the_committed_form_of_an_item_is_its_kind_file_line_and_digest_and_no_text() -> None:
    lines = CHIP.split("\n")
    item = cover.list_function(CHIP, "chipx_device::idle").items[0]
    record = item.record("src/devices/machine/chipx.cpp", lines)
    assert set(record) == {"kind", "file", "line", "sha"}
    assert record["line"] == 59 and len(str(record["sha"])) == 64
    assert "holds no statement" not in str(record) and "idle" not in str(record)


def test_comments_and_literals_hide_their_text_from_the_reader() -> None:
    src = ('void f() {\n  // if (a) { b(); }\n  /* c(); \n d(); */\n  s = "if (x) { y(); }";\n'
           "  t = '}';\n  u = \"a\\\"b\";\n}\n")
    got = items(src, "f")
    assert [(k, t) for _, k, t in got] == [("store", "s ="), ("store", "t ="), ("store", "u =")]


def test_a_string_that_never_closes_ends_with_its_line() -> None:
    assert [k for _, k, _ in items('void f() {\n  s = "open;\n  x = 1;\n}\n', "f")] == [
        "store", "store"]


@pytest.mark.parametrize(("cond", "defined", "arm"), [
    ("#ifdef A", ["A"], "compiled"), ("#ifdef A", [], "not compiled"),
    ("#ifndef A", [], "compiled"), ("#if 1", [], "compiled"), ("#if 0", [], "not compiled"),
    ("#if defined(A)", ["A"], "compiled"), ("#if !defined A", ["A"], "not compiled"),
    ("#if A", ["A"], "compiled"), ("#if !A", ["A"], "not compiled")])
def test_each_way_to_ask_the_preprocessor_is_decided_from_the_defines(
        cond: str, defined: list[str], arm: str) -> None:
    got = items(f"void f() {{\n{cond}\n x = 1;\n#endif\n}}\n", "f", defined=defined)
    assert any(k == "build" and t.endswith(f": {arm}") for _, k, t in got)


def test_an_elif_arm_is_taken_only_when_no_arm_before_it_was() -> None:
    src = ("void f() {\n#if defined(A)\n x = 1;\n#elif defined(B)\n x = 2;\n#else\n x = 3;\n"
           "#endif\n}\n")
    for defined, line in ((["A"], 3), (["B"], 5), ([], 7)):
        got = items(src, "f", defined=defined)
        assert [n for n, k, _ in got if k == "store"] == [line]


def test_loops_exits_and_labels_of_a_function_are_items() -> None:
    src = ("void f(int n) {\n for (int i = 0; i < n; i++) {\n  if (i == 2) continue;\n"
           "  while (a) b();\n }\n do { c = 1; } while (d);\n switch (n) {\n default:\n  e = 2;\n"
           "  goto out;\n }\n x = a ? 1 : 2;\n"
           " if (p) { q = 1; } else if (r) { q = 2; } else { q = 3; }\n out: return;\n}\n")
    got = items(src, "f")
    texts = [(k, t) for _, k, t in got]
    for want in [("branch", "for (int i = 0; i < n; i++)"), ("exit", "continue"),
                 ("branch", "while (a)"), ("branch", "do while (d)"), ("branch", "default"),
                 ("exit", "goto out"), ("branch", "ternary in: x = a ? 1 : 2"),
                 ("branch", "else of line 13"), ("branch", "if (r)")]:
        assert want in texts


def test_a_condition_with_a_call_lists_the_call() -> None:
    assert (1, "call", "ready") in items("void f() { if (ready()) { x = 1; } }", "f")


def test_a_function_with_a_const_qualifier_and_a_call_before_its_definition_is_found() -> None:
    src = "void g() { f(); }\nint C::f(int a) const\n{\n  a = 1;\n}\n"
    assert items(src, "C::f") == [(4, "local", "a =")]


def test_a_switch_with_no_case_for_every_value_takes_its_default_or_nothing() -> None:
    src = "void f() { switch (v) { case 1: a = 1; break; default: b = 2; break; } }"
    got = items(src, "f", key=cover.parse_key("v=5"))
    assert (1, "store", "b =") in got
    bare = "void f() { switch (v) { case 1: a = 1; break; } z = 0; }"
    assert [t for _, k, t in items(bare, "f", key=cover.parse_key("v=5")) if k == "store"] == [
        "z ="]


def test_a_case_label_that_is_a_name_is_matched_by_its_text() -> None:
    src = "void f() { switch (v) { case MODE_A: a = 1; break; case MODE_B: b = 2; break; } }"
    assert [t for _, k, t in items(src, "f", case=["MODE_B"]) if k == "store"] == ["b ="]


def test_a_case_that_falls_into_the_next_runs_both() -> None:
    src = ("void f() {\n switch (v) {\n case 1:\n case 2:\n  a = 1;\n  break;\n case 3:\n"
           "  b = 2;\n }\n}\n")
    assert [t for _, k, t in items(src, "f", case=["1"]) if k == "store"] == ["a ="]


def test_a_case_whose_switch_has_no_such_label_is_invalid() -> None:
    from scry_core.knowledge.cover import Node, _case_body
    with pytest.raises(Invalid, match="no case 7"):
        _case_body(Node("switch", 3), "7")


def test_a_directive_inside_a_function_is_no_statement() -> None:
    src = "void f() {\n#pragma once\n x = 1;\n}\n"
    assert items(src, "f") == [(3, "store", "x =")]


def test_a_function_whose_braces_never_close_is_not_found() -> None:
    with pytest.raises(Invalid, match="no definition of f"):
        cover.list_function("void f() { if (a) {", "f")


def test_an_exit_in_a_loop_before_the_dispatch_comes_before_it_and_a_break_does_not() -> None:
    src = ("void f() {\n if (a) {\n  while (b) {\n   return;\n  }\n }\n if (c) {\n"
           "  switch (d) {\n  case 1:\n   break;\n  }\n }\n switch (v) {\n case 1:\n  x = 1;\n"
           "  break;\n }\n}\n")
    got = items(src, "f", case=["1"])
    assert [(n, k) for n, k, _ in got if k == "before"] == [(4, "before")]


@pytest.mark.parametrize("cond", ["(data", "data @ 1", "data data"])
def test_a_test_that_is_not_an_expression_is_not_decided(cond: str) -> None:
    assert cover.Key("data", 0, 3).evaluate(cond) is None


def test_a_deferring_macro_with_no_function_names_nothing() -> None:
    assert [t for _, k, t in items("void f() { g(FUNC()); }", "f") if k == "call"] == ["g"]


def test_a_conditional_inside_an_arm_that_is_not_compiled_is_not_read_either() -> None:
    src = ("void f() {\n#if 0\n#if A\n a = 1;\n#else\n c = 3;\n#endif\n#else\n b = 2;\n#endif\n"
           "#endif\n}\n")
    got = items(src, "f", defined=["A"])
    assert [t for _, k, t in got if k == "store"] == ["b ="]
    assert [(n, t) for n, k, t in got if k == "build"] == [
        (2, "#if 0: not compiled"), (8, "#else : compiled")]


def test_a_switch_on_something_other_than_the_key_stays_a_branch() -> None:
    src = "void f() { switch (other) { case 1: a = 1; break; } }"
    got = items(src, "f", key=cover.parse_key("v=1"))
    assert (1, "branch", "switch (other)") in got


def test_a_switch_on_the_key_with_named_labels_is_left_a_branch_and_not_dropped() -> None:
    src = "void f(int val) { switch (val) { case CMD_A: x = 1; break; case CMD_B: y = 2; } }"
    got = items(src, "f", key=cover.parse_key("val=16"))
    assert not any(k == "key" for _, k, _ in got)
    assert [t for _, k, t in got if k == "store"] == ["x =", "y ="]


@pytest.mark.parametrize("label", ["0x10u", "16"])
def test_a_numeric_label_with_a_suffix_is_matched_by_its_value(label: str) -> None:
    src = f"void f(int val) {{ switch (val) {{ case {label}: x = 1; break; case 2: y = 2; }} }}"
    got = items(src, "f", key=cover.parse_key("val=16"))
    assert [t for _, k, t in got if k == "store"] == ["x ="]


def test_a_store_to_the_key_changes_what_later_tests_decide() -> None:
    src = "void f(int data) { data >>= 4; if (data == 1) { a = 1; } }"
    got = items(src, "f", key=cover.parse_key("data=0x10"))
    assert (1, "key", "if (data == 1) is always true for this key") in got
    assert (1, "store", "a =") in got


@pytest.mark.parametrize("body", [
    "if (p) { data = 5; } if (data == 1) { a = 1; }",   # a store on one path only
    "data = read(); if (data == 1) { a = 1; }",         # a value the reader cannot work out
    "data++; if (data == 2) { a = 1; }"])
def test_a_store_the_reader_cannot_follow_leaves_the_tests_after_it_branches(body: str) -> None:
    got = items(f"void f(int data) {{ {body} }}", "f", key=cover.parse_key("data=1"))
    assert not any(k == "key" for _, k, _ in got)
    assert (1, "store", "a =") in got


@pytest.mark.parametrize(("cond", "low", "high", "want"), [
    ("(int8_t)data < 0", 0x80, 0x8F, 1),
    ("(uint8_t)(data + 1) == 0", 0xFF, 0xFF, 1),
    ("(uint16_t)(data << 8) == 0", 0xFF, 0xFF, 0),
    ("(bool)data", 5, 5, 1),
    ("(int)data > 0", 3, 3, 1)])
def test_a_cast_wraps_to_its_width_as_c_does(cond: str, low: int, high: int, want: int) -> None:
    assert cover.Key("data", low, high).evaluate(cond) == want


@pytest.mark.parametrize("cond", ["data - 0x20 < 8", "-data < 0", "(Bitu)data < 1", "(char)data"])
def test_a_test_whose_c_meaning_depends_on_a_type_the_text_does_not_give_is_not_decided(
        cond: str) -> None:
    assert cover.Key("data", 0x10, 0x10).evaluate(cond) is None


def test_a_labelled_statement_is_read_as_the_statement_it_labels() -> None:
    src = "void f(int a) {\n if (a) goto fail;\n x = 1;\n fail: return;\n}\n"
    assert (4, "exit", "return") in items(src, "f")


def test_a_labelled_if_keeps_its_branch() -> None:
    src = "void f(int a) {\n done: if (a) { return; }\n y = 2;\n}\n"
    got = items(src, "f")
    assert (2, "branch", "if (a)") in got and (3, "store", "y =") in got


def test_a_constexpr_if_and_an_attribute_are_read_like_the_statements_they_decorate() -> None:
    src = "void f(int a) {\n if constexpr (a) { return; }\n [[likely]] x = 1;\n}\n"
    assert items(src, "f") == [(2, "branch", "if (a)"), (2, "exit", "return"),
                               (3, "store", "x =")]


def test_a_digit_separator_is_no_character_literal() -> None:
    src = "void f() {\n x = 1'000;\n if (a) { return; }\n y = 2;\n}\n"
    assert [(n, k) for n, k, _ in items(src, "f")] == [
        (2, "store"), (3, "branch"), (3, "exit"), (4, "store")]


def test_a_string_continued_over_a_line_keeps_the_count_of_lines() -> None:
    assert cover.blank('a = "x\\\nb";\nc = 1;').count("\n") == 2


def test_a_call_with_template_arguments_is_a_call() -> None:
    assert (1, "call", "clamp") in items("void f() { x = clamp<int>(v, 0, 7); }", "f")
