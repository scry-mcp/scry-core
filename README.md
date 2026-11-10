<p align="center"><img src="docs/scry-logo.png" alt="Scry" width="480"></p>

# scry-core

What the Scry emulator MCP servers ([scry-mame](https://github.com/scry-mcp/scry-mame) and
[scry-dosbox-x](https://github.com/scry-mcp/scry-dosbox-x)) share, held once:

| Module | What it holds |
|---|---|
| `scry_core.instruction` | the one shape of a stopped machine's instruction (`address`, `bytes`, `text`, `symbol`, `delta`), which each server's reply model extends with what only its platform has |
| `scry_core.reply_contract` | the refusal contract (`status`, `code`, `message`), its class and its envelope check; a datum that could not be read as `unavailable(why)`, never a null; a wait's `verdict` words |
| `scry_core.log_wait` | a wait for a line of a log: what the log already holds answered first, then the wait, ended by a match, its bound, a stopped machine or a gone emulator, and the sentence each server says when a stop ended it |
| `scry_core.sequence_account` | the account of a list of steps run in one call: compact rows, the two files, and the count of the stops numbered while it ran; the fields a sequence's reply names (`SequenceFields`), `summaries`' description and check, and `drive`'s look after its act |
| `scry_core.steps` | a step of a list judged against the tool it names before any step runs: its `recorded` check, no `ctx`, names the tool takes, scalars of the declared type; the ops a list may name, read off the registry (`step_ops`) |
| `scry_core.sequence` | the executor of a list of steps run in one call (`perform`, `drive`'s act, `start`'s plan) |
| `scry_core.vocabulary` | a closed vocabulary or a range, the judge and the schema half from one tuple, and the one ceiling on a wait |
| `scry_core.reply_schema` | each tool's reply model published as its `outputSchema` (every field its value or `unavailable(why)`, the fields an `ok` reply always carries required), the envelope every reply carries, the strict check of every reply the battery builds, a field marked `OmitEmpty` left out when empty or `When(...)` stated in its sentence, and the names a description's `Reply:` sentence gives that its model does not hold or leaves optional without a stated condition |
| `scry_core.roster` | a server's tools by family: the `instructions`' roster and the sentence naming what answers a running machine, both rendered from one table that partitions the registry, and the gate saying what a step may run on a running machine |
| `scry_core.media_replies` | the reply models of the file tools both servers share |
| `scry_core.tool_replies` | the fields of `screen_map_write`, `log_wait` and `comment_write` that mean the same on both servers, each server's model adding its own |
| `scry_core.regpoint` | the `regpoint_hit` of a registerpoint stop: its ref, condition and pc, and the sentence saying it stays armed |
| `scry_core.process_tree` | ending a launched process with everything it started, and whether a pid lives (a zombie is not alive; a failing `ps` is an error) |
| `scry_core.session_block` | the `session` block that closes every reply: the alarms on every one, the fixed half on `start` and `status`, the short block naming what it left out, or the half itself where naming it would cost more; what `close` and `status` say with no session |
| `scry_core.boundary` | the call boundary every server wraps its tools in: the lock, the nesting, a cancelled call's end and record, and the reply every path closes with |
| `scry_core.ends_table` | a server reference's table of how a cancelled call ends, held against what its tools declare |
| `scry_core.envelope` | the MCP boundary's server object: its `instructions` closed by the notice that the servers are in development and want the model's criticism, the schema's refusal given the server's envelope, off the event loop, a tool's picture attached, and a reply whose text JSON cannot take (a NaN, an infinity) refused naming the tool |
| `scry_core.progress` | the progress line of a bounded wait: one a second, one short line, never backwards, none once the call is cancelled, bridged from the tool's worker thread to the request |
| `scry_core.cancel` | a cancelled call: the poll every bounded wait makes, the shield its end runs under, how each tool declares it ends, and the record the next reply carries |
| `scry_core.strict_arguments` | the schema as part of a tool's contract: what it does not declare is refused |
| `scry_core.given` | the arguments a call was given, before the schema fills the defaults: what the MCP boundary read from the client, or what a call in process passed, held for the tool's body so a profile fills only the rest |
| `scry_core.methods` | a tool whose operation is a `method` argument: the method dispatched, an argument it does not take refused naming it, and the fold's pre-gate judge and summary line |
| `scry_core.prose` | how a count is said in a summary, a note or a refusal: the one plural rule, and the verb that agrees with it; and the one summary line every tool answers for a refusal |
| `scry_core.declaration_file` | the file both servers keep their declarations in: read whole, a key's rows judged by shape, one key written atomically |
| `scry_core.project_store` | the store a repository declares for its own program (`.scry/`): the root found by walking up, a `start` profile read against it (`scry-start/1`), each path resolved against the one base, and the caller's argument winning over the profile's |
| `scry_core.promote` | the session's draft and the promotion that writes it into a repository's store: one candidate per (kind, name), complete only with what makes it replayable, a name the store already holds shown as its update's diff, every path expressed against `${root}`, `${home}`, `${state}` or `${env:NAME}`, and `.scry/` created only by an approved call |
| `scry_core.promote_diff` | what an update changes in a store entry, as a promotion's review shows it |
| `scry_core.promote_paths` | a path as a tracked store file may hold it: under the store's placeholders or refused |
| `scry_core.declaration_rows` | the identity every listed declaration carries on both servers: ref, how declared, cpu, when and in which session, whether that session is this one, and its age; the kinds a list was asked for, the one refusal of a clear's scope, and a comment's own remedy for a row of no session |
| `scry_core.log_marks` | the argument `log` and `log_wait` take to read what came after a mark: its description and the `mark` of `state_write(method="load")`, its schema bound, and the refusals of a position that names none |
| `scry_core.signalled_end` | how a server ends on SIGTERM, SIGHUP or Ctrl-C: the emulator closed under the lock or past its wait, the scratch removed, the process left |
| `scry_core.state_files` | a saved state's name, as `file_names.word` spells it, what sits under it and holds no state (a dangling link, a directory, a FIFO), said instead of opened, and the load's refusal of it |
| `scry_core.file_names` | the name of a file a server writes ([docs/file-names.md](docs/file-names.md)): an outside value normalised into it or refused, a made-up name built inside it, a caller's path changed in its last component only, and the walk a battery holds the files it wrote to |
| `scry_core.value_format` | how a watched value is typed: the format of its bytes (scalars, arrays, strings, structs, pointers; a NaN or infinite float read as the text `nan`, `inf` or `-inf`), the `types` file naming one per symbol, and the pointer ref read through one |
| `scry_core.reply_differences` | the advance tools' reply fields of the two servers side by side, read off their generated reference pages into `docs/advance-differences.md`, which a test holds to the run |
| `scry_core.names_written` | the files a server wrote during its battery, judged by their names case by case for a server's `conftest.py`: the new ones outside the rule, less the names another program fixes, and whether a whole run judged none |
| `scry_core.reply_shapes` | the pytest plugin running the test-time guard (`reply_shapes_guard`) that holds one word to one shape in every reply |
| `scry_core.reply_shapes_guard` | what that plugin runs: every key of a reply in the one shape the table gives it, no null anywhere, and the reply held to its tool's declared model (`reply_schema.check`) |
| `scry_core.verdict` | what every instrument here answers when it has no verdict (the probe, the cap check, the live bench, the demo, the replay, the hook): `Invalid` and the exit codes 0, 1 and 3 |
| `scry_core.client_cap` | the prefix of a text the MCP client delivers, in its own unit |
| `scry_core.probe` | what a model calls when all it holds is what the client delivers |
| `scry_core.probe_any_of` | a task's expected values: JSON equality that keeps a bool from passing for a number, the `any_of` alternatives, and a `regex` node that judges a pattern by the lines of a captured text it selects |
| `scry_core.probe_captures` | the capture store: one file per task with the lines a real run answered it with, written from a run and judged again, free, against the surface as it is now |
| `scry_core.probe_checks` | what each server's suite checks on its own probe surface: tasks, captures, the cap and its margins |
| `scry_core.live_bench` | the pinned copies a server's live tier runs on |
| `scry_core.live_host` | the host a live tier runs on: a canary that refuses one which cannot start the emulator, the ledger that proves no emulator outlived a run, and the run's scratch left as its verdict says |
| `scry_core.live_ledger` | the bookkeeping a live matrix keeps: the sections it plans and the cells each promises, the calls it records, the tally, the transcript, the evidence a FAIL leaves, and the jobs it pools |
| `scry_core.live_focus` | the focus section both live matrices run: the control that opens a run and the verdict that closes it, judged into the ledger that ran them |
| `scry_core.app_launch` | an emulator launched as a `.app` through `open`: the bundle's executable, the command that connects its channels, the pid the session's token finds, and a handle that never claims an exit status it did not reap |
| `scry_core.binaries` | which emulator a session runs: the caller's `binary`, else the server's variable, else the PATH's, and what the build says it is |
| `scry_core.hook` | the pre-commit every pinning repository runs: new duplication, the probe's tasks, the prose ceiling, and the tree typed as Windows sees it |
| `scry_core.host_program` | a test double's program and a path as the host runs and spells them, and the markers that skip a case only one host can hold |
| `scry_core.demo` | the runner of a server's `demos/`: its steps over stdio, their checks, the README block they generate (the steps a demo marks as its highlights, each with how the call does it, and a link to the whole run it commits beside the README), and the flow of the steps it shows in the server's front door |
| `scry_core.game_demo` | one game's demo written once for both servers: the `Binding` that holds only what a platform cannot say the same way (how it starts, which input fires each of the game's actions, the screen's refresh, the recording its sound is held to) and the steps a script builds from it |
| `scry_core.games` | the scripts of the games both servers run, one module per game with its one screen map |
| `scry_core.recording` | a session as a bench: what a server did, recorded from its `start` through its call boundary, and exported as `perform`'s own document (`perform_export`); the check a replayed step holds to |
| `scry_core.comment_file` | the comment file both servers read and write (version 1): its header, columns, text and stamp rules, parse and render, each server's `ref` and `cpu` columns handed in as a `Policy` |
| `scry_core.replay` | the runner of that document: the server over stdio, its steps in one `perform`, with no model |
| `scry_core.focus_watch` | whether a live run took the owner's focus or moved their Space: the frontmost application and each display's Space, keyed by the display, sampled from outside the run (macOS), and the judge of a window of samples |
| `scry_core.focus_gate` | the flow a live section takes the watch through: the control (a start in front, one behind, the owner's Space moved and put back; the first and last only when asked), the verdict after it, each in `live_pool`'s words |
| `scry_core.frame_window` | `perform(until_frame=F)` on a server whose stops carry an absolute `frame`: the arguments' check, the list's check against where the machine stands, and the `Cycle` that repeats the list until a stop reads the frame, bounded in steps and in time |
| `scry_core.presence` | the presence indicator: a session's state, the look both emulators draw (colour, edge, fades; the pointer is DOSBox-X's own), and the check that holds a server's declaration of which tools drive against its registry |
| `scry_core.guardian` | what ends an emulator with its server: on POSIX a watcher process that also keeps its session's wall-clock bound, on Windows a job object the server holds, which the OS closes however the server ends |
| `scry_core.window_capture` | what the host shows of an emulator's window, for a live tier: the window found by its owner's pid, captured by the host (macOS, a refusal raised as `Blocked`), two captures compared by where they differ, and whether that difference is the presence edge |
| `scry_core.window` | the window a server was asked to open, as the host shows it: the `display`, `fullscreen` and `size` of a watched `start` validated against the host's displays and each emulator's full-screen rule, the window found by its owner's pid and read as a `window` reply block (display, bounds, on screen, in front, full screen), waited for, and brought forward and read back; plus the shared launch-behind decision and environment |
| `scry_core.window_words` | a window request as an emulator's command-line words (MAME's `-screen0`, DOSBox-X's `sdl display` and position), the one place a server's `start` and the shell read them from |
| `scry_core.window_size` | the size of a window in the host's unit: parsed, fitted to a display's usable area, judged against what the host lists (client area on Windows, outer on macOS), and each emulator's full-screen rule per platform |
| `scry_core.window_cli` | `python -m scry_core.window_cli displays`, `words`, `launch` and `proof`: the same display index, placement words and window proof a watched `start` uses, for a session with only a shell, the same on macOS and Windows |
| `scry_core.window_host` | the window system behind `window`: macOS through CoreGraphics (a window forward means its display's Space switched to, then its application frontmost) and Windows through user32, per-monitor DPI aware |
| `scry_core.conformance` | the session contract a server runs in one test file: `SessionContract` over a `subject` fixture, the rules every server's `start`, `window`, `status` and `close` meet |
| `scry_core.window_tier` | the pytest plugin serving the window tier: the `window` marker and the `behind_a_fullscreen_app` fixture, with nothing to copy into a server's tests |
| `scry_core.window_stand_ins` | what that fixture opens (a window of its own, then a full-screen application taking its Space) and `on_the_desk`, which marks a test as the tier and skips it unless the desk may be moved; `hosts`, the window doubles of a server's unit tests |
| `scry_core.process_name` | the name a server's process, and its guardians', go by in the host's process list |
| `scry_core.narrowing` | a reply that answers less than everything and says so: `omitted` and `how`, and the `sections` list a caller narrows by |
| `scry_core.traffic` | what a server's replies and its tool list cost the model, per tool, in the client's unit, and the visual tokens of the pictures replies attach, read from `list_tools()` and, when given, live transcripts |
| `scry_core.live_pool` | a live tier's independent jobs run as parallel child processes, merged from the summaries they declare |
| `scry_core.png` | one PNG codec in the standard library: indexed or RGB, a transparent index, APNG, the nearest-neighbour enlargement, and a decoder of every row filter that refuses any other kind by name |
| `scry_core.picture` | the picture a view tool attaches: the inline ceiling, the integer scale, the file written once, and the attachment beside the JSON |
| `scry_core.raster` | what a picture is compared by: its crop, its one signature, its difference from another, the region measures |
| `scry_core.series` | a series of frames on disk (`scry-series/1`): its manifest and its reply's tail, and series against series and a region through a series, each with its control |
| `scry_core.goldens` | files against goldens written by `shasum -a 256`, by name |
| `scry_core.media_tools` | the tools that read media files and no emulator, one body, description, summary and judge each, registered by each server through its own decorator |
| `scry_core.judges` | the argument judges both servers share: a number as an integer or its `0x` spelling, whole numbers, a written file's path, size and hash, rectangles, shifts, the one path rule (absolute or `~`-led, `~` expanded), a file to write under the name `file_names` gives it, a folder to make, the picture a path names, and a caller's file that must exist and its text read whole |
| `scry_core.fresh` | files and directories created new, never over another, never left half written; a file the caller asked to replace, renamed over the old one whole or not at all; and a directory taken back when the work that fills it fails |
| `scry_core.avi` | an AVI's main header: its frame size, and its frames, by the header once the file is finished and by its chunks while it is written |
| `scry_core.wav` | what a recording says, measured from the WAV: whether it sounded, how loud, when, whether it clipped, and how close two recordings are; and whether a recorder's own file is finished, with its header and its lowest and highest sample |
| `scry_core.bus_writes` | a tap's bus access as bytes: the lanes its mask drove in either byte order, and a count watch's value table |
| `scry_core.docs` | a tool description's `{NAME}` placeholders, filled from the constants that enforce them |
| `scry_core.reference` | a server's reference generated from its registry: per tool its call, arguments, reply fields, description and a live example, on its family's page; the index and the envelope in `REFERENCE.md`; and `drift`, the check each server's test runs |
| `scry_core.scan_vocabulary` | the words a value scan is asked in: its cell widths, its comparisons, the most hits a call lists |
| `scry_core.screen_map` | screen maps (`scry-screen-map/1`): which screen of an application a machine shows, off one read of it, and its named controls, in a file layer and a session layer; a map's mode (verified or consolidated), each screen's anchor for `run_to(screen=)`, and the view a machine shows the program's picture through |
| `scry_core.pens` | the views of a screen by pen both servers draw: an isolation's hue and greys, its pixels and box, the pixel view's crop, and unused pens said as runs |

Each server pins it by a release tag, never by a branch:

```toml
dependencies = ["scry-core @ git+https://github.com/scry-mcp/scry-core@<tag>"]
```

The probe, the bench and traffic take what they act on as options, so none reads a tree it was
not pointed at. The probe's paths below, and traffic's servers file, are a server repository's
own; the bench is the directory a server's live tier resolved, and its manifest is
`<bench>/bench.json`. The hook takes none: it runs from inside a repository that tracks
`.jscpd-baseline.json`, has `jscpd` on the path and keeps its probe at `mcp_probe/servers.py` and
`mcp_probe/tasks/`. The reference runs from a server repository too, where `<module>` imports:

```sh
uv run python -m scry_core.probe all --check --servers mcp_probe/servers.py --tasks mcp_probe/tasks
uv run python -m scry_core.live_bench check --bench <bench>
uv run python -m scry_core.traffic <server> --servers mcp_probe/servers.py --transcript <jsonl>
uv run python -m scry_core.hook
uv run python -m scry_core.window_cli {displays|words|launch|proof}
uv run python -m scry_core.replay <document> [--binary PATH] [--rompath DIR] [--transcript PATH]
uv run python -m scry_core.reference <module>:<attribute> [--examples JSONL ... [--mark PATH=TEXT ...]] [--write]
```

`--help` on each is its contract. A real probe run asks the `claude` CLI and needs the network;
`--check` and the probe's answers seam (`MCP_PROBE_ANSWERS`) need neither. `fill` runs the `capture` commands its manifest names,
so it fills only from checkouts you trust. Each repository's `.githooks/pre-commit.sh` is the one
line that calls the hook through its own `uv run`.

`reply_shapes` is a pytest plugin, loaded through the `pytest11` entry point wherever this package
is installed. A suite declares the modules it wraps in its own configuration, and a run that
declares none is refused:

```toml
[tool.pytest.ini_options]
reply_shapes_anchors = ["scry_core.reply_contract", "server"]
```

## Focus watch

A live tier that runs beside somebody working wraps its run in `scry_core.focus_watch.FocusWatch`,
takes `scry_core.focus_gate.control` in the same harness (one start that must be seen in front,
one that must not, and the owner's Space moved and put back, which must be seen moved), and
judges the run after it with `focus_gate.verdict`; each outcome is OK, FAIL or BLOCKED,
`live_pool`'s words, put on the tier's own cells. The start in front and the Space move take the
desk of whoever is working, so they run only with `SCRY_FOCUS_CONTROL=1` on an idle machine;
unset, those two cells are BLOCKED and the verdict says it is unproven (a stolen focus still
fails it); run while somebody works, the control takes their desk and its start-in-front cell
fails anyway, since macOS keeps focus with the app in use. The two module docstrings are the contract. The watch is a sampler: it sees what stays
in front at its instants, and a theft between two samples leaves no trace in it. A green focus cell reads "nothing stayed in
front", never "nothing took focus"; when the person at the machine says they lost focus, that is
the fact, and the cause is read off the process tree while it happens.

## On-demand tiers

A tier that takes the desk of whoever is working never runs by accident. Each is a marker, left
out of the default run by `addopts` and run by naming it:

| Marker | What it opens or moves | Command |
|---|---|---|
| `window` | stand-in windows, and the owner's Space (macOS: skipped without the variable or without `swiftc`; Windows: the `WindowsHost` tests need an interactive desktop, not the variable) | `SCRY_FOCUS_CONTROL=1 uv run pytest -m window --no-cov` (macOS), `uv run pytest -m window --no-cov` (Windows) |

The marker, the `behind_a_fullscreen_app` fixture and the `on_the_desk` decorator arrive with this
package, so a server adds only `not window` to its own `addopts` (`-m 'not live and not window'`).
`--no-cov` because a partial run cannot judge a floor that belongs to the whole tree, and a
command-line `-m` replaces the one in `addopts`. A run with `-o addopts=` drops the deselection
altogether, so it names `-m window` explicitly and keeps `-p pytester`, which that override drops
too and without which the conformance tests error. Before the tier, check that nobody else is
using the screen: a peer's run on the same machine loses its desk the same way.

On Windows the tier runs on an interactive desktop, and what looks like a bug in the code under
test is usually the desktop: `WindowsHost.activate` says what it takes to bring a window to the front.

## A new server

[docs/new-emulator.md](docs/new-emulator.md) is the checklist, and `scry_core.conformance` holds
the contract a server's own `start`, `window`, `status` and `close` run against. [docs/katas.md](docs/katas.md)
lists the demos and screen maps and which servers run each.

## Parallel live tiers

A live tier whose jobs share nothing runs them as child processes of its own script through
`scry_core.live_pool.run_pool`, each child writing its summary with `write_summary`, and passes
`default_workers()` to keep half the host free. The module docstring is the contract.

A child that dies at import, because the environment holds another `scry_core` than the parent's,
reads as cells failing: `live_pool`'s docstring says how to see it and what to set.

## Demos

Each server keeps its demos in `demos/<name>/`: a README with the prompt to give an MCP client, a
`demo.py` making the same calls and checking each answer, and what `demo.py --update-readme`
writes from a run where every step passed, so what the README shows is what the server answered:
the README's block, which holds every step or, where the demo marks steps as highlights, only
those with how each call does it and a `TRANSCRIPT.md` beside it with every step, and
`screen.png`. `scry_core.demo` is the runner both servers share, and its module
docstring is the contract. A game that exists on both platforms is one script in `scry_core.games`,
run by each server's `demos/<game>/` through a short `Binding` (`scry_core.game_demo`): the same
steps, symbols, screen map and checks on both, which is what proves the two servers answer one
surface.

## Trying a server by hand

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) calls either server directly
and shows each raw request and reply. It starts its own copy of the server, so it cannot see a
session another client holds. One config covers both servers, which is why it lives here. The
UI labels an entry by its key, and a server given on the command line is labelled by its command,
`uv`, so save the servers under their names as `inspector.json`:

```json
{
  "mcpServers": {
    "Scry - MAME MCP": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/scry-mame", "python", "server.py"],
      "env": {"MAME_BINARY": "/path/to/mame"}
    },
    "Scry - DOSBox-X MCP": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/scry-dosbox-x", "python", "dosbox_x_server.py"]
    }
  }
}
```

`MAME_BINARY` is optional: without it `start` takes `mame` from the `PATH`, and either way the
build needs what the scry-mame README lists. Run this beside the file and open the URL it prints,
token included; `HOST` keeps the UI on loopback:

```sh
HOST=127.0.0.1 npx -y @modelcontextprotocol/inspector@2.11.0 --web --config inspector.json
```

`--cli` starts a fresh server per call, so the emulator a `start` opened dies with it; use the
web UI for anything that spans calls. `--cli` exits 0 on a refusal: an `INVALID` reply is a
result, `isError: false`, so read its `status`. A non-zero exit is the call itself failing,
such as an unknown tool.

## Platforms

macOS and Windows, as a library: every module imports on both, and what only one of them has is
chosen by `sys.platform` (a guardian is a watcher process on POSIX and a job object on Windows).
Linux runs the unit tests (`.github/workflows/ci.yml`); the servers support macOS and Windows only.

## Developing

```sh
uv sync
uv run ruff check .
uv run mypy --strict .
uv run mypy --strict --platform win32 .
uv run pytest -q
```

On Windows the same, with `uv run pytest -q --no-cov`: the coverage floor is judged on macOS,
since Windows skips by design the cases that need what it lacks (a FIFO, a mode bit).

Each repository runs `jscpd` on itself only, so a shape both servers print (an address's width,
an unknown op's refusal, a timestamp) can be written once per server with every battery green,
and the two copies diverge while each keeps passing its own tests. Before writing a formatter, a
parser or a reply helper in one server, search this package and the other server for it: a shape
both servers need lives here from the second server on, never as two copies. At a review of work
that touched both servers, run `jscpd` over the three trees together as a report (it refuses
nothing) and read its JSON beside the diff: a new cross-repository clone is a finding like any
other, and so are a helper with one caller, a wrapper and a parameter nobody passes.

Licence: MIT.

## Credits

Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).
