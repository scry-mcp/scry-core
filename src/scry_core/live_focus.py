"""The focus section both live matrices run, judged into the ledger that ran it."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from scry_core import focus_gate, focus_watch, live_ledger


def judge(made: live_ledger.Ledger, label: str, judged: focus_gate.Judged) -> None:
    """A BLOCKED reason blocks; anything else is the verdict it came with."""
    if judged.status == "BLOCKED":
        made.block(label, judged.reason)
    else:
        made.judge(label, judged.status == "OK", judged.reason)


def control(made: live_ledger.Ledger, watch: focus_watch.FocusWatch, names: set[str],
            hold: Callable[[bool], tuple[int, int]],
            labels: Sequence[str]) -> int | None:
    """Run the control, judge its three cells, answer its `since`."""
    found = focus_gate.control(watch, names, hold)
    for label, judged in zip(labels, (found.front, found.behind, found.space), strict=True):
        judge(made, label, judged)
    return found.since


def verdict(made: live_ledger.Ledger, watch: focus_watch.FocusWatch, names: set[str],
            since: int | None, label: str) -> None:
    """Judge the run's own cell from what the watch saw, and close the watch."""
    judge(made, label, focus_gate.verdict(watch, names, since, focus_watch.now_ms()))
