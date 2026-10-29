from __future__ import annotations

import setproctitle


def set_title(title: str) -> None:
    setproctitle.setproctitle(title)
