"""`scry_core.knowledge.reach`: the state a region shares with the rest of its file, and the
tables it indexes."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core.knowledge import closure, cover, reach
from scry_core.knowledge.rows import Region

DMAC = """// synthetic source for the tests of what a region reaches: not MAME or DOSBox-X code

static const int rates[4] = {
	1, 16,
	64, 0
};
static int scratch[2] = {0};

void dmac_device::write(int offset, int data)
{
	switch (offset)
	{
	case 1:
		m_chan[offset >> 1].count = data;
		m_chan[offset >> 1].base = data;
		break;
	case 2:
		m_rate = rates[data & 3];
		m_status[0] = scratch[data & 1];
		break;
	case 3:
		m_rate = rates[2];
		break;
	}
}

int dmac_device::read(int offset)
{
	int data = 0;
	switch (offset)
	{
	case 1:
		data = m_chan[offset >> 1].count;
		break;
	case 3:
		data = m_status[1];
		break;
	}
	return data;
}

void dmac_device::advance(int ch)
{
	chan_t &c = m_chan[ch];
	if (c.count-- == 0)
		c.count = c.base;
	m_status[STATUS_TC] |= 1;
	m_local_only = 1;
}

void dmac_device::device_start()
{
	save_item(NAME(m_rate));
	m_status = make_unique<int[]>(4);
}

dmac_device::dmac_device(int clock)
	: device_t(clock), m_rate(0)
{
	m_chan[0].base = 0;
}

void dmac_device::tick()
{
	if (m_rate > 4)
		advance(0);
}
"""
RTC = """// synthetic source for the tests of the reach of a region: it is not DOSBox-X code

static void check_alarm(void) {
	if (rtc.sec == rtc.alarm_sec)
		rtc.regs[0x0c] |= 0x20;
}

static void tick(void) {
	if (rtc.regs[0xb] & 0x20) check_alarm();
	rtc.sec = reg_al;
}

static Bitu rtc_read(Bitu reg) {
	switch (reg) {
	case 0xc: {
		uint8_t val = rtc.regs[0xc];
		rtc.regs[0xc] = 0;
		reg_al = val;
		return val;
	}
	}
	return 0xff;
}
"""

OWN = """uint8_t flag_device::read(int offset)
{
	switch (offset)
	{
	case 0:
		return m_flag;
	case 1:
		m_flag = 0;
		return 0;
	}
	return 0;
}

void flag_device::set(int v)
{
	const chan_t *p = &m_chan[v];
	m_mode = v;
}

int flag_device::size()
{
	return sizeof(chan_t);
}
"""


KEYED = """int key_device::read(int data)
{
	if (data & 0x10)
		return m_init;
	return m_ocw;
}

void key_device::write(int v)
{
	m_init = v;
	m_ocw = v;
}
"""

CLOCK = """int clock_device::read(int offset)
{
	switch (offset)
	{
	case 0:
		return m_data[REG_C];
	case 1:
		return m_data[12];
	case 2:
		return m_data[offset];
	case 3:
		return m_chan[offset].count;
	case 4:
		return m_chan[0].base;
	}
	return 0;
}

void clock_device::tick()
{
	m_data[REG_C] |= 0x80;
	m_data[REG_A] = 1;
	m_data[12] = 0;
	m_chan[1].count = 0;
	m_chan[1].base = 0;
}

