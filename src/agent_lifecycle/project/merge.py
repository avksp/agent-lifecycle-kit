"""Deterministic composition of project defaults with lifecycle authority."""

from __future__ import annotations

import copy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.project_profile_schemas import (
    EFFECTIVE_PROJECT_PROFILE_SCHEMA,
    PROJECT_PROFILE_STAGES,
)
from agent_lifecycle.policy.risk_execution import RISK_TIERS, resolve_risk_tier
from agent_lifecycle.project.profile import (
    normalize_project_profile,
    project_profile_digest,
    validate_stage_settings,
)


def build_effective_project_profile(
    profile: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    project_root: Any = None,
) -> dict[str, Any]:
    """Return a bounded effective profile without changing any source artifact."""

    normalized = normalize_project_profile(profile, project_root=project_root)
    if lock is not None and plan is None:
        raise LifecycleError("project-profile-lock-without-plan", "a profile lock requires a plan")
    authority = _plan_authority(plan, lock)
    overrides = _validate_cli_overrides(cli_overrides or {}, project_root=project_root)

    defaults = {
        "defaultAdapter": normalized.get("defaultAdapter"),
        "defaultMode": normalized["defaultMode"],
        "defaultRisk": normalized["defaultRisk"],
    }
    defaults.update({key: value for key, value in overrides.items() if key != "stages"})
    defaults["defaultRisk"] = _resolve_risk(defaults["defaultRisk"], authority)

    stages = copy.deepcopy(normalized.get("stages", {}))
    for stage, settings in overrides.get("stages", {}).items():
        stages.setdefault(stage, {}).update(settings)
    for stage, settings in stages.items():
        settings["risk"] = _resolve_risk(settings.get("risk", defaults["defaultRisk"]), authority)
        if authority["reviewMeshRequired"] and settings.get("reviewMesh", "off") == "off":
            raise LifecycleError(
                "project-profile-review-downgrade",
                "project profile cannot disable a review mesh required by the frozen plan",
                {"stage": stage},
            )

    body = {
        "schemaVersion": EFFECTIVE_PROJECT_PROFILE_SCHEMA,
        "status": "PASS",
        "profileId": normalized["profileId"],
        "sourceProfileDigest": project_profile_digest(normalized),
        **defaults,
        "policies": copy.deepcopy(normalized.get("policies", {})),
        "stages": stages,
        "authority": authority,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "effectiveProfileDigest": canonical_digest(body)}


def merge_project_profile(
    profile: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    project_root: Any = None,
) -> dict[str, Any]:
    """Alias for callers that describe composition as a merge operation."""

    return build_effective_project_profile(
        profile,
        plan=plan,
        lock=lock,
        cli_overrides=cli_overrides,
        project_root=project_root,
    )


def require_profile_digest(profile: dict[str, Any], expected_digest: str) -> dict[str, Any]:
    """Reject changed profile input when a frozen run binds its digest."""

    actual = profile.get("effectiveProfileDigest") or project_profile_digest(profile)
    if actual != expected_digest:
        raise LifecycleError(
            "project-profile-drift",
            "project profile digest does not match the bound frozen run",
            {"expectedDigest": expected_digest, "actualDigest": actual},
        )
    return profile


