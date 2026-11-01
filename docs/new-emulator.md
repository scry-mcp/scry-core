# A new emulator server

What a server for another emulator takes from this package and what it writes itself. The window
half is exercised by `tests/null_server.py`, a server with no emulator behind it that passes
`scry_core.conformance` against window doubles (the real hosts are the desk tier's); the rest is
how the two existing servers are wired.

## The window, from core

Every watched `start` and the `window` tool call these of `scry_core.window`:

- `requested(shared, display, fullscreen)` in `start`, before anything launches: the validated
  `WindowRequest`, or None for a run nobody watches. Keep it with the session's own state;
  `window` needs it.
- `prove(pid, asked)` once the emulator is up: the window as the host lists it, as the `window`
  block of the `start` reply. A refusal leaves the session live, so `close` still acts.
- `answer(pid, asked, front=, launched_behind=)` is the body of the `window` tool once the server
  has judged its session (no session, an emulator that has died). `answer` itself refuses only a
  session started without a window (`no_channel`), so the other refusals come first.
- `judge_background(background, shared)` and `launch_environment(base, background)` decide and
  mark a launch behind. `launched_behind` of `answer` is that decision, with no default, so a
  server that forgets it fails at the call.

What stays the server's: the emulator's own argv for the display and for full screen, the
refusal of a full screen its emulator cannot show, and refusing caller flags that retune a window
the arguments own. The emulator centres its own window; a server never computes geometry.

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
   which is what `window_stand_ins.hosts.Obeying` reads to open a window where it was asked.
2. Keep in the server's own tests only what the contract cannot know: the argv, the owned flags,
   the full screen the emulator cannot show.
3. Put `not window` in `addopts` (`-m 'not live and not window'`); the marker, the fixture and the
   stand-in windows arrive with this package. The desk tier uses `under_a_cover` and
   `comes_forward` of `window_stand_ins`, so a server's tier test is its `start` and one line per
   case, run for a foreground and for a `background=true` session. Command and conditions: README, *On-demand tiers*.

## The rest of the wiring

Read from the two servers; none of it is proved by the null server.

- `server.py`: a `roster.Roster`, an `envelope.Envelope`, a `recording.Recorder` and a
  `boundary.Boundary`, tools registered through `Boundary.tool`, and the closing calls
  (`strict_arguments`, `reply_schema.declare`, `reference.Registry`, `signalled_end.SignalledEnd`).
- `pyproject.toml`: `reply_shapes_anchors = ["scry_core.reply_contract", "scry_core.boundary"]`.
  The `reply_shapes` and `window_tier` plugins load by installing this package.
- Reference pages: `python -m scry_core.reference <package>.server:REFERENCE --write`.
- Probe: `mcp_probe/servers.py`, `mcp_probe/tasks/`, run with
  `python -m scry_core.probe <name> --servers ... --tasks ... --check`.
- Live matrix: sections chosen by an environment variable of the server's own. The ones that say
  nothing of the emulator are the window checks, against the host's window list with an unwatched
  start as the control, and the focus section, which moves the owner's Space and is opt-in only.

## Katas

[katas.md](katas.md) lists every demo and screen map and which servers run each.
