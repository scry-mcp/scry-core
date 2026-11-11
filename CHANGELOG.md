# Changelog

What a server author notices. A client's view of each server is in that server's own changelog.

## Unreleased

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
  caller's Claude Code configuration.
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

- `live_ledger`: the bookkeeping both live matrices keep — the sections a run plans and the cells
  each promises, the calls it records, the tally and the transcript, the evidence a FAIL leaves,
  and the jobs it pools — with `Cell`, `Section`, `Blocked`, `chosen_sections`,
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
