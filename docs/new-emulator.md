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
  precision, and one to three `sources`, each a `ref` of a known scheme and the source's own line
  in `cites`: at most one `documentation`, and two `emulator` sources only when one is
  `dosbox-x:` and the other `mame:` (a chip both emulators model); `differs` says how the
  sources disagree, and is required when the index's read and write marks of two sources
  differ. An entry with no source is not written. A placed device may map its ports to
  handlers in `handlers` (`"0x388:write": "data_w"`): each port must lie in its `ports` and each
  value must be a handler of a chip it `contains` (or of the chip that has its own key), which
  the relations case checks. A `register` or `command` key may be a
  range (`0x20..0x35`, a bank as one entry) and a number inside it finds the entry; two
  registers or two commands of one dictionary may not overlap unless their `access` tells them
  apart. `access` (`read` or `write`) is for a port, a register or a command that differs by
  direction, and it is part of the id (`ym:register:0x0F:read`). A `call` key is `INT/AH` or
  `INT/AH/AL`, and may end in one selector, a register and its value (`0x10/0x12/BL=0x36`, or a
  range of values `BL=0x31..0x36`), for a call whose variants a register other than AH or AL
  picks; the registers are `BL BH CL CH DL DH BX CX DX SI DI`, never `AH`, `AL` or `AX`, which
  the key's own parts already say (`0x21/0x44/0x00`, not `0x21/0x44/AL=0x00`). A variant sorts and
  ranges with its parent, which may be an entry too: `knowledge_find` for the parent lists the
  variants, for a key with the selector answers the variant. The variants of one call select on
  one register and no value picks two, or the second is a load fault. A list section keyed by
  the parent (`0x10/0x12`) is the source of every variant that cites it, so a variant needs no
  key of its own in the source index.
- **Checked entries**: a second session reads an entry against its source and adds `checked`
  with `by`, `writer` and `against` (per source `ref`, the line it compared: the entry's own
  `cites`, or a part of the line the source index holds for it). Then one command seals it:

  ```sh
  python -m scry_core.knowledge.seal <dictionary.json> <entry id>... --lock <lock.json>
  ```

  It stamps the seal into `checked.digest` (a hash of the entry's text, of the check itself and, for a register, of the ports its
  dictionary header says it is reached by)
  and writes the entry's id, its seal, who checked it and the lines compared to the
  repository's lock (`scry-knowledge-lock/2`). The dictionary file must already
  be written the way the command writes it (two-space JSON, a final newline); a file that is
  not is refused untouched. From then on the entry is never touched: the contract fails when a
  checked entry no longer gives its seal, when a locked entry is gone or has lost its `checked`
  record, and when a checked entry is not in the lock. The lock sits beside the package's
  `knowledge/` directory, never inside it: every `.json` there is read as a dictionary. A correction is a new write and a new
  check by another session, sealed with the same command, which replaces the lock's row and
  refuses a re-check whose `by` and `against` are the ones already locked while the entry
  changed: the check has to be by another session or against other lines. An
  entry retired for good has its line deleted from the lock by hand, in the commit that removes
  it.
- **Reopening a sealed entry**: an entry a check or a reading finds wrong or incomplete is
  reopened with its own command, never by editing the lock or the dictionary by hand:

  ```sh
  python -m scry_core.knowledge.reopen <dictionary.json> <entry id>... --lock <lock.json> \
      --by <who reopens> --why <what is wrong>
  ```

  It removes the entry's `checked` record and its lock row and adds to the lock's `reopened`
  list the id, the digest the entry had, who reopened it and why, and who had checked it against
  which lines, so the lock tells the history and `seal` still refuses a re-check by that checker
  against those lines. It refuses
  an entry that is not locked, and writes both files or neither. The entry is then rewritten,
  checked by another session and sealed again with `seal`. The contract fails when a
  reopening is recorded for an entry that is sealed at the digest it had, and when a checked
  entry has no lock row.
- **The declaration**: `knowledge/support.py` holds one `Support` listing the `Scope`s (a system
  or a cpu, with the kinds it owes; `support="named"` for a cpu the base names and the server
  does not claim to run), the `Device`s and the `Chip`s. Adding one there is the only step; the
  suite is red until its dictionaries exist.
