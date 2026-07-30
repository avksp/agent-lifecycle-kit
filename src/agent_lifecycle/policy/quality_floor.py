"""Quality-floor helpers for lifecycle policy proposals."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.metrics import DEFAULT_MODE_LIMITS

MODES = tuple(DEFAULT_MODE_LIMITS)
PROTECTED_TASK_SHAPES = {"adapter", "architecture", "release"}
PROTECTED_RISKS = {"security", "contracts", "adapter", "architecture", "release", "migration", "dataMigration", "S2"}


def mode_index(mode: str | None) -> int:
    return MODES.index(mode) if mode in MODES else MODES.index("standard")


def is_downgrade(before: str | None, after: str | None) -> bool:
    return mode_index(after) < mode_index(before)


def protected_work(recommendation: dict[str, Any], risk_flags: list[str] | None = None) -> bool:
    task_shape = recommendation.get("taskShape")
    quality_floor = recommendation.get("qualityFloor")
    risks = set(risk_flags or [])
    if isinstance(task_shape, str) and task_shape in PROTECTED_TASK_SHAPES:
        return True
    if isinstance(quality_floor, str) and quality_floor in {"strict", "release"}:
        return True
    return bool(risks.intersection(PROTECTED_RISKS))
