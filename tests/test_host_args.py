"""The host's own emulator arguments, read from `SCRY_EMULATOR_ARGS`."""

from __future__ import annotations

import pytest

from scry_core import host_args


@pytest.mark.parametrize("exported, tokens", [
    (None, []),
    ("", []),
    ("-screen0\nscreen1", ["-screen0", "screen1"]),
    ("-set\nsdl display=1\n-set\nsdl windowposition=2088,40",
     ["-set", "sdl display=1", "-set", "sdl windowposition=2088,40"]),
    ("-screen0\r\n\n  \nscreen1\n", ["-screen0", "screen1"]),
    ("-set\nsdl title=a\x0cb", ["-set", "sdl title=a\x0cb"]),
])
def test_the_tokens_are_the_variable_s_lines(
        monkeypatch: pytest.MonkeyPatch, exported: str | None, tokens: list[str]) -> None:
    if exported is None:
        monkeypatch.delenv(host_args.VARIABLE, raising=False)
    else:
        monkeypatch.setenv(host_args.VARIABLE, exported)
    assert host_args.emulator_args() == tokens


def test_the_variable_is_the_one_the_fleet_spells() -> None:
    assert host_args.VARIABLE == "SCRY_EMULATOR_ARGS"
