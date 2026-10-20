# scry-core

What the Scry emulator MCP servers ([scry-mame](https://github.com/scry-mcp/scry-mame) and
[scry-dosbox-x](https://github.com/scry-mcp/scry-dosbox-x)) share, held once:

| Module | What it holds |
|---|---|
| `scry_core.reply_contract` | the refusal contract (`status`, `code`, `message`), its class and its envelope check; a datum that could not be read as `unavailable(why)`, never a null; a wait's `verdict` words |
| `scry_core.log_wait` | a wait for a line of a log: what the log already holds answered first, then the wait, ended by a match, its bound, a stopped machine or a gone emulator |
| `scry_core.sequence_account` | the account of a list of steps run in one call: compact rows, the two files, and the count of the stops numbered while it ran |
| `scry_core.steps` | a step of a list judged against the tool it names before any step runs: its `recorded` check, no `ctx`, names the tool takes, scalars of the declared type |
| `scry_core.sequence` | the executor of a list of steps run in one call (`perform`, `drive`'s act, `start`'s plan): the wait for a stop before a step that needs one, the end at a failed or diverged step, the tail and its verdict, the machine's own answers handed in as a `SequenceMachine` and a repeated list as a `Cycle` |
| `scry_core.vocabulary` | a closed vocabulary or a range, the judge and the schema half from one tuple: `enum`, a `pattern` for the words taken in any case, `minimum` and `maximum` (`exclusiveMinimum` for a floor the judge itself refuses, a wait's 0), and `one_of`'s one sentence |
| `scry_core.reply_schema` | each tool's reply model published as its `outputSchema` (the field names, no value constrained), the envelope every reply carries, and the strict check of every reply the battery builds, any field also taking `unavailable(why)` |
| `scry_core.media_replies` | the reply models of the file tools both servers share |
| `scry_core.session_block` | the `session` block that closes every reply: the alarms on every one, the fixed half on `start` and `status`, the short block naming what it left out, or the half itself where naming it would cost more |
| `scry_core.boundary` | the call boundary every server wraps its tools in: the lock, the nesting, the outermost-only end of a cancelled call and its record, a cancel met as the body returns, the recording it feeds, the listener that hears each outermost call begin and end, and the reply every path closes with, its summary line first; the server's vocabulary handed in as hooks |
| `scry_core.ends_table` | a server reference's table of how a cancelled call ends, held against what its tools declare |
| `scry_core.envelope` | the MCP boundary's server object: the schema's refusal given the server's envelope, off the event loop, and a tool's picture attached |
| `scry_core.progress` | the progress line of a bounded wait: one a second, one short line, never backwards, none once the call is cancelled, bridged from the tool's worker thread to the request |
| `scry_core.cancel` | a cancelled call: the poll every bounded wait makes, the shield its end runs under, how each tool declares it ends, and the record the next reply carries |
| `scry_core.strict_arguments` | the schema as part of a tool's contract: what it does not declare is refused |
| `scry_core.prose` | how a count is said in a summary, a note or a refusal: the one plural rule, and the verb that agrees with it |
| `scry_core.value_format` | the grammar of a watched value: scalars, arrays, strings, structs, pointers |
| `scry_core.reply_shapes` | the pytest plugin running the test-time guard (`reply_shapes_guard`) that holds one word to one shape in every reply |
| `scry_core.reply_shapes_guard` | what that plugin runs: every key of a reply in the one shape the table gives it, no null anywhere, and the reply held to its tool's declared model (`reply_schema.check`) |
| `scry_core.client_cap` | the prefix of a text the MCP client delivers, in its own unit |
| `scry_core.probe` | what a model calls when all it holds is what the client delivers |
| `scry_core.probe_checks` | what each server's suite checks on its own probe surface: tasks, captures, the cap |
| `scry_core.live_bench` | the pinned copies a server's live tier runs on |
| `scry_core.live_host` | the host a live tier runs on: a canary that refuses one which cannot start the emulator, the ledger that proves no emulator outlived a run, and the run's scratch left as its verdict says |
| `scry_core.binaries` | which emulator a session runs: the caller's `binary`, else the server's variable, else the PATH's, and what the build says it is |
| `scry_core.hook` | the pre-commit every pinning repository runs: new duplication, and the probe's tasks |
| `scry_core.demo` | the runner of a server's `demos/`: its steps over stdio, their checks, and the README block they generate |
| `scry_core.recording` | a session as a bench: what a server did, recorded from its `start` through its call boundary, and exported as `perform`'s own document (`perform_export`); the check a replayed step holds to |
| `scry_core.comment_file` | the comment file both servers read and write (version 1): its header, columns, text and stamp rules, parse and render, each server's `ref` and `cpu` columns handed in as a `Policy` |
| `scry_core.replay` | the runner of that document: the server over stdio, its steps in one `perform`, with no model |
| `scry_core.focus_watch` | whether a live run took the owner's focus or moved their Space: the frontmost application and each display's Space, keyed by the display, sampled from outside the run (macOS), and the judge of a window of samples |
| `scry_core.focus_gate` | the flow a live section takes the watch through: the control (a start in front, one behind, the owner's Space moved and put back), the verdict after it, each in `live_pool`'s words |
| `scry_core.presence` | the presence indicator: a session's state (held, acting), the one look both emulators draw, the writer that delivers the latest state off the call's path, what a server keeps of it (`Shown`), and the check that holds a server's declaration of which tools drive against its registry |
| `scry_core.guardian` | the process beside every emulator that kills it when its server dies or its session's wall-clock bound passes (POSIX) |
| `scry_core.window_capture` | what the host shows of an emulator's window, for a live tier: the window found by its owner's pid, captured by the host (macOS, a refusal raised as `Blocked`), two captures compared by where they differ, and whether that difference is the presence edge |
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
| `scry_core.judges` | the argument judges both servers share: a number as an integer or its `0x` spelling, whole numbers, a written file's path, size and hash, rectangles, shifts, the one path rule (absolute or `~`-led, `~` expanded), a file to write, the picture a path names |
| `scry_core.fresh` | files and directories created new, never over another, never left half written, and a directory taken back when the work that fills it fails |
| `scry_core.avi` | an AVI's main header: its frame size, and its frames, by the header once the file is finished and by its chunks while it is written |
| `scry_core.wav` | what a recording says, measured from the WAV: whether it sounded, how loud, when, whether it clipped, and how close two recordings are |
| `scry_core.docs` | a tool description's `{NAME}` placeholders, filled from the constants that enforce them |
| `scry_core.screen_map` | screen maps (`scry-map/1`): which screen of an application a machine shows, off one read of it, and its named controls, in a file layer and a session layer |

Each server pins it by a release tag, never by a branch:

```toml
dependencies = ["scry-core @ git+https://github.com/scry-mcp/scry-core@<tag>"]
```

The probe, the bench and traffic take what they act on as options, so none reads a tree it was
not pointed at. The probe's paths below, and traffic's servers file, are a server repository's
own; the bench is the directory a server's live tier resolved, and its manifest is
`<bench>/bench.json`. The hook takes none: it runs from inside a repository that tracks
`.jscpd-baseline.json`, has `jscpd` on the path and keeps its probe at `mcp_probe/servers.py` and
`mcp_probe/tasks/`:

```sh
python -m scry_core.probe all --check --servers mcp_probe/servers.py --tasks mcp_probe/tasks
python -m scry_core.live_bench check --bench <bench>
python -m scry_core.traffic <server> --servers mcp_probe/servers.py --transcript <jsonl>
python -m scry_core.hook
python -m scry_core.replay <document> [--binary PATH] [--rompath DIR] [--transcript PATH]
```

`--help` on each is its contract. A real probe run asks the `claude` CLI and needs the network;
`--check` and the replay seam need neither. `fill` runs the `capture` commands its manifest names,
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
`live_pool`'s words, put on the tier's own cells. The two module docstrings are the contract.

## Parallel live tiers

A live tier whose jobs share nothing runs them as child processes of its own script through
`scry_core.live_pool.run_pool`, each child writing its summary with `write_summary`, and passes
`default_workers()` to keep half the host free. The module docstring is the contract.

## Demos

Each server keeps its demos in `demos/<name>/`: a README with the prompt to give an MCP client, a
`demo.py` making the same calls and checking each answer, and the transcript and `screen.png` that
`demo.py --update-readme` writes from a run where every step passed, so what the README shows is
what the server answered. `scry_core.demo` is the runner both servers share, and its module
docstring is the contract.

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

## Developing

```sh
uv sync
uv run ruff check .
uv run mypy --strict .
uv run pytest -q
```

Licence: MIT.