- **The shared chips**: a chip both emulators model is written once, in this package.
  `scry_core.knowledge.shared` holds `CHIPS` (their declarations, so
  `Support(chips=shared.CHIPS)` is complete by construction), `CPUS` (cpus named for any
  system built on them, which a server that runs one adds to its `scopes`) and `PINS` (the
  commit or tag each `dosbox-x:` and `mame:` ref is read at). `knowledge/chips/` is loaded by
  every server and `knowledge/cpus/` only by a server that declares those cpus, as
  `Base.load(<own package>, files("scry_core.knowledge") / "chips")`. A register of a shared
  chip has the id `<chip>:register:<key>` on both servers, and its `reached` names handlers,
  never a port: the board that places the chip says which port is which handler, in the
  `handlers` of its own device entry. The rows these dictionaries cite are in
  `knowledge_index/shared.json`, which a server's subject merges with its own index;
  `tools/knowledge_sources.py` writes it from the real sources, and `--check` compares it.
- **The source index**: a tool of the server captures, from the real sources, the rows its
  dictionaries cite (the line, the key the locator carries, the read and write marks) and the
  lists they must cover (`scry-knowledge-sources/1`, `scry_core.knowledge.sources`), and the
  result is committed. The tests need no network. A row holds the `line` or, where the index
  must not copy a third party's text, the `digest` of it (`sources.digest`: the SHA-256 of the
  line's UTF-8 bytes, in lower-case hex), never both; an entry's `cites` is then held to the
  digest, and a check's `against` line to the whole `cites`, since a digest cannot say what part
  of a line it came from.
- **The tests**: a subclass of `conformance.KnowledgeContract` with a `subject` that gives the
  declaration, the loaded `Base` (`fts5=False` forces the search index of our own), the source
  index, the lock of the checked entries (`scry_core.knowledge.read_lock`) and the scopes the
  code depends on. `tests/null_server.py`'s `NullKnowledge` is the
  model.
- **The tool**: `knowledge_tool.register(wrap, answer, base, live)`. `live` says what the running
  machine can answer by itself (MAME's inputs and device tags, which a model may give as
  `kind=device key=:tag` or `device=:tag`); a server with none passes nothing. The registered
  description lists the scopes of `base`, so a server types none, and a scope that is a near
  miss of one (`6809` for `m6809`) is read as it, with a `note` saying so. `knowledge_tool.judge`
  goes in the pre-gate table.

## Naming what the replies show

A reply and a caption call a number by its name where the server knows one (`DAC write address
(0x3C8)`), so a reader does not look it up. The server writes one namer and a table of its replies'
number fields; `scry_core.naming` does the rest.

- **The namer** answers `arguments(tool, given)`, a `Named` per argument whose value it can name,
  and `reply(tool, reply)`, a `Named` per number field of a reply, by the path of its `Field`
  (`naming.walk` reads `a.b` and `a[].b`). It reads only what the server already holds in memory
  and never asks the emulator: it runs under the call's lock, before the call is heard. The
  server's test builds it over a session that fails on any call to the emulator and runs it over
  every example, and expects zero calls.
- **The wiring**: `naming.Guarded(namer)` goes to `Boundary(namer=..., names_on=...)`. A failure
  of the namer gives no names and is counted: `Guarded.failed()` is what `status` says as
  `names_failed`, and never a call's own reply. `Boundary` puts the names on `Call.named`, which
  the caption uses, and, while `names_on()` holds, adds `names` and `names_cut` to every reply and
  names the numbers its summary prints, at the first whole occurrence: a short number such as `1`
  is ambiguous in a line, so a tool gives its field a `shown` spelling (`irq {}`) that is not. The
  block also names the call's own arguments, under `given.<argument>`; the demo runner builds its
  captions from those with the function the window's captions use.
- **The switch**: `start` takes `names: naming.Switch = True`, whose description is
  `naming.ARGUMENT`, and `naming.ASK` is the sentence for `asks.json`. Off, a reply has no
  `names`, no names in its summary and no note on a disassembled line; the window's captions
  keep theirs.
- **A call with variants**: `naming.named_call(base, scope, interrupt, registers)` names `INT
  interrupt` from the registers a stop holds (upper-case names, `AH`, `BX`; a word or its two
  bytes serve either way). It answers the variant whose selector's register is known and holds
  the variant's value, else the call itself, else None; a register the stop does not say never
  picks a variant, so a caption never names one it cannot know. A namer calls it where it names
  a call.
- **A disassembled line's note**: `notes.note(base, scope, operands, names_on=...)` returns what
  the base calls the operands the server parsed (a port, an interrupt, an address), and None when
  the session's `names` switch is off. It goes in a row's `note`, never in a person's `comment`. An operand a register holds is named only for the instruction at
  a stop, and `Note.live` says the line was named that way. An interrupt operand takes the
  stop's `registers` too: a call's variant is named (`video refresh (BL=0x36)`) only when the
  selector's register is among them, else the note names the call.
