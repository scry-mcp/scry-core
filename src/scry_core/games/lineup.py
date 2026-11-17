"""LineUp (Eco-Games / GAMART, 1994): one script for the arcade board and the PC port.

One source, so the script names the game's own routines and variables and each server resolves
them through its build's map: the high scores by symbol, a coin and the credits counted, a game
started, its level, then a move, a colour and a shot read back off `Player1`, the stage's music
held to the platform's recording, and a picture of the board.

Every arrival is the game's own code, never a time, because the ports differ in pace: a routine
by symbol, or a screen judged at the frame after the game's tick. The one map signs palette
indices: the arcade's 5-bit palette and the VGA's 6-bit DAC show the same index in different
colours. `insert` is listed before
`hiscores`: it is the high-score table with the coin's banner over it, so it is tried first.
"""

from __future__ import annotations

from collections.abc import Callable

from scry_core.demo import Reply, Run, Step, expect
from scry_core.game_demo import (
    WAIT_S,
    Binding,
    arrived,
    found,
    map_load,
    sound,
    word_is,
    words,
)

#: The game's actions as its source names them (`J_*`): what every platform binds.
ACTIONS = ("COIN", "START", "RIGHT", "FIRE1", "UP")
#: Run on every tick of the game's 50 Hz interrupt, the attract included.
CONTROL = "Check_Money25"
#: Its neighbour on the same tick, where a screen is judged: `CONTROL` stays free for `run_to`.
TICK = "Check_Money100"
#: Called once a game frame, after the players' moves are taken (`Main_Prog`).
MOVES_TAKEN = "Gest_Scores"
#: A coin in the slot the game reads as 100 points is three credits (`Check_Money100`).
CREDITS_PER_COIN = 3
#: `Player`'s first words, as the source declares them.
PLAYER_FIELDS = ("Status", "Column", "Block", "S_Column", "S_Row", "S_Block")
PLAYER_ACTIVE = 1
#: Where a one-player game puts the player.
START_COLUMN, START_BLOCK = 3, 1
MUSIC_MS = 2000


def player(want: dict[str, int], what: str) -> Step:
    def check(reply: Reply, run: Run) -> str:
        got = dict(zip(PLAYER_FIELDS, words(reply), strict=True))
        wrong = {k: got[k] for k, v in want.items() if got[k] != v}
        expect(not wrong, f"Player1 holds {wrong}, not {dict((k, want[k]) for k in wrong)}")
        return what
    return Step(f"player {what}", "read_memory",
                {"ref": "Player1", "length": 2 * len(PLAYER_FIELDS)}, check)


def said(what: str) -> Callable[[Reply, Run], str]:
    return lambda reply, run: what


def shown(name: str, screen: str, what: str, condition: str = "") -> list[Step]:
    """Wait until the map names `screen`, judged only after the game's tick."""
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "TARGET", f"screen_wait {screen}: verdict {reply['verdict']}")
        return what
    return [Step(f"{name}: tick", "breakpoint_at", {"ref": TICK}, said(f"a stop on {TICK}")),
            Step(name, "screen_wait", {"screen": screen, "on_breakpoint": TICK,
                                       **({"condition": condition} if condition else {}),
                                       "seconds": WAIT_S}, check,
                 volatile={"waited_s": "wall-clock time the wait took"}),
            Step(f"{name}: untick", "declaration_clear", {"kind": "breakpoint", "all": True},
                 said("the tick's stop cleared"))]


def taken(name: str, what: str) -> Step:
    """Run to where the frame after an input has taken the moves."""
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "TARGET", f"run_to {MOVES_TAKEN}: verdict {reply['verdict']}")
        return what
    return Step(name, "run_to", {"ref": MOVES_TAKEN, "control": CONTROL, "seconds": WAIT_S},
                check)


def steps(binding: Binding) -> list[Step]:
    """The script on `binding`'s platform."""
    pressed = {a: binding.press(f"press {a.lower()}", a, said(f"{a} pressed")) for a in ACTIONS}
    return [
        *binding.boot,
        map_load("map", binding.map),
        Step("to the high scores", "run_to",
             {"ref": "Draw_High_Scores_Screen", "control": CONTROL, "seconds": WAIT_S},
             arrived("Draw_High_Scores_Screen"),
             title="Run to a routine by its name",
             ask=("Run the game until it starts drawing its high-score table, and count "
                  f"`{CONTROL}` on the way."),
             shown=("summary", "verdict", "control_hits"),
             reads=("`TARGET` means the game stopped where `Draw_High_Scores_Screen` begins. "
                    "`control_hits` counts an address that runs on every tick, so a run that "
                    "misses its target still says the game was running.")),
        *shown("drawn", "hiscores", "the table drawn"),
        Step("is hiscores", "screen_map_find", {}, found("hiscores")),
        Step("no credits", "read_memory", {"ref": "Credits", "length": 2},
             word_is("Credits", 0)),
        pressed["COIN"],
        *shown("counted", "insert", "the coin counted"),
        Step("is insert", "screen_map_find", {}, found("insert")),
        Step("credits", "read_memory", {"ref": "Credits", "length": 2},
             word_is("Credits", CREDITS_PER_COIN),
             title="Read a variable by its name",
             ask="Read the game's `Credits` variable now that the coin is in.",
             shown=("summary", "addr", "hex"),
             reads=("`Credits` is a name from the game's own symbol map, so the same call works "
                    "on the arcade board and on the PC port. `hex` is the value, low byte first: "
                    "three credits for one coin.")),
        pressed["START"],
        Step("to the level", "run_to", {"ref": "Level_Write", "control": CONTROL,
                                        "seconds": WAIT_S}, arrived("Level_Write")),
        *shown("level shown", "level", "LEVEL 1 written"),
        Step("is level", "screen_map_find", {}, found("level")),
        Step("one spent", "read_memory", {"ref": "Credits", "length": 2},
             word_is("Credits", CREDITS_PER_COIN - 1)),
        Step("first stage", "read_memory", {"ref": "Stage_Act", "length": 2},
             word_is("Stage_Act", 0)),
        *shown("play", "play", "the board filled and the player in it",
               f"d@Player1 == {START_COLUMN << 16 | PLAYER_ACTIVE:#x}"),
        Step("is play", "screen_map_find", {}, found("play")),
        player({"Status": PLAYER_ACTIVE, "Column": START_COLUMN, "Block": START_BLOCK},
               "in play"),
        pressed["RIGHT"],
        taken("moved", "the move taken"),
        player({"Column": START_COLUMN + 1}, "one column right"),
        pressed["FIRE1"],
        taken("raised", "the colour taken"),
        player({"Block": START_BLOCK + 1}, "the next colour"),
        pressed["UP"],
        taken("shot", "the shot launched"),
        player({"S_Column": START_COLUMN + 1, "S_Block": START_BLOCK + 1}, "a shot of it"),
        *epilogue(binding),
    ]


def epilogue(binding: Binding) -> list[Step]:
    """What follows the script on every platform: its sound held to the platform's recording, a
    picture of the board, and the close."""
    return [*sound(binding, MUSIC_MS, "music.wav"),
            Step("screen", "screen_view",
                 lambda run: {"dest": run.dir / "screen.png", "attach": False},
                 lambda reply, run: f"the board, {reply['width']}x{reply['height']}"),
            Step("close", "close", {}, lambda reply, run: f"closed: {reply['ended_by']}")]
