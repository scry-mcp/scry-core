"""`scry_core.overlay`: the `overlay` argument's defaults and its strict schema, and the reply's
`overlay`: the layers drawn, the place in effect, why each layer asked cannot be drawn."""

from __future__ import annotations

from typing import Any

import pytest

from scry_core import overlay as ov
from scry_core import strict_arguments as strict
from scry_core.envelope import Envelope


def _start_tool() -> Any:
    mcp = Envelope("t", instructions="i", refusal=lambda *a: {})

    @mcp.tool(title="Start")
    def start(overlay: ov.Overlay = ov.OVERLAY) -> dict[str, Any]:
        return {"status": "ok"}

    strict.strict_arguments(mcp)
    return strict.registered(mcp)[0]


def test_every_layer_is_on_and_auto_placed_by_default() -> None:
    assert ov.OVERLAY.asked() == ("edge", "pointer", "keys", "calls", "pause", "record")
    assert ov.OVERLAY.place == "auto"
    assert ov.Overlay(calls=False, pause=False).asked() == ("edge", "pointer", "keys", "record")
    assert ov.Overlay(record=False).asked() == ("edge", "pointer", "keys", "calls", "pause")


@pytest.mark.parametrize(("given", "refusal"), [
    ({}, None),
    ({"overlay": {"calls": False, "place": "top"}}, None),
    ({"overlay": {"calls": "no"}}, "overlay.calls: Input should be a valid boolean"),
    ({"overlay": {"edge": False}}, "overlay.edge: Extra inputs are not permitted"),
    ({"overlay": {"place": "left"}}, "overlay.place: Input should be 'top', 'bottom' or 'auto'"),
    ({"overlay": '{"calls": false}'}, "overlay: Input should be a valid dictionary"),
])
def test_the_argument_takes_only_its_own_fields_strictly(
        given: dict[str, Any], refusal: str | None) -> None:
    said = strict.refused(_start_tool(), given)
    assert (said is None) if refusal is None else (said is not None and said.startswith(refusal))


def test_the_argument_is_one_object_with_its_defaults_in_the_schema() -> None:
    schema = _start_tool().parameters
    props = schema["$defs"]["Overlay"]["properties"]
    assert {k: v["default"] for k, v in props.items()} == {
        "calls": True, "keys": True, "pointer": True, "pause": True, "record": True,
        "place": "auto"}


def test_the_reply_names_the_layers_drawn_and_why_the_others_are_not() -> None:
    assert ov.reply(ov.OVERLAY, {}) == {
        "layers": ["edge", "pointer", "keys", "calls", "pause", "record"], "place": "auto"}
    assert ov.reply(ov.Overlay(keys=False), {"pointer": "MAME has no pointer"}, "bottom") == {
        "layers": ["edge", "calls", "pause", "record"], "place": "bottom",
        "lacking": {"pointer": "MAME has no pointer"}}


def test_a_layer_drawn_with_a_limit_says_so_in_its_note() -> None:
    notes: dict[ov.Layer, str] = {"pause": "kept still while stopped", "calls": "cut, not scrolled"}
    assert ov.reply(ov.Overlay(keys=False), {"pointer": "MAME has no pointer"}, "bottom",
                    notes) == {
        "layers": ["edge", "calls", "pause", "record"], "place": "bottom",
        "lacking": {"pointer": "MAME has no pointer"},
        "notes": {"calls": "cut, not scrolled", "pause": "kept still while stopped"}}
    assert "notes" not in ov.reply(ov.OVERLAY, {}, None, {})


@pytest.mark.parametrize(("lacking", "notes", "message"), [
    ({"keys": "x"}, {}, "a layer not asked: keys"),
    ({}, {"keys": "x"}, "a note is given for a layer not drawn: keys"),
    ({"pointer": "no pointer"}, {"pointer": "x"}, "a note is given for a layer not drawn: pointer"),
    ({}, {"calls": " "}, "says why"),
])
def test_a_note_for_a_layer_not_drawn_or_an_empty_one_is_refused(
        lacking: dict[ov.Layer, str], notes: dict[ov.Layer, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ov.reply(ov.Overlay(keys=False, pointer=True), lacking, None, notes)


@pytest.mark.parametrize(("lacking", "message"), [
    ({"keys": "x"}, "a layer not asked: keys"),
    ({"calls": " "}, "says why"),
])
def test_a_reason_for_a_layer_not_asked_or_an_empty_one_is_refused(
        lacking: dict[ov.Layer, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ov.reply(ov.Overlay(keys=False), lacking)


def test_a_reply_model_holding_the_overlay_builds_on_every_python_the_package_takes() -> None:
    """Below 3.12 pydantic refuses `typing.TypedDict`; `typing_extensions`' class builds on all,
    and on 3.12 and later the two are different classes, so the second line is red there too."""
    from pydantic import BaseModel, TypeAdapter
    from typing_extensions import TypedDict

    class Reply(BaseModel):
        overlay: ov.OverlayReply

    class Probe(TypedDict):
        pass

    assert Reply(overlay=ov.reply(ov.OVERLAY, {})).overlay["place"] == "auto"
    made: object = type(ov.OverlayReply)
    assert made is type(Probe)
    assert TypeAdapter(ov.OverlayReply).validate_python({"layers": [], "place": "top"})
