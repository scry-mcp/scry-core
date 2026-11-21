"""`scry_core.naming`: the walk of a reply's number fields, the `names` block with its ceiling and
its order, the names inside a summary, the namer that never fails the call it names, and the
`names` switch every server shares."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from pydantic import TypeAdapter

from scry_core import asks, naming
from scry_core.naming import Field, Guarded, Named

PORT = Named("port", "DAC write address", "0x03C8", id="ibm-pc:port:0x3C8", device="vga-dac")


def _walk(reply: dict[str, Any], *fields: Field) -> list[tuple[str, int | str]]:
    return [(s.path, s.value) for s in naming.walk(reply, fields)]


def test_the_walk_reads_a_field_a_list_of_numbers_and_the_field_of_each_row() -> None:
    reply = {"port": 0x3C8, "watch_hit": {"writer_pc": "0x0000b58c"}, "hits": [1, "0x2", True],
             "irqs": [{"irq": 0}, {"irq": 7}, {"other": 3}], "gone": None}
    assert _walk(reply, Field("port", "port"), Field("watch_hit.writer_pc", "symbol"),
                 Field("hits[]", "memory"), Field("irqs[].irq", "irq"), Field("gone", "port"),
                 Field("absent.deeper", "port")) == [
        ("port", 0x3C8), ("watch_hit.writer_pc", "0x0000b58c"), ("hits[]", 1), ("hits[]", "0x2"),
        ("irqs[].irq", 0), ("irqs[].irq", 7)]


def test_the_walk_passes_over_what_is_no_number_and_a_path_through_a_non_list() -> None:
    assert _walk({"a": {"b": 5}, "c": [[1]], "d": "", "e": 2.5, "f": [{"g": {"h": 1}}]},
                 Field("a[].b", "port"), Field("c[]", "port"), Field("d", "port"),
                 Field("e", "port"), Field("f[].g", "port")) == []


def test_a_field_spells_its_number_as_the_summary_does_when_it_says_so() -> None:
    [seen] = naming.walk({"vectors": [{"number": 0x33}]},
                         [Field("vectors[].number", "vector", shown="INT {:02X}")])
    assert seen.spelled == "INT 33"
    [text] = naming.walk({"n": "0x33"}, [Field("n", "vector", shown="INT {:02X}")])
    assert text.spelled == "", "a number the field already spells as text needs no other spelling"
    [broken] = naming.walk({"n": 5}, [Field("n", "vector", shown="{:q}")])
    assert broken.spelled == ""


def test_the_block_keeps_a_distinct_fact_once_in_the_order_it_was_seen() -> None:
    seen = [("given.port", PORT), ("port", PORT),
            ("vectors[]", Named("vector", "DOS", "0x21")),
            ("hits[]", Named("call", "exit", "0x21"))]
    items, cut = naming.block(seen)
    assert [i["field"] for i in items] == ["given.port", "vectors[]", "hits[]"]
    assert items[0] == {"field": "given.port", "number": "0x03C8", "kind": "port",
                        "name": "DAC write address", "id": "ibm-pc:port:0x3C8",
                        "device": "vga-dac"}
    assert cut == 0


def test_an_item_carries_a_delta_only_when_it_is_not_zero_and_never_an_empty_id() -> None:
    [inside, outside] = naming.block([
        ("a", Named("symbol", "count_coin", "0x0000b58c", delta=9)),
        ("b", Named("symbol", "count_coin", "0x0000b583"))])[0]
    assert inside == {"field": "a", "number": "0x0000b58c", "kind": "symbol",
                      "name": "count_coin", "delta": 9}
    assert outside == {"field": "b", "number": "0x0000b583", "kind": "symbol",
                       "name": "count_coin"}


def test_the_block_lists_at_most_its_ceiling_and_says_how_many_it_left_out() -> None:
    seen = [("hits[]", Named("memory", f"area {n}", f"0x{n:04X}")) for n in range(30)]
    items, cut = naming.block(seen)
    assert len(items) == naming.BLOCK_MAX == 24 and cut == 6
    assert items[-1]["number"] == "0x0017"
    assert naming.block(seen[:24]) == (items, 0)
    assert naming.block([]) == ([], 0)


def test_two_arguments_that_name_one_fact_are_each_listed_so_a_demo_reads_both() -> None:
    closed = Guarded(_Namer()).close("find", {}, {"start": PORT, "end": PORT}, "find")
    assert [i["field"] for i in closed.names] == ["given.start", "given.end"]
    both = naming.arguments_of(closed.names)
    assert both == {"start": PORT, "end": PORT}


def test_the_names_of_a_calls_arguments_are_read_back_from_a_reply() -> None:
    items = [{"field": "given.port", "number": "0x03C8", "kind": "port", "name": "DAC write",
              "id": "ibm-pc:port:0x3C8"},
             {"field": "port", "number": "0x03C8", "kind": "port", "name": "DAC write"},
             {"field": "given.ref", "number": "0x9405", "kind": "symbol", "name": "score",
              "delta": 2},
             {"field": "given.bad", "number": "1", "kind": "nothing", "name": "x"},
             {"field": "given.gone", "kind": "port"}, "not an item"]
    assert naming.arguments_of(items) == {
        "port": Named("port", "DAC write", "0x03C8", id="ibm-pc:port:0x3C8"),
        "ref": Named("symbol", "score", "0x9405", delta=2)}
    assert naming.arguments_of(None) == {} == naming.arguments_of({"a": 1})


@pytest.mark.parametrize(("summary", "said"), [
    ("port 0x03C8: write", "port 0x03C8 (DAC write address): write"),
    ("port 0x03C80: write", "port 0x03C80: write"),
    ("sent 0x03C8 and 0x03C8", "sent 0x03C8 (DAC write address) and 0x03C8"),
    ("port 0x03C8 (DAC write address): write", "port 0x03C8 (DAC write address): write"),
    ("nothing numbered", "nothing numbered"),
])
def test_a_summary_names_the_first_whole_occurrence_of_each_number_it_prints(
        summary: str, said: str) -> None:
    assert naming.in_summary(summary, [PORT]) == said


def test_a_summary_takes_every_name_where_its_number_is_and_a_name_never_hides_another() -> None:
    first, second = Named("port", "a (0x20)", "0x20"), Named("irq", "timer", "0")
    assert naming.in_summary("irq 0 on port 0x20", [second, first]) == \
        "irq 0 (timer) on port 0x20 (a (0x20))"
    assert naming.in_summary("0x20", [first, Named("vector", "other", "0x20")]) == "0x20 (a (0x20))"


def test_a_summary_uses_the_spelling_the_tool_gives_its_number_and_the_name_is_cut() -> None:
    dos = Named("vector", "DOS functions of the whole system", "0x33", shown="INT 33")
    assert naming.in_summary("stopped at INT 33", [dos]) == \
        "stopped at INT 33 (DOS functions of the w..)"
    assert naming.in_summary("stopped at 0x33", [dos]) == "stopped at 0x33"


def test_a_name_inside_a_symbol_says_how_far_in_and_whitespace_is_one_space() -> None:
    inside = Named("symbol", "count  coin", "0x0000b58c", delta=0x1F)
    assert naming.in_summary("hit 0x0000b58c", [inside]) == "hit 0x0000b58c (count coin+0x1F)"


class _Namer:
    """Answers from the tables it is given, as a server's namer does from its own memory."""

    def __init__(self, arguments: Mapping[str, Named] | None = None,
                 reply: Sequence[tuple[str, Named]] = ()) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []
        self._arguments = arguments or {}
        self._reply = reply

    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        self.calls.append((tool, given))
        return self._arguments

    def reply(self, tool: str, reply: Mapping[str, Any]) -> Sequence[tuple[str, Named]]:
        self.calls.append((tool, reply))
        return self._reply


