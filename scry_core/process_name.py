"""The name a server's process goes by in the host's process list, so whoever cleans up a host can
tell a Scry server (and its guardians) from the emulators it launched and from every other
interpreter, without reading a command line.

Without it the host shows the interpreter's name whichever way the server is launched: a console
script on macOS and Linux is a file whose shebang runs the interpreter, so the process is still
`python`. `setproctitle` rewrites the process's title, which `ps` shows, and on macOS also the
display name the Activity Monitor lists.
"""

from __future__ import annotations

import setproctitle


def set_title(title: str) -> None:
    """Show this process as `title` from now on."""
    setproctitle.setproctitle(title)
