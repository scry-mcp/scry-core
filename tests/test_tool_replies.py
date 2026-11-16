"""The fields both servers' models share are composed with an envelope, and a reply of their shape
passes the strict check every battery holds its replies to."""
from __future__ import annotations

from typing import Any

import pytest
from typing_extensions import TypedDict

from scry_core import media_replies, reply_schema, tool_replies


class _Captures(reply_schema.RunEnvelope, media_replies.CapturesFields, total=False):
    pass


class _Export(reply_schema.RunEnvelope, media_replies.PerformExportFields, total=False):
    pass


class _MapWrite(reply_schema.RunEnvelope, tool_replies.MapWriteFields, total=False):
    pass


class _LogWait(reply_schema.RunEnvelope, tool_replies.LogWaitFields, total=False):
    pass


class _CommentWrite(reply_schema.RunEnvelope, tool_replies.CommentWriteFields, total=False):
    pass


class _WindowRefused(reply_schema.RunEnvelope, tool_replies.WindowRefusedFields, total=False):
    pass


class _StopWait(reply_schema.RunEnvelope, tool_replies.StopWaitFields, total=False):
    pass


class _ProfileRefused(reply_schema.RunEnvelope, tool_replies.ProfileRefusedFields, total=False):
    pass


SAMPLES: list[tuple[type[TypedDict], dict[str, Any]]] = [  # type: ignore[valid-type]
    (_Captures, {"captures": [], "last_stop": {}, "exit_code": 0}),
    (_Export, {"checks": 1, "cut": {}, "dropped": [], "dropped_total": 0, "path": "p",
               "replay": "r", "steps": 2, "answers_while_running": []}),
    (_MapWrite, {"screen": "play", "screens": 1, "stopped_on_its_own": {}}),
    (_LogWait, {"arrived_during": 0, "lines_examined": 3, "verdict": "TIMEOUT", "waited_s": 1.0}),
    (_CommentWrite, {"added": 1, "comments_total": 4, "path": "c.json"}),
    (_WindowRefused, {"activation": "", "asked_display": 1, "seen": {}}),
    (_StopWait, {"waited_on": {"kind": "watch", "ref": "lives"}, "firings": 2,
                 "frames_examined": 1, "fired_line": {"available": False, "why": "none"}}),
    (_ProfileRefused, {"searched": ["/repo", "/"]}),
]


@pytest.mark.parametrize(("model", "reply"), SAMPLES, ids=[m.__name__ for m, _ in SAMPLES])
def test_a_reply_of_the_shared_shape_passes_the_strict_check_and_an_unknown_field_does_not(
        model: Any, reply: dict[str, Any]) -> None:
    judge = reply_schema.judged(model)
    judge.validate_python({"status": "ok", **reply})
    with pytest.raises(ValueError, match="not_a_field"):
        judge.validate_python({"status": "ok", **reply, "not_a_field": 1})


REQUIRED = [(_Captures, {"captures"}),
            (_Export, {"checks", "cut", "dropped", "dropped_total", "path", "replay", "steps"}),
            (_LogWait, {"arrived_during", "lines_examined", "verdict", "waited_s"})]


@pytest.mark.parametrize(("model", "fields"), REQUIRED, ids=[m.__name__ for m, _ in REQUIRED])
def test_an_ok_reply_of_the_shared_shape_always_carries_these_fields(
        model: Any, fields: set[str]) -> None:
    assert reply_schema.own_required(model) == fields
