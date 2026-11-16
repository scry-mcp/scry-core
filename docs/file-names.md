# The names of the files a server writes

A file a server writes is named in lowercase ASCII letters and digits, in words joined by single
hyphens, then one dot and an extension of lowercase letters and digits (`snapshot-3.png`,
`f000012.png`): `^[a-z0-9]+(-[a-z0-9]+)*\.[a-z0-9]+$`. A value that comes from outside (an
argument, a profile, a system's name, the last component of a path the caller names) is
normalised into that rule by `scry_core.file_names`, or refused when nothing of it fits; a value
other than a caller's file name is refused too when what fits is longer than its `WORD_MAX`,
since a caller's whole file name is the host's to bound. The server's reply names the file that
was written, and when its name is not the one the caller gave, the reply's `note` says so in one
sentence (`file_names.written_as`): a caller reads a file back by the name in the reply. A reply
that wrote no file (nothing yet, or nothing to write) names none and says nothing of it. A tool
declares the argument that names its file (`names_file` at registration) and the call boundary
adds the sentence, so no tool words it.

The data a repository tracks for its servers (its fixtures, demos and `.scry/` files) follows the
same rule, with two exceptions. A file a DOS program runs, reads or writes by its own name keeps
DOS's 8.3 form in capitals (`MINES.COM`, `BUILD.BAT`, `MAPDEMO.MAP`):
`^[A-Z0-9_]{1,8}\.[A-Z0-9]{1,3}$`. And a name a convention fixes keeps it: `README.md`,
`CHANGELOG.md`, `CONTRIBUTING.md`, `REFERENCE.md`, `TRANSCRIPT.md`, `LICENSE`, a dotfile. Code is
named by its language (a Python module takes `_`).

A `.scry/` entry is found by its name, so its file is that name as the rule spells it, with its
kind's suffix (`start/pac-man.json`, `maps/lineup-screen-map.json`), and a stem the rule would
spell differently (`Pac_Man.json`) is never looked up: `project_store.misnamed` lists the
entries of a store `locate` cannot find under their own name, and each server's suite holds its
own `.scry/` to it.
