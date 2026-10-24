"""UTC timestamp contract shared by closing state and accounting readers."""

from datetime import UTC, datetime
from typing import Any

from .errors import LifecycleError


def closing_instant(value: Any, label: str) -> datetime:
    if type(value) is not str:
        raise LifecycleError("closing-context-invalid", f"{label} must be an aware UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LifecycleError("closing-context-invalid", f"{label} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise LifecycleError("closing-context-invalid", f"{label} must be UTC")
    return parsed
