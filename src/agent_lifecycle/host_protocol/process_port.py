"""Narrow process port used by host-protocol qualification decisions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class QualificationRunner(Protocol):
    """Run one explicitly supplied, bounded host command."""

    def __call__(self, argv: list[str], timeout_seconds: float) -> dict[str, Any]: ...


QualificationRunnerFactory = Callable[[dict[str, Any], Any], QualificationRunner]

__all__ = ["QualificationRunner", "QualificationRunnerFactory"]
