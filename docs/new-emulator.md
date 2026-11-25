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
  file. A header names what it covers, and its `entries` hold the facts:

| header field | what it says |
|---|---|
| `kind` | what the dictionary holds |
| `scope` | the system or cpu it is about |
| `covers` | what it answers |
| `complete_against` | the list it must cover |
| `left_out` | a reason per key it leaves out |
| `reached` | how a register is reached |
| `both` | set when the documentation and the emulator both exist |

| entry field | what it says |
|---|---|
| `key` | the key, in the one spelling of its kind (`scry_core.knowledge.keys`) |
| `name` | at most 24 ASCII characters |
| `description` | what it is |
| `behaviour` | the source summarised without losing precision |
| `sources` | one to three: a `ref` of a known scheme and the source's own line in `cites` |
| `differs` | how the sources disagree; required when their read and write marks differ |
| `handlers` | a placed device's ports to handlers (`"0x388:write": "data_w"`) |

- **Sources**: at most one `documentation` source, and two `emulator` sources only when one is
  `dosbox-x:` and the other `mame:` (a chip both emulators model). An entry with no source is
  not written.
- **Handlers**: a handler must be one of a chip the device `contains`, and each port must lie in
  its `ports`; the relations case checks both.
- **Keys**: a `register` or `command` key may be a range (`0x20..0x35`, a bank as one entry),
  and a number inside it finds the entry. Two registers or two commands of one dictionary may
  not overlap unless their `access` tells them apart.
- **Direction**: `access` (`read` or `write`) is for a port, a register or a command that
  differs by direction, and it is part of the id (`ym:register:0x0F:read`).
- **Calls**: a `call` key is `INT/AH` or `INT/AH/AL`, and may end in one selector, a register and
  its value (`0x10/0x12/BL=0x36`, or a range `BL=0x31..0x36`). The registers are
  `BL BH CL CH DL DH BX CX DX SI DI`, never `AH`, `AL` or `AX`, which the key's own parts say
  (`0x21/0x44/0x00`).
- **Variants**: a variant sorts and ranges with its parent, which may be an entry too.
  `knowledge_find` for the parent lists the variants, and for a key with the selector answers the
  variant. The variants of one call select on one register, and no value picks two.
- **A variant's source**: a list section keyed by the parent (`0x10/0x12`) is the source of
  every variant that cites it, so a variant needs no key of its own in the source index.
- **Checked entries**: a second session reads an entry against its source and adds `checked`
  with `by`, `writer` and `against` (per source `ref`, the line it compared: the entry's `cites`,
  or a part of the line the source index holds). One command seals it:

  ```sh
  python -m scry_core.knowledge.seal <dictionary.json> <entry id>... --lock <lock.json>
  ```

  It stamps the seal into `checked.digest`: a hash of the entry's text, of the check itself and,
  for a register, of the ports its header says it is reached by. It also writes the id, the
  seal, who checked it and the lines compared to the repository's lock
  (`scry-knowledge-lock/2`).

  The dictionary must already be written the way the command writes it (two-space JSON, a final
  newline); a file that is not is refused untouched.
- **A sealed entry is never touched.** The contract fails when a checked entry no longer gives
  its seal, when a locked entry is gone or has lost its `checked` record, and when a checked
  entry is not in the lock. The lock sits beside the package's `knowledge/` directory, never
  inside it: every `.json` there is read as a dictionary.
- **A correction** is a new write and a new check by another session, sealed with the same
  command. That command replaces the lock's row and refuses a re-check whose `by` and `against`
  are the ones already locked while the entry changed. An entry retired for good has its line
  deleted from the lock by hand, in the commit that removes it.
- **Reopening a sealed entry**: an entry a check or a reading finds wrong or incomplete is
  reopened with its own command, never by editing the lock or the dictionary by hand:

  ```sh
  python -m scry_core.knowledge.reopen <dictionary.json> <entry id>... --lock <lock.json> \
      --by <who reopens> --why <what is wrong>
  ```

  It removes the entry's `checked` record and its lock row, and adds to the lock's `reopened`
  list the id, the digest the entry had, who reopened it and why, and who had checked it against
  which lines.

  It refuses an entry that is not locked, and writes both files or neither.
- **After a reopening** the entry is rewritten, checked by another session and sealed again with
  `seal`. The contract fails when a reopening is recorded for an entry sealed at the digest it
  had, and when a checked entry has no lock row.
