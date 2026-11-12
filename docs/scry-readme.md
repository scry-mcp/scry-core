# The `.scry/README.md` of a repository

One template, shipped by scry-core, renders every repository's `.scry/README.md`, so a reader
meets the same page everywhere and a change to `.scry/` reaches every repository by a re-render.

Run it inside the repository, under its own `uv run`:

    uv run python -m scry_core.scry_readme [--check] [DIR]

The page is always written whole, so never edit it by hand. `--check` writes nothing and exits 1
when the page differs from its render; it is not wired to any commit or CI.

## What the folder cannot say: `.scry/about.json`

Format `scry-about/1`. Every key but `format`, `purpose`, `server` and `files` is optional.

| Key | Holds |
| --- | --- |
| `purpose` | one line: what this repository's folder is for |
| `server` | `mame` or `dosbox-x`, the server whose `start` tool reads the recipes |
| `build` | `{"command": "...", "note": "..."}`: the step to run before a recipe boots; `note` is optional |
| `files` | one line per file of `start/`, `maps/` and `perform/`, keyed by its path under `.scry/` |
| `notes` | paragraphs that belong to this repository alone, printed after the files |

`files` must cover exactly the files there: a file with no line, or a line for a file that is
not there, is refused by name. Exits: 0 written, unchanged or current; 1 `--check` found drift; 2 the manifest
breaks its format; 3 INVALID. A folder with no `.scry/` above it, or none of those files, is
INVALID, never a clean page; so is a page that cannot be read or written.

## When `.scry/` gains a kind of file

The template (`src/scry_core/scry_readme_template.md`) and the kinds listed in `scry_readme.py`
change here, and each repository re-renders.
