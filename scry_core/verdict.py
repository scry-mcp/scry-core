"""What every instrument of this package answers when it could not produce a verdict, the
exception that says so, and the exit codes a run ends with, one spelling each for the probe, the
cap check, the live bench, the demo, the replay and the hook. A refusal raised as `Invalid`
survives `python -O`, which strips an `assert`.
"""

from __future__ import annotations

#: 0 every case passed (the hook: the commit may go), 1 a case failed (the hook: blocked), 3
#: nothing here is a verdict.
EXIT_PASS, EXIT_FAIL, EXIT_INVALID = 0, 1, 3


class Invalid(Exception):
    """The instrument could not produce a verdict: nothing here is a PASS or a FAIL."""
