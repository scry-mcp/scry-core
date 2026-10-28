"""The host's emulator argv: `SCRY_EMULATOR_ARGS`, a token a line."""

from __future__ import annotations

import os

VARIABLE = "SCRY_EMULATOR_ARGS"


def emulator_args() -> list[str]:
    return [line.strip() for line in os.environ.get(VARIABLE, "").split("\n") if line.strip()]
