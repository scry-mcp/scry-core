# The `.scry/README.md` of a repository

One template, shipped by scry-core, renders the `README.md` of every repository's `.scry/`
folder. So the page reads the same everywhere, and a changed template reaches a repository
when its page is rendered again.

## Set up SCRY in a new project

A repository with no `.scry/` gets one the first time a session saves into it. There is nothing
to install or write by hand.

`promote` is the tool that saves what a session learned. `promote(entries=[...])` is your
approval, and that call does four things:

1. It creates `.scry/`.
2. It writes the entries you chose. An entry is one file under `start/`, `maps/` or `perform/`.
3. It builds `about.json`.
4. It renders the page, replacing any page already there.

`promote(dry_run=true, root=<the repository>)` lists beforehand what would be created, in
`would_create`. The approved reply says what was created, in `created`. Nothing is written
without that approval.

The folder says how a program starts. What a run of the program means belongs to the
repository's own rules and tests. That covers which stop serves a test case, how a key is
spelled, and what a change on screen proves.

## What the page shows

The page has these parts, in this order. A part with nothing to show is left out.

1. `purpose`, then a fixed paragraph that says what SCRY is.
2. "Build first", when `about.json` has a `build`.
3. "How to start", when the folder holds a start profile.
4. "Start profiles", "Screen maps" and "Saved step lists", each with one line per file.
5. `notes`, then a closing line that says how the page is rendered.

| Heading | Lists the files of | Each file is |
| --- | --- | --- |
| Start profiles | `start/` | a saved set of `start` arguments |
| Screen maps | `maps/` | a program's screens and the named areas of each |
| Saved step lists | `perform/` | a list of steps the `perform` tool replays |

## What `promote` writes into `about.json`

`promote` builds `about.json` from the entries alone, for a folder that has none.

| Key | What it gets |
| --- | --- |
| `server` | the server that ran `promote` |
| `purpose` | "What this repository keeps for SCRY's `<server>` server." |
| `files` | one line per file, derived from that file |

| File | Its derived line |
| --- | --- |
| a start profile | "boots `X`.", `X` being its `program` or, without one, its `system` |
| a start profile with neither | "a start profile." |
| a screen map | "the screens of X.", `X` being its `application` or, without one, its name |
| a saved step list | "replays N steps." |
| a saved step list with no steps to count | "a saved step list." |

A later `promote` changes as little as it can:

- It keeps every line that is already there, so a line written by hand survives.
- It gives a derived line only to a file that has none.
- It renders the page again.

An `about.json` it cannot render from refuses the `promote` before anything is written. Two
examples: a file that is not JSON, and a line for a file that is gone.

## Render the page by hand

Run the command from a scry-core checkout. `DIR` is the repository, or the current directory
when left out.

```sh
uv run python -m scry_core.scry_readme [--check] [DIR]
```

The page is always written whole, so never edit it by hand. `--check` writes nothing and exits
1 when the page differs from its render. No commit hook and no CI job runs it.

| Exit | Means |
| --- | --- |
| 0 | the page was written, was unchanged, or is current under `--check` |
| 1 | `--check` found the page out of date |
| 2 | `about.json` breaks its format |
| 3 | INVALID: nothing was rendered |

Exit 3 has three causes: no `.scry/` at or above `DIR`, none of those files in it, or a page
that cannot be read or written. None of them is ever reported as a clean page.

## What the folder cannot say: `.scry/about.json`

`about.json` holds what the files of the folder cannot say for themselves. Its format is
`scry-about/1`. `format`, `purpose`, `server` and `files` are required; every other key is
optional.

| Key | Holds |
| --- | --- |
| `purpose` | one line: what this repository's folder is for |
| `server` | `mame` or `dosbox-x`, the server whose `start` tool reads the start profiles |
| `build` | `{"command": "...", "note": "..."}`: the step to run before a start profile boots; `note` is optional |
| `files` | one line per file of `start/`, `maps/` and `perform/`, keyed by its path under `.scry/` |
| `notes` | paragraphs that belong to this repository alone, printed after the files |

`files` must cover exactly the files there. A file with no line, or a line for a file that is
not there, is refused by name.

## When `.scry/` gains a kind of file

Two things change, both in scry-core: the kinds in `project_store.py` (`KINDS`, and `SUFFIXES`
for a file not named `<name>.json`) and each kind's heading and sentence in `scry_readme.py`.
Then each repository renders its page again.
