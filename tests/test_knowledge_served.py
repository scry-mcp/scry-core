"""What a base serves: only the entries its confirmation confirms, in one place, so no query
shape, no namer and no note can reach one that is held back, and the base counts both."""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path
from typing import Any

import pytest
from null_server import EXIT_REF, KNOWLEDGE, an_entry, write_dictionary

from scry_core import naming, notes
from scry_core.knowledge import Base, Confirmation, confirmed, digest, read_index
from scry_core.knowledge.confirmed import SecondCheck
from scry_core.knowledge.lock import Lock, Locked, Reopened

LINE = read_index(KNOWLEDGE / "null-sources.json").rows[EXIT_REF].line
OTHER = "f" * 64
PORTS = ("0x3C0", "0x3C1", "0x3C2", "0x3C3", "0x3C4", "0x3C5")
#: What each fixture port is, in the order of `PORTS`: one confirmed and one of each way to be
#: held back.
KINDS = (confirmed.CONFIRMED, confirmed.UNSEALED, confirmed.REOPENED, confirmed.SEALED_ONCE,
         confirmed.ANOTHER_DIGEST, confirmed.CHANGED)


def checked(scope: str, kind: str, raw: dict[str, Any],
            reached: dict[str, Any] | None = None) -> dict[str, Any]:
    """`raw` with a `checked` record sealed over its own text and its header's `reached`."""
    raw["checked"] = {"by": "checker", "writer": "writer", "digest": "",
                      "against": [{"ref": EXIT_REF, "line": LINE}]}
    raw["checked"]["digest"] = digest(scope, kind, raw, reached)
    return raw


def ibm_id(kind: str, key: str) -> str:
    return f"ibm-pc:{kind}:{key}"


def fixture(folder: Path) -> tuple[Base, Confirmation]:
    """Six ports, one per standing, a device held back and a port and an IRQ-less device that
    point at it, and the confirmation that gives each its standing."""
    ports = [
        checked("ibm-pc", "port", an_entry(key, f"port {n} timer", description="A timer port."))
        if n in (0, 3, 4, 5) else an_entry(key, f"port {n} timer", description="A timer port.")
        for n, key in enumerate(PORTS)]
    write_dictionary(folder, "ports", "port", "ibm-pc", ports)
    held_device = an_entry("held-dev", "held device", contains=["seen-dev"])
    seen_device = an_entry("seen-dev", "seen device")
    for raw in (held_device, seen_device):
        checked("ibm-pc", "device", raw)
    write_dictionary(folder, "devices", "device", "ibm-pc", [held_device, seen_device])
    write_dictionary(folder, "users", "port", "ibm-pc", [
        checked("ibm-pc", "port", an_entry("0x61", "speaker", device="held-dev"))])
    write_dictionary(folder, "regs", "register", "held-dev", [
        checked("held-dev", "register", an_entry("0x00", "held reg"))])
    reached = {"index": "0x3C1", "data": "0x3C0"}
    write_dictionary(folder, "seen-regs", "register", "seen-dev", [
        checked("seen-dev", "register", an_entry("0x10", "seen reg"), reached)], reached=reached)
    loaded = Base.load(folder)
    assert loaded.faults() == []
    sealed, recorded, reopened = {}, {}, set()
    for key, kind in zip(PORTS, KINDS, strict=True):
        e = loaded.get("port", key, "ibm-pc")
        assert e is not None
        if kind in (confirmed.CONFIRMED, confirmed.SEALED_ONCE, confirmed.ANOTHER_DIGEST):
            sealed[e.id] = e.digest
        if kind == confirmed.CONFIRMED:
            recorded[e.id] = e.digest
        if kind == confirmed.ANOTHER_DIGEST:
            recorded[e.id] = OTHER
        if kind == confirmed.CHANGED:
            sealed[e.id] = OTHER
        if kind == confirmed.REOPENED:
            reopened.add(e.id)
    for kind, key, scope in (("device", "seen-dev", "ibm-pc"), ("port", "0x61", "ibm-pc"),
                             ("register", "0x10", "seen-dev")):
        e = loaded.get(kind, key, scope)
        assert e is not None
        sealed[e.id] = recorded[e.id] = e.digest
    held = loaded.get("device", "held-dev", "ibm-pc")
    assert held is not None
    sealed[held.id] = held.digest  # sealed once: held back
    reg = loaded.get("register", "0x00", "held-dev")
    assert reg is not None
    sealed[reg.id] = recorded[reg.id] = reg.digest
    lock = Lock({i: Locked(d, "checker", ()) for i, d in sealed.items()},
                tuple(Reopened(i, OTHER, "reopener", "wrong", "checker", ()) for i in reopened))
    return loaded, Confirmation.of([lock], [SecondCheck(
        {i: confirmed.Recorded("second", d) for i, d in recorded.items()})])


@pytest.fixture
def served(tmp_path: Path) -> Base:
    everything, confirmation = fixture(tmp_path)
    got = Base.load(tmp_path, confirmation=confirmation)
    assert got.faults() == []
    everything.close()
    return got


def test_each_way_to_be_held_back_has_its_own_standing(tmp_path: Path) -> None:
    everything, confirmation = fixture(tmp_path)
    got = [confirmation.standing(everything.get("port", key, "ibm-pc"))  # type: ignore[arg-type]
           for key in PORTS]
    assert got == list(KINDS)


