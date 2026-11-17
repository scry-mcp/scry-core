# Paths in a `.scry/` store

A store is tracked by its repository, so a file in it must read the same on every machine. Every
path in a recipe resolves against one base, the directory holding `.scry/`: a relative path is
relative to the repository, and in a `;`-separated list of folders (`rompath`, `inipath`) each
folder resolves on its own. Whatever would otherwise be a path of this machine is written as a
placeholder:

| Placeholder | Stands for |
| --- | --- |
| `${root}` | the repository that holds `.scry/` |
| `${home}` | the user's home |
| `${state}` | the session's scratch directory |
| `${env:NAME}` | the environment variable `NAME`; refused by name when it is unset |

Any other `${...}` is refused. `promote` writes each path in these terms, and lists apart an entry
with a path none of them covers. A `start` profile is resolved when `start` reads it, and a
`perform` document the store holds when `perform(path=)` replays it, `${state}` naming that
session's scratch, or when `python -m scry_core.replay` runs it, which refuses one that uses
`${state}` because it has no session to name. A promotion made by a server also writes the
folder's `about.json` and README: [docs/scry-readme.md](scry-readme.md).
