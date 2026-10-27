"""LineUp's script: what it asks of a binding, and the one map it ships."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scry_core import screen_map
from scry_core.demo import Reply, Run, Step, StepFailed
from scry_core.game_demo import Binding, Press
from scry_core.games import lineup


def _binding(actions: tuple[str, ...] = lineup.ACTIONS) -> Binding:
    boot = [Step("start", "start", {}, lambda r, run: "")]
    return Binding("board", boot, {a: Press("input", {"field": a}) for a in actions}, 50.0,
                   Path("/music.wav"))


def test_the_script_starts_with_the_binding_and_ends_by_closing() -> None:
    steps = lineup.steps(_binding())
    assert steps[0].name == "start" and steps[-1].tool == "close"
    names = [s.name for s in steps]
    assert len(names) == len(set(names)), "a step name is the key its reply is kept by"


def test_every_action_the_script_fires_is_one_it_declares() -> None:
    fired = {s.args["field"] for s in lineup.steps(_binding())
             if s.tool == "input" and isinstance(s.args, dict)}
    assert fired == set(lineup.ACTIONS)


def test_a_binding_missing_an_action_is_refused_before_anything_runs() -> None:
    with pytest.raises(KeyError, match="binds no 'UP'"):
        lineup.steps(_binding(tuple(a for a in lineup.ACTIONS if a != "UP")))


def test_the_script_checks_only_screens_its_map_holds_and_the_map_signs_indices() -> None:
    application, screens = screen_map.parse(json.loads(lineup.MAP.read_text()), str(lineup.MAP))
    assert application == "lineup"
    assert all(s.cells == "index" and s.size == (320, 200) for s in screens.values())
    steps = lineup.steps(_binding())
    asked = {s.name.removeprefix("is ") for s in steps if s.tool == "map_find"}
    assert asked == set(screens)
    run = Run(dir=Path("/unused"))
    for step in (s for s in steps if s.tool == "map_find"):
        name = step.name.removeprefix("is ")
        assert step.check(Reply({"matched": True, "screen": name, "controls": []}), run)


def test_a_read_of_player1_names_the_fields_it_wants_and_what_they_held(tmp_path: Path) -> None:
    step = lineup.player({"Column": 4, "Block": 2}, "one column right")
    assert step.args == {"ref": "Player1", "length": 12}
    held = Reply({"hex": "0100" "0400" "0200" "0000" "0300" "0000"})
    assert step.check(held, Run(dir=tmp_path)) == "one column right"
    off = Reply({"hex": "0100" "0300" "0200" "0000" "0300" "0000"})
    with pytest.raises(StepFailed, match=r"Player1 holds \{'Column': 3\}, not \{'Column': 4\}"):
        step.check(off, Run(dir=tmp_path))
