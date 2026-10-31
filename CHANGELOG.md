# Changelog

What a server author notices. A client's view of each server is in that server's own changelog.

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
