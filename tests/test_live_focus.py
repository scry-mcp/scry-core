"""`scry_core.live_focus`: the control and the verdict of a live matrix's focus section, judged
into the ledger that runs it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scry_core import focus_gate, live_focus, live_host, live_ledger


class _Host:
    """The run's host, with a scratch of the test's own and nothing that reaches a machine."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self.finished = False

    def made(self) -> Path:
        self.scratch.mkdir(parents=True, exist_ok=True)
        return self.scratch


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> live_ledger.Ledger:
    monkeypatch.setattr(live_host.LiveRun, "for_process",
                        classmethod(lambda cls, prefix, job=False: _Host(tmp_path / "scratch")))
    ran = live_ledger.Ledger("test-live-", "TEST_LIVE_SUMMARY")
    ran.current = live_ledger.Section("O", "the focus gate", [live_ledger.Cell(label) for label
                                                             in ("front", "behind", "space")],
                                      lambda: None)
    return ran


def _judged(status: str, reason: str = "") -> focus_gate.Judged:
    return focus_gate.Judged(status=status, reason=reason)  # type: ignore[arg-type]


def test_a_blocked_cell_is_blocked_not_judged(made: live_ledger.Ledger) -> None:
    live_focus.judge(made, "front", _judged("BLOCKED", "the desk was not free"))
    assert made.tally == {"OK": 0, "FAIL": 0, "BLOCKED": 1}
    assert made.reasons["front"] == "the desk was not free"


def test_a_judged_cell_is_its_verdict(made: live_ledger.Ledger) -> None:
    live_focus.judge(made, "behind", _judged("OK", "nothing was in front"))
    live_focus.judge(made, "space", _judged("FAIL", "the Space moved"))
    assert made.tally == {"OK": 1, "FAIL": 1, "BLOCKED": 0}
    assert made.failed == ["space"]


def test_the_control_judges_its_three_cells_and_answers_its_since(
        made: live_ledger.Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    found = focus_gate.Control(front=_judged("OK"), behind=_judged("OK"), space=_judged("OK"),
                               since=1234)
    monkeypatch.setattr(focus_gate, "control", lambda watch, names, hold: found)
    since = live_focus.control(made, _watch(), {"dosbox-x"}, lambda front: (0, 1),
                               ["front", "behind", "space"])
    assert since == 1234 and made.tally == {"OK": 3, "FAIL": 0, "BLOCKED": 0}


def test_the_verdict_judges_the_runs_cell(
        made: live_ledger.Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus_gate, "verdict",
                        lambda watch, names, since, now: _judged("FAIL", "MAME came to the front"))
    live_focus.verdict(made, _watch(), {"mame"}, 7, "space")
    assert made.failed == ["space"] and made.reasons["space"] == "MAME came to the front"


def _watch() -> Any:
    return object()
