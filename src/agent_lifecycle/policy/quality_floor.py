"""Policy protection rules with shared, compatible quality-floor exports."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.quality_modes import (
    MODES,
    is_downgrade,
    max_mode,
    mode_index,
    quality_floor_mode,
    resolve_quality_floor,
)
from agent_lifecycle.contracts.quality_modes import (
    QUALITY_FLOOR_DECISION_SCHEMA as QUALITY_FLOOR_DECISION_SCHEMA,
)
from agent_lifecycle.contracts.quality_modes import (
    REQUIRED_EVIDENCE_FLOORS as REQUIRED_EVIDENCE_FLOORS,
)

__all__ = [
    "MODES",
    "is_downgrade",
    "max_mode",
    "mode_index",
    "protected_work",
    "quality_floor_mode",
    "resolve_quality_floor",
]

PROTECTED_TASK_SHAPES = {"adapter", "architecture", "release"}
PROTECTED_RISKS = {"security", "contracts", "adapter", "architecture", "release", "migration", "dataMigration", "S2"}


def protected_work(recommendation: dict[str, Any], risk_flags: list[str] | None = None) -> bool:
    task_shape = recommendation.get("taskShape")
    quality_floor = recommendation.get("qualityFloor")
    risks = set(risk_flags or [])
    if isinstance(task_shape, str) and task_shape in PROTECTED_TASK_SHAPES:
        return True
    if isinstance(quality_floor, str) and quality_floor in {"strict", "release"}:
        return True
    return bool(risks.intersection(PROTECTED_RISKS))