void clock_device::write(int offset, int data)
{
	m_data[offset] = data;
}
"""


def reached(source: str, name: str, case: list[str], **kw: Any
            ) -> list[tuple[int, str, str, tuple[int, ...]]]:
    got = cover.list_function(source, name, case=case, **kw)
    items = reach.state(got.text, got.start, got.region, got.tree, (got.first, got.last))
    items += reach.lookup(got.text, got.region)
    return [(i.line, i.kind, i.text, i.lines) for i in items]


def test_a_member_a_read_returns_is_owed_once_by_each_function_that_writes_it() -> None:
    assert reached(DMAC, "dmac_device::read", ["1"]) == [
        (14, "state", "m_chan[offset >> 1].count written by dmac_device::write", (14,)),
        (45, "state", "m_chan[offset >> 1].count written by dmac_device::advance", (45, 46))]


def test_a_member_a_write_stores_owes_none_of_the_functions_that_read_it() -> None:
    assert [i for i in reached(DMAC, "dmac_device::write", ["1"]) if i[1] == "state"] == []


def test_a_member_only_its_region_writes_owes_nothing() -> None:
    own = "int f()\n{\n\tm_a = 1;\n\treturn m_a;\n}\n\nint g()\n{\n\treturn m_b;\n}\n"
    assert reached(own, "f", []) == []


def test_a_function_that_writes_a_member_on_two_lines_owes_one_item() -> None:
    rate = DMAC.replace("\tcase 3:\n\t\tdata = m_status[1];", "\tcase 3:\n\t\tdata = m_rate;")
    assert reached(rate, "dmac_device::read", ["3"]) == [
        (18, "state", "m_rate written by dmac_device::write", (18, 22))]


def test_a_constructor_is_named_past_its_initializer_list() -> None:
    names = [f.name for f in reach.functions(cover.one_build(cover.blank(DMAC), set())[0])]
    assert names == ["dmac_device::write", "dmac_device::read", "dmac_device::advance",
                     "dmac_device::device_start", "dmac_device::dmac_device", "dmac_device::tick"]


def test_a_fixed_index_is_owed_only_for_the_same_element() -> None:
    assert reached(CLOCK, "clock_device::read", ["0"]) == [
        (21, "state", "m_data[REG_C] written by clock_device::tick", (21,))]
    assert reached(CLOCK, "clock_device::read", ["1"]) == [
        (23, "state", "m_data[12] written by clock_device::tick", (23,))]


def test_an_element_the_region_reaches_at_an_index_it_does_not_fix_owes_nothing() -> None:
    assert reached(CLOCK, "clock_device::read", ["2"]) == []


def test_a_computed_index_before_the_last_part_picks_any_instance_and_a_fixed_one_its_own(
        ) -> None:
    assert reached(CLOCK, "clock_device::read", ["3"]) == [
        (24, "state", "m_chan[offset].count written by clock_device::tick", (24,))]
    assert reached(CLOCK, "clock_device::read", ["4"]) == []


def test_a_table_the_region_indexes_by_a_value_is_owed_at_its_definition() -> None:
    assert [i for i in reached(DMAC, "dmac_device::write", ["2"]) if i[1] == "lookup"] == [
        (3, "lookup", "rates[data & 3]", (3, 4, 5, 6))]


@pytest.mark.parametrize("case", ["3", "1"])
def test_a_constant_index_a_table_that_is_not_const_or_no_table_is_no_lookup(case: str) -> None:
    assert not [i for i in reached(DMAC, "dmac_device::write", [case]) if i[1] == "lookup"]


def test_a_flag_another_function_sets_reaches_the_read_that_returns_it() -> None:
    assert reached(RTC, "rtc_read", ["0xc"]) == [
        (5, "state", "rtc.regs[0xc] written by check_alarm", (5,))]


def test_a_guest_register_is_no_state_another_function_shares() -> None:
    got = reached(RTC, "rtc_read", ["0xc"])
    assert not [i for i in got if "reg_al" in i[2]]


def test_a_guest_register_a_service_sets_hands_out_the_member_it_is_given() -> None:
    service = ("static void svc(void) {\n\treg_al = dos.err;\n}\n\n"
               "static void set_err(int e) {\n\tdos.err = e;\n}\n")
    assert reached(service, "svc", []) == [(6, "state", "dos.err written by set_err", (6,))]


def test_another_case_of_the_handler_that_writes_what_its_region_returns_is_owed() -> None:
    assert reached(OWN, "flag_device::read", ["0"]) == [
        (8, "state", "m_flag written by flag_device::read", (8,))]


def test_the_declaration_of_a_local_writes_no_member_named_by_its_type() -> None:
    assert reached(OWN, "flag_device::size", []) == []


def test_an_arm_the_key_leaves_out_hands_out_nothing_another_function_is_owed() -> None:
    assert reached(KEYED, "key_device::read", [], key=cover.parse_key("data=0..15")) == [
        (11, "state", "m_ocw written by key_device::write", (11,))]


def test_a_member_a_region_returns_twice_is_owed_once_by_each_writer() -> None:
    twice = ("int f(int k)\n{\n\tif (k)\n\t\treturn m_a;\n\treturn m_a + 1;\n}\n\n"
             "void g()\n{\n\tm_a = 1;\n\tm_a |= 2;\n\t++m_a;\n}\n")
    assert reached(twice, "f", []) == [(10, "state", "m_a written by g", (10, 11, 12))]


READS = """int f::status()
{
	return m_flag + m_regs[m_idx];
}

