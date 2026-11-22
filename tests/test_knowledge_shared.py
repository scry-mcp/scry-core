"""The dictionaries both servers share (`chips/`) and the Z80's vectors (`cpus/`): each is held to
the committed source index by the same contract a server's own base meets, loaded the way each
server loads it."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType

import pytest

import scry_core
from scry_core import conformance
from scry_core.knowledge import (
    Base,
    Confirmation,
    Lock,
    Scope,
    SecondCheck,
    SourceIndex,
    Support,
    check,
    read_index,
    read_lock,
    shared,
)
from scry_core.knowledge.sources import Row

PACKAGE = Path(scry_core.__file__).parent
CHIPS = PACKAGE / "knowledge" / "chips"
CPUS = PACKAGE / "knowledge" / "cpus"
INDEX = PACKAGE / "knowledge_index" / "shared.json"
LOCKS = {
    CHIPS: PACKAGE / "knowledge_index" / "shared-lock.json",
    CPUS: PACKAGE / "knowledge_index" / "cpus-lock.json",
}
ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).parent / "fixtures" / "knowledge" / "shared-sample"


class Shared:
    """A server's view of the shared base: `directories` are what it loads, `scopes` what its own
    support declares beside the shared chips."""

    def __init__(self, directories: tuple[Path, ...], scopes: tuple[Scope, ...]) -> None:
        self.directories, self.scopes = directories, scopes

    def support(self) -> Support:
        return Support(scopes=self.scopes, chips=shared.CHIPS)

    def base(self, fts5: bool | None = None) -> Base:
        return Base.load(*self.directories, fts5=fts5, pins=shared.PINS,
                         confirmation=shared.confirmation())

    def sources(self) -> SourceIndex:
        return read_index(INDEX)

    def lock(self) -> Lock:
        locks = [read_lock(LOCKS[directory]) for directory in self.directories]
        return Lock(
            {id_: held for got in locks for id_, held in got.checked.items()},
            tuple(r for got in locks for r in got.reopened),
        )

    def second_check(self) -> SecondCheck:
        return shared.second_check()

    def code_scopes(self) -> Iterable[str]:
        return ()


class TestAsAPcServerLoadsIt(conformance.KnowledgeContract):
    """scry-dosbox-x: the chips, and no cpu."""

    @pytest.fixture
    def subject(self) -> Shared:
        return Shared((CHIPS,), (Scope("ibm-pc"),))


class TestAsScryMameLoadsIt(conformance.KnowledgeContract):
    """scry-mame: the chips and the cpus, the Z80 declared named."""

    @pytest.fixture
    def subject(self) -> Shared:
        return Shared((CHIPS, CPUS), shared.CPUS)


class TestWhereEachFileLoads:
    """The directory is the unit a server selects: the Z80 must not reach a PC server, and a chip
    nobody declared must fail."""

    def test_a_server_that_loads_the_cpus_without_declaring_the_z80_fails(self) -> None:
        loads_all = Shared((CHIPS, CPUS), (Scope("ibm-pc"),))
        faults = check.undeclared(loads_all.base(), loads_all.support(), ())
        assert any("z80" in fault for fault in faults), faults

    def test_a_chip_dictionary_without_its_declaration_fails(self) -> None:
        missing = shared.CHIPS[-1].name
        base = Shared((CHIPS,), (Scope("ibm-pc"),)).base()
        support = Support(scopes=(Scope("ibm-pc"),), chips=shared.CHIPS[:-1])
        faults = check.undeclared(base, support, ())
        assert any(missing in fault for fault in faults), faults

    def test_the_index_carries_the_pins_the_dictionaries_cite_at(self) -> None:
        assert dict(read_index(INDEX).pins) == shared.PINS

    def test_the_lock_the_contract_judges_carries_the_reopenings_the_files_record(self) -> None:
        both = Shared((CHIPS, CPUS), shared.CPUS).lock()
        recorded = [r for lock_file in LOCKS.values() for r in read_lock(lock_file).reopened]
        assert recorded, "the control: the shared locks record a reopening"
        assert list(both.reopened) == recorded

    def test_the_vectors_are_declared_named_and_not_supported(self) -> None:
        z80 = next(scope for scope in shared.CPUS if scope.name == "z80")
        assert z80.support == "named"
        assert not Support(scopes=shared.CPUS).claims("z80")


class TestWhatIsServedHoldsAtThePin:
    """An entry is served only while the lines it cites are what the sources, at their pins, say:
    a line that differs there takes the entry out of the second check."""

    @staticmethod
    def served() -> Base:
        return Shared((CHIPS, CPUS), shared.CPUS).base()

    def test_every_served_entry_cites_lines_the_index_holds(self) -> None:
        served = self.served()
        assert len(served) > 0, "the control: the shared base serves entries"
        cited = [s for e in served.entries() for s in e.sources if s.ref.startswith("mame:")]
        assert cited, "the control: a served entry cites MAME"
        assert check.against_sources(served, read_index(INDEX)) == []

    def test_an_entry_whose_cited_mame_line_differs_at_the_pin_is_not_served(self) -> None:
        victim = "ins8250:register:0x00"
        index = read_index(INDEX)
        entry = self.served().by_id(victim)
        assert entry is not None, "the control: the entry is served before"
        ref = next(s.ref for s in entry.sources if s.ref.startswith("mame:"))
        moved = SourceIndex(
            {**index.rows, ref: Row("\t\tcase 0: // reworded at the pin")},
            index.lists,
            index.pins,
        )
        assert any(victim.split(":")[0] in fault for fault in
                   check.against_sources(self.served(), moved)), "the control: the line differs"
        seconds = shared.second_check()
        kept = SecondCheck({i: row for i, row in seconds.confirmed.items() if i != victim})
        base = Base.load(
            CHIPS, CPUS, pins=shared.PINS, confirmation=Confirmation.of(shared.locks(), (kept,))
        )
        assert base.by_id(victim) is None
        assert not any(ref in fault for fault in check.against_sources(base, moved))


def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "knowledge_sources", ROOT / "tools" / "knowledge_sources.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PIC = "mame:src/devices/machine/pic8259.cpp"
SAA = "mame:src/devices/sound/saa1099.cpp"
AM = "mame:src/devices/machine/am9517a.cpp"


def sample_rules(t: ModuleType) -> list[object]:
    """Rules over three excerpts of real MAME sources: a switch holding a nested switch, labels
    stacked on one line that make runs, and a switch whose labels are enumerators."""
    return [
        t.Cases(f"{PIC} pic8259_device::read", "pic8259_device::read"),
        t.DeviceTypes(f"{PIC} DEFINE_DEVICE_TYPE"),
        t.Line(
            f"{PIC} pic8259_device::read ISR", r"data = m_isr & ~m_imr;", "pic8259_device::read"
        ),
        t.Cases(f"{SAA} saa1099_device::data_w", "saa1099_device::data_w", runs=True),
        t.Cases(
            f"{AM} am9517a_device::read high",
            "am9517a_device::read",
            after=r"switch \(offset & 0x0f\)",
            enum_after=r"REGISTER_ADDRESS = 0",
        ),
    ]


def sample_repo(tmp_path: Path) -> tuple[Path, str]:
    """A git repository holding the sample's MAME files in one commit, and that commit."""
    repo = tmp_path / "mame-repo"
    if not repo.exists():
        shutil.copytree(SAMPLE / "mame", repo)
        git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
               "-c", "commit.gpgsign=false"]
        for step in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "sample"]):
            subprocess.run([*git, *step], check=True, capture_output=True)
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return repo, done.stdout.strip()


