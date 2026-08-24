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
from agent_lifecycle.policy.thread_bridge import merge_thread_bridge_policy
from agent_lifecycle.project.profile import (
    normalize_project_profile,
    profile_field_is_explicit,
    project_profile_digest,
    validate_stage_settings,
)

_PROVENANCE_SOURCES = ("defaults", "preset", "profile", "command", "plan")


def build_effective_project_profile(
    profile: dict[str, Any],
    *,
    preset: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    project_root: Any = None,
) -> dict[str, Any]:
    """Return a bounded effective profile without changing any source artifact."""

    preset_metadata = None
    source_profile = copy.deepcopy(profile)
    if preset is not None:
        from agent_lifecycle.project.presets import merge_preset_defaults

        profile = merge_preset_defaults(profile, preset, project_root=project_root)
        preset_metadata = {
            "presetId": preset.get("presetId"),
            "presetVersion": preset.get("presetVersion"),
            "reviewMesh": preset.get("reviewMesh"),
            "implementationAuthority": preset.get("implementationAuthority"),
            "presetDigest": preset.get("presetDigest"),
        }
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
    if preset is not None and authority.get("planTier") is not None and not profile_field_is_explicit(source_profile, "defaultRisk"):
        defaults["defaultRisk"] = "auto"
    defaults.update({key: value for key, value in overrides.items() if key != "stages"})
    defaults["defaultRisk"] = _resolve_risk(defaults["defaultRisk"], authority)
    thread_bridge = merge_thread_bridge_policy(normalized.get("threadBridge"), authority.get("threadBridgePolicy"))
    principles = copy.deepcopy(normalized.get("principles")) if normalized.get("principles") else None

    stages = copy.deepcopy(normalized.get("stages", {}))
    for stage, settings in overrides.get("stages", {}).items():
        stages.setdefault(stage, {}).update(settings)
    explicit_stage_risks = {
        stage: isinstance(settings, dict) and "risk" in settings
        for stage, settings in source_profile.get("stages", {}).items()
    }
    for stage, settings in stages.items():
        if preset is not None and authority.get("planTier") is not None and not explicit_stage_risks.get(stage, False):
            settings["risk"] = defaults["defaultRisk"]
        settings["risk"] = _resolve_risk(settings.get("risk", defaults["defaultRisk"]), authority)
        if authority["reviewMeshRequired"] and settings.get("reviewMesh", "off") == "off":
            raise LifecycleError(
                "project-profile-review-downgrade",
                "project profile cannot disable a review mesh required by the frozen plan",
                {"stage": stage},
            )

    field_provenance = _build_field_provenance(
        source_profile=source_profile,
        preset=preset,
        normalized=normalized,
        effective_defaults=defaults,
        stages=stages,
        authority=authority,
        overrides=overrides,
        thread_bridge=thread_bridge,
        principles=principles,
    )

    body = {
        "schemaVersion": EFFECTIVE_PROJECT_PROFILE_SCHEMA,
        "status": "PASS",
        "profileId": normalized["profileId"],
        "sourceProfileDigest": project_profile_digest(normalized),
        **defaults,
        "policies": copy.deepcopy(normalized.get("policies", {})),
        "stages": stages,
        "principles": principles,
        "principlesDigest": principles.get("digest") if principles else None,
        "threadBridge": thread_bridge,
        "preset": preset_metadata,
        "authority": authority,
        "fieldProvenance": field_provenance,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    return {**body, "effectiveProfileDigest": canonical_digest(body)}


def _build_field_provenance(
    *,
    source_profile: dict[str, Any],
    preset: dict[str, Any] | None,
    normalized: dict[str, Any],
    effective_defaults: dict[str, Any],
    stages: dict[str, Any],
    authority: dict[str, Any],
    overrides: dict[str, Any],
    thread_bridge: dict[str, Any],
    principles: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Explain effective values without turning provenance into authority."""

    provenance: list[dict[str, Any]] = []
    source_stages = source_profile.get("stages", {})
    preset_stages = preset.get("stages", {}) if isinstance(preset, dict) else {}
    source_policies = source_profile.get("policies", {})
    preset_policies = preset.get("policies", {}) if isinstance(preset, dict) else {}

    def add(
        field: str,
        value: Any,
        candidates: list[tuple[str, Any]],
        *,
        plan_constraint: dict[str, Any] | None = None,
        winning_source: str | None = None,
    ) -> None:
        available = [source for source, candidate in candidates if candidate is not _MISSING]
        winner = winning_source or (available[-1] if available else "defaults")
        overridden = [source for source in available if source != winner]
        provenance.append(
            {
                "field": field,
                "value": value,
                "winningSource": winner,
                "overriddenSources": overridden,
                "planConstraint": plan_constraint,
                "enforceability": "UNAVAILABLE",
            }
        )

    for field in ("defaultAdapter", "defaultMode", "defaultRisk"):
        profile_explicit = profile_field_is_explicit(source_profile, field)
        preset_value = preset.get(field, _MISSING) if isinstance(preset, dict) else _MISSING
        profile_value = source_profile.get(field, _MISSING) if profile_explicit else _MISSING
        command_value = overrides.get(field, _MISSING)
        candidates: list[tuple[str, Any]] = [
            ("defaults", {"defaultAdapter": None, "defaultMode": "auto", "defaultRisk": "auto"}[field]),
            ("preset", preset_value),
            ("profile", profile_value),
            ("command", command_value),
        ]
        plan_constraint = _risk_constraint(authority) if field == "defaultRisk" else None
        requested = _last_candidate(candidates)
        winner = None
        if field == "defaultRisk" and plan_constraint is not None and requested in {None, "auto"}:
            candidates.append(("plan", effective_defaults[field]))
            winner = "plan"
        add(field, effective_defaults[field], candidates, plan_constraint=plan_constraint, winning_source=winner)

    for key, value in sorted(source_policies.items() if isinstance(source_policies, dict) else []):
        candidates = [("defaults", _MISSING), ("preset", preset_policies.get(key, _MISSING)), ("profile", value)]
        add(f"policies.{key}", normalized.get("policies", {}).get(key), candidates)
    if isinstance(principles, dict):
        add(
            "principles",
            principles,
            [("defaults", _MISSING), ("profile", source_profile.get("principles", _MISSING))],
        )
    add(
        "threadBridge",
        thread_bridge,
        [
            ("defaults", _MISSING),
            ("preset", _MISSING if preset is None else preset.get("threadBridge", _MISSING)),
            ("profile", source_profile.get("threadBridge", _MISSING)),
            ("plan", authority.get("threadBridgePolicy", _MISSING)),
        ],
        plan_constraint=_thread_bridge_constraint(authority),
    )

    for stage, settings in sorted(stages.items()):
        profile_settings = source_stages.get(stage, {}) if isinstance(source_stages, dict) else {}
        preset_settings = preset_stages.get(stage, {}) if isinstance(preset_stages, dict) else {}
        for key, value in sorted(settings.items()):
            profile_value = profile_settings.get(key, _MISSING) if isinstance(profile_settings, dict) else _MISSING
            preset_value = preset_settings.get(key, _MISSING) if isinstance(preset_settings, dict) else _MISSING
            command_settings = overrides.get("stages", {}).get(stage, {})
            command_value = command_settings.get(key, _MISSING) if isinstance(command_settings, dict) else _MISSING
            candidates = [("defaults", _MISSING), ("preset", preset_value), ("profile", profile_value), ("command", command_value)]
            plan_constraint = _risk_constraint(authority) if key == "risk" else None
            requested = _last_candidate(candidates)
            winner = None
            if key == "risk" and plan_constraint is not None and requested in {None, "auto"}:
                candidates.append(("plan", value))
                winner = "plan"
            if key == "risk" and requested is _MISSING:
                default_risk = next(
                    (entry for entry in provenance if entry["field"] == "defaultRisk"), None
                )
                if isinstance(default_risk, dict):
                    winner = default_risk["winningSource"]
                    candidates.append((winner, value))
            add(
                f"stages.{stage}.{key}",
                value,
                candidates,
                plan_constraint=plan_constraint,
                winning_source=winner,
            )
    return provenance


class _Missing:
    pass


_MISSING = _Missing()


def _last_candidate(candidates: list[tuple[str, Any]]) -> Any:
    for _source, value in reversed(candidates):
        if value is not _MISSING:
            return value
    return _MISSING


def _risk_constraint(authority: dict[str, Any]) -> dict[str, Any] | None:
    tier = authority.get("planTier")
    if not isinstance(tier, str) or not tier:
        return None
    return {"type": "minimum-risk", "tier": tier}


def _thread_bridge_constraint(authority: dict[str, Any]) -> dict[str, Any] | None:
    policy = authority.get("threadBridgePolicy")
    if not isinstance(policy, dict):
        return None
    return {"type": "non-widening-thread-bridge", "policyDigest": canonical_digest(policy)}


def merge_project_profile(
    profile: dict[str, Any],
    *,
    preset: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    project_root: Any = None,
) -> dict[str, Any]:
    """Alias for callers that describe composition as a merge operation."""

    return build_effective_project_profile(
        profile,
        preset=preset,
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
            "threadBridgePolicy": None,
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
        "threadBridgePolicy": _thread_bridge_policy(plan),
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


def _thread_bridge_policy(plan: dict[str, Any]) -> dict[str, Any] | None:
    candidate = plan.get("threadBridgePolicy")
    if not isinstance(candidate, dict):
        candidate = plan.get("threadBridge")
    if not isinstance(candidate, dict):
        specification = plan.get("specification")
        candidate = specification.get("threadBridge") if isinstance(specification, dict) else None
    return copy.deepcopy(candidate) if isinstance(candidate, dict) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None
