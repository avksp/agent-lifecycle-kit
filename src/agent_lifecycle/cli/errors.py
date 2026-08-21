"""Safe exception mapping for the root command-line boundary."""

from __future__ import annotations

import json
from typing import Final

from agent_lifecycle.contracts import LifecycleError

_SAFE_ERRORS: Final[tuple[tuple[type[Exception], str, str], ...]] = (
    (json.JSONDecodeError, "cli-invalid-json", "CLI input contains invalid JSON"),
    (UnicodeError, "cli-invalid-encoding", "CLI input uses an unsupported encoding"),
    (RecursionError, "cli-json-depth-exceeded", "CLI input exceeds the supported JSON nesting depth"),
    (OSError, "cli-io-error", "CLI input or output could not be read or written"),
)


def to_lifecycle_error(exc: Exception) -> LifecycleError:
    """Convert an unexpected root-CLI exception without exposing local data."""

    if isinstance(exc, LifecycleError):
        return exc
    for exception_type, code, message in _SAFE_ERRORS:
        if isinstance(exc, exception_type):
            return LifecycleError(code, message)
    return LifecycleError("cli-unexpected-error", "CLI operation failed")


__all__ = ["to_lifecycle_error"]
