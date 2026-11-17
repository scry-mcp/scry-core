# Changelog

What a server author notices. A client's view of each server is in that server's own changelog.

## 0.117.0

- `narrowing.map_rest` says what a short `machine_map` reply asks for the rest (the sections it
  left out, else `dest` for a cut list no file holds), and `narrowing.write_whole` writes every
  row of the sections read to the caller's new file, for both servers.
- `narrowing.clip_text` bounds a console's text of no known shape for both servers: whole up to
  `TEXT_MAX` characters, else written whole to the first free `<stem>-N.txt` of the scratch with a
  preview, `output_chars` and `output_path`.
- `stop_wait.DISARM_WATCHES` is the sentence both servers' `run_to` and `run_for` say of
  `disarm_watches`, and `tool_replies.DisarmFields` the two fields it adds (`disarmed_watches`,
  `not_rearmed`), so a reply that runs without the flag does not list them.
- `stop_wait.not_a_stop` refuses a wait on a control, which counts its hits and never stops the
  machine, in one wording for both servers.
- `screen_map.check_frame_flags` refuses a run's own flags (`disarm_watches`, a `condition`) on a
  run to a screen with no anchor, which runs a frame at a time and has nothing to apply them to,
  in one wording for both servers.

## 0.116.0

- `judges.regex(name, pattern)` judges a caller's regular expression for both servers: a
  non-string, an empty one and one that does not compile are refused naming the argument.
- `SequenceMachine.missed` holds the one rule both servers follow: a `log_wait` or
  `screen_wait` TIMEOUT, or an input's `verify` one, ends a list; a run's TIMEOUT does not.
- A list `sequence.run` ends because a step missed what it waited to see ends its `note` with
  that step's own words (its `summary` and its `verify` note), for every server: the cause was in
  the step's reply and only one server copied it into the note, by matching the note's words.
- `log_wait.SILENT` is the clause `timeout_note` says of a writer that wrote no line, for a
  server that adds its own account to say it once.
- `recording.steps_to_replay` and `read_document` resolve the placeholders of a `perform`
  document a store holds, `state` naming the session's scratch (`no_session` when the document
  needs it and there is none): a promoted document's steps were replayed with `${root}` in their
  paths, and refused. A document outside a store keeps any `${` as its steps' own text.
- A promoted `start` recipe writes each part of a `;`-separated `inipath` under the store's
  placeholders, as it did for `rompath`; the parts after the first were left as this host's paths.
- `roster.SHARED_FAMILIES` declares `window` under Session and `screen_wait` under Advance, the
  two tools both servers register that it left out, so `misfiled` refuses a server filing them
  elsewhere.
- `scry_core.reply_differences` compares every tool both servers register, read off all their
  `docs/reference/*.md` pages, into `docs/reply-differences.md` (which replaces
  `docs/advance-differences.md`); the tools only one server has are listed under it.
- `scry_core.promote.Drafts.loaded_entry` keeps the entry name as the session read it: a stem
  outside the file-name rule is no longer respelled, so `keep` never matches it to the entry it
  came from. Every store a server writes holds rule names only.

## 0.115.0

- `scry_core.stop_wait` builds the refusals of a row a wait under `on_*` cannot judge at
  (`no_such_row`, `not_a_change_watch`, `follows_pointer`) and the `TIMEOUT` note
  (`timeout_note`, with where the server judges a firing's frame), and its `DOC_VALUES` carries
  `ON_FIELDS`, the reply sentence for the four fields `tool_replies.StopWaitFields` declares,
  beside `CONDITION_GRAMMAR`.
- `scry_core.promote.keep_start` and `after_map` keep a `start`'s recipe and a map's `add`,
  named by the entry the session read, else by the guest the server names.
- `scry_core.project_store.locate`'s refusal carries `searched`, the directories it walked, so
  a server tells it apart by a field instead of by its words; `tool_replies.ProfileRefusedFields`
  declares it for `start`.

## 0.114.0

- `scry_core.file_names.written_as` words the one sentence a reply's `note` carries when a
  caller's file is written under another name than the one given (`'Shot_1.PNG' is written as
  'shot-1.png'`), and `Boundary.tool(names_file=)` names the argument a tool writes its file by,
  so the boundary adds that sentence to every `ok` reply that names the file written under a
  changed name, a step's included. A name already in the rule, or a reply that wrote no file,
  carries none.

## 0.113.0

- `scry_core.window_host.screens_for` asks the screens again once its answer is older than
  `SCREENS_MAX_AGE_S`, so a Dock or menu bar that shows, hides or moves is placed around within
  that age: it changes a display's usable area and not its bounds, and the answer used to stand
  for the life of the server.
- `scry_core.project_store.misnamed` lists the entries of a store whose file name is not the
  one `locate` looks for under their own name (`Pac_Man.json`, a map without its
  `-screen-map.json`, an entry in a subdirectory), and raises on a store with no entry; a
  server's suite holds its own `.scry/` to it. No lookup takes an older spelling.
- `scry_core.demo.Step.optional` names reply keys a server sends only sometimes (a `note` on a
  stop the host placed), each with its reason; the normalised transcript and the front door drop
  them whether they came or not, so two honest runs write one transcript. A key a step also
  `shown`s is refused before a call.

## 0.112.0

- `scry_core.probe` resolves two marks beside `{root}` in a task file: `{tmp}`, a directory there
  to write into (`/tmp` on POSIX, the temporary directory on Windows), and `{anchor}`, the start
  of an absolute path (`/`, or the root's drive). A task set spelled through them holds before a
  server's judge on every host; one spelling `/tmp/x` is refused on Windows, where that path is
  relative. `resolve_root` and `mark_root` are now `resolve_marks` and `mark_paths`, which puts
  the three back in a capture's lines, and `ProbeRepo` carries `tmp` and `anchor`.
- `scry_core.host_program.POSIX_TASKS` is gone: no task file needs to be skipped on Windows.
- `scripts/windows/bundle.sh` copies the `sync.sh` of the scry-core `main` it carries before it
  runs it, so the host never runs a stale copy, and a sync that could not bring a repository fails
  the step.

## 0.111.2

- `scry_core.hook` starts `jscpd` as `PATH` and `PATHEXT` resolve it, so on Windows it runs the
  `jscpd.cmd` npm installs and not the extensionless shim beside it, which Windows cannot start
  (WinError 193): the duplication check, and a server's hook cases with it, run there too.
- `scry_core.host_program.release_fifo` releases a reader that opens the FIFO after it is called,
  within `seconds` (`RELEASE_S` when left out), and with no reader by then returns: it used to try
  once, find no reader yet, and return, leaving the late reader blocked for good.
- `scry_core.live_ledger.chosen_sections` takes the run's section `names`, and refuses a value with
  no comma that holds a two-letter section's name (`AA`, `BAA`), naming the comma form (`AA,`),
  and a value that names no section (`,`): read as letters the first ran other sections, and the
  second ran every one, both saying nothing.

## 0.111.1

- `scry_core.stop_wait.GRAMMAR`, the condition grammar a server puts in `screen_wait`'s
  description, names a register of the stopped cpu instead of `AX` and `d0`: `d0` is no register
  DOSBox-X's pre-gate takes, so the description offered a call its own server refuses.
- `scry_core.promote.Drafts.loaded_entry` keeps the entry's name as `keep` spells it, so an
  update of a store entry whose stem predates the file-name rule (`Intro_Run`) is still the
  entry read and stays bound to that entry's store.
- `scry_core.window_host.screens` asks its child with a bound (`SCREENS_TIMEOUT_S`), and
  `screens_for` keeps no answer of no screen, so one failed child no longer stands for the
  displays until their bounds move.
- `scripts/windows/run-task.sh` exits 0 only for a step that said `DONE`, left no task and whose
  logs came back; `sync.sh` exits 1 when a repository did not come over; `push-tree.sh` carries a
  tracked file deleted in the working tree to the host, and no longer ends before the copy when
  the file it skips sorts last.

## 0.111.0

- `scry_core.log_wait.timeout_note` takes the clause that closes the note as `run_state`, by
  keyword; left out it is `STILL_RUNNING`, the clause it always closed on, for a caller that
  knows the machine is running. A caller whose own question went unanswered passes what it
  knows instead of cutting the clause off the text.

## 0.110.0

- `scry_core.promote`: an entry a session keeps belongs to one project, fixed when it is kept:
  the repository whose store it was read from, else the current start's, which a server names
  by running its launch inside `Drafts.starting(profile=, anchor=, live=)`: the profile's
  repository, else the anchor's. A start that raises leaving no session of its own live (`live`
  answers what it answered before) leaves the draft as it was, and a start forgets the script
  the last session replayed. The draft is keyed by (project, kind, name) (`Candidate.key`,
  `Drafts.held`). Without `root` an entry is written only into its own project's store
  (`own_store`), one store a call: one whose project holds none is `unwritable` in a review and
  refused in an approval, naming that repository and the `root` to pass; a call none of whose
  entries has a store, entries of two stores, and a name two projects hold (unless `root` is one
  of them) are refused naming them; the server's own directory is never searched, and without
  `root` a review of an empty draft is `needs_call`. With `root` a candidate kept in another
  project says `from`. `kept_line(drafts)` names each project with no store.
  Gone: the module function `starting(drafts, paths)`; the `starting` argument of `promote`,
  `review`, `write`, `unkept` and `after_close`; `store`'s first argument (`store(root)`); and
  the `has_store` of `kept_line` and `after_export`.
- `scry_core.project_store.project`: the project a path belongs to, its links and `..` resolved:
  the nearest directory holding `.scry/`, else `.git`, else its own.
- `scry_core.conformance.PromoteContract`: the promotion rules a server runs against its own
  `start`, `promote` and `close`, the way it runs `SessionContract`.

## 0.109.4

- `scry_core.demo`: `window_args` is what a demo's `start` asks of the window (watched,
  behind, on the display the run names), so both servers' demos declare one policy and the
  reason their `host_args` hides the display is written once.

## 0.109.3

- `scry_core.demo`: a loop whose recording a bound or a stop cut is a failed step, not a
  loop, and the note a stop leaves with it is reported as the host's like the rest of the
  stop it describes.

## 0.109.2

- `scry_core.demo`: the loop step also reports the stop that ended the recording (its
  cause, the place and the survey around it) as volatile, so a program that polls a
  retrace gives the same transcript twice.

## 0.109.1

- `scry_core.demo`: a demo's loop reports what the recording's own start decides (the
  frames it got, the clock and cycles around them, the place it stopped and the file's
  size) as volatile, and its line names the frames the demo asked for, so a demo whose
  picture is taken where the host reached records the same transcript twice.

## 0.109.0

- `scry_core.demo`: `--display` picks the display a watched run's window opens on, so a
  demo records itself on one of the host's own displays instead of the main one.

## 0.108.0

- `scry_core.demo`: a demo declares a `Loop` and the runner records it, right after the step the
  loop names, as one `record` call whose reply joins the transcript; `--update-readme` converts it
  to the demo's `loop.mp4` beside the capture, refused past the loop's budget with its bytes and
  its file named, and `stale` asks that the file is committed, never that its bytes are the run's.

## 0.107.1

- `scry_core.roster`: the `record` words say what a bound does when its release answers, so a
  server that answers `ended: false` over a capture it could not turn off is not contradicted;
  the reply sentence is derived from the field list rather than restated.

## 0.107.0

- `scry_core.promote`: a `root` that reaches the store through `..` is refused as naming the store
  itself, instead of creating a store inside the store.
- `scry_core.hook`: a Lua string's `\z` continuation is part of the string, so the text after it
  is not counted as a comment.
- `scry_core.scry_readme`: the page's introduction no longer names the two servers, so a server
  whose profile forbids naming its sibling renders a page that holds.
- `scry_core.roster`: the `record` reply family and the words both servers' descriptions use
  for it, so the video contract is written once.

## 0.106.0

- `scry_core.promote`: the conditions of `would_create` and `created` use words the `promote`
  description says, so a server's reply-model check no longer refuses the description it takes
  from here.

## 0.105.0

- `scry_core.promote`: an approved `promote` that is given the promoting server's name
  (`server=`, `mame` or `dosbox-x`) also writes the store's `about.json` and the rendered
  `.scry/README.md`. `dry_run` lists what would be created (`would_create`), the approval what was
  (`created`), and `promote_line` says it. A line already in `about.json` is kept and only a new
  file gets a line derived from it; a manifest the page cannot be rendered from refuses the call
  before anything is written. `kept_line` and `after_export` take `has_store`, and with no
  `.scry/` above the project say so and how to see what an approval would create.
- `scry_core.scry_readme`: the footer of every page says it is rendered by `promote`, and that by
  hand the command runs from a scry-core checkout against the repository.

## 0.104.0

- `scry_core.scry_readme`: one template for every repository's `.scry/README.md`, rendered by
  `python -m scry_core.scry_readme` from the folder and a small `.scry/about.json`
  (`scry-about/1`). `--check` reports a page that drifted from its render and writes nothing.

## 0.103.0

- `scry_core.hook`: the prose ceiling judges `*.lua` as it judges `*.py`, per file, counting
  line and block comments and never a string's text or a statement-slot line
  (`--- __SCRY_<name>__`).

## 0.102.0

- `scry_core.window_host`: a server that places a window on macOS reads the screens from a
  one-shot child, so macOS no longer holds the server as an application, which Activity Monitor
  could show as not responding. The answer is reused while the displays' bounds stay the same,
  and a child that fails leaves the displays with no usable area, as before.

## 0.101.0

- `scry_core.demo`: a demo's committed `screen.png` matches a run's capture when the pixels
  match, whatever bytes the host's zlib compressed them into, and a normalised transcript
  hides a written picture's `bytes` and `sha256` for the same reason.
- `scry_core.games.lineup`: the script arrives by the game's code, never by time: each screen
  is waited for at the frame after the game's tick (`Check_Money100`), with `Player1` in the
  condition for the board, and each move is read once the frame that took it has run
  (`Gest_Scores`).

## 0.100.0

- `scry_core.stop_wait`: a screen wait judged at a declared breakpoint or watch, the same on
  both servers. The arguments (`on_breakpoint` or `on_watch`, never with `every`, and a
  `condition` of up to four `&&` terms over registers and `b@`/`w@`/`d@` memory reads), the
  `changed` predicate (a screen the map names other than the first; a frame it names nothing
  does not end the wait), the reply's `waited_on`, `firings`, `frames_examined` and
  `fired_line`, and the `never_fired` refusal, a new code of the reply contract.

## 0.99.0

- `scry_core.focus_listener`: every application that comes to the front, heard as it happens
  by a listener built with `swiftc` beside the record. `focus_watch` runs one, so a stay in
  front shorter than a sampling period is a `TOOK_FOCUS` naming the application and its pid.
  `judge` takes what was heard (`heard=`, required) and answers `INVALID` for a window the
  listener did not hear whole: with no listener no window is `CLEAN`. The activations are kept
  beside the samples, in `<record>-activations.tsv`.
- The sampler no longer asks System Events who is in front: the listener says it, so a watch
  sends no Apple event and needs no Automation permission.
- `focus_gate.control` holds its start in front only when the listener heard it, and blocks
  that cell when nothing listened.
- `private_run` also fails a run whose temp folder could not be removed, naming it: a file
  still held open keeps the folder on Windows.

## 0.98.0

- `scry_core.private_run`, a pytest plugin a suite asks for with `private_run = true`: the run
  gets a home and a temp folder of its own, and fails naming each file it left in that home. A
  run with a `live` case among those selected stands aside.
- A live run that passes its canary removes the scratch earlier runs of its kind kept, past a
  day and beyond the three newest, and says how many; a pooled job removes none.
  `LiveRun.leave` says `kept` with the path when the scratch could not be removed.
- The probe's model call runs with auto memory off, so a run leaves no folder per call under the
  caller's configuration.
- `scripts/windows/run-task.sh` fetches into `scry-win-*` under `TMPDIR` and removes from the
  host the logs of a step that ended and was fetched.

## 0.97.1

- `project_store.locate` finds a screen map by its entry's name: `file_name` and `entry_of`
  hold what a kind's file name adds, where `locate` looked for `<name>.json` in every kind;
  `promote.file_name` and `promote.SUFFIXES` are gone.
- `scry_core.names_written`: what a server's battery holds its files' names to, once for both
  servers. `Names.outside` answers the new files of a case named outside the rule, and
  `judged_nothing` whether a whole run met none.

## 0.97.0

The files this package names or judges follow the one rule
([docs/file-names.md](docs/file-names.md)). A file kept under a retired spelling (a state or a
store entry with uppercase or `_`, `<application>.screen-map.json`) is no longer found until it
is renamed:

- `judges.writable_file` and `judges.fresh_file` return the path under the name it is written
  as, settled before the place is looked at; a name with no extension is refused. A server
  writes the path the judge returns. `judges.fresh_folder` judges a directory to make and asks
  no extension.
- `state_files.check_state_name` returns the name a state is written and read under (`Boss_1`
  and `boss-1` are one state); `STATE_NAME` and `STATE_NAME_MAX` are gone.
- `project_store.entry_name` returns the name a store entry is kept under, and `locate` looks
  for that one.
- A screen map is `<application>-screen-map.json`, and its `application` field is the name its
  file carries.
- A list's files are `batch-<n>-ran.jsonl` and `batch-<n>-replies.jsonl`.
- `file_names.word` refuses a value past `WORD_MAX`, and `file_names.stamp` spells an instant as
  one word.
- A replay document's `needs.states` names each state as it is written.
- The probe keeps a capture under its task's id as `file_names.word` spells it, refuses two
  tasks whose ids spell one file, and names its run directories and the traffic tables with
  `file_names.stamp`.
- The demo runner writes `transcript-normalised.md`, `transcript-flow.md` and
  `transcript-story.md`; a live matrix keeps a failed cell's evidence under its label as words,
  the log's tail as the log's name in words and `-tail.txt`.

## 0.96.0

`scry_core.file_names`, the one rule for the names of the files a server writes
([docs/file-names.md](docs/file-names.md)):

- `word` turns an outside value into words of a name, or refuses it by its argument.
- `name` builds a made-up name and raises on one outside the rule.
- `caller_file` normalises the last component of a path the caller names, and refuses a name
  with no extension.
- `outside` lists the files under a folder named outside the rule, for a battery to hold what it
  wrote to.

The reference generator names its pages through it: a family with no letter or digit is refused
instead of written as `.md`.

## 0.95.1

An app bundle's launch:

- The console no longer blocks its writer: a FIFO holds 8 KiB and a stopped emulator reads
  nothing, so a server could hang writing to it. `app_launch.QueuedConsole` queues what the
  emulator cannot take yet.
- Finding the app's pid no longer fails because another process has an undecodable command line.

## 0.95.0

`promote`:

- A review lists apart, in `unwritable` with its reason, each entry it cannot write, instead of
  refusing the whole review at the first. An approval of one is still refused.
- `close` no longer names an entry the store already holds as it is.
- A stored relative path that resolves to the same place counts as unchanged and keeps its
  spelling; a stored absolute path is rewritten as a placeholder.
- `after_close` takes `starting` as a callable, so a working directory that is gone cannot cost
  `close` its reply.

The module is split: `scry_core.promote_paths` and `scry_core.promote_diff`. `recording.EXPORTS`
and `recording.EXPORT_REPLY`, which nothing read, are gone.

## 0.94.1

### Fixed

- A variable holding a filesystem root (`/`, `C:`) no longer covers every path in `promote`: a
  path of the machine could reach a tracked file as `${env:OLDPWD}...`.

## 0.94.0

`promote`:

- A draft holding only a map or a script looks for the store from the file the session loaded, and a
  `perform` document's `start` block counts as a recipe. `~`-led and relative paths are handled the
  same way as everywhere else in the store.
- Free text in a `perform` step that begins with `~` is left alone: only a step's `path` and `dest`
  are read as paths.
- A `.scry` that is a link, a `~/..` path and two entries that differ only in case are refused by
  name.
- `only_the_run` and `starting` are shared by both servers; `PerformFields` and `perform`'s
  description halves are too.

A server's tests can run on a Windows host with the helpers in `scripts/windows/`: `bundle.sh`
and `push-tree.sh` carry the repositories, or a working tree under test, there, and `run-task.sh`
runs a step as a scheduled task and fetches its logs. Set `SCRY_WIN_SSH` and `SCRY_WIN_ROOT` to
the host and its run root.

## 0.93.0

### Changed

- `promote`'s review names under `unchanged` the entries a promotion would write unchanged,
  and offers only what differs. An update keeps the keys a run owns (`logfile`) as the store
  has them, so a recipe loaded and run as it is is neither offered nor stripped of one.

### Fixed

- A symlinked kind directory of the store is refused by name: its byte cap could not see
  through it.
- A path whose case differs from the store's or the home's is written against the placeholder
  where the host says it names the same directory; a drive path is read as Windows reads it.
- A `~user` path inside a `perform` step is refused by name, as a declared key's is.

## 0.92.2

### Fixed

- `promote`'s description names the kinds an entry may be of (`start`, `maps`, `perform`): a
  model asked to approve a map candidate could not choose the one spelling the store refuses.

## 0.92.1

### Fixed

- `promote.PromoteFields` is a `typing_extensions.TypedDict`, as the servers' own models are:
  a `typing` one gave every model that inherits it a metaclass conflict at import.

## 0.92.0

### Added

- `promote`: the session's draft and the promotion that writes it into a repository's `.scry/`.
  One candidate per (kind, name), complete only with what the reader of its kind accepts; a name
  the store already holds is an update shown as its diff; `dry_run` reviews and `entries` writes,
  creating the store only then, under the caps `project_store` declares. A declared path is
  written as `${root}`, `${home}`, `${state}` or `${env:NAME}`, and one that would leave them is
  refused.
- `promote.after_export`, `after_close`, `kept_line` and `promote_line`: the reply, the unkept
  list and the summary line both servers say, written once.
- `screen_map.Maps.session_application`: the entry this session loaded or saved, which names what
  it adds next; a `start` forgets it, so a map learned afterwards is named after the machine.

### Changed

- `scry_core.hook`'s probe step runs where a repository holds `mcp_probe/servers.py` and says it
  skipped where one holds none, so the steps after it run in this repository.
- `project_store.entry_name` is public and its refusal no longer calls every entry a profile.
- `project_store.absolute` is the public name of what the store reads paths with.

## 0.91.2

### Added

- `recording.check_perform_arguments`: `perform`'s two arguments judged without reading anything,
  so a server's pre-gate can refuse them before it asks for the document; `steps_to_replay` reads
  it after that judgement.

## 0.91.1

### Added

- `recording.steps_to_replay`: `perform`'s list, the caller's own or the steps of the document it
  names, refused beside each other, so both servers enforce one rule in one place.

## 0.91.0

### Added

- `recording.read_document`: the `perform` document a caller names by path, judged before a step
  runs (JSON, a version this module writes, a list of step objects), so a server replays the
  script a repository declares in `.scry/perform/`.

### Changed

- `game_demo.Binding` names the game's `map` and `map_load` asks the run for it: a game's map
  lives in its own repository (`.scry/maps/`), not in this package.
- `screen_map`'s file prose places a map in the application's store,
  `.scry/maps/<application>.screen-map.json`.

## 0.90.0

### Added

- `project_store`: the store a repository declares for its own program (`.scry/`): the root
  found by walking up from a starting directory, a `start` profile (`scry-start/1`) read against
  it with an unknown version or key refused by name, `${root}`, `${home}`, `${state}` and
  `${env:NAME}` resolved against the one base, the caps, and `precedence`, the caller's argument
  winning.
- `project_store.applied` and `Applied`: the profile found by name (or read where a path names
  it), filling only the names the call did not give, and the reply's `profile` block.
- `project_store.demanded`: the refusal of an argument neither the call nor a profile gave.
- `given`: the names a call was given, before the schema fills the defaults, held for the tool's
  body from the MCP boundary or the call boundary, so a profile never overrides a caller's own
  value whether the call came from a client or in process.
- A path key holding a table (`{"cpu": "maps/x.map"}`) resolves each entry against the base.

## 0.89.2

### Added

- `screen_map.Maps.check_known`: the refusal for a name no layer maps, so a wait can refuse it
  before it steps the machine.

## 0.89.1

### Added

- `app_launch`: an emulator launched as an `.app` bundle through `open`: the executable its
  `Info.plist` names, the command that connects the process log, the console's FIFO, the
  environment and the working directory, the pid found by a token the session alone carries, and
  a handle that reports the exit status it never reaped as `unavailable`.
- `binaries.Ladder` lands a rung naming a `.app` on the executable inside it and says so in
  `Resolved.bundle`; `guardian.spawn` watches a detached pid only when the handle says
  `pid_is_ours`.

### Fixed

- `window_capture.window_of` takes the largest layer-0 window the host has **on screen**, not
  merely the largest: an app bundle owns more than the machine's window (MAME as a `.app` has a
  500x500 blank one beside a 320x272 emulator), and the capture read the blank one.

## 0.89.0

### Added

- `live_ledger`: the bookkeeping both live matrices keep: the sections a run plans and the cells
  each promises, the calls it records, the tally and the transcript, the evidence a FAIL leaves,
  and the jobs it pools, with `Cell`, `Section`, `Blocked`, `chosen_sections`,
  `cannot_be_judged` and `Ledger`, whose `run(..., name=)` speaks the verdict of the run it ran.
- `live_focus`: the focus section both matrices run, judged into the ledger that ran them.

### Fixed

- `screen_map`: a map that declares only the `pointer` and no screen has a file form again. It
  loads and saves, and one naming neither a screen nor a pointer is still refused.

## 0.88.0

### Changed

- `conformance.Subject` has `takes_fullscreen`, whether the server's `start` has a `fullscreen`
  argument at all, and the contract skips its full-screen rules for one that has none: MAME's
  `start` dropped the argument because no supported host shows a full-screen window. A server
  built on the contract adds the attribute to its `subject`.

## 0.87.0

### Added

- `prose.picture`, `log_marks.tail`, `narrowing.last_words` and `window.fit_size`: the picture line of a view,
  the last characters of a log read from its end, the close reply's last words, and a fitted window size, each
  written once for both servers. `focus_watch.graphics` and `focus_watch.managed` are public, as `window_host`
  already used them.

### Fixed

- `window_words.dosbox_x`: a window as wide as the usable area is placed so its right edge stays on the display
  (it started at the margin and ran past it). On Windows the whole outer window, its borders, title bar and
  menu included, stays inside the usable area whatever the scale and `dpi aware` setting; at 300 % the title
  bar used to start above the display.
- `window.prove`: the refusal of a full-screen window that does not fill its display reports the last reading,
  not the first.
- `reply_differences`: a reply table with no block marker before it is an invalid page (exit 3), not a traceback.

### Removed

- `window_words.mame`'s `resolution` argument, which no caller passed.

## 0.86.0

### Added

- `screen_map.Maps.set_pointer`, `check_pointer`, `pointer_line` and the `MAP_POINTER` description: the program's own
  pointer declared by a call, kept by `save`, for a server's `screen_map_write` to offer as a `pointer` method.

## 0.85.0

### Added

- `scry_core.reply_differences`: the advance tools' reply fields of the two servers side by side, read off their
  generated reference pages into `docs/advance-differences.md`; a test holds the page to the run.

## 0.84.0

### Fixed

- `window_words.dosbox_x` on Windows: a DOSBox-X that reads real pixels (`dpi aware=true`, or `auto` below 200 %) gets a window margin that grows with the scale, so its title bar is on the display (at 300 % with `dpi aware=true` it was above it). `dpi aware=auto` is decided by the primary display's scale (`WindowRequest.system_scale`), as DOSBox-X reads it, not by the asked display's.

## 0.83.0

### Added

- `scry_core.window_size`: a stated window size (`WIDTHxHEIGHT`, in the host's unit) parsed, refused
  naming the display's usable size when it does not fit, fitted (`integer_fit`, `aspect_fit`) and judged
  against the host's window list (`judge`: the client area on Windows, the outer rectangle with a title
  bar's height on macOS, with the tolerance named). `window.request` takes `size`, `emulator` and
  `halted`; `Display` carries `usable` and `scale`, `Seen` the `client` area, `WindowRequest` the
  `size`, `scale`, `usable`, `height_free` and `fitted`. `window.answer` adds `size` to a session
  started with one, and `tool_replies.WindowSizeField` is its reply type. `window_cli` takes `--size`
  on `words`, `launch` and `proof` (exit 3 when the window is another size).
- The macOS host reads each display's visible frame and backing scale (`NSScreen`), the Windows host
  `rcWork`, the monitor's DPI and `GetClientRect`.

### Changed

- The platform rule on full screen is judged once, in `window.request`, for both emulators
  (`window_size.refuse_fullscreen`); `window_words.refuse_mame_fullscreen` is gone and
  `window_words.mame` only builds words. A shell run is never halted, so `window_cli words dosbox-x
  --fullscreen --display 1` prints its words on macOS. A stated size drops `-nomaximize` for MAME on
  Windows, where it would ignore `-resolution`, and reaches DOSBox-X as logical pixels.

### Fixed

- `WindowRequest.dpi_aware` and `window_words.dosbox_x`: the unit of a DOSBox-X size follows the conf's `dpi aware` (`true`: real pixels at any scale; `false`: logical pixels at any scale; unset: logical from 200 %), not the scale alone. A conf that states `dpi aware=true` at 200 % opened a window half the size asked.
- `window.settle_size`, used by `window_cli proof --size`: an emulator that shows its window and resizes it a moment later (DOSBox-X on Windows) was judged on its first sighting and refused as the wrong size. The proof reads again until the window has the size or the one `--seconds` bound passes.
- `window.request` refuses a watched DOSBox-X window on macOS when its display sits left of or above the main one: DOSBox-X ignores a negative `windowposition` and would open the window on the main display. Full screen is not refused (it sends no position); the message advises it only to a start that is not halted. Measured on macOS only.
- `window_cli proof` refused with the next step of a server's tools (`status`, `resume`, `close`),
  which a shell does not have; `prove` and `wait_visible` take `shell=True` and word the step for it.

## 0.82.0

### Added

- `python -m scry_core.window_cli` (`displays`, `words mame|dosbox-x`, `launch`, `proof PID`): the display
  index, the emulator's placement words and the window proof a watched `start` uses, for a session
  with only a shell, the same on macOS and Windows. `scry_core.window_words` is where a server's
  `start` and the shell read those words from.

### Changed

- `WindowsHost` is per-monitor DPI aware: an unaware process reads the scaled desktop (1280x720
  on a 4K panel at 300 %) while an emulator places its window in real pixels, so a second display's
  origin would have been false. The taskbar, no longer under the minimum side, is listed by `above`.
- `prove` takes the bound and the host to read; the default is still `WAIT_S` and the host the
  platform's.

## 0.81.0

### Added

- `window`: the window a watched `start` asks for (`request`: `display` as the OS's index with 0 the
  main display, `fullscreen`; both refused on an unwatched start rather than ignored, a display the
  host lacks refused naming how many it has), its state read from the host (`state_of`, the
  `window` reply block), `wait_visible`, and `bring_front`, read back. `judge_background` and
  `launch_environment`, which both servers each wrote, are here once.
- `WindowRequest.origin`: the asked display's top-left, read from the host's displays, for an
  emulator that places a window by position and not by index. `request` takes the displays in
  place of their count.
- `window_host`: macOS and Windows hosts for it, the Windows one run on a real desktop
  (`tests/test_window_host_windows.py`, `-m window`).
  - `WindowsHost` lists only windows that are shown or minimised: an application's hidden helper
    windows (an IME or toolkit root, larger than the real one) would make `main_window` pick a
    window nobody sees. `activate` gets the foreground from a process the task scheduler started,
    by joining the foreground thread's input queue unless that thread is hung.
  - `MacHost.above` leaves out a window on a Space known to differ from the window's own: the
    window server keeps a full-screen application's window listed on screen, and above, while the
    display shows another Space. A window on several Spaces needs no Space switch when one of them
    is shown, and an ID that names no Space of the desk (0, reported for a window on every
    desktop) says nothing of where a window is. `MacHost.spaces_of` reads them.
- `bring_front` takes `launched_behind`, which has no default so a server that forgets to say
  whether it launched behind fails at the call. When the window does not come forward it names
  `background=true` as what may keep it behind and says to start again with `background=false`; a
  session started `background=true` does come forward when the window can be shown. It activates the
  largest window of the pid, the one `state_of` reads, and not the first it lists: MAME lists a
  small auxiliary window before its own.
- `observe(pid, host)`: the window a pid owns now, wherever it is, with no display to compare; a
  pid with none is `window_not_visible`. The `window` tools answer from it.
- `window.requested`, `prove`, `answer` and `summary`, `window.WAIT_S`, and
  `tool_replies.WindowRefusedFields`: the body of a server's `start` window half and of its
  `window` tool, which both servers had written once each. `prove` waits, within the one `WAIT_S`,
  for a full-screen window to fill the asked display after its first sighting; a window that fills
  another display is still `window_not_visible`.
- The `window_not_visible` code: the window never appeared, appeared on another display, or did not
  come forward.
- `window_tier` and `window_stand_ins`: the `window` pytest marker, its fixture and `on_the_desk`,
  served to every suite with this package installed; the tier is out of the default run and runs
  with `-m window` (README, *On-demand tiers*). `window_stand_ins` also holds the desk tier's shared
  steps (`under_a_cover`, `comes_forward`).
- `conformance.SessionContract`: the rules a server runs against its own `start`, `window`,
  `status` and `close` (the window ones, and what `close` and `status` answer with and without a
  session) in one test file, and `window_stand_ins.hosts`, the window doubles its unit tests use.
- `docs/new-emulator.md` and `docs/katas.md`: what a server for another emulator takes from this
  package, and which demos exist and where.

### Changed

- `game_demo.expect` is `demo.expect`, beside `StepFailed`, for every demo's step checks.

### Removed

- `host_args` and `SCRY_EMULATOR_ARGS`: the window is the caller's, said in `start`, so a host no
  longer injects placement flags.

## 0.80.0

### Added

- `reply_schema.RunEnvelope`, `media_replies.CapturesFields` and `PerformExportFields`,
  `tool_replies.MapWriteFields`, `LogWaitFields` and `CommentWriteFields`: the reply fields both
  servers repeat, declared once.
- `regpoint.hit`: the `regpoint_hit` object of a registerpoint stop, with the note that the
  registerpoint stays armed said once. A server adds its own fields.
- `screen_map.run_to_screen`: the whole `run_to(screen=)` flow, anchored or a frame at a time,
  written once. `screen_map.no_control` is the one refusal for a missing `control`.
- `process_tree.end_tree` and `pid_alive`: one recipe to end a process tree (a group on POSIX, the
  tree by pid on Windows) and one to ask whether a pid lives.
- `demo.Step.highlight`: a demo that marks steps puts only those in its README block and commits
  the whole normalised run as `TRANSCRIPT.md`; `demo.stale` compares both.
- `live_pool.cannot_be_judged`: the one predicate for a verdict a run cannot judge.
- `SequenceFields` declares `still_running` and `stopped` once; `reply_schema.parenthesised_fields`
  makes the Reply check read a field named inside a parenthesis.

### Changed

- `screen_map.view` is now `judged_view`.
- `presence.Look` drops the DOSBox-X-only pointer fields; the arrow is that server's own.
- `docs.filled` fills a value that names another placeholder, and refuses a cycle by name.
- `reference` normalises more clock forms in examples, and `--skip` matches the text a person reads.
- `replay.build` refuses an `entry` script that is not a file under the root, naming it.
- `live_harness` repeats each BLOCKED row once after the failures.

### Fixed

- `bench.run_group` ended only the leader on Windows and waited without a bound; it ends the tree and
  waits a bounded time.
- A pty drained to its end raised `EIO` on Linux; the drain now ends there.
