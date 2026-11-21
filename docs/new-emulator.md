# A new emulator server

What a server for another emulator takes from this package, and what it writes itself.

Two test servers show the parts this package checks:

- `tests/null_server.py` has no emulator behind it. It passes `scry_core.conformance` against
  stand-in windows; the opt-in tests that open windows check the real window systems.
- `tests/null_promoter.py` passes `PromoteContract`, the rules for saving into a repository's
  `.scry/` folder.
- `tests/null_server.py` also holds `NullKnowledge`, a base of six fixture entries that passes
  `KnowledgeContract`, the rules for a server's dictionaries (see *The knowledge base*).

The rest is how the two existing servers are wired.

## The window

A `start` with `shared=true` opens a window for a person to watch. Every such `start`, and the
`window` tool, call these functions of `scry_core.window`.

| Function | When the server calls it |
|---|---|
| `requested(shared, display, fullscreen, size, emulator=, halted=)` | in `start`, before anything launches |
| `prove(pid, asked)` | once the emulator is up |
| `answer(pid, asked, front=, launched_behind=)` | as the body of the `window` tool |
| `judge_background(background, watched)` | to decide whether the emulator launches behind other windows |
| `launch_environment(base, background)` | to set that decision in the emulator's environment |

- `requested` returns the checked `WindowRequest`, or None for a `start` without `shared=true`.
  Keep it with the session's own state, because `window` needs it.
- `prove` returns the window as the host lists it. Its `block()` is the `window` block of the
  `start` reply. A refusal leaves the session live, so `close` still acts.
- `answer` comes after the server's own checks of its session: no session, an emulator that
  has died. So the session's own refusals come first.
- `answer` itself refuses a session started without a window, with the code `no_channel`. It
  also refuses a window that is not listed or not visible.
- `launched_behind` of `answer` takes the decision of `judge_background`. It has no default, so
  a server that forgets it fails at the call.

`window.WAIT_S` is the one limit on waiting for the host's window list. A test lowers it with
`monkeypatch.setattr(window, "WAIT_S", 0.0)`.

### The emulator's command line

- `scry_core.window_words` (`dosbox_x`, `mame`) holds each emulator's own command-line words
  for the display, the size and full screen.
- `scry_core.window_size.refuse_fullscreen` refuses a full screen the emulator cannot show on
  macOS or Windows. It is checked once, inside `window.request(..., emulator=)`.

Add the new emulator's words and its rule there. Then `python -m scry_core.window_cli` opens
and checks its window from a shell too.

Two things stay in the server:

- Refusing a flag of the caller's that would change a window the arguments already set.
- The reasons its full screen cannot show that no platform test knows, such as the `output`
  setting of a DOSBox-X configuration file (`sdl output=surface`).

### A size the server chooses

A server may fit a size to `WindowRequest.usable` with `integer_fit` or `aspect_fit` of
`window_size`, and mark it `fitted=True`. The `window` tool then does not check that size. A
size the caller stated is checked against what the host lists.

## Replies

- `tool_replies.WindowRefusedFields` holds what a `window_not_visible` refusal says about the
  window. Combine it with the server's own class for the fields every reply carries, into a
  `WindowRefused` model. The `start` and `window` replies inherit it.
- `window.summary` is the `window` tool's line in a transcript.

## Tests

The shared test classes are in `scry_core.conformance`. A server subclasses each in one file
and provides a `subject` fixture.

### `SessionContract`

The subject is an object over the server's own stand-in for a started emulator. It has
`start(**arguments)`, `window(front=)`, `status()`, `close()`, `asked()` and `has_session()`.

- `asked()` returns the pid and the `WindowRequest` of the live session.
  `window_stand_ins.hosts.Obeying` reads it to open a window where it was asked.
- `shows_fullscreen` says whether the emulator can show a full screen on this host.
- `takes_fullscreen` says whether `start` has the argument at all. The full-screen rules are
  skipped for a server whose `start` has none.

### `PromoteContract`

`promote` is the tool that saves what a session learned into a repository's `.scry/`. The
subject runs the server's own code for it, with a launch that starts no emulator and nothing
waiting to be saved. It has `start(project, name)`, `promote(**arguments)` and `close()`.

Its rules:

- Without `root`, an entry is written only into the `.scry/` of its own project.
- An entry whose project has no `.scry/` is named, with the `root` it takes.
- The server's own directory never lends its `.scry/`.

### What stays in the server's own tests

Keep only what the shared classes cannot know: the flags the server refuses, and the full
screen its emulator cannot show for its own reasons. The command-line words are tested in this
package.

### The tests that open windows

