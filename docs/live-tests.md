# Tests that need a real screen or a real emulator

What the opt-in tests open, how a run shows that it took nobody's focus, and how independent
jobs run in parallel. The module docstrings named here are the contracts; this page says when
to reach for each.

## Tests that open windows

They carry the `window` marker, and a plain `pytest` leaves them out through `addopts`.

| Marker | What it opens or moves | Needs |
|---|---|---|
| `window` | stand-in windows, and your Space | macOS: `SCRY_FOCUS_CONTROL=1` and `swiftc`. Windows: an interactive desktop |

```sh
SCRY_FOCUS_CONTROL=1 uv run pytest -m window --no-cov   # macOS
uv run pytest -m window --no-cov                        # Windows
```

- The marker, the `behind_a_fullscreen_app` fixture and the `on_the_desk` decorator arrive with
  this package. A server adds only `not window` to its own `addopts`
  (`-m 'not live and not window'`).
- `--no-cov` because a partial run cannot check a coverage floor that belongs to the whole
  repository. A `-m` on the command line replaces the one in `addopts`.
- A run with `-o addopts=` drops the deselection, so it names `-m window` itself. It also keeps
  `-p pytester`, which that override drops and the shared test classes need.
- Check first that nobody else is using the screen: another run on the same machine loses its
  screen and keyboard the same way.

On Windows these tests run on an interactive desktop. What looks like a defect in the code under
test is usually the desktop: `WindowsHost.activate` says what it takes to bring a window to the
front.

## The focus watch

Tests against a real emulator can run beside somebody working, and then they show that they
took nobody's focus. A run does three things:

1. It wraps itself in `scry_core.focus_watch.FocusWatch`.
2. It runs `scry_core.focus_gate.control` the same way: one start that must be seen in front,
   one that must not, and a Space moved and put back.
3. It ends with `focus_gate.verdict`, which answers OK, FAIL or BLOCKED.

The start in front and the Space move take your screen and keyboard. They run only with
`SCRY_FOCUS_CONTROL=1`, on a machine nobody is using. Without the variable those two cases are
BLOCKED and the verdict says it is unproven; a stolen focus still fails it.

Run while somebody works, the control still takes their screen and keyboard, and its start in
front fails anyway: macOS keeps the focus with the application in use.

The watch is two programs:

- A listener, built with `swiftc`, prints every application the window server brings to the
  front, with its process id. However short the stay, it leaves a line.
- A sampler reads each display's Space at its instants.

So a green focus case means this: no application of the run came to the front, and no sample
found a Space moved. It does not mean that no window took the keyboard inside the application
already in front. Nor does it mean that no Space was moved and put back between two samples.

Where nothing can listen (no `swiftc`, not macOS) the verdict is never green. Neither program
sends an Apple event, so the watch needs no Automation permission; the control's Space move
does. When the person at the machine says they lost focus, that is the fact, and the listener's
record names who came to the front and when.

## Parallel jobs

A test script whose jobs share nothing runs them as child processes through
`scry_core.live_pool.run_pool`. Each child writes its summary with `write_summary`, and
`default_workers()` keeps half the host free.

A child that dies at import, because its environment holds another `scry_core` than its
parent's, reads as failed cases. `live_pool`'s docstring says how to see it and what to set.