def run_tool(
    t: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: list[object], *flags: str
) -> tuple[int, Path]:
    monkeypatch.setattr(t, "rules", lambda: rules)
    repo, sha = sample_repo(tmp_path)
    monkeypatch.setattr(t, "PINS", {**t.PINS, "mame": sha})
    index = tmp_path / "index.json"
    got = t.main(
        [
            "--mame",
            str(repo),
            "--dosbox",
            str(tmp_path / "none"),
            "--rbil",
            str(tmp_path / "none"),
            "--index",
            str(index),
            *flags,
        ]
    )
    return int(got), index


class TestTheSourceIndexTool:
    def test_it_writes_the_rows_and_lists_a_real_run_captured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = tool()
        rc, index = run_tool(t, tmp_path, monkeypatch, sample_rules(t))
        assert rc == 0
        written = json.loads(index.read_text(encoding="utf-8"))
        captured = json.loads((SAMPLE / "index.json").read_text(encoding="utf-8"))
        assert written["rows"] == captured["rows"]
        assert written["lists"] == captured["lists"]
        text = "\n".join(p.read_text(encoding="utf-8") for p in (SAMPLE / "mame").rglob("*.cpp"))
        assert all(row["line"] in text.split("\n") for row in written["rows"].values())

    def test_a_nested_switch_gives_no_key_and_stacked_labels_make_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = tool()
        _, index = run_tool(t, tmp_path, monkeypatch, sample_rules(t))
        lists = json.loads(index.read_text(encoding="utf-8"))["lists"]
        assert lists[f"{PIC} pic8259_device::read"] == ["0x00", "0x01"]
        assert lists[f"{SAA} saa1099_device::data_w"][:3] == [
            "0x00..0x05",
            "0x08..0x0D",
            "0x10..0x12",
        ]
        assert lists[f"{AM} am9517a_device::read high"] == ["0x08", "0x0D", "0x0F"]

    def test_check_is_zero_on_an_equal_index_and_one_on_a_changed_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = tool()
        rules = sample_rules(t)
        _, index = run_tool(t, tmp_path, monkeypatch, rules)
        assert run_tool(t, tmp_path, monkeypatch, rules, "--check")[0] == 0
        index.write_text(
            index.read_text(encoding="utf-8").replace("0x0F", "0x0E"), encoding="utf-8"
        )
        assert run_tool(t, tmp_path, monkeypatch, rules, "--check")[0] == 1

    @pytest.mark.parametrize(
        ("make", "said"),
        [
            (
                lambda t: t.Line(f"{PIC} nothing", r"no such text", "pic8259_device::read"),
                "matches 0",
            ),
            (
                lambda t: t.Line(
                    f"{PIC} nothing", r"x", "pic8259_device::read", after=r"no such line"
                ),
                "matches 0 lines",
            ),
            (
                lambda t: t.Line(
                    f"{PIC} nothing", r"x", "pic8259_device::read", until=r"no such line"
                ),
                "nothing matches",
            ),
            (lambda t: t.Line(f"{PIC} nothing", r"x", "no_such_function"), "defined 0 times"),
            (lambda t: t.Line(f"{PIC} twice", r"case", "pic8259_device::read"), "not one"),
            (
                lambda t: t.Line(f"{AM} twice", r"x", "am9517a_device::read", after=r"switch"),
                "matches 2 lines of am9517a_device::read",
            ),
            (
                lambda t: t.Cases(
                    f"{AM} am9517a_device::read all",
                    "am9517a_device::read",
                    enum_after=r"REGISTER_",
                ),
                "matches 17 lines, not the one of an enum",
            ),
        ],
    )
    def test_a_rule_that_matches_nothing_is_invalid_and_writes_nothing(
        self,
        make: Callable[[ModuleType], object],
        said: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        t = tool()
        rc, index = run_tool(t, tmp_path, monkeypatch, [*sample_rules(t), make(t)])
        assert rc == 3 and not index.exists()
        assert said in capsys.readouterr().err

    def test_no_rule_at_all_is_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        t = tool()
        rc, index = run_tool(t, tmp_path, monkeypatch, [])
        assert rc == 3 and not index.exists()

    def test_a_missing_source_is_invalid_and_names_the_commit_it_looked_in(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        t = tool()
        rules = [t.Line(f"{PIC.replace('pic8259', 'absent')} x", r"x", "x")]
        rc, _ = run_tool(t, tmp_path, monkeypatch, rules)
        assert rc == 3
        assert f"git show {sample_repo(tmp_path)[1]}:" in capsys.readouterr().err

    def test_an_unknown_option_exits_non_zero(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as caught:
            tool().main(
                [
                    "--mame",
                    str(tmp_path),
                    "--dosbox",
                    str(tmp_path),
                    "--rbil",
                    str(tmp_path),
                    "--nonsense",
                ]
            )
        assert caught.value.code == 2
