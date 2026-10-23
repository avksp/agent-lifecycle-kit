"""Validated durable closing record passed between recovery checks.

Construction alone grants no authority; recovery performs the database and
financial joins before exposing balances.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClosingPolicyRecord:
    body: dict[str, Any]
    effect: dict[str, Any]
    candidate: dict[str, Any]
    proposal: dict[str, Any]
    effect_digest: str
