"""LineUp's script: what it asks of a binding, and the screens it asks its map for."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from scry_core.demo import Reply, Run, Step, StepFailed
from scry_core.game_demo import Binding, Press
from scry_core.games import lineup


def _map(run: Run) -> Path:
    return Path("/game/.scry/maps/lineup-screen-map.json")


def _binding(actions: tuple[str, ...] = lineup.ACTIONS,
             map_at: Callable[[Run], Path] = _map) -> Binding:
    boot = [Step("start", "start", {}, lambda r, run: "")]
    return Binding("board", boot, {a: Press("input", {"field": a}) for a in actions}, 50.0,
                   Path("/music.wav"), map_at)


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


def test_the_script_asks_the_screens_the_game_has() -> None:
    asked = [s.name.removeprefix("is ") for s in lineup.steps(_binding())
             if s.tool == "screen_map_find"]
    assert asked == ["hiscores", "insert", "level", "play"]
    run = Run(dir=Path("/unused"))
    for step in (s for s in lineup.steps(_binding()) if s.tool == "screen_map_find"):
        name = step.name.removeprefix("is ")
        assert step.check(Reply({"matched": True, "screen": name, "controls": []}), run)


def test_the_map_is_the_binding_s_and_a_copy_of_it_goes_into_the_run(tmp_path: Path) -> None:
    shared = tmp_path / "lineup-screen-map.json"
    shared.write_text("{}", encoding="utf-8")
    step = next(s for s in lineup.steps(_binding(map_at=lambda run: shared)) if s.name == "map")
    run = Run(dir=tmp_path / "run")
    run.dir.mkdir()
    args = cast(Callable[[Run], dict[str, Any]], step.args)(run)
    assert Path(args["path"]) == run.dir / shared.name
    assert (run.dir / shared.name).read_text() == "{}"


def test_a_read_of_player1_names_the_fields_it_wants_and_what_they_held(tmp_path: Path) -> None:
    step = lineup.player({"Column": 4, "Block": 2}, "one column right")
    assert step.args == {"ref": "Player1", "length": 12}
    held = Reply({"hex": "0100" "0400" "0200" "0000" "0300" "0000"})
    assert step.check(held, Run(dir=tmp_path)) == "one column right"
    off = Reply({"hex": "0100" "0300" "0200" "0000" "0300" "0000"})
    with pytest.raises(StepFailed, match=r"Player1 holds \{'Column': 3\}, not \{'Column': 4\}"):
        step.check(off, Run(dir=tmp_path))
