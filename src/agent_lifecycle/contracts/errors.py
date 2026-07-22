"""Stable lifecycle error envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LifecycleError(RuntimeError):
    """Fail-closed error with a stable machine-readable code."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": "agent-lifecycle-error.v1",
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }
