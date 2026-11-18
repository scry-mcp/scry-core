# The names of the files a server writes

One rule names every file a server writes, so a caller knows the name to read back on any
machine. `scry_core.file_names` holds the rule and the functions that apply it.

## The rule

A name is lowercase ASCII letters and digits, in words joined by single hyphens. One dot and an
extension of lowercase letters and digits follow: `snapshot-3.png`, `f000012.png`.

```
^[a-z0-9]+(-[a-z0-9]+)*\.[a-z0-9]+$
```

## A name that comes from outside

A value from outside is an argument, a start profile's name, a system's name, or the last part
of a path the caller names. A start profile is a saved set of `start` arguments.
`scry_core.file_names` rewrites the value to fit the rule, or refuses it.

- Rewritten: `My Dump.BIN` is written as `my-dump.bin`.
- Refused: a value with no letter or digit, since nothing of it fits.
- Refused: a caller's file name with no extension of letters and digits after its last dot.
- Refused: any other value that is still longer than `WORD_MAX` characters once rewritten. A
  caller's whole file name has no such limit, because the host already limits it.

## What the reply says

- The reply names the file that was written. A caller reads the file back by that name.
- When that name is not the one the caller gave, the reply's `note` says so in one sentence
  (`file_names.written_as`).
- A reply that wrote no file, because there is nothing yet or nothing to write, names none. Its
  `note` then says nothing about a name.

A tool names the argument that holds its file when it is registered: `names_file` of
`Boundary.tool`. The call wrapper adds the sentence, so no tool writes it itself.

## Files a repository tracks

The data a repository tracks for its servers follows the same rule: its test fixtures, its
demos and its `.scry/` files. There are two exceptions:

- A file a DOS program runs, reads or writes by its own name keeps DOS's 8.3 form in capitals:
  `MINES.COM`, `BUILD.BAT`, `MAPDEMO.MAP`. Its pattern is `^[A-Z0-9_]{1,8}\.[A-Z0-9]{1,3}$`.
- A name a convention fixes keeps it: `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `REFERENCE.md`, `TRANSCRIPT.md`, `LICENSE`, a dotfile.

Code is named by its language: a Python module takes `_`.

## Files in a `.scry/` folder

A file of a repository's `.scry/` folder is found by its name. So the file is that name as the
rule spells it, plus the suffix of its kind: `start/pac-man.json`,
`maps/lineup-screen-map.json`.

A file the rule would spell differently, such as `Pac_Man.json`, is never looked up.
`project_store.misnamed` lists those files: the ones `project_store.locate` cannot find under
their own name. Each server's tests run it on that server's own `.scry/`.
