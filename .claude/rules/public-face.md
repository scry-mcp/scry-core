---
paths:
  - "README.md"
  - "REFERENCE.md"
  - "CHANGELOG.md"
  - "CONTRIBUTING.md"
  - "docs/**"
---

> **This is the public-face profile of this repository.** It loads when one of the public
> documents below is opened, and it says who each layer of the documentation is written for, in
> what character and within which limits, so that an edit is made for its reader and not for its
> author. It is reference, not a task list: nothing here is an instruction to act on right now.

## The layers of the public face

| layer | files or globs | audience | character | language |
|---|---|---|---|---|
| package front door | `README.md` | first a visitor who arrived from a server's README or the site and wants to know what SCRY is and where to install it; then a developer of a SCRY server who needs to know what the shared package holds before writing a helper twice | the visitor's part first and short: what SCRY is in one sentence, the two servers in one line each with a link to each one's install. Then the developer's: how a server uses the package, how to try a server by hand, how to develop here, and a link to the module list. The WHY of a module's contract lives in its docstring, not here. No history and no measurement | English |
| contributor docs | `docs/*.md` | somebody writing or changing a server on this package | reference: the shared contracts (file names, store paths, every shared tool's replies side by side, a new emulator, the katas) and the list of modules (`docs/modules.md`) | English |
| changelog | `CHANGELOG.md` | a server author upgrading the pin | what a server author notices, one entry per change, newest first | English |

## What is public and what is not

- Public: `README.md`, `CHANGELOG.md` and `docs/*.md`.
- Not public and not this profile's business: `.claude/`.
- Extra READMEs kept public: none.

## Countable limits

They serve the reader, so a fact is never what gets cut to meet one: it moves to the layer that
reader goes to for it. Words are counted in prose, outside code blocks and generated blocks.

| layer | limit |
|---|---|
| every layer | a paragraph is at most 3 sentences and 60 words; a sentence at most 30 words |
| every layer | a code block showing has at most 12 lines of at most 100 columns |
| package front door | the opening is one bold sentence of at most 25 words |
| package front door | at most 120 words between the title and the links to the two servers' install |
| package front door | a table has at most 3 columns and 12 rows; the module list, which has one row a module, is `docs/modules.md` |
| package front door | under 16 KB |
| contributor docs | a table has at most 4 columns; a reference list may run as long as what it lists |

## The front door: its sections and their order

1. The logo and the title.
2. The bold sentence: what SCRY is, for a person.
3. `## Install a server`: one line per server (what it is for, what it needs) and a link to that
   server's own `## Install`. The package itself is never installed by hand, and this README
   carries no client block of its own: the servers' front doors hold them, generated from the
   table this package keeps.
4. `## What the package holds`: at most 12 rows naming the groups of modules, and a link to
   `docs/modules.md`.
5. `## How a server uses it`, `## Trying a server by hand`, `## Developing`, the on-demand tiers.
6. `## Platforms`, `## Credits`.

## What this package generates for the servers

The servers' profiles state the rules; this package holds the programs that keep them.

| program | writes | rule it keeps |
|---|---|---|
| `scry_core.reference` | each server's `REFERENCE.md`, `docs/reference/*.md`, `docs/reference/examples.json` | a tool's entry in its one order (name, one sentence, signature, the example, arguments, what comes back, what it refuses, the contract folded), read from the registry and the server's hand-written `docs/reference/asks.json`; an entry without its `what` and `ask`, or over their word limits, is drift |
| `scry_core.demo` | each demo's README block, `TRANSCRIPT.md`, `screen.png`, `loop.webp` and the front door's flow | the example's shape on the steps a demo marks (`Step.ask`), and the demo's motion: up to 3 `Moment`s recorded in the run, 6 seconds in all, at most 400 KB, refused past either |
| `scry_core.install` | the `<!-- scry-install -->` block of each server's front door | one table of clients (the name, the form its documentation gives a local server, the vendor's page), rendered once per server, so the front doors and the site carry the same blocks |
| `scry_core.scry_readme` | each repository's `.scry/README.md` | its headings in plain words: "Start profiles" for the saved arguments of `start`, "Saved step lists" for what `perform` replays |

A sentence one of these programs prints into a public document follows *Vocabulary* like a
hand-written one: "The reply carries only the fields every reply has.", "Example, recorded from
a run against the real emulator:". A finding about such a sentence is fixed in the program.

## Generated documents

| document | generated from | regenerated by |
|---|---|---|
| `docs/reply-differences.md` | the two servers' generated `docs/reference/*.md` | `python -m scry_core.reply_differences --write`, held by its test |

## Captures

- None: the package has no surface of its own to show, and the auditor does not report a missing
  capture.

## Vocabulary: words a programmer who never saw SCRY knows

- Headings and running text use words a programmer who has never seen SCRY knows. A heading says
  what is under it in those words: "Tools this demo uses", never "What it walks".
- A term of ours appears only if it is the name of a tool, an argument, a reply field, one of
  its values, or a family of tools. It is set in code type (a family's name as a plain capital
  word), and where it first appears on a page it is explained in plain words, in that sentence
  or the next. A page is one document, or one page of the site.
- A wording a server prints inside a reply is shown as printed, because a reply is copied and
  never typed; the sentence that reads the reply says it in plain words.
- A metaphor is not a term. A thing is called what it is each time, even when a shorter image
  has become a habit here.
- An emulator's own vocabulary (MAME's, DOSBox-X's, DOS's) is used as its documentation uses it,
  and a word of it a programmer may not know is explained once the same way.
