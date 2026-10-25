from __future__ import annotations

EXIT_PASS, EXIT_FAIL, EXIT_INVALID = 0, 1, 3


class Invalid(Exception):
    """No verdict."""
