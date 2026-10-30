"""One game's demo, written once and run on both servers: the proof that they answer one surface.

A game on both platforms shares its source, so its symbols, screens and variables. Its script
(`scry_core.games.<game>`) is built against a `Binding`, which holds ONLY what a platform cannot
do the same way; anything else a script needs from one platform is an incoherence between the
servers, never a second branch in the script. Time is milliseconds, never frames: the two screens
refresh at different rates.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scry_core.demo import Args, Reply, Run, Step, StepFailed

WAIT_S = 120


@dataclass(frozen=True)
class Press:
    """One of the game's actions as a platform fires it: `tool` with `args`."""

    tool: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class Binding:
    """What one platform answers for a script: `boot` leaves the machine stopped with the game's
    symbols loaded, `inputs` fires each of the game's actions, `rate_hz` is the screen's refresh,
    `sound` the recording the script's sound is held to, `volatile` what its input replies vary
    in between two honest runs."""

    platform: str
    boot: Sequence[Step]
    inputs: Mapping[str, Press]
    rate_hz: float
    sound: Path
    volatile: Mapping[str, str] = field(default_factory=dict)

    def frames(self, milliseconds: int) -> int:
        """`milliseconds` of emulated time as whole frames of this screen, rounded up."""
        return -(-milliseconds * round(self.rate_hz * 1000) // 1_000_000)

    def press(self, name: str, action: str, check: Callable[[Reply, Run], str]) -> Step:
        """A step firing `action`, refused when the script is built if this platform lacks it."""
        if action not in self.inputs:
            raise KeyError(f"{self.platform} binds no {action!r}; it binds {sorted(self.inputs)}")
        bound = self.inputs[action]
        return Step(name, bound.tool, dict(bound.args), check, volatile=self.volatile)


def expect(holds: bool, why: str) -> None:
    if not holds:
        raise StepFailed(why)


def words(reply: Reply) -> list[int]:
    """A `read_memory` reply as little-endian 16-bit words."""
    raw = bytes.fromhex(reply["hex"])
    return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw) - 1, 2)]


def word_is(name: str, value: int) -> Callable[[Reply, Run], str]:
    def check(reply: Reply, run: Run) -> str:
        got = words(reply)[0]
        expect(got == value, f"{name} holds {got}, not {value}")
        return f"{name} holds {value}"
    return check


def found(screen: str) -> Callable[[Reply, Run], str]:
    """`screen_map_find`'s check: the machine shows `screen`."""
    def check(reply: Reply, run: Run) -> str:
        expect(reply["matched"] is True and reply.get("screen") == screen,
               f"screen_map_find answered {reply.get('screen', 'no screen')}, not {screen}")
        named = ", ".join(c["name"] for c in reply["controls"])
        return f"the {screen} screen" + (f", its controls {named}" if named else "")
    return check


def arrived(ref: str) -> Callable[[Reply, Run], str]:
    """`run_to`'s check: it stopped at `ref`, the control having counted on the way."""
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "TARGET", f"run_to {ref}: verdict {reply['verdict']}")
        expect(reply["control_hits"] > 0, f"run_to {ref}: the control never fired")
        return f"stopped at {ref}"
    return check


def elapsed(what: str) -> Callable[[Reply, Run], str]:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}")
        return what
    return check


def map_load(name: str, shared: Path) -> Step:
    """The shared map, loaded from a copy in the run: the transcript names no install path."""
    def args(run: Run) -> dict[str, Any]:
        copy = run.dir / shared.name
        shutil.copyfile(shared, copy)
        return {"method": "load", "path": copy}

    def check(reply: Reply, run: Run) -> str:
        return f"{reply['screens']} screens and {reply['controls']} controls loaded"
    return Step(name, "screen_map_write", args, check)


def recorded(binding: Binding, milliseconds: int) -> Callable[[Reply, Run], str]:
    def check(reply: Reply, run: Run) -> str:
        expect(reply["verdict"] == "ELAPSED", f"verdict {reply['verdict']}")
        return (f"{binding.frames(milliseconds)} frames recorded, the first whole frames past "
                f"{milliseconds} ms")
    return check


def heard(reply: Reply, run: Run) -> str:
    first = reply["measures"][0]
    expect(first["silent"] is False, f"the recording is silent: {first}")
    return f"a sound, peaking at {first['peak_dbfs']} dBFS"


def exact(reference: Path) -> Callable[[Reply, Run], str]:
    def check(reply: Reply, run: Run) -> str:
        if reply["exact"] is not True:
            raise StepFailed(f"the recording differs from {reference.name}: {reply['class']}, "
                             f"{reply['snr_db']} dB")
        return f"the recording is {reference.name}, sample for sample"
    return check


def sound(binding: Binding, milliseconds: int, wav: str) -> list[Step]:
    """Record `milliseconds` into the run's `wav`, then hold it to the binding's reference."""
    run_path: Callable[[Run], Path] = lambda run: run.dir / wav  # noqa: E731
    in_run = {"path": "the run's own directory"}

    def record(run: Run) -> dict[str, Any]:
        run_path(run).unlink(missing_ok=True)  # the server writes no file over an existing one
        return {"frames": binding.frames(milliseconds), "dest": run_path(run)}

    measure: Args = lambda run: {"method": "measure", "path": run_path(run)}  # noqa: E731
    diff: Args = lambda run: {"method": "diff", "a": run_path(run),  # noqa: E731
                              "b": binding.sound, "align": False}
    return [Step("record", "audio_record", record, recorded(binding, milliseconds),
                 volatile=in_run),
            Step("heard", "audio_compare", measure, heard, volatile=in_run),
            Step("exact", "audio_compare", diff, exact(binding.sound),
                 highlight=("The recording is compared with the platform's reference with "
                            "alignment off: `exact` is true only when every sample is equal, so a "
                            "changed sound, a different mixer or a drifted start fails the run."))]