class _Raises(_Namer):
    def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
        raise KeyError("no such symbol table")

    def reply(self, tool: str, reply: Mapping[str, Any]) -> Sequence[tuple[str, Named]]:
        raise RuntimeError("the table changed")


def test_a_guarded_namer_answers_what_its_namer_does_and_counts_nothing() -> None:
    guard = Guarded(_Namer({"port": PORT}, [("port", PORT)]))
    assert guard.arguments("port", {"port": 968}) == {"port": PORT}
    closed = guard.close("port", {"port": 968}, {"port": PORT}, "port 0x03C8")
    assert closed.summary == "port 0x03C8 (DAC write address)"
    assert [i["field"] for i in closed.names] == ["given.port"] and closed.cut == 0
    assert guard.failed() is None


def test_a_namer_that_raises_gives_no_names_and_the_failure_is_counted_not_raised() -> None:
    guard = Guarded(_Raises())
    assert guard.arguments("port", {"port": 1}) == {}
    closed = guard.close("port", {"port": 1}, {}, "port 1")
    assert (closed.summary, closed.names, closed.cut) == ("port 1", [], 0)
    assert guard.failed() == {"count": 2, "last": "RuntimeError: the table changed"}


def test_an_answer_that_names_nothing_is_a_failure_of_the_namer() -> None:
    guard = Guarded(_Namer({"port": Named("port", "", "0x1")}, [("port", Named("nope", "x", "1"))]))
    assert guard.arguments("port", {}) == {}
    assert guard.close("port", {}, {}, "s").names == []
    failed = guard.failed()
    assert failed is not None and failed["count"] == 2
    for bad in (Named("port", "x", " "), Named("port", "x", "1", delta=-1),
                Named("port", "x", "1", delta=True)):
        again = Guarded(_Namer({"a": bad}))
        assert again.arguments("t", {}) == {}, bad


