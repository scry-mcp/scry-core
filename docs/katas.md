# Katas

A kata is a demo that checks every answer it gets, with the screen map of its program where it has
one. One whose logic is not about an emulator lives here and each server binds its inputs; one
about a single program stays in the server that runs it.

| Kata | Servers | Lives in | Screen map |
|---|---|---|---|
| lineup | DOSBox-X, MAME | the arcade's script in `scry_core/games/` and the PC port's in its own `.scry/perform/`; each port binds its inputs in its own `demos/lineup/demo.py` | `lineup-screen-map.json`, in each port's `.scry/maps/` |
| bricks | DOSBox-X | `scry-dosbox-x/demos/bricks/` | `bricks-screen-map.json` |
| mines | DOSBox-X | `scry-dosbox-x/demos/mines/` | `mines-screen-map.json` |
| dpaint | DOSBox-X | `scry-dosbox-x/demos/dpaint/` | `dpaint-screen-map.json` |
| dpaint_maps | DOSBox-X | `scry-dosbox-x/demos/dpaint_maps/` | `dpaint-screen-map.json` (its own) |
| monkey | DOSBox-X | `scry-dosbox-x/demos/monkey/` | `monkey-screen-map.json` |
| speedf | DOSBox-X, MAME | each server's `demos/speedf/` | none |
| rechip | DOSBox-X | `scry-dosbox-x/demos/rechip/` | none |
| gridlee | MAME | `scry-mame/demos/gridlee/` | none |
| starfire | MAME | `scry-mame/demos/starfire/` | none |
| circus (live fixture) | MAME | `scry-mame/tests/live/` | `circus-screen-map.json` |

A third server runs `lineup` by binding its own inputs to the game's actions; the others need the
program they name. The step checks (`expect`, `word_is`, `map_load`) are in `scry_core.demo` and
`scry_core.game_demo`.
