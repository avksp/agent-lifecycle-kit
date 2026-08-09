"""Deterministic risk-tier execution profiles for frozen workflow tasks."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.policy.quality_floor import resolve_quality_floor

RISK_EXECUTION_POLICY_SCHEMA = "agent-risk-execution-policy.v1"
RISK_EXECUTION_PROFILE_SCHEMA = "agent-risk-execution-profile.v1"
RISK_TIERS = ("S0", "S1", "S2")
RISK_REQUESTS = ("auto", *RISK_TIERS)


def validate_risk_execution_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate the versioned local policy that supplies non-token caps."""

    blockers: list[dict[str, Any]] = []
    if policy.get("schemaVersion") != RISK_EXECUTION_POLICY_SCHEMA:
        blockers.append({"code": "risk-policy-schema-unsupported"})
    tiers = policy.get("tiers")
    if not isinstance(tiers, dict):
        blockers.append({"code": "risk-policy-tiers-missing"})
        tiers = {}
    for tier in RISK_TIERS:
        config = tiers.get(tier)
        if not isinstance(config, dict):
            blockers.append({"code": "risk-policy-tier-missing", "tier": tier})
            continue
        if not isinstance(config.get("budgetClass"), str) or not config["budgetClass"]:
            blockers.append({"code": "risk-policy-budget-class-invalid", "tier": tier})
        for field in ("maxInvocations", "maxWallSeconds"):
            value = config.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                blockers.append({"code": "risk-policy-cap-invalid", "tier": tier, "field": field})
    if policy.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "risk-policy-production-claim"})
    body = {
        "schemaVersion": "agent-risk-execution-policy-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "policyDigest": canonical_digest(policy),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def resolve_risk_tier(plan_tier: str, requested_risk: str) -> str:
    """Resolve auto or a tightening override without allowing downgrade."""

    if plan_tier not in RISK_TIERS:
        raise LifecycleError("risk-plan-tier-invalid", "frozen plan tier is unsupported", {"tier": plan_tier})
    if requested_risk not in RISK_REQUESTS:
        raise LifecycleError("risk-request-invalid", "requested risk is unsupported", {"risk": requested_risk})
    resolved = plan_tier if requested_risk == "auto" else requested_risk
    if RISK_TIERS.index(resolved) < RISK_TIERS.index(plan_tier):
        raise LifecycleError(
            "risk-tier-downgrade",
            "requested risk cannot be lower than the frozen plan tier",
            {"planTier": plan_tier, "requestedRisk": requested_risk},
        )
    return resolved


def derive_risk_execution_profile(
    *,
    manifest: dict[str, Any],
    state: dict[str, Any],
    task_id: str,
    adapter_id: str,
    adapter_host: str,
    operation_id: str,
    source_revision: str,
    requested_risk: str,
    risk_policy: dict[str, Any],
    routing_profile: dict[str, Any],
    baseline_profile: dict[str, Any],
    host_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a provider-neutral profile without changing workflow state."""

    # Keep model-routing imports lazy: its resolver imports quality-floor policy,
    # so importing it while the policy package is initializing creates a cycle.
    from agent_lifecycle.model_routing import (
        resolve_model_route,
        validate_host_model_profile,
        validate_model_routing_profile,
    )

    _require_frozen_manifest(manifest)
    _require_state_lineage(manifest, state, source_revision=source_revision)
    _require_task(manifest, state, task_id)
    policy_validation = validate_risk_execution_policy(risk_policy)
    if policy_validation["status"] != "PASS":
        raise LifecycleError("risk-policy-invalid", "risk execution policy is invalid", {"validation": policy_validation})
    validate_model_routing_profile(routing_profile)

    plan_tier = _plan_tier(manifest)
    resolved_tier = resolve_risk_tier(plan_tier, requested_risk)
    host_validation = None
    if host_profile is not None:
        host_validation = validate_host_model_profile(host_profile)
        if host_validation["host"] != adapter_host:
            raise LifecycleError(
                "risk-host-profile-mismatch",
                "host model profile does not match the adapter descriptor host",
                {"expected": adapter_host, "actual": host_validation["host"]},
            )
    if resolved_tier in {"S1", "S2"} and host_validation is None:
        raise LifecycleError(
            "risk-host-profile-required",
            "managed S1/S2 execution requires a host model profile",
            {"riskTier": resolved_tier},
        )

    risk_flags = _risk_flags(manifest)
    quality_floor = resolve_quality_floor(
        task_shape=_task_shape(manifest),
        baseline_profile=baseline_profile,
        sdd_tier=resolved_tier,
        risk_flags=risk_flags,
    )
    if quality_floor["status"] != "PASS":
        raise LifecycleError("risk-quality-floor-failed", "quality floor could not be resolved", {"decision": quality_floor})
    tier_policy = risk_policy["tiers"][resolved_tier]
    route = resolve_model_route(
        {
            "schemaVersion": "agent-lifecycle-model-route-request.v1",
            "operationId": operation_id,
            "phase": "task-implementation",
            "sddTier": resolved_tier,
            "riskFlags": risk_flags,
            "capabilityRequirements": [],
            "targetContextWindow": "8k",
            "routingPolicy": "balanced",
            "budgetClass": tier_policy["budgetClass"],
            "lifecycleMode": quality_floor["qualityFloor"],
            "qualityFloor": quality_floor["qualityFloor"],
        },
        routing_profile,
        host_profile=host_profile,
    )
    caps = {
        "maxBillableTokens": int(route["maxBillableTokens"]),
        "maxInvocations": int(tier_policy["maxInvocations"]),
        "maxWallSeconds": int(tier_policy["maxWallSeconds"]),
    }
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    body = {
        "schemaVersion": RISK_EXECUTION_PROFILE_SCHEMA,
        "status": "PASS",
        "requestedRisk": requested_risk,
        "planRiskTier": plan_tier,
        "resolvedRiskTier": resolved_tier,
        "adapterId": adapter_id,
        "operationId": operation_id,
        "runId": state["runId"],
        "packageId": package.get("id"),
        "planRevision": manifest["planRevision"],
        "planDigest": canonical_digest(manifest),
        "taskId": task_id,
        "sourceRevision": source_revision,
        "qualityFloorDecision": quality_floor,
        "modelRoute": route,
        "resourceCaps": caps,
        "usageEvidence": {
            "required": resolved_tier in {"S1", "S2"} or route.get("requiresUsageReceipt") is True,
            "hostAttestationRequired": resolved_tier in {"S1", "S2"},
            "requiredMetrics": ["billableTokens", "invocations", "wallSeconds"],
            "estimatesAccepted": False,
        },
        "policyDigest": policy_validation["policyDigest"],
        "hostProfileDigest": host_validation["profileDigest"] if host_validation else None,
        "blockers": [],
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def _require_frozen_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != "agent-plan-manifest.v1" or manifest.get("status") != "FROZEN":
        raise LifecycleError("risk-frozen-plan-required", "risk execution profile requires a FROZEN plan")


def _plan_tier(manifest: dict[str, Any]) -> str:
    specification = manifest.get("specification")
    tier = specification.get("tier") if isinstance(specification, dict) else None
    if not isinstance(tier, str):
        raise LifecycleError("risk-plan-tier-invalid", "frozen plan tier is missing")
    return tier


def _risk_flags(manifest: dict[str, Any]) -> dict[str, bool]:
    specification = manifest.get("specification") if isinstance(manifest.get("specification"), dict) else {}
    request = specification.get("tierResolutionRequest") if isinstance(specification.get("tierResolutionRequest"), dict) else {}
    flags = request.get("riskFlags") if isinstance(request.get("riskFlags"), dict) else {}
    return {str(key): bool(value) for key, value in flags.items()}


def _task_shape(manifest: dict[str, Any]) -> str:
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    if isinstance(manifest.get("releaseTarget"), dict) or str(package.get("id", "")).startswith("release-"):
        return "release"
    hints = " ".join(
        str(item).lower()
        for item in (
            manifest.get("specification", {}).get("tierResolutionRequest", {}).get("capabilityHints", [])
            if isinstance(manifest.get("specification"), dict)
            else []
        )
    )
    if "adapter" in hints:
        return "adapter"
    if "architecture" in hints:
        return "architecture"
    return "feature"


def _require_state_lineage(manifest: dict[str, Any], state: dict[str, Any], *, source_revision: str) -> None:
    package = manifest.get("package") if isinstance(manifest.get("package"), dict) else {}
    expected = {
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "planDigest": canonical_digest(manifest),
        "sourceRevision": source_revision,
    }
    for field, value in expected.items():
        if state.get(field) != value:
            raise LifecycleError("risk-state-lineage-mismatch", f"workflow state {field} mismatch")
    if not isinstance(state.get("runId"), str) or not state["runId"]:
        raise LifecycleError("risk-state-lineage-mismatch", "workflow state runId is missing")


def _require_task(manifest: dict[str, Any], state: dict[str, Any], task_id: str) -> None:
    workstreams = manifest.get("workstreams") if isinstance(manifest.get("workstreams"), list) else []
    state_tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
    if task_id not in {item.get("id") for item in workstreams if isinstance(item, dict)}:
        raise LifecycleError("risk-task-missing", "task is not declared by the frozen plan", {"taskId": task_id})
    if task_id not in {item.get("id") for item in state_tasks if isinstance(item, dict)}:
        raise LifecycleError("risk-task-missing", "task is not present in workflow state", {"taskId": task_id})