- **Confirmed entries**: a reply serves an entry only when it is confirmed: the lock holds it
  sealed at the digest it has now, and the second check recorded that same digest
  (`scry_core.knowledge.confirmed`). An entry that is unsealed, reopened, sealed once only,
  changed since it was sealed or recorded under another digest is held back.
- **The second check** is one file format for every repository,
  `scry-knowledge-second-check/1`: `{"format": ..., "confirmed": [{"id", "by", "digest"}, ...]}`,
  read by `read_second_check`; a file of another shape is refused by name.
- **The confirmation** is built with `Confirmation.of(locks, second_checks)` from a server's own
  lock and second check (and `shared.locks()` and `shared.second_check()` for the shared
  dictionaries) and passed to `Base.load(..., confirmation=...)`. A base with no second check
  serves nothing of its own.
- **One filter**: the namer, the line notes, the summary and `machine_map`'s rows read a base
  that cannot hold a held-back entry. A `device` or `contains` that points at one is dropped when
  the base loads.
- **A held-back answer**: `knowledge_find` answers a key whose entry is held back with its id in
  `unconfirmed`, never its text. A server's `status` carries `knowledge_tool.counts`.
- **The declaration**: `knowledge/support.py` holds one `Support` listing the `Scope`s (a system
  or a cpu, with the kinds it owes; `support="named"` for a cpu the base names and the server
  does not claim to run), the `Device`s and the `Chip`s. Adding one there is the only step; the
  suite is red until its dictionaries exist.
- **The shared chips**: a chip both emulators model is written once, in this package.
  `scry_core.knowledge.shared` holds `CHIPS` (their declarations, so
  `Support(chips=shared.CHIPS)` is complete by construction), `CPUS` (cpus named for any system
  built on them) and `PINS` (the commit or tag each `dosbox-x:` and `mame:` ref is read at).
- **Where the shared files load**: `knowledge/chips/` is loaded by every server and
  `knowledge/cpus/` only by a server that declares those cpus, as
  `Base.load(<own package>, files("scry_core.knowledge") / "chips")`. A server takes its pins
  from `PINS`, and the contract fails when it declares another.
- **A shared register** has the id `<chip>:register:<key>` on both servers, and its `reached`
  names handlers, never a port: the board that places the chip says which port is which handler,
  in the `handlers` of its own device entry.
- **The shared rows** are in `knowledge_index/shared.json`, which a server's subject merges with
  its own index. `tools/knowledge_sources.py` writes it from the real sources, and `--check`
  compares it.
- **The source index**: a tool of the server captures, from the real sources, the rows its
  dictionaries cite (the line, the key the locator carries, the read and write marks) and the
  lists they must cover (`scry-knowledge-sources/1`, `scry_core.knowledge.sources`). The result
  is committed, and the tests need no network.
- **A row** holds the `line` or, where the index must not copy a third party's text, the
  `digest` of it (`sources.digest`: the SHA-256 of the line's UTF-8 bytes, in lower-case hex),
  never both. An entry's `cites` is held to the digest, and a check's `against` line to the whole
  `cites`.
- **The tests**: a subclass of `conformance.KnowledgeContract` with a `subject` that gives the
  declaration, the loaded `Base` as the server serves it (`fts5=False` uses the search index this
  package builds; the contract judges the files on `Base.unfiltered()`), the source index, the
  lock of the checked entries (`scry_core.knowledge.read_lock`), the second check
  (`scry_core.knowledge.read_second_check`) and the scopes the code depends on.
- **The model** for those tests is `tests/null_server.py`'s `NullKnowledge`.
- **The tool**: `knowledge_tool.register(wrap, answer, base, live)`. `live` says what the running
  machine can answer by itself (MAME's inputs and device tags, which a model may give as
  `kind=device key=:tag` or `device=:tag`); a server with none passes nothing.
- **The description** lists the scopes of `base`, so a server types none. A scope that is a near
  miss of one (`6809` for `m6809`) is read as it, with a `note` saying so.
  `knowledge_tool.judge` goes in the pre-gate table.
  `kind=device key=:tag` or `device=:tag`); a server with none passes nothing. The registered
  description lists the scopes of `base`, so a server types none, and a scope that is a near
  miss of one (`6809` for `m6809`) is read as it, with a `note` saying so. `knowledge_tool.judge`
  goes in the pre-gate table.