class _Emulator:
    """A session that must never be asked: every call is counted, and refuses."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def ask(*args: Any, **kwargs: Any) -> Any:
            self.asked.append(name)
            raise AssertionError(f"the namer asked the emulator: {name}")
        return ask


def _asks_through(namer_reads_emulator: bool) -> tuple[_Emulator, Guarded]:
    session, symbols = _Emulator(), {"score": 0x9405}

    class Server:
        def arguments(self, tool: str, given: Mapping[str, Any]) -> Mapping[str, Named]:
            if namer_reads_emulator:
                session.registers()
            ref = given.get("ref")
            return {"ref": Named("symbol", ref, f"0x{symbols[ref]:04X}")} if ref in symbols else {}

        def reply(self, tool: str, reply: Mapping[str, Any]
                  ) -> Sequence[tuple[str, Named]]:
            return [(s.path, Named("port", "DAC", f"0x{s.value:04X}"))
                    for s in naming.walk(reply, [Field("port", "port")])]

    guard = Guarded(Server())
    calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("read_memory", {"ref": "score"}, {"status": "ok"}),
        ("port", {"port": 968}, {"status": "ok", "port": 968}),
        ("find", {"ref": "unknown"}, {"hits": [1, 2]})]
    for tool, given, reply in calls:
        named = guard.arguments(tool, given)
        guard.close(tool, reply, named, "summary")
    return session, guard


def test_a_namer_that_reads_only_the_servers_memory_never_asks_the_emulator() -> None:
    """The contract's proof: a namer over a session that fails on any call, run over calls and
    replies, reaches it zero times and fails zero times."""
    session, guard = _asks_through(False)
    assert session.asked == [] and guard.failed() is None


def test_the_proof_is_red_for_a_namer_that_asks_the_emulator() -> None:
    session, guard = _asks_through(True)
    assert session.asked == ["registers"] * 3
    failed = guard.failed()
    assert failed is not None and failed["count"] == 3


def test_the_switch_is_one_strict_boolean_that_describes_itself() -> None:
    schema = TypeAdapter(naming.Switch).json_schema()
    assert schema == {"type": "boolean", "description": naming.ARGUMENT}
    with pytest.raises(ValueError, match="valid"):
        TypeAdapter(naming.Switch).validate_python("false", strict=True)


def test_the_switchs_words_fit_a_line_of_a_servers_asks_file() -> None:
    assert asks.words(naming.ASK) <= asks.LINE_WORDS
    assert asks.words(naming.ARGUMENT) <= 40
