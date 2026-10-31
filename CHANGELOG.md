# Changelog

What a server author notices. A client's view of each server is in that server's own changelog.

## Unreleased

### Added

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
