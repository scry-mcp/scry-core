# The modules of scry-core

One row per module, so you can find what is already written before writing it again in a
server. Each module's docstring is its contract; this page only says what it is for. The rows
are in the groups the [README](../README.md#what-the-package-holds) names.

## Replies

| Module | What it holds |
|---|---|
| `scry_core.reply_contract` | A refusal's three fields (`status`, `code`, `message`), the class that builds one, and `unavailable(why)` for a value that could not be read. |
| `scry_core.reply_schema` | Each tool's reply model published as its `outputSchema`, and the check that every reply a test builds matches it. |
| `scry_core.session_block` | The `session` block that closes every reply, and what `close` and `status` answer with no session. |
| `scry_core.envelope` | The MCP server object: its `instructions`, a tool's picture attached to its reply, and a reply JSON cannot carry refused by name. |
| `scry_core.narrowing` | A reply that answers less than everything and says so: `omitted`, `how`, and the `sections` a caller asks for. |
| `scry_core.instruction` | The fields of the instruction a stopped machine is at (`address`, `bytes`, `text`, `symbol`, `delta`). |
| `scry_core.tool_replies` | The reply fields that mean the same on both servers for `screen_map_write`, `log_wait`, `comment_write`, `screen_wait` and a refused `profile`. |
| `scry_core.media_replies` | The reply models of the file tools both servers have. |
| `scry_core.knowledge` | The knowledge base: the entries of a server's dictionaries (`scry-knowledge/1`), the database that loads them and answers by number, range, words and device, what a server declares it supports, and the checks its dictionaries are held to. |
| `scry_core.knowledge_tool` | `knowledge_find`, the one tool that asks the base what a number is called: its description, judge, body, summary line and reply model, registered by each server. |
| `scry_core.prose` | How a count is written in a summary or a refusal, and the one summary line of a refusal. |

## Calls

| Module | What it holds |
|---|---|
| `scry_core.boundary` | The wrapper every tool call goes through: the lock, a call inside a call, how a cancelled call ends, the reply each path closes with, and the listener that hears every call begin and end. |
| `scry_core.cancel` | A cancelled call: the check every wait makes, how each tool says it ends, and the record the next reply carries. |
| `scry_core.progress` | The progress line of a wait: one a second, never backwards, none after a cancel. |
| `scry_core.strict_arguments` | An argument the schema does not name is refused. |
| `scry_core.given` | The arguments a call was given before the schema filled its defaults, so a start profile fills only the rest. |
| `scry_core.methods` | A tool whose operation is its `method` argument: the method chosen, and an argument that method does not take refused by name. |
| `scry_core.judges` | The argument checks both servers use: numbers and their `0x` spelling, paths, rectangles, a file to write, a file that must exist. |
| `scry_core.vocabulary` | A closed set of words or a range as one tuple, read by the check and by the schema, and the longest a wait may be. |
| `scry_core.docs` | The `{NAME}` marks of a tool description, filled from the constants the code enforces. |

## Running and stopping

| Module | What it holds |
|---|---|
| `scry_core.log_wait` | A wait for a line of a log: what the log already holds first, then the wait, and what ended it. |
| `scry_core.stop_wait` | `screen_wait` checked at a breakpoint or a watch: its arguments, its condition grammar, its reply fields and its refusals. |
| `scry_core.regpoint` | The `regpoint_hit` of a stop on a register condition, and the sentence saying it stays set. |
| `scry_core.log_marks` | The `mark` argument of `log` and `log_wait`, which reads only what came after a position. |
| `scry_core.frame_window` | `perform(until_frame=F)`: a list of steps repeated until a stop reads frame `F`, limited in steps and in time. |

## Several calls as one

| Module | What it holds |
|---|---|
| `scry_core.sequence` | What runs a list of steps in one call (`perform`, the action of `drive`, the `plan` of `start`). |
| `scry_core.steps` | A step checked against the tool it names before any step runs. |
| `scry_core.sequence_account` | What a list's reply says of each step: compact rows, the two files, and how many stops it counted. |
| `scry_core.recording` | A session recorded from its `start` and exported as a document `perform` replays (`perform_export`). |
| `scry_core.replay` | The program that replays that document with no model: the server over stdio, its steps in one `perform`. |

## Breakpoints, watches and comments

| Module | What it holds |
|---|---|
| `scry_core.declaration_file` | The file both servers save breakpoints and watches in: read whole, one key written at a time. |
| `scry_core.declaration_rows` | What every listed breakpoint or watch says of itself: its `ref`, its cpu, when and in which session it was made. |
| `scry_core.comment_file` | The comment file both servers read and write: its header, its columns, its parser and its writer. |
| `scry_core.value_format` | How a watched value is typed: scalars, arrays, strings, structs and pointers, and the `types` file. |
| `scry_core.bus_writes` | A write on the bus as bytes, in either byte order, and the table a counting watch keeps. |

## The `.scry/` folder

| Module | What it holds |
|---|---|
| `scry_core.project_store` | A repository's `.scry/` folder: found by going up from a path, and a start profile read from it. |
| `scry_core.promote` | What a session learned, and the reviewed call that writes it into a repository's `.scry/`. |
| `scry_core.promote_diff` | What an update changes in a file of `.scry/`, as the review shows it. |
| `scry_core.promote_paths` | A path as a tracked file of `.scry/` may hold it: under `${root}`, `${home}`, `${state}` or `${env:NAME}`, or refused. |
| `scry_core.scry_readme` | The template of a repository's `.scry/README.md` and the command that renders it ([scry-readme.md](scry-readme.md)). |

## Pictures, video and sound

| Module | What it holds |
|---|---|
| `scry_core.png` | A PNG encoder and decoder in the standard library: indexed or RGB, APNG, whole-pixel enlargement, a rectangle cut out. |
| `scry_core.picture` | The picture a tool attaches: its size limit, its whole-number scale, and the file written once. |
| `scry_core.raster` | What two pictures are compared by: a crop, a fingerprint, the difference, the measures of a region. |
| `scry_core.series` | A series of frames on disk (`scry-series/1`), and series compared with series. |
| `scry_core.pens` | The views of a screen by palette index that both servers draw. |
| `scry_core.screen_map` | Screen maps (`scry-screen-map/1`): which screen of a program is showing, and its named controls. |
| `scry_core.scan_vocabulary` | The words of a value scan: cell widths, comparisons, and the most hits one call lists. |
| `scry_core.avi` | An AVI's header: its frame size and how many frames it holds, finished or still being written. |
| `scry_core.wav` | What a recording says, measured from its WAV: whether it sounded, how loud, and how close two recordings are. |
| `scry_core.goldens` | Files compared with reference digests written by `shasum -a 256`. |
| `scry_core.media_tools` | The tools that read media files and no emulator, registered by each server. |

## Windows and processes

| Module | What it holds |
|---|---|
| `scry_core.window` | The window a `start` asked for, as the host shows it: display, bounds, on screen, in front, full screen. |
| `scry_core.window_words` | A window request as an emulator's command-line words. |
| `scry_core.window_size` | A window's size in the host's unit: parsed, fitted to a display, and each emulator's full-screen rule. |
| `scry_core.window_host` | The window system behind `window`: CoreGraphics on macOS, user32 on Windows. |
| `scry_core.window_cli` | `python -m scry_core.window_cli`: the same display index, words and window check from a shell. |
| `scry_core.window_capture` | What the host shows of an emulator's window: captured, and two captures compared. |
| `scry_core.presence` | The coloured border both emulators draw while a session holds the window, the layers drawn over it (`Payload`), the keys and pointer a server reports, and the tints and timings (`Look`). |
| `scry_core.overlay` | `start`'s `overlay` argument, which layers presence draws, and the `overlay` field of `start`'s and `status`'s replies. |
| `scry_core.overlay_timeline` | What the overlay shows at a moment: a caption's minimum time, a burst joined with a count, its tint, its exit, and a keycap kept long enough to be seen. |
| `scry_core.abbreviation` | A call as its caption reads: the tool and its values, each cut short, a path by its last name and never a home folder's. |
| `scry_core.placement` | Whether captions go to the top or the bottom of the picture, and `placement_vectors.txt`, the cases each emulator's drawer replays. |
| `scry_core.app_launch` | An emulator launched as a macOS `.app` through `open`, and the process id found for it. |
| `scry_core.binaries` | Which emulator a session runs: the caller's `binary`, else the server's variable, else the one on `PATH`. |
| `scry_core.guardian` | What ends an emulator when its server ends: a watcher process on POSIX, a job object on Windows. |
| `scry_core.process_tree` | Ending a launched process with everything it started, and whether a process id is alive. |
| `scry_core.process_name` | The name a server's process has in the host's process list. |
| `scry_core.signalled_end` | How a server ends on SIGTERM, SIGHUP or Ctrl-C: the emulator closed, its temporary folder removed. |

## Files

| Module | What it holds |
|---|---|
| `scry_core.file_names` | The one rule for the name of a file a server writes ([file-names.md](file-names.md)). |
| `scry_core.fresh` | Files and folders created new: never over another, never left half written. |
| `scry_core.state_files` | A saved state's name, and what is refused under that name because it holds no state. |
| `scry_core.names_written` | The files a server's tests wrote, checked against the naming rule. |

## What generates the documents

| Module | What it holds |
|---|---|
| `scry_core.reference` | A server's reference pages written from its tool registry and its `asks.json`, and the check that they are current. |
| `scry_core.asks` | The hand-written half of a reference, `docs/reference/asks.json`: each tool's sentences, checked against the registry and a page's word limits. |
| `scry_core.entry` | One tool's entry on its page, in the one order every entry has. |
| `scry_core.transcript` | A demo's committed transcript read back as calls and replies, for the reference's examples. |
| `scry_core.roster` | A server's tools by group: the list its `instructions` carry and the tools that answer while the program runs. |
| `scry_core.ends_table` | The reference's table of how a cancelled call ends, compared with what the tools say. |
| `scry_core.reply_differences` | The reply fields of every tool both servers have, side by side, in [reply-differences.md](reply-differences.md). |
| `scry_core.demo` | What runs a server's `demos/`: each step over stdio, its check, and the README blocks a run writes. |
| `scry_core.example` | The one shape of an example: the ask, the call, an excerpt of the reply, how to read it. |
| `scry_core.motion` | A demo's `loop.webp` and `screen.png`: stretches cut from a run's recordings and assembled with ffmpeg and `img2webp`, both shown at 4:3. |
| `scry_core.aspect` | The shape a game's picture is shown in: the whole frame at 4:3, one function for the loop and the still. |
| `scry_core.timeline` | What a demo run did, call by call, in the emulator's frames: the file the demo decorator reads. |
| `scry_core.install` | The table of MCP clients and the block of a server's README that says how to add it to each. |
| `scry_core.game_demo` | One game's demo written once for both servers, with a `Binding` for what each emulator does differently. |
| `scry_core.games` | The scripts of the games both servers run, one module per game. |

### A demo run's timeline

A run writes `<transcript>-timeline.json` beside its transcript: the calls it made, in order, with the emulator frame each began and ended at. `scry_core.timeline.loads` reads it back and refuses a document the writer never writes.

The document is `{"version": 1, "demo": <name>, "calls": [...]}`. Each call holds:

| Field | Holds |
|---|---|
| `n`, `step`, `tool` | Its position in the run from 1, the demo's name for it, and the tool called. |
| `args` | The arguments as the demo gave them: a symbol stays the symbol written, with host paths spelled as in the transcript. |
| `status` | The reply's `status`, or `ended` when there was no reply. |
| `before`, `after` | The frame the call began and ended at, or null before any reply counted one. |
| `events` | The input the call fired, each with its `frame`. |

`before` and `after` come from the reply's `frame_before` and `frame_after`, else its last `frame`; a call that counts none stays where the call before left the machine. Loading a saved state rewinds the machine, so `after` can be smaller than `before`.

An event is `{"kind": "key", "name", "down", "frame"}`, `{"kind": "button", "name", "down", "frame"}` or `{"kind": "pointer", "x", "y", "frame"}`. A pointer's `x` and `y` are the position the reply reports, in the emulator's screen pixels. A step names its events with `Step.events`, and an event's `frame` lies between its call's `before` and `after`.

## Tests a server runs

| Module | What it holds |
|---|---|
| `scry_core.conformance` | The rules every server's `start`, `window`, `status`, `close`, `promote` and knowledge base meet, as test classes. |
| `scry_core.reply_shapes` | The pytest plugin that runs `reply_shapes_guard` on every reply a test builds. |
| `scry_core.reply_shapes_guard` | One name, one shape in every reply, no null anywhere, and each reply checked against its model. |
| `scry_core.private_run` | The pytest plugin that gives a run a home and a temporary folder of its own. |
| `scry_core.probe` | The description test: what a model calls when all it has is what the client delivers. |
| `scry_core.probe_any_of` | A description test's expected values: JSON equality, alternatives, and a pattern over captured text. |
| `scry_core.probe_captures` | The answers a real run gave each task, kept so they can be checked again for free. |
| `scry_core.probe_checks` | What each server's suite checks on its own description tests. |
| `scry_core.client_cap` | The prefix of a text that the MCP client delivers, in the client's own unit. |
| `scry_core.traffic` | What a server's replies and tool list cost the model, per tool. |
| `scry_core.hook` | The pre-commit check of every repository that pins this package. |
| `scry_core.verdict` | `Invalid` and the exit codes 0, 1 and 3 that every program here answers with. |
| `scry_core.host_program` | A test's stand-in program and a path as the host spells them, and the marks that skip a case on one host. |

## Tests against a real emulator

| Module | What it holds |
|---|---|
| `scry_core.live_bench` | The pinned copies of the programs those tests run. |
| `scry_core.live_host` | The host those tests run on: a first check that it can start the emulator, and proof that none outlived a run. |
| `scry_core.live_ledger` | What a test script records: the cases it plans, the calls it made, the tally and the transcript. |
| `scry_core.live_pool` | Independent jobs run as parallel child processes and merged from their summaries. |
| `scry_core.live_focus` | The focus section both test scripts run. |
| `scry_core.focus_watch` | Whether a run took the focus or moved a Space, sampled from outside the run (macOS). |
| `scry_core.focus_listener` | Every application that comes to the front, heard as it happens by a listener built with `swiftc` (macOS). |
| `scry_core.focus_gate` | The control and the verdict a section of tests wraps the focus watch in. |
| `scry_core.window_tier` | The pytest plugin of the tests that open windows: the `window` marker and its fixture. |
| `scry_core.window_stand_ins` | What that fixture opens, and the stand-in windows of a server's unit tests. |
