# Changelog

What a server author notices. A client's view of each server is in that server's own changelog.

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

- `WindowRequest.origin`: the asked display's top-left, read from the host's displays, for an
  emulator that places a window by position and not by index. `request` takes the displays in
  place of their count.
- `WindowsHost` run on a real desktop for the first time (`tests/test_window_host_windows.py`,
  `-m window`).

### Fixed

- `WindowsHost` lists only windows that are shown or minimised: an application's hidden helper
  windows (an IME or toolkit root, larger than the real one) made `main_window` pick a window
  nobody sees. `activate` now gets the foreground from a process the task scheduler started, by
  joining the foreground thread's input queue unless that thread is hung.
- `prove` waits, within the one `WAIT_S`, for a full-screen window to fill the asked display
  after its first sighting; a window that fills another display is still `window_not_visible`.
- `MacHost.above` leaves out a window on a Space known to differ from the window's own: the window
  server keeps a full-screen application's window listed on screen, and above, while the display
  shows another Space, so a window brought back to its Space still read as covered (MAME's did).
  A window on several Spaces needs no Space switch when one of them is shown, and an ID that names
  no Space of the desk (0, reported for a window on every desktop) says nothing of where a window
  is. `MacHost.space_of` is gone for `spaces_of`.
- `bring_front` takes `launched_behind` and, when the window does not come forward, names
  `background=true` as what may keep it behind and says to start again with `background=false`.
  A session started `background=true` does come forward when the window can be shown.
- `bring_front` activates the largest window of the pid, the one `state_of` reads, and not the
  first it lists: MAME lists a small auxiliary window before its own.

### Changed

- `bring_front`'s `launched_behind` has no default: a server that forgets to say whether it launched
  behind fails at the call instead of losing the explanation.
- `game_demo.expect` is `demo.expect`, beside `StepFailed`, for every demo's step checks.

### Added

- `window.requested`, `prove`, `answer` and `summary`, `window.WAIT_S`, and
  `tool_replies.WindowRefusedFields`: the body of a server's `start` window half and of its
  `window` tool, which both servers had written once each.
- `conformance.SessionContract`: the rules a server runs against its own `start`, `window`,
  `status` and `close` (the window ones, and what `close` and `status` answer with and without a
  session) in one test file, and `window_stand_ins.hosts`, the window doubles its unit tests use.
  `window_stand_ins` also holds the desk tier's shared steps (`under_a_cover`, `comes_forward`).
- `docs/new-emulator.md` and `docs/katas.md`: what a server for another emulator takes from this
  package, and which demos exist and where.
- `observe(pid, host)`: the window a pid owns now, wherever it is, with no display to compare; a
  pid with none is `window_not_visible`. The `window` tools answer from it.
- `window`: the window a watched `start` asks for (`request`: `display` as the OS's index with 0 the
  main display, `fullscreen`; both refused on an unwatched start rather than ignored, a display the
  host lacks refused naming how many it has), its state read from the host (`state_of`, the
  `window` reply block), `wait_visible`, and `bring_front`, read back. `judge_background` and
  `launch_environment`, which both servers each wrote, are here once.
- `window_host`: macOS and Windows hosts for it. Windows is written against user32 and not yet run.
- `window_tier` and `window_stand_ins`: the `window` pytest marker, its fixture and `on_the_desk`,
  served to every suite with this package installed; the tier is out of the default run and runs
  with `-m window` (README, *On-demand tiers*).
- The `window_not_visible` code: the window never appeared, appeared on another display, or did not
  come forward.

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
