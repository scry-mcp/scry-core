# A new emulator server

What a server for another emulator takes from this package and what it writes itself. The window
half is exercised by `tests/null_server.py`, a server with no emulator behind it that passes
`scry_core.conformance` against window doubles (the real hosts are the desk tier's), and the
store's by `tests/null_promoter.py`, which passes its `PromoteContract`; the rest is how the two
existing servers are wired.

## The window, from core

Every watched `start` and the `window` tool call these of `scry_core.window`:

- `requested(shared, display, fullscreen, size, emulator=, halted=)` in `start`, before anything launches: the validated
  `WindowRequest`, or None for a run nobody watches. Keep it with the session's own state;
  `window` needs it.
- `prove(pid, asked)` once the emulator is up: the window as the host lists it, as the `window`
  block of the `start` reply. A refusal leaves the session live, so `close` still acts.
- `answer(pid, asked, front=, launched_behind=)` is the body of the `window` tool once the server
  has judged its session (no session, an emulator that has died). `answer` itself refuses a
  session started without a window (`no_channel`) and a window that is not listed or not visible,
  so the session's own refusals come first.
- `judge_background(background, watched)` and `launch_environment(base, background)` decide and
  mark a launch behind. `launched_behind` of `answer` is that decision, with no default, so a
  server that forgets it fails at the call.

The emulator's own argv for the display, the size and full screen is `scry_core.window_words`
(`dosbox_x`, `mame`); the refusal of a full screen it cannot show on macOS or Windows is
`scry_core.window_size.refuse_fullscreen`, judged once inside `window.request(..., emulator=)`.
Add the new emulator's words and rule there, so `python -m scry_core.window_cli` places and
proves its window from a shell too. What stays the server's: refusing caller flags that retune a
window the arguments own, and the reasons its full screen cannot show that no platform test knows
(a conf's `output`). A server may fit a size to `WindowRequest.usable` with `window_size`'s
`integer_fit` or `aspect_fit` and mark it `fitted=True`, which the `window` tool then does not
judge; a size the caller stated is judged against what the host lists.

`window.WAIT_S` is the one bound on waiting for the host's window list; a test lowers it with
`monkeypatch.setattr(window, "WAIT_S", 0.0)`.

## Replies

- `tool_replies.WindowRefusedFields` composes with the server's envelope into its `WindowRefused`
  model; `start` and `window` replies inherit it.
- `window.summary` is the tool's transcript line.

## Tests

1. Subclass `conformance.SessionContract` in one file and provide a `subject` fixture: an object
   with `start(**arguments)`, `window(front=)`, `status()`, `close()`, `asked()` and `has_session()` over the
   server's own booted fake. `asked()` returns the pid and `WindowRequest` of the live session,
   which is what `window_stand_ins.hosts.Obeying` reads to open a window where it was asked. The
   subject also says `shows_fullscreen` and `takes_fullscreen` (whether `start` has the argument at
   all); the full-screen rules are skipped for a server whose `start` has none.
2. Subclass `conformance.PromoteContract` the same way, over the server's own promotion with the
   launch faked and an empty draft: a `subject` with `start(project, name)`, `promote(**arguments)`
   and `close()`. Its rules: without `root` an entry is written only into its own project's
   store, an entry whose project has none is named with the `root` it takes, and the server's own
   directory never lends its store.
3. Keep in the server's own tests only what the contracts cannot know: the owned flags and the
   full screen the emulator cannot show for its own reasons; the words are tested in core.
4. Put `not window` in `addopts`, as README, *On-demand tiers*, says. The desk tier uses `under_a_cover` and
   `comes_forward` of `window_stand_ins`, so a server's tier test is its `start` and one line per
   case, run for a foreground and for a `background=true` session. Command and conditions: README, *On-demand tiers*.

## The rest of the wiring

Read from the two servers; none of it is proved by the null server.

- `server.py`: a `roster.Roster`, an `envelope.Envelope`, a `recording.Recorder` and a
  `boundary.Boundary`, tools registered through `Boundary.tool`, and the closing calls
  (`strict_arguments`, `reply_schema.declare`, `reference.Registry`, `signalled_end.SignalledEnd`).
- `pyproject.toml`: the `reply_shapes_anchors` README's `reply_shapes` paragraph gives; the
  `reply_shapes` and `window_tier` plugins load by installing this package.
- The store: `start` runs its launch inside `Drafts.starting(profile=, anchor=, live=)`, naming
  the profile it read, where its program lives (none when the arguments do not say) and how to
  read its live session, and answers with `promote.after_start`, which keeps its recipe
  (`keep_start`: named by the profile read, else by the guest; nothing kept when a profile is
  only run again) and adds `kept` and the profile block; `screen_map_write` is
  `promote.after_map`; `perform_export`,
  `close` and `promote` are `promote.after_export`, `promote.after_close` and `promote.promote`.
  Which store an entry may be written to is decided there and never by the server.
- Reference pages: `python -m scry_core.reference <package>.server:REFERENCE --write`.
- Probe: `mcp_probe/servers.py`, `mcp_probe/tasks/`, run with
  `python -m scry_core.probe <name> --servers ... --tasks ... --check`.
- Live matrix: sections chosen by an environment variable of the server's own. The ones that say
  nothing of the emulator are the window checks, against the host's window list with an unwatched
  start as the control, and the focus section, which moves the owner's Space and is opt-in only.

## Katas

[katas.md](katas.md) lists every demo and screen map and which servers run each.