void f::tick(int i)
{
	if (m_en && m_flag)
		m_flag = 0;
	m_idx = i;
}
"""


def test_a_condition_declares_nothing_and_a_subscript_hands_out_what_it_names() -> None:
    assert reached(READS, "f::status", []) == [
        (9, "state", "m_flag written by f::tick", (9,)),
        (10, "state", "m_idx written by f::tick", (10,))]


def test_a_statement_that_opens_with_a_word_of_the_language_declares_nothing() -> None:
    freed = ("void *g()\n{\n\tdelete m_obj;\n\treturn m_obj;\n}\n\n"
             "void f()\n{\n\tm_obj = make();\n}\n")
    assert reached(freed, "g", []) == [(9, "state", "m_obj written by f", (9,))]


def writer(body: str, returned: str = "m_n") -> str:
    return f"int f()\n{{\n\treturn {returned};\n}}\n\nvoid g(int ch)\n{{\n\t{body}\n}}\n"


@pytest.mark.parametrize("body", ["if (m_en && --m_n == 0)\n\t\tm_x = 1;",
                                  "while (m_n--)\n\t\tm_x = 1;",
                                  "for (m_n = 0; m_x < 4; m_x++)\n\t\tm_t = 1;"])
def test_a_prefix_operator_and_a_loop_s_head_write_the_member_they_change(body: str) -> None:
    assert reached(writer(body), "f", []) == [(8, "state", "m_n written by g", (8,))]


def test_a_field_named_like_the_returned_local_gives_that_local_nothing() -> None:
    latch = ("int f(int sel)\n{\n\tint data = 0;\n\tif (sel)\n\t\tm_latch.data = m_b;\n"
             "\treturn data;\n}\n\nvoid g()\n{\n\tm_b = 1;\n}\n")
    assert reached(latch, "f", []) == []


def test_a_guest_register_returned_is_no_member_its_writers_owe() -> None:
    assert reached(writer("reg_al = 1;", "reg_al"), "f", []) == []


@pytest.mark.parametrize(("returned", "owed"), [("m_chan[0].count", True),
                                                ("m_chan.count", False)])
def test_a_fixed_or_absent_index_before_the_last_part_against_a_computed_one(
        returned: str, owed: bool) -> None:
    got = reached(writer("m_chan[ch].count = 0;", returned), "f", [])
    assert got == ([(8, "state", f"{returned} written by g", (8,))] if owed else [])


def test_a_member_written_whole_is_not_one_of_its_elements() -> None:
    whole = "int r()\n{\n\treturn m_buf[2];\n}\n\nvoid reset()\n{\n\tm_buf = alloc();\n}\n"
    assert reached(whole, "r", []) == []


def test_a_nested_subscript_writes_the_outer_member_and_reads_the_inner() -> None:
    got = sorted(reach._paths("m_tab[m_map[i]].count = 5", {"i"}))
    assert [(member, inner) for _, member, _, inner in got] == [
        ((("m_tab", "*"), ("count", "")), False), ((("m_map", "*"),), True)]


@pytest.mark.parametrize(("index", "value"), [("010", "8"), ("0x10", "16"), ("10", "10"),
                                              ("10u", "10"), ("REG_C", "REG_C"), ("i", "*")])
def test_an_index_is_read_as_c_reads_a_literal(index: str, value: str) -> None:
    assert reach._index(index) == value


def test_two_functions_of_one_name_each_owe_what_they_write() -> None:
    items = [cover.Item(1, "state", "m_x written by write", (1,)),
             cover.Item(2, "state", "m_x written by write", (2,))]
    listings = [(Region("mame:a.cpp", "w"), cover.Listing(items, 5, 9))]
    closure._reached(listings)
    assert len(listings[0][1].items) == 2


def test_what_two_regions_of_an_entry_reach_is_listed_once() -> None:
    item = cover.Item(40, "state", "m_x written by f", (40, 41))
    listings = [(Region("mame:a.cpp", "g", ("1",)), cover.Listing([item], 1, 9)),
                (Region("mame:a.cpp", "g", ("2",)), cover.Listing([item], 10, 19))]
    closure._reached(listings)
    assert [len(lg.items) for _, lg in listings] == [1, 0]
