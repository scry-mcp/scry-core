"""A server with no emulator behind it, written only on what `scry_core.window` offers, and two
that break one rule each. `scry_core.conformance` is what tells them apart."""

from __future__ import annotations

from typing import Any

from scry_core import session_block
from scry_core import window as w
from scry_core.reply_contract import Invalid

PID = 4242


class NullServer:
    shows_fullscreen = True

    def __init__(self) -> None:
        self.live = False
        self.requested: w.WindowRequest | None = None
        self.background = False

    def asked(self) -> tuple[int, w.WindowRequest] | None:
        return (PID, self.requested) if self.live and self.requested else None

    def has_session(self) -> bool:
        return self.live

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        try:
            asked = self._ask(shared, display, fullscreen)
            self.live, self.requested = True, asked
            self.background = w.judge_background(background, shared)
            return {"status": "ok", **({} if asked is None
                                       else {"window": w.prove(PID, asked).block()})}
        except Invalid as refused:
            return refused.reply()

    def _ask(self, shared: bool, display: int | None,
             fullscreen: bool | None) -> w.WindowRequest | None:
        return w.requested(shared, display, fullscreen)

    def window(self, front: bool = False) -> dict[str, Any]:
        try:
            if not self.live:
                raise Invalid("no_session", "no session is live: call `start`")
            return {"status": "ok", **w.answer(PID, self.requested, front=front,
                                               launched_behind=self.background)}
        except Invalid as refused:
            return refused.reply()

    def close(self) -> dict[str, Any]:
        was, self.live, self.requested = self.live, False, None
        if not was:
            return {"status": "ok", "closed": False, "ended_by": "none",
                    "note": session_block.NO_SESSION_CLOSE_NOTE,
                    "summary": session_block.NO_SESSION_CLOSE}
        return {"status": "ok", "closed": True, "ended_by": "quit"}

    def status(self) -> dict[str, Any]:
        if not self.live:
            return {"status": "ok", "summary": session_block.NO_SESSION_STATUS,
                    "session": {"alive": False}}
        return {"status": "ok", "system": "null", "session": {"alive": True}}


class WithoutWindowTool(NullServer):
    """Has no `window` tool: the call is refused as an unknown argument, whatever the session."""

    def window(self, front: bool = False) -> dict[str, Any]:
        return Invalid("bad_argument", "no tool `window`").reply()


class IgnoresDisplayUnwatched(NullServer):
    """Takes `display` and `fullscreen` on a run nobody watches and says nothing."""

    def _ask(self, shared: bool, display: int | None,
             fullscreen: bool | None) -> w.WindowRequest | None:
        return super()._ask(shared, None, None) if not shared else super()._ask(
            shared, display, fullscreen)


class AlwaysBehind(NullServer):
    """Tells every `window` call its session was launched behind, whatever it was."""

    def window(self, front: bool = False) -> dict[str, Any]:
        self.background = True
        return super().window(front)


class SkipsProve(NullServer):
    """Answers a watched `start` without waiting for the window it asked for."""

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        try:
            self.requested = self._ask(shared, display, fullscreen)
        except Invalid as refused:
            return refused.reply()
        self.live = True
        self.background = w.judge_background(background, shared)
        return {"status": "ok"}


class CachesStartBlock(NullServer):
    """Answers `window` with the block `start` read, never reading the host again."""

    def start(self, shared: bool = False, display: int | None = None,
              fullscreen: bool | None = None, background: bool | None = None) -> dict[str, Any]:
        self.block = super().start(shared, display, fullscreen, background).get("window")
        return {"status": "ok", **({} if self.block is None else {"window": self.block})}

    def window(self, front: bool = False) -> dict[str, Any]:
        return {"status": "ok", "window": self.block} if self.live and self.block else (
            super().window(front))


class RefusesToCloseNothing(NullServer):
    """Answers a `close` with no session as a refusal."""

    def close(self) -> dict[str, Any]:
        if not self.live:
            return Invalid("no_session", "close: no session is live").reply()
        return super().close()


class StatusInventsASession(NullServer):
    """Answers a `status` with no session as if one were alive."""

    def status(self) -> dict[str, Any]:
        return {"status": "ok", "system": "null", "session": {"alive": True}}


class StatusDeniesASession(NullServer):
    """Answers a `status` with a live session as if there were none."""

    def status(self) -> dict[str, Any]:
        return {"status": "ok", "summary": session_block.NO_SESSION_STATUS,
                "session": {"alive": False}}