Put `not window` in the server's `addopts`, as the README's
[Opt-in tests](../README.md#opt-in-tests) says. Those tests use `under_a_cover` and
`comes_forward` of `window_stand_ins`.

So a server's test is its `start` and one line per case. It runs for a foreground session and
for a `background=true` one. The command and what it needs are in
[Tests that open windows](live-tests.md#tests-that-open-windows).

## The rest of the wiring

Read this part from the two servers. The test servers above check none of it.

- `mcp.py` builds a `roster.Roster`, an `envelope.Envelope`, a `recording.Recorder` and a
  `boundary.Boundary`. [The modules of scry-core](modules.md) says what each one is.
- `server.py` registers each tool through `Boundary.tool`. It ends with `strict_arguments`,
  `reply_schema.declare`, `reference.Registry` and `signalled_end.SignalledEnd`.
- `pyproject.toml` sets `reply_shapes_anchors`, as the README's paragraph on `reply_shapes`
  gives it. The `reply_shapes` and `window_tier` plugins load when this package is installed.
- The reference pages are written by
  `python -m scry_core.reference <package>.server:REFERENCE --write`.

### Saving into `.scry/`

`start` runs its launch inside `Drafts.starting(profile=, anchor=, live=)`. It passes three
things: the start profile it read, where its program lives, and how to read its live session.
`anchor` is empty when the arguments do not say where the program lives.

A start profile is a saved set of `start` arguments. `start` answers with
`promote.after_start`, which saves the call's arguments as one, waiting for `promote`
(`keep_start`). It also adds `kept` and the `profile` block to the reply.

- The saved profile takes the name of the profile `start` read, or else the name of the
  program inside the emulator.
- A profile that is only run again saves nothing.

| Tool | Answers with |
|---|---|
| `screen_map_write` | `promote.after_map` |
| `perform_export` | `promote.after_export` |
| `close` | `promote.after_close` |
| `promote` | `promote.promote` |

`scry_core.promote` decides which `.scry/` an entry may be written to. The server never does.

### The description test

The description test gives a model only what the client delivers and checks the calls it
makes. A server keeps `mcp_probe/servers.py` and `mcp_probe/tasks/` for it.

```sh
python -m scry_core.probe <name> --servers ... --tasks ... --check
```

### The live test script

The live test script runs the tests against a real emulator. An environment variable of the
server's own chooses its sections. Two kinds of section say nothing about the emulator:

- The window checks compare with the host's window list. A `start` that opens no window is
  the comparison.
- The focus section moves the Space of whoever is using the computer, so it is opt-in only.

## Checked demos

[The list of checked demos](katas.md) says which servers run each demo and which screen map
each uses.

## The knowledge base

What a number is called on the machine (a port, an interrupt, a vector, a register), with the
public source each fact was checked against. A server ships dictionaries and one declaration;
`scry_core.knowledge` loads, searches and checks them, and `scry_core.knowledge_tool` is the
`knowledge_find` tool both servers register.

- **Dictionaries**: JSON files `scry-knowledge/1` in `<package>/knowledge/`, one dictionary per
  file: a header (`kind`, `scope`, what it `covers`, the list it must cover as
  `complete_against`, `left_out` with a reason per key, `reached` for registers, `both` when the
  documentation and the emulator both exist) and its `entries`. An entry holds its `key` in the
  one spelling of its kind (`scry_core.knowledge.keys`), a `name` of at most 24 ASCII
  characters, a `description`, a `behaviour` that summarises the source without losing
  precision, and one or two `sources`, each a `ref` of a known scheme and the source's own line
  in `cites`. An entry with no source is not written.
- **Checked entries**: a second session reads an entry against its source and adds `checked`
  (who checked, who wrote, the line compared per `ref`, and the digest of the entry's text, from
  `scry_core.knowledge.digest`). From then on the text is never reworded: the contract fails when
  the digest no longer matches, and a correction is a new write and a new check.
- **The declaration**: `knowledge/support.py` holds one `Support` listing the `Scope`s (a system
  or a cpu, with the kinds it owes; `support="named"` for a cpu the base names and the server
  does not claim to run), the `Device`s and the `Chip`s. Adding one there is the only step; the
  suite is red until its dictionaries exist.
- **The source index**: a tool of the server captures, from the real sources, the rows its
  dictionaries cite (the line, the key the locator carries, the read and write marks) and the
  lists they must cover (`scry-knowledge-sources/1`, `scry_core.knowledge.sources`), and the
  result is committed. The tests need no network.
- **The tests**: a subclass of `conformance.KnowledgeContract` with a `subject` that gives the
  declaration, the loaded `Base` (`fts5=False` forces the search index of our own), the source
  index and the scopes the code depends on. `tests/null_server.py`'s `NullKnowledge` is the
  model.
- **The tool**: `knowledge_tool.register(wrap, answer, base, live)`. `live` says what the running
  machine can answer by itself (MAME's inputs and device tags); a server with none passes
  nothing. `knowledge_tool.judge` goes in the pre-gate table.