def _plan_authority(plan: dict[str, Any] | None, lock: dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {
            "planBound": False,
            "planStatus": None,
            "planDigest": None,
            "lockDigest": None,
            "planTier": None,
            "qualityFloor": None,
            "writeScope": [],
            "requiredGates": [],
            "reviewMeshRequired": False,
            "mandatoryStages": list(PROJECT_PROFILE_STAGES),
        }
    if not isinstance(plan, dict):
        raise LifecycleError("project-profile-plan-invalid", "plan authority must be an object")
    plan_status = plan.get("status")
    if lock is not None:
        if not isinstance(lock, dict):
            raise LifecycleError("project-profile-lock-invalid", "plan lock must be an object")
        if plan_status != "FROZEN":
            raise LifecycleError("project-profile-plan-not-frozen", "a bound profile requires a frozen plan")
        plan_digest = canonical_digest(plan)
        lock_digest = lock.get("manifestHash")
        if lock_digest != plan_digest:
            raise LifecycleError(
                "project-profile-lock-mismatch",
                "plan lock does not match the plan authority",
                {"expected": plan_digest, "actual": lock_digest},
            )
    else:
        if plan.get("status") == "FROZEN":
            raise LifecycleError("project-profile-lock-required", "a frozen plan requires its lock for profile composition")
        plan_digest = canonical_digest(plan)
        lock_digest = None
    tier = _first_string(
        plan.get("tierResolution", {}).get("tier") if isinstance(plan.get("tierResolution"), dict) else None,
        plan.get("tier"),
    )
    if tier is not None and tier not in RISK_TIERS:
        raise LifecycleError("project-profile-plan-tier-invalid", "plan tier is unsupported", {"tier": tier})
    review_mesh = plan.get("reviewMesh")
    review_required = bool(plan.get("reviewMeshRequired")) or (
        isinstance(review_mesh, dict) and review_mesh.get("required") is True
    )
    return {
        "planBound": True,
        "planStatus": plan_status,
        "planDigest": plan_digest,
        "lockDigest": lock_digest,
        "planTier": tier,
        "qualityFloor": _first_string(plan.get("qualityFloor"), plan.get("minimumQualityFloor")),
        "writeScope": _write_scope(plan),
        "requiredGates": _string_list(plan.get("requiredGates", [])),
        "reviewMeshRequired": review_required,
        "mandatoryStages": list(PROJECT_PROFILE_STAGES),
    }


def _validate_cli_overrides(overrides: dict[str, Any], *, project_root: Any) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        raise LifecycleError("project-profile-cli-overrides-invalid", "CLI overrides must be an object")
    allowed = {"defaultAdapter", "defaultMode", "defaultRisk", "stages"}
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        raise LifecycleError("project-profile-cli-field-unsupported", "unsupported CLI profile override", {"fields": unknown})
    checked = copy.deepcopy(overrides)
    if "defaultAdapter" in checked and checked["defaultAdapter"] is not None and not isinstance(checked["defaultAdapter"], str):
        raise LifecycleError("project-profile-adapter-invalid", "CLI defaultAdapter must be a string or null")
    if "defaultMode" in checked and checked["defaultMode"] not in {"auto", "research", "plan", "review", "implement"}:
        raise LifecycleError("project-profile-value-invalid", "CLI defaultMode is unsupported")
    if "defaultRisk" in checked and checked["defaultRisk"] not in {"auto", "S0", "S1", "S2"}:
        raise LifecycleError("project-profile-value-invalid", "CLI defaultRisk is unsupported")
    stages = checked.get("stages", {})
    if not isinstance(stages, dict):
        raise LifecycleError("project-profile-stages-invalid", "CLI stages must be an object")
    for stage, settings in stages.items():
        checked["stages"][stage] = validate_stage_settings(stage, settings, project_root=project_root)
    return checked


def _resolve_risk(requested: str, authority: dict[str, Any]) -> str:
    plan_tier = authority.get("planTier")
    if plan_tier is None:
        return requested if requested != "auto" else "S0"
    try:
        return resolve_risk_tier(plan_tier, requested)
    except LifecycleError as exc:
        if exc.code == "risk-tier-downgrade":
            raise LifecycleError(exc.code, f"project profile risk downgrade: {exc.message}", exc.details) from exc
        raise


def _write_scope(plan: dict[str, Any]) -> list[str]:
    scope: set[str] = set()
    workstreams = plan.get("workstreams", [])
    if isinstance(workstreams, list):
        for workstream in workstreams:
            if isinstance(workstream, dict) and isinstance(workstream.get("writes"), list):
                scope.update(item for item in workstream["writes"] if isinstance(item, str) and item)
    return sorted(scope)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None
