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


KEYED = """void key_device::write(int data)
{
	if (data & 0x10)
		m_init = data;
	else
		m_ocw = data;
}

int key_device::read()
{
	return m_init + m_ocw;
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


def test_a_member_a_write_stores_is_owed_by_each_function_that_reads_it() -> None:
    assert reached(DMAC, "dmac_device::write", ["1"]) == [
        (33, "state", "m_chan[offset >> 1].count read by dmac_device::read", (33,)),
        (45, "state", "m_chan[offset >> 1].count read by dmac_device::advance", (45,)),
        (46, "state", "m_chan[offset >> 1].base read by dmac_device::advance", (46,))]


def test_a_member_only_its_region_touches_owes_nothing() -> None:
    assert not [i for i in reached(DMAC, "dmac_device::advance", [])
                if "m_local_only" in i[2]]


def test_a_saved_state_a_member_written_whole_and_an_initializer_list_touch_nothing() -> None:
    assert [i for i in reached(DMAC, "dmac_device::write", ["2"]) if i[1] == "state"] == [
        (47, "state", "m_status[0] read by dmac_device::advance", (47,)),
        (65, "state", "m_rate read by dmac_device::tick", (65,))]


def test_a_constructor_is_named_past_its_initializer_list() -> None:
    names = [f.name for f in reach.functions(cover.one_build(cover.blank(DMAC), set())[0])]
    assert names == ["dmac_device::write", "dmac_device::read", "dmac_device::advance",
                     "dmac_device::device_start", "dmac_device::dmac_device", "dmac_device::tick"]


def test_a_number_and_a_constant_name_may_be_one_index_and_two_numbers_must_agree() -> None:
    assert reached(DMAC, "dmac_device::read", ["3"]) == [
        (47, "state", "m_status[1] written by dmac_device::advance", (47,))]


def test_a_table_the_region_indexes_by_a_value_is_owed_at_its_definition() -> None:
    assert [i for i in reached(DMAC, "dmac_device::write", ["2"]) if i[1] == "lookup"] == [
        (3, "lookup", "rates[data & 3]", (3, 4, 5, 6))]


@pytest.mark.parametrize("case", ["3", "1"])
def test_a_constant_index_a_table_that_is_not_const_or_no_table_is_no_lookup(case: str) -> None:
    assert not [i for i in reached(DMAC, "dmac_device::write", [case]) if i[1] == "lookup"]


def test_a_flag_another_function_sets_reaches_the_read_that_returns_it() -> None:
    assert reached(RTC, "rtc_read", ["0xc"]) == [
        (5, "state", "rtc.regs[0xc] read by check_alarm", (5,)),
        (5, "state", "rtc.regs[0xc] written by check_alarm", (5,))]


def test_a_guest_register_is_no_state_another_function_shares() -> None:
    got = reached(RTC, "rtc_read", ["0xc"])
    assert not [i for i in got if "reg_al" in i[2]]


def test_another_case_of_the_handler_that_writes_what_its_region_returns_is_owed() -> None:
    assert reached(OWN, "flag_device::read", ["0"]) == [
        (8, "state", "m_flag written by flag_device::read", (8,))]


def test_the_declaration_of_a_local_writes_no_member_named_by_its_type() -> None:
    assert reached(OWN, "flag_device::set", []) == []


def test_an_arm_the_key_leaves_out_stores_nothing_another_function_is_owed() -> None:
    assert reached(KEYED, "key_device::write", [], key=cover.parse_key("data=0..15")) == [
        (11, "state", "m_ocw read by key_device::read", (11,))]


def test_a_member_a_region_stores_twice_is_owed_once_by_each_reader() -> None:
    twice = "void f()\n{\n\tm_a = 1;\n\tm_a |= 2;\n}\n\nint g()\n{\n\treturn m_a;\n}\n"
    assert reached(twice, "f", []) == [(9, "state", "m_a read by g", (9,))]


READS = """void f::write_ctl(int data)
{
	m_flag = data;
	m_idx = data;
	m_buf[data] = 0;
}

int f::tick(int i)
{
	if (m_en && m_flag)
		return m_regs[m_idx];
	m_buf = alloc();
	m_tab[m_map[i]].count = 5;
	return m_regs[010];
}
"""


def test_a_condition_declares_nothing_and_a_subscript_reads_what_it_names() -> None:
    assert reached(READS, "f::write_ctl", []) == [
        (10, "state", "m_flag read by f::tick", (10,)),
        (11, "state", "m_idx read by f::tick", (11,))]


def test_a_statement_that_opens_with_a_word_of_the_language_declares_nothing() -> None:
    freed = "void f()\n{\n\tm_obj = make();\n}\n\nvoid g()\n{\n\tdelete m_obj;\n}\n"
    assert reached(freed, "f", []) == [(8, "state", "m_obj read by g", (8,))]


def test_a_member_written_whole_is_not_an_element_read_at_a_computed_index() -> None:
    whole = "int r(int i)\n{\n\treturn m_buf[i];\n}\n\nvoid reset()\n{\n\tm_buf = alloc();\n}\n"
    assert reached(whole, "r", []) == []


def test_a_nested_subscript_writes_the_outer_member_and_reads_the_inner() -> None:
    got = sorted(reach._paths("m_tab[m_map[i]].count = 5", {"i"}))
    assert [(member, inner) for _, member, _, inner in got] == [
        ((("m_tab", "*"), ("count", "")), False), ((("m_map", "*"),), True)]


@pytest.mark.parametrize(("index", "value"), [("010", "8"), ("0x10", "16"), ("10", "10"),
                                              ("10u", "10"), ("REG_C", "REG_C"), ("i", "*")])
def test_an_index_is_read_as_c_reads_a_literal(index: str, value: str) -> None:
    assert reach._index(index) == value


def test_two_functions_of_one_name_each_owe_what_they_read() -> None:
    items = [cover.Item(1, "state", "m_x read by read", (1,)),
             cover.Item(2, "state", "m_x read by read", (2,))]
    listings = [(Region("mame:a.cpp", "w"), cover.Listing(items, 5, 9))]
    closure._reached(listings)
    assert len(listings[0][1].items) == 2


def test_what_two_regions_of_an_entry_reach_is_listed_once() -> None:
    item = cover.Item(40, "state", "m_x read by f", (40, 41))
    listings = [(Region("mame:a.cpp", "g", ("1",)), cover.Listing([item], 1, 9)),
                (Region("mame:a.cpp", "g", ("2",)), cover.Listing([item], 10, 19))]
    closure._reached(listings)
    assert [len(lg.items) for _, lg in listings] == [1, 0]
