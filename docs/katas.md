# Checked demos

A checked demo is a demo that checks every answer it gets. This page lists every one: which
servers run it, where it lives, and which screen map it uses.

A screen map is a file that names a program's screens and the areas of each. A demo uses its
program's screen map where the program has one.

## Where a demo lives

- A demo whose logic does not depend on an emulator lives in this package. Each server maps the
  demo's inputs to its own emulator's.
- A demo about one program stays in the server that runs it.

| Demo | Servers | Lives in | Screen map |
|---|---|---|---|
| `lineup` | DOSBox-X, MAME | this package and the game's own `.scry/`: see below | `lineup-screen-map.json` |
| `bricks` | DOSBox-X | `scry-dosbox-x/demos/bricks/` | `bricks-screen-map.json` |
| `mines` | DOSBox-X | `scry-dosbox-x/demos/mines/` | `mines-screen-map.json` |
| `dpaint` | DOSBox-X | `scry-dosbox-x/demos/dpaint/` | `dpaint-screen-map.json` |
| `dpaint_maps` | DOSBox-X | `scry-dosbox-x/demos/dpaint_maps/` | `dpaint-screen-map.json`, its own copy |
| `monkey` | DOSBox-X | `scry-dosbox-x/demos/monkey/` | `monkey-screen-map.json` |
| `speedf` | DOSBox-X, MAME | each server's `demos/speedf/`: see below | none |
| `rechip` | DOSBox-X | `scry-dosbox-x/demos/rechip/` | `rechip-screen-map.json` |
| `gridlee` | MAME | `scry-mame/demos/gridlee/` | none |
| `starfire` | MAME | `scry-mame/demos/starfire/` | none |
| `circus` | MAME | `scry-mame/tests/live/` | `circus-screen-map.json` |

`circus` is not under `demos/`: the tests against a real emulator use it.

## The two demos both servers run

`lineup` is one game with an arcade board and a PC port, so both servers run it.

- The arcade board's script is in `scry_core/games/`.
- The PC port's script is in the port's own `.scry/perform/`.
- Each server's `demos/lineup/demo.py` maps the game's actions to that emulator's inputs.
- The screen map is in each port's own `.scry/maps/`.

A third server runs `lineup` by mapping its own inputs to the game's actions. Every other demo
needs the program it names.

`speedf` has two scripts that share no logic, because the arcade board and the PC port are two
programs. Each script runs to a routine of its own program, with its own `control`: an address
that runs often, counted beside the target. The PC port's script does so only once DOS has
loaded the game.

## Where the step checks are

- `expect` is in `scry_core.demo`.
- `word_is` and `map_load` are in `scry_core.game_demo`.
