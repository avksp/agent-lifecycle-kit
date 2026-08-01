"""Quality-floor helpers for lifecycle policy proposals and decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.metrics.costs import DEFAULT_MODE_LIMITS

MODES = tuple(DEFAULT_MODE_LIMITS)
PROTECTED_TASK_SHAPES = {"adapter", "architecture", "release"}
PROTECTED_RISKS = {"security", "contracts", "adapter", "architecture", "release", "migration", "dataMigration", "S2"}
QUALITY_FLOOR_DECISION_SCHEMA = "agent-lifecycle-quality-floor-decision.v1"
REQUIRED_EVIDENCE_FLOORS = {
    "adapter-promotion": "release",
    "production-promotion": "release",
    "release-proof": "release",
    "bug-forensics": "strict",
    "cross-check": "strict",
    "proof-integrity": "strict",
    "sandbox": "strict",
    "security-review": "strict",
}


def mode_index(mode: str | None) -> int:
    return MODES.index(mode) if mode in MODES else MODES.index("standard")


def is_downgrade(before: str | None, after: str | None) -> bool:
    return mode_index(after) < mode_index(before)


def max_mode(*modes: str | None) -> str:
    valid = [mode for mode in modes if mode in MODES]
    if not valid:
        return "standard"
    return max(valid, key=mode_index)


def quality_floor_mode(
    *,
    task_shape: str,
    baseline_profile: dict[str, Any],
    sdd_tier: str | None = None,
    risk_flags: list[str] | dict[str, Any] | None = None,
    required_evidence: list[str] | None = None,
) -> str:
    """Return the minimum safe lifecycle mode for the given neutral inputs."""

    return resolve_quality_floor(
        task_shape=task_shape,
        baseline_profile=baseline_profile,
        sdd_tier=sdd_tier,
        risk_flags=risk_flags,
        required_evidence=required_evidence,
    )["qualityFloor"]


def resolve_quality_floor(
    *,
    task_shape: str,
    baseline_profile: dict[str, Any],
    sdd_tier: str | None = None,
    risk_flags: list[str] | dict[str, Any] | None = None,
    required_evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic quality-floor receipt from baseline policy inputs."""

    blockers: list[dict[str, Any]] = []
    reasons: list[str] = []
    risks = _risk_list(risk_flags)
    evidence = sorted({item for item in (required_evidence or []) if isinstance(item, str) and item})
    shapes = baseline_profile.get("taskShapes") if isinstance(baseline_profile, dict) else None
    shape_config = shapes.get(task_shape) if isinstance(shapes, dict) and isinstance(shapes.get(task_shape), dict) else None
    floor = "standard"
    min_mode: str | None = None
    if shape_config is None:
        blockers.append({"code": "quality-floor-task-shape-missing", "taskShape": task_shape})
        reasons.append("task-shape-missing")
    else:
        min_mode = shape_config.get("minMode") if isinstance(shape_config.get("minMode"), str) else None
        if min_mode not in MODES:
            blockers.append({"code": "quality-floor-min-mode-invalid", "taskShape": task_shape, "mode": min_mode})
            reasons.append("task-shape-min-mode-invalid")
        else:
            floor = min_mode
            reasons.append(f"task-shape-min-mode-{floor}")
        if shape_config.get("highRisk") is True:
            floor = max_mode(floor, "strict")
            reasons.append("task-shape-high-risk")

    risk_floors = baseline_profile.get("riskFloors") if isinstance(baseline_profile, dict) else None
    if not isinstance(risk_floors, dict):
        blockers.append({"code": "quality-floor-risk-floors-invalid"})
        risk_floors = {}
    for risk in [*risks, sdd_tier]:
        if isinstance(risk, str) and risk in risk_floors:
            risk_floor = risk_floors[risk]
            if risk_floor in MODES:
                floor = max_mode(floor, str(risk_floor))
                reasons.append(f"risk-floor-{risk}-{risk_floor}")
            else:
                blockers.append({"code": "quality-floor-risk-mode-invalid", "risk": risk, "mode": risk_floor})
    for item in evidence:
        evidence_floor = REQUIRED_EVIDENCE_FLOORS.get(item)
        if evidence_floor is not None:
            floor = max_mode(floor, evidence_floor)
            reasons.append(f"evidence-floor-{item}-{evidence_floor}")

    body = {
        "schemaVersion": QUALITY_FLOOR_DECISION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "taskShape": task_shape,
        "sddTier": sdd_tier,
        "riskFlags": risks,
        "requiredEvidence": evidence,
        "minMode": min_mode,
        "qualityFloor": floor,
        "reasonCodes": reasons,
        "blockers": blockers,
        "baselineProfileDigest": canonical_digest(baseline_profile),
        "productionPromotionClaimed": False,
    }
    return {**body, "floorDigest": canonical_digest(body)}


def protected_work(recommendation: dict[str, Any], risk_flags: list[str] | None = None) -> bool:
    task_shape = recommendation.get("taskShape")
    quality_floor = recommendation.get("qualityFloor")
    risks = set(risk_flags or [])
    if isinstance(task_shape, str) and task_shape in PROTECTED_TASK_SHAPES:
        return True
    if isinstance(quality_floor, str) and quality_floor in {"strict", "release"}:
        return True
    return bool(risks.intersection(PROTECTED_RISKS))


def _risk_list(risk_flags: list[str] | dict[str, Any] | None) -> list[str]:
    if isinstance(risk_flags, dict):
        return sorted(str(key) for key, value in risk_flags.items() if value)
    if isinstance(risk_flags, list):
        return sorted({item for item in risk_flags if isinstance(item, str) and item})
    return []