- **Rows (`scry-knowledge/2`, in `<package>/knowledge_rows/`)**: an entry as rows that carry
  their evidence, written and checked with `python -m scry_core.knowledge.rows`. The official
  source is the spine: a `doc` row says what the official source says (the list, or a maker's
  datasheet or guide held in `knowledge_index/datasheets.json`), and a row of an emulator is a
  note beside it, with a `vs` that says which kind: `differs` or `absent` name the `doc` row
  (`row`) the emulator does otherwise or does not do, `extra` is what it does that the
  document leaves open, `place` is how it reaches the thing (`on: place`). A row has one party
  (`of`: `doc`, `dosbox-x` or `mame`), a subject (`on`) and one sentence of at most 30 words, with
  the source lines that say it. A quote is a `ref` (`<scheme>:<file>`), `lines` and `sha`, the
  digest of those lines with white space folded; no file holds source text, and the digest is
  written by the tool, never typed. The sources are read at their pins: `--mame` a tree of the
  tag's files, `--dosbox` a checkout holding the pin of `knowledge.shared.PINS`, `--rbil` a
  folder with the list's files or archives, `--datasheets` a folder of the captures the document
  table names. The document table is scry-core's together with the
  `knowledge_index/datasheets.json` of the package that holds the dictionary, if it has one; a
  document the two hold in two forms is INVALID.
  - The header names what the dictionary covers in a few words (`title`, "INT 21h, the DOS
    services") and says where the entry comes from: `source` is `official` or `emulator`. An
    `official` dictionary names its `documents` (a row of the document table, with the `variant`
    each describes) and, per document, the lines of its capture that are the programming model
    (`official`). An `emulator` dictionary, or one entry that says `source: emulator`, has no
    `doc` row and says where it looked (`searched`, each of its fixed places with what it gave).
    A document is in the table with its class, whether its text is a layer or an OCR, the tool
    and version that made its capture, and a second URL.
  - An entry's official region is a section of the list or the lines of a capture (its own, or a
    header handler's when it names none), and every line of it is claimed by a `doc` row or closed
    as `key`, `see-also`, `version`, `layout`, `electrical` or `elsewhere` (a line another entry
    owns). A `doc` row quotes inside that region only. A line about a version of MS-DOS or PC DOS
    gets a `doc` row that names the version; a line about another product is closed `version`.
  - Each emulator the dictionary has code of owes a verdict on each `doc` row whose subject is
    not `is`, of one class: closures `agrees` that together show the row done (a row of two
    halves takes one per half), closures `unfollowed`, or notes `differs` or `absent` (one per part
    that departs). Two classes on one row are red, an `is` row included. Advice to the programmer
    ("the programmer should...", "it is recommended", "AH may be destroyed") is an `is` row: it
    says what the document asks of a program, no emulator can do it, so it owes no verdict. Every
    item of an emulator's code is claimed by a note, closed by a verdict, or closed with another
    reason of the fixed set; an `absent` note claims nothing. A line a note claims may also lie
    in a verdict of another row or in a `structure` closure, since one statement can do what
    several rows say; any other closure over it is red.
  - A closure `elsewhere`, `parent` or `preamble` names its `owner`, which holds those lines by a
    row or by a closure of its own that is not one of these three (an owner that hands them on in
    turn holds nothing). The owner may be an entry of any dictionary in the same folder (a chip's
    registers and its device are two files). An owner no dictionary there holds is counted as owed
    under `--partial` and is red without it.
  - What a verdict's lines must show, because a line that exists proves nothing by existing: an
    `agrees` cites an effect, a `store`, a call to a callee the table says `writes`, a `local`, the
    return of a value (a DOSBox-X callback's `CBRET_*` is its dispatcher's, not one) or a line of a
    section; lines that hold only a
    condition, a decode, a `switch`, a label or a call fault. A `local` is an assignment to a
    variable the function owns or to a parameter it takes by value, when the value is no call's
    result; it counts as an effect and is owed no row, so a closure over lines that hold only
    locals and inputs closes nothing and is red. An `input` is a line that hands a guest register to a call or to a
    local (`reg_dx` to `MEM_StrCopy`); it counts as an effect only for an `in` row, and only when
    the register is one the row names (`in DS:DX` takes `reg_dx`, `in AL` takes `reg_al` and
    `reg_ax`). A call counts when the callee table follows it
    (`open`) and the verdict cites an effect in its body. A verdict cites as a row quotes: at most
    6 places of at most 12 lines. A callee with several bodies (a drive's `FileOpen`, a device's
    `Read`) is listed in the table as each `<file> <function>`, and its call is open until a
    verdict or a note covers it; an `agrees` through it cites an effect in each body, otherwise
    the row gets a `differs` note per body that departs or a closure `unfollowed` over the call
    (the emulator's behaviour for this row was not established), which `rows review` prints as
    such. `unfollowed` closes only a call the table leaves to another entry, to the engine or to
    several bodies; a `none` callee does nothing a row is about; and a line of an `unfollowed`
    that holds an effect of the entry's own code holds such a call too, because what those lines
    show is established and is an `agrees` or a note. An `absent` note cites, in one file, the
    whole body where the thing would be: the region itself, or a case, a block or a branch the
    lister reads inside it, or a section of a region of the entry.
  - A row that says a thing is left unchanged or that nothing is returned is closed `agrees` with
    `"nothing": true`, over that same kind of whole body (an early exit, an empty case) holding no
    store of a register the row names, or of anything when it names none, and no call that
    `writes` then. `rows review` prints it as agreeing by doing nothing; a range that is not one
    whole body is red, as is a body that stores what the row says is kept.
  - The callee table: `open` follows the callee in an entry that holds its body as a region, and
    in any other entry the call is owed to the entry that does, as `shared:<that entry>` is, so a
    function has one line in the table. `writes` marks a helper that writes the guest's memory or
    flags (`real_writeb`, `mem_writeb`, `CALLBACK_SCF` and their kin): a call to it is an effect
    for a verdict and is owed a row or a closure, as a store is; a call to a reader is not. A
    method two classes of one file define (`tone_t::set_period`, `envelope_t::set_period`) is
    named `Class::name` in a region and in a list of bodies; its bare name is refused there, so
    a region never reads the other class's body.
  - `rows quote <ref> <lines>` prints the lines and their digest (`--json` for the quote to
    paste); `rows quote --stamp <dictionary>` writes the digest into every quote that has none.
  - `rows cover <dictionary> [<id>...]` lists what each entry's code owes rows for, item by
    item (`path`, `before`, `branch`, `exit`, `call`, `store`, `key`, `build`, `empty`, `list`,
    `state`, `lookup`), each with what closes it; the `local` and `input` items a verdict may cite
    are not listed, because no row is owed for them. It reads C++ as text: macros, calls through a
    pointer or a member and values carried in a variable are named, never followed. An `#if` on a
    name the file itself defines as `0` or `1`, bare or in parentheses, is decided by that value,
    so the compiled arm is the one listed.
  - Two items reach past the region's own lines, so a fact that lives in the chip's clockwork
    (a count that wraps to 0xFFFF after terminal count, a flag set only under its enable bit) is
    owed by the entry that hands it out. A `state` item is a member the region hands out (in a
    `return`, in a local the function returns, or in a guest register) and code of its file
    writes outside the region, the handler's other cases included: one item per member and
    function, carrying every line of that function that writes it. It names one thing: a
    scalar member, or an element at a fixed index (a literal, a constant's name), and that index
    matches only itself, so `m_data[REG_C]` is owed for a write of `m_data[REG_C]` and never for
    one of `m_data[REG_A]`, `m_data[12]` or `m_data[offset]`. An element the region reaches at
    an index it does not fix (`m_data[offset]`, a loop's variable) owes nothing, while a
    computed index earlier in the path picks an instance (`m_chan[ch].count`) and matches any.
    What a region stores is owed by the entries that read it back, not by every function that
    reads it, since those are the chip's whole engine and no one fact about the write. A guest
    register is not state (it is the call's own output), a member only the entry's own regions
    write owes nothing, and an arm the key leaves out hands out nothing. A `lookup` item is a `const` table the file defines (`name[] = {`) that the region
    reads at an index computed from something, owed at the table's lines. Each closes like any
    other item, at any of its lines: a row that quotes one (the wrap, the table's value), a
    `parent` closure naming the entry whose region holds that line and has a row there, or a
    reason of the set (`unseen`, with its reason, for a debugger's own listing).
  - `rows check <dictionary> [<id>...]` is the script half of the check: every quote is at the
    pin and gives its digest, every row quotes its own party only, every item is closed by a row,
    the key, a `closed` entry with a reason of the fixed set, or the callee table (`--callees`,
    `scry-knowledge-callees/1`, one decision a function, the `callees.json` beside the
    dictionary when not given), and the verdicts and the official ranges hold. A line of a declared range that no entry and no dictionary closure holds is red,
    as is a closure for an owner not written; `--partial` counts both instead, for a dictionary
    still being written. Exit 0 closed,
    1 a fault or an item left open, 3 INVALID (a source or a function not found, a capture that is not
    the document table's, or nothing examined).
  - `rows review <dictionary> [<id>...]` prints the entry in the order a reply shows it: the `doc`
    rows, each emulator's notes with their `vs` and the row they name, each verdict closed on a
    row (every place of an `agrees` together, or `unfollowed`) beside the row it names, and the
    official region whole for the notes that are `extra`; for the reader who judges whether each
    sentence says only what its lines say.
  - Writing a note, each rule with the error it prevents:
    - Registers are named in hex as the emulator's code writes them (`0x0E`), never in the
      document's own numbering (R16 is octal in the AY's manual), or a reader matches the wrong
      register.
    - A negation ("has no reset", "never reads AL") is written only with a line that shows it: a
      whole body with nothing in it, a handler table without the entry. A search that found
      nothing is not a line.
    - A hedge of the source ("reportedly", "usually", "should") stays in the row: dropping it
      states as fact what the source does not.
    - A note is `extra` only when no official line of the entry or of the dictionary speaks of
      its subject; otherwise it is `differs` or `absent` and names that row.
    - Something a program can observe happening instead (a logged refusal, a fixed answer, a
      success faked) makes the note `differs`, not `absent`.
    - A row whose emulator half agrees and half departs is not split, since its verdict is one
      class: the agreeing half goes in the sentence of the `differs` note, or the reader cannot
      tell what still holds.
    - An `agrees` whose code does more than the row says gets an `extra` note for the more, or the
      reader refutes the `agrees` for what it does not say.
    - A row about what a stored bit is for is closed on the store, and its sentence says the bit
      is stored: the purpose is the document's, and the code that reads the bit lies outside the
      entry.
  - Reading a verdict, the test of each in one sentence:
    - `agrees`: the cited lines, read alone, do every part of the row and nothing it excludes.
    - `differs`: the cited lines show the emulator doing something observable that the row's
      text does not say.
    - `absent`: the cited body is where the row's behaviour would be, and nothing in it does it.
    - `agrees` marked `nothing`: the cited body is the whole path the row's case takes, and nothing
      in it changes what the row says is kept.
    - `agrees` through a call that `writes`: the call writes what the row says, at the place the
      row names.
    - `unfollowed`: the cited call is the one the behaviour goes through, the table does not
      follow it, and no cited line shows the behaviour by itself.
    - `extra`: no line of the entry's official region, read whole, speaks of the subject.
  - `rows migrate <old dictionary> <id> --evidence <file>` drafts an entry from an old-shape one
    and the evidence its check gathered: what quotes an official document becomes a `doc` row, and
    what quotes an emulator is a `candidate` whose official line is still to be found. Quotes it
    cannot find at their lines are dropped and said, and every statement it could not anchor is
    marked, so the draft fails `rows check` until a person resolves the marks and sets each row's
    `on`.
  - The seal: a part of an entry is its official part (`doc`: its key, name, aliases, source,
    `doc` rows, the closures of the document's lines and its official regions) or one emulator's
    (its notes, its closures, its regions and the digest of each `doc` row it gives a verdict
    on, so a `doc` row rewritten holds back the verdicts given on it until they are read again).
    A reader who did not write a part seals it; a quote with no digest is refused:

    ```sh
    python -m scry_core.knowledge.rows seal <dictionary> <id>... --lock <lock> --part <part> \
        --by <reader> --writer <writer>
    ```

    The lock (`scry-knowledge-rows-lock/1`, beside the package's `knowledge_rows/`, never in it)
    keeps per part its seal, its reader, its writer and, per row, the row's digest and who judged
    it. A row's digest is what it says and each quote's file and digest, not its `lines`, so a pin
    that only moves the text breaks no seal. A part that changed since its seal is refused: its
    rows at fault are reopened first, which lifts the part's seal and records who reopened it and
    why:

    ```sh
    python -m scry_core.knowledge.rows reopen <dictionary> <id>... --lock <lock> --part <part> \
        --row <n> --by <who> --why <what is wrong>
    ```

    With no `--row`, the fault is in the part's closures, regions or names. When the part is
    sealed again, a row whose digest is unchanged keeps its judgement, a reopened row that was
    not rewritten is refused, and the reader who judged what was reopened (the rows named, or the
    part) does not seal it again. Both commands exit 0 done and 1 refused, writing nothing.
  - The base: `knowledge.base.Base.load(<package or directory>..., lock=...)` serves an entry
    only when every part of it (the official one and each emulator's) is sealed at the seal it
    gives now; one held back keeps its id, kind and key, so `knowledge_find` says it exists and
    is not confirmed (`unconfirmed`). `Base.unfiltered()` is the view the checks of the files
    take. The rows sit in the database in the order a reply shows them, with each emulator's
    verdict on each `doc` row; the search reads the names, the aliases and the rows' text.
    `knowledge.shared.rows_lock()` is the lock of the shared dictionaries.
  - `knowledge_find` over it answers an entry whole with its `rows`: the `doc` rows, each with
    `verdicts` (per emulator: as documented, differs, absent or unfollowed), then each emulator's
    notes with `vs` and the `row` they name; each row's `cites` says where its lines are (the
    document's title, or the emulator's file, and the lines) and never copies them, and
    `sources` gives each place once with its URL. Past 24 rows the reply is cut, the notes
    before the `doc` rows, and says `rows_total`. An entry no official document answers carries
    `source`, the sentence that says whose code it is from. `id=<entry id>#<n>` answers one row,
    each cited line with the URL that opens it at the pin.
  - The tests: `KnowledgeSubject` gives `rows_base()`, `rows_sources()` (the packages or
    directories its dictionaries of rows are in) and `rows_lock()`, and `KnowledgeContract`
    holds them: every dictionary of rows parses, a sealed part is never changed (it names the
    rows that were), the base serves exactly the entries the lock seals, and no query shape
    returns one held back.

||||||| /tmp/ne-base.md
  `kind=device key=:tag` or `device=:tag`); a server with none passes nothing. The registered
  description lists the scopes of `base`, so a server types none, and a scope that is a near
  miss of one (`6809` for `m6809`) is read as it, with a `note` saying so. `knowledge_tool.judge`
  goes in the pre-gate table.

## Naming what the replies show

A reply calls a number by its name where the server knows one (`DAC write address
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
  `names_failed`, and never a call's own reply. `Boundary` puts the names on `Call.named` and, while `names_on()` holds,
  adds `names` and `names_cut` to every reply and
  names the numbers its summary prints, at the first whole occurrence: a short number such as `1`
  is ambiguous in a line, so a tool gives its field a `shown` spelling (`irq {}`) that is not. The
  block also names the call's own arguments, under `given.<argument>`.
- **The switch**: `start` takes `names: naming.Switch = True`, whose description is
  `naming.ARGUMENT`, and `naming.ASK` is the sentence for `asks.json`. Off, a reply has no
  `names`, no names in its summary and no note on a disassembled line.
- **A call with variants**: `naming.named_call(base, scope, interrupt, registers)` names `INT
  interrupt` from the registers a stop holds (upper-case names, `AH`, `BX`; a word or its two
  bytes serve either way). It answers the variant whose selector's register is known and holds
  the variant's value, else the call itself, else None; a register the stop does not say never
  picks a variant, so a name never says one it cannot know. A namer calls it where it names
  a call. `base` is either base a server loads, its dictionaries or its base of rows, and so for
  `notes.note` and `knowledge.calls.resolve`; on a base of rows an address is named by a
  `memory` entry's key only: it does not read an entry's `address` and `length`.
- **A disassembled line's note**: `notes.note(base, scope, operands, names_on=...)` returns what
  the base calls the operands the server parsed (a port, an interrupt, an address), and None when
  the session's `names` switch is off. It goes in a row's `note`, never in a person's `comment`. An operand a register holds is named only for the instruction at
  a stop, and `Note.live` says the line was named that way. An interrupt operand takes the
  stop's `registers` too: a call's variant is named (`video refresh (BL=0x36)`) only when the
  selector's register is among them, else the note names the call.
