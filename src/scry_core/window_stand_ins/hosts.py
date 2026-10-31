"""Window hosts for a server's unit tests: an emulator that opens its window where it was asked,
and the desks that differ from it. `asked` answers the server's own state: the pid and the
`WindowRequest` of its live session, or None when it was started without a window."""

from __future__ import annotations

from collections.abc import Callable

from scry_core.window import Display, Seen, WindowRequest

DISPLAYS = [Display(0, (0, 0, 1920, 1080)), Display(1, (1920, 0, 1920, 1080))]
SIZE = (640, 400)
BAR = 30     # a title bar's height
Asked = Callable[[], tuple[int, WindowRequest] | None]


def _inset(display: int) -> tuple[int, int, int, int]:
    x, y, _, _ = DISPLAYS[display].bounds
    return (x + 100, y + 100, *SIZE)


class Obeying:
    def __init__(self, asked: Asked) -> None:
        self.asked = asked

    def displays(self) -> list[Display]:
        return list(DISPLAYS)

    def windows(self) -> list[Seen]:
        got = self.asked()
        if got is None:
            return []
        pid, request = got
        bounds = DISPLAYS[request.display].bounds if request.fullscreen else _inset(request.display)
        return [Seen(pid=pid, number=1, bounds=bounds, onscreen=True)]

    def above(self, window: Seen) -> list[Seen]:
        return []

    def activate(self, window: Seen) -> str:
        return ""


class Absent(Obeying):
    """No window is ever listed."""

    def windows(self) -> list[Seen]:
        return []


class Covered(Obeying):
    """Off screen until activated."""

    def __init__(self, asked: Asked) -> None:
        super().__init__(asked)
        self.activations = 0

    def windows(self) -> list[Seen]:
        return [Seen(s.pid, s.number, s.bounds, self.activations > 0) for s in super().windows()]

    def activate(self, window: Seen) -> str:
        self.activations += 1
        return ""


class Dragged(Obeying):
    """The owner dragged the window to the other display after it opened."""

    def windows(self) -> list[Seen]:
        return [Seen(s.pid, s.number, _inset(1), True) for s in super().windows()]


class Stuck(Obeying):
    """Listed but never shown, whatever is done to bring it forward."""

    def windows(self) -> list[Seen]:
        return [Seen(s.pid, s.number, s.bounds, False) for s in super().windows()]


class Bordered(Obeying):
    """A title bar takes the top of every window, so a full-screen one never fills its display."""

    def windows(self) -> list[Seen]:
        return [Seen(s.pid, s.number, (s.bounds[0], s.bounds[1] + BAR, s.bounds[2],
                                       s.bounds[3] - BAR), True) for s in super().windows()]


class Late(Obeying):
    """The window is listed only from the `after`th reading on, as an emulator that is still
    opening it."""

    def __init__(self, asked: Asked, after: int) -> None:
        super().__init__(asked)
        self.after, self.readings = after, 0

    def windows(self) -> list[Seen]:
        self.readings += 1
        return super().windows() if self.readings > self.after else []


class WithAuxiliary(Obeying):
    """A small window of the same pid is listed before the main one, as MAME lists its own."""

    def windows(self) -> list[Seen]:
        main = super().windows()
        return [Seen(s.pid, s.number + 1, (s.bounds[0], s.bounds[1], 200, 200), True)
                for s in main] + main
