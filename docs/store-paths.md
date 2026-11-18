# Paths in a `.scry/` folder

A repository tracks its `.scry/` folder, so a file in it must read the same on every machine.
This page says how a path is written there, and when it is resolved.

## How a path is written

A start profile is a saved set of `start` arguments, kept in `.scry/start/`. Every path in one
resolves against one base: the directory that holds `.scry/`.

- A relative path is relative to the repository.
- In a `;`-separated list of folders (`rompath`, `inipath`), each folder resolves on its own.
- A path that would belong to one machine is written with a placeholder.

| Placeholder | Stands for |
| --- | --- |
| `${root}` | the repository that holds `.scry/` |
| `${home}` | the home directory of whoever runs the server |
| `${state}` | the session's temporary folder |
| `${env:NAME}` | the environment variable `NAME`; refused by name when it is unset |

Any other `${...}` is refused.

## Who writes the placeholders

`promote` is the tool that saves what a session learned into `.scry/`. It writes each path with
these placeholders. A file with a path none of them covers is listed apart, in `unwritable`,
and is not written.

An approved `promote` also writes the folder's `about.json` and `README.md`:
[The `.scry/README.md` of a repository](scry-readme.md).

## When a path is resolved

- A start profile is resolved when `start` reads it.
- A list of steps saved in `.scry/perform/` is resolved when `perform(path=)` replays it.
  There `${state}` is that session's temporary folder.
- `python -m scry_core.replay` resolves the same file the same way. It refuses one that uses
  `${state}`, because it has no session to name.