- The table is part of the rule. A word of its left column, used in that private sense in a
  heading or in running text, is a finding, and the right column is what to write. A coinage
  the table does not hold yet is a finding too: it is added with its plain words.
- This file's own labels for the layers ("front door", "demo guide") are names inside this
  file. A public document says "the README" and "the demo's page".

| ours | write |
|---|---|
| What it walks | Tools this demo uses |
| A first answer | Your first question |
| From an investigation to a bench | From a session to a test that replays itself |
| The battery | The checks |
| The live tier | Tests against a real emulator |
| The store | The `.scry/` folder / What is saved between sessions |
| The route | How input gets into the program |
| The code pane is the control | Checked against the debugger's own disassembly |
| The one table | Tools that answer while the program runs |
| Recipes | Start profiles |
| Sessions (in `.scry/`) | Saved step lists |
| Two machines | Two emulators |
| Shared core | scry-core, the shared package |
| walk | sequence of steps / destination rectangle / list of files |
| front door | the README |
| flow | the README's example calls |
| bench | replay test / folder of test programs / live-test helper |
| tier | tests against a real emulator / opt-in tests |
| battery | the checks |
| desk | your screen and keyboard |
| kata | checked demo |
| roster | tool list |
| envelope | the fields every reply carries |
| survey | the readings taken at each stop |
| store | the `.scry/` folder / the saved breakpoints file |
| recipe | start profile |
| park | stopped at the debugger |
| place | address / resolved to an address |
| census | write log |
| LATCHES | stays set until `close` |
| law | rule |
| rung, ladder | the first of these that is set |
| broom | way of clearing |
| golden, blessed | reference capture / reference build |
| held to | matches / is compared with |
| judged | checked |
| signed | fingerprinted |
| rest | confirmed stopped |
| fly | fast-forward |
| release | resume |
| alarms | warnings |
| ride | is included in |
| matrix, cell | the live test script / test case |
| probe | description test / version check |
| residual | known failure, tolerated |
| sweep | cleanup pass / manual check |
| gate | check |
| drift | out of date |
| surface | the tools and their replies |
| instrument | check |
| seam | test override |
| guardian | watchdog |
| highlight, epilogue | featured step / closing steps |
| the loop | the demo's clip |
| one-off images | say the thing itself |
| the owner, the reader | you |
| answer by name | by your program's symbol names |
| proves they landed | checks the program took them |
| the beam | the screen line being drawn |
| heavy debugger | a DOSBox-X built with heavy debugging |
| arrival | reaching the target |
| channel | log / debugger connection |
| stub | the input helper inside DOS |
| guest | the program (inside the emulator) |
| double | stand-in for tests |
| dumper | table writer |
| cold, hot | rarely run / often run |
| harness, binding | boot script / per-emulator settings |
| known answer | reference data |
| lap | repetition |
| batch | the loaded symbol table |
| scratch | temporary folder |
| cap | the client's text limit |
| ledger, canary | run log / preflight check |
| call boundary | call wrapper |
| fold | merged tool |
| bound | time limit |
| live run | a run against the real emulator |
| declare (a repository) | keeps in `.scry/` |

Kept and explained where they first appear, never renamed by a document:

- The families: Declarations (breakpoints, watches and comments, declared by name and saved by the server), Lists (the tools that run several calls as one (`perform`, `drive`), not tools that list things), Store (the tool that writes into the repository's `.scry/` (`promote`)), Advance (the tools that let the program run and stop it again), Film (MAME's tools that record the frames in which a write happened).
- The names: `promote`, `kept`, `draft`, `not_settled`, `settle_seconds`, `verdict`, `OTHER_STOP`, `ELAPSED`, `TARGET`, `TIMEOUT`, `altered`, `control`, `control_silent`, `anchor`, `mark`, `since_mark`, `ref`, `held`, `recorded`, `diverged`, `route`, `armed`, `pending`, `unresolved`, `unarmable`, `stale`, `foreign`, `inherited`, `orphan`, `declaration`, `regpoint`, `shared`, `presence`, `tally`, `show`, `change`, `count`, `capture`, `freeze`, `consolidated`, `verified`, `perform`, `drive`, `e9`, `no_channel`, `enrichment`, `unaccounted`, `surveyed`, `superseded`, `cut`, `posted`, `arrived`, `pen`, `profile`, `keep_noise`, `heavy_debug`, and every other tool, argument, field and value the reference lists.
- What a reply prints: "survivors"; "posted, unverified / effect seen"; "retraces"; "kept N (promote to review)"; "<volatile>, <host>, <run>, <time>".

## Limits

- Language: every public document here is in English. This line is the declaration.
- A public document over 64 KB whose headings also belong to more than one layer is a God README.
- The README closes with the credits line, verbatim, its links resolving; it is attribution the
  project ships, not a leak, and a README without it is the finding:

  `Developed by Optimiza ([Marcos Hernández](https://www.linkedin.com/in/optimiza/)), in collaboration with [MS-DOS Club](https://msdos.club) and its [podcast](https://www.ivoox.com/podcast-ms-dos-club_sq_f11160693_1.html).`
- The `claude` command, named where it is the program a reader runs (an install command, the
  probe that executes it), is the name of a program and not a mention of the assistant; no other
  use of the name is exempt.
- Nothing else is exempt: a dated measurement, a note on the project's own history, a
  home-directory path or an assistant's name in a tracked file outside `.claude/` is a finding.