class TestOnlyConfirmedEntriesAreLoaded:
    def test_the_base_serves_the_confirmed_and_counts_the_rest(self, served: Base) -> None:
        assert [e.key for e in served.entries() if e.kind == "port" and e.key != "0x61"] == [
            "0x3C0"]
        assert len(served) == 5 and served.held_back == 6

    def test_a_base_with_no_confirmation_serves_every_entry(self, tmp_path: Path) -> None:
        everything, _ = fixture(tmp_path)
        assert len(everything) == 11 and everything.held_back == 0

    def test_the_unfiltered_view_of_a_served_base_holds_every_entry(self, served: Base) -> None:
        assert len(served.unfiltered()) == 11

    @pytest.mark.parametrize("key", PORTS[1:])
    def test_a_held_back_entry_is_reached_by_no_query_shape(self, served: Base, key: str) -> None:
        wanted = ibm_id("port", key)
        assert served.by_id(wanted) is None
        assert served.get("port", key, "ibm-pc") is None
        assert served.search(kind="port", key=key).total == 0
        assert served.search(kind="port", key="0x3C0..0x3CF").total == 1
        assert served.search(words="timer*", limit=50).total == 1
        assert served.search(key=key).total == 0
        assert served.by_alias(f"port {PORTS.index(key)} timer") == []
        assert wanted not in [e.id for e in served.entries()]

    def test_the_held_back_entries_a_question_matches_are_named_by_id(self, served: Base) -> None:
        assert served.unconfirmed(kind="port", key="0x3C1") == [ibm_id("port", "0x3C1")]
        assert served.unconfirmed(kind="port", key="0x3C0") == []
        assert served.unconfirmed(id=ibm_id("port", "0x3C2")) == [ibm_id("port", "0x3C2")]
        assert len(served.unconfirmed(kind="port", key="0x3C0..0x3CF")) == 5
        assert served.unconfirmed(device="held-dev") == [ibm_id("device", "held-dev")]

    def test_a_relation_to_a_held_back_entry_is_dropped(self, served: Base) -> None:
        speaker = served.get("port", "0x61", "ibm-pc")
        assert speaker is not None and speaker.device == ""
        assert served.related(speaker).device is None
        seen = served.get("device", "seen-dev", "ibm-pc")
        assert seen is not None and served.related(seen).used_by == ()
        held_registers = served.get("register", "0x00", "held-dev")
        assert held_registers is not None and served.related(held_registers).device is None

    def test_a_register_is_not_reached_through_a_port_held_back(self, served: Base) -> None:
        reg = served.get("register", "0x10", "seen-dev")
        assert reg is not None
        assert served.related(reg).reached == {"index": (), "data": (ibm_id("port", "0x3C0"),)}

    def test_a_device_that_contains_a_held_back_one_no_longer_lists_it(
            self, tmp_path: Path) -> None:
        everything, confirmation = fixture(tmp_path)
        outer = checked("ibm-pc", "device", an_entry("outer", "outer", contains=["held-dev"]))
        write_dictionary(tmp_path, "outer", "device", "ibm-pc", [outer])
        sealed = {**confirmation.sealed, "ibm-pc:device:outer": digest("ibm-pc", "device", outer)}
        recorded = {**confirmation.recorded, "ibm-pc:device:outer": sealed["ibm-pc:device:outer"]}
        got = Base.load(tmp_path, confirmation=Confirmation(sealed, confirmation.reopened,
                                                            recorded))
        e = got.get("device", "outer", "ibm-pc")
        assert e is not None and e.contains == () and got.related(e).contains == ()
        everything.close()

    def test_the_namer_and_the_line_notes_cannot_reach_a_held_back_entry(
            self, served: Base) -> None:
        assert notes.note(served, "ibm-pc", [notes.Operand("port", 0x3C1)],
                          names_on=True) is None
        assert notes.note(served, "ibm-pc", [notes.Operand("port", 0x3C0)],
                          names_on=True) is not None
        assert naming.named_call(served, "ibm-pc", 0x21, {"AH": 0x4C}) is None


#: What the base may keep in Python objects per entry with the filter on, as the unfiltered
#: case bounds it (`test_knowledge.KEPT_PER_ENTRY`).
KEPT_PER_ENTRY = 64


def test_a_filtered_base_keeps_no_python_object_per_entry(tmp_path: Path) -> None:
    from test_knowledge import sized
    count = 2000
    sized(tmp_path, count)
    if not Base.load(tmp_path).uses_fts5:
        pytest.skip("this host's SQLite has no FTS5, so the index of our own is built in Python")
    # Nothing in the synthetic base is sealed: the filter holds all of it back, so the case
    # measures the held table, which is the worst case for the filter's own memory.
    nothing = Confirmation({}, frozenset(), {})
    gc.collect()
    tracemalloc.start()
    try:
        base = Base.load(tmp_path, confirmation=nothing)
        gc.collect()
        kept, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(base) == 0 and base.held_back == count
    assert kept / count < KEPT_PER_ENTRY, f"{kept / count:.0f} bytes kept an entry"
