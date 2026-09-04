"""Workflow-state and usage gates for derived risk execution profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.policy.quality_floor import MODES as QUALITY_MODES
from agent_lifecycle.policy.risk_execution import (
    RISK_EXECUTION_PROFILE_SCHEMA,
    RISK_REQUESTS,
    RISK_TIERS,
    resolve_risk_tier,
)
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.model_usage import validate_attempt_model_route


def load_task_risk_profile(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    profile_path: str,
    *,
    operation_id: str,
    source_revision: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate a profile before it receives task-start authority."""

    root = package_root(state_path, state)
    relative = normalize_repo_path(profile_path, label="risk execution profile")
    profile = read_json_object(root / relative, label="risk execution profile")
    validate_task_risk_profile(
        state,
        task,
        profile,
        operation_id=operation_id,
        source_revision=source_revision,
    )
    return profile, artifact_identity(root, relative, profile)


def validate_task_risk_profile(
    state: dict[str, Any],
    task: dict[str, Any],
    profile: dict[str, Any],
    *,
    operation_id: str,
    source_revision: str,
) -> dict[str, Any]:
    """Validate profile digest, workflow lineage, route and resource caps."""

    if profile.get("schemaVersion") != RISK_EXECUTION_PROFILE_SCHEMA or profile.get("status") != "PASS":
        raise LifecycleError("risk-profile-invalid", "risk execution profile must be a PASS v1 profile")
    expected_digest = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
    if profile.get("profileDigest") != expected_digest:
        raise LifecycleError("risk-profile-digest-mismatch", "risk execution profile digest mismatch")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "taskId": task.get("id"),
        "sourceRevision": source_revision,
        "operationId": operation_id,
    }
    for field, value in expected.items():
        if profile.get(field) != value:
            raise LifecycleError("risk-profile-lineage-mismatch", f"risk execution profile {field} mismatch")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("risk-profile-lineage-mismatch", "workflow state sourceRevision mismatch")
    plan_tier = profile.get("planRiskTier")
    resolved_tier = profile.get("resolvedRiskTier")
    if plan_tier not in RISK_TIERS or resolved_tier not in RISK_TIERS:
        raise LifecycleError("risk-profile-tier-invalid", "risk execution profile tier is unsupported")
    requested_risk = profile.get("requestedRisk")
    if requested_risk not in RISK_REQUESTS or resolve_risk_tier(plan_tier, requested_risk) != resolved_tier:
        raise LifecycleError(
            "risk-profile-tier-mismatch", "resolved risk tier does not match the requested and plan tiers"
        )
    adapter_id = profile.get("adapterId")
    if not isinstance(adapter_id, str) or not adapter_id:
        raise LifecycleError("risk-profile-adapter-invalid", "risk execution profile adapterId is required")
    task_adapter_id = task.get("adapterId")
    if isinstance(task_adapter_id, str) and task_adapter_id and task_adapter_id != adapter_id:
        raise LifecycleError("risk-profile-adapter-mismatch", "risk execution profile adapterId changed for the task")
    _validate_quality_floor(profile.get("qualityFloorDecision"), resolved_tier)
    route = profile.get("modelRoute")
    if not isinstance(route, dict) or not route:
        raise LifecycleError("risk-profile-route-missing", "risk execution profile modelRoute is required")
    if route.get("operationId") != operation_id or route.get("sddTier") != resolved_tier:
        raise LifecycleError("risk-profile-route-lineage-mismatch", "model route does not match risk profile lineage")
    route_digest = canonical_digest({key: value for key, value in route.items() if key != "decisionDigest"})
    if route.get("decisionDigest") != route_digest:
        raise LifecycleError("risk-profile-route-digest-mismatch", "model route decision digest mismatch")
    validate_attempt_model_route({"modelRoute": route})
    caps = profile.get("resourceCaps")
    if not isinstance(caps, dict):
        raise LifecycleError("risk-profile-caps-missing", "risk execution profile resourceCaps is required")
    for field in ("maxBillableTokens", "maxInvocations", "maxWallSeconds"):
        value = caps.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise LifecycleError("risk-profile-cap-invalid", f"resourceCaps.{field} must be a positive integer")
    if caps["maxBillableTokens"] != route.get("maxBillableTokens"):
        raise LifecycleError("risk-profile-token-cap-mismatch", "risk token cap must match the model route")
    _validate_usage_evidence(profile.get("usageEvidence"), resolved_tier)
    if not _digest_string(profile.get("policyDigest")):
        raise LifecycleError("risk-profile-policy-digest-invalid", "risk execution profile policyDigest is invalid")
    host_digest = profile.get("hostProfileDigest")
    if resolved_tier in {"S1", "S2"} and (
        not _digest_string(host_digest) or route.get("hostProfileDigest") != host_digest
    ):
        raise LifecycleError(
            "risk-profile-host-digest-mismatch", "risk execution host profile digest is missing or inconsistent"
        )
    if profile.get("blockers") != []:
        raise LifecycleError("risk-profile-blocked", "PASS risk execution profile must not contain blockers")
    for field in ("modelCallsStarted", "hostLaunchStarted", "productionPromotionClaimed"):
        if profile.get(field) is not False:
            raise LifecycleError("risk-profile-authority-invalid", f"risk execution profile {field} must be false")
    return {
        "schemaVersion": "agent-risk-execution-profile-validation.v1",
        "status": "PASS",
        "profileDigest": profile["profileDigest"],
        "routeDecisionDigest": route["decisionDigest"],
        "resolvedRiskTier": resolved_tier,
    }


def apply_task_risk_profile(task: dict[str, Any], profile: dict[str, Any], identity: dict[str, Any]) -> None:
    """Copy a validated profile and route into mutable task state."""

    task["riskExecutionProfile"] = {
        **identity,
        "profileDigest": profile["profileDigest"],
        "adapterId": profile["adapterId"],
        "resolvedRiskTier": profile["resolvedRiskTier"],
        "routeDecisionDigest": profile["modelRoute"]["decisionDigest"],
        "resourceCaps": dict(profile["resourceCaps"]),
        "usageEvidence": dict(profile["usageEvidence"]),
    }
    task["adapterId"] = profile["adapterId"]
    task["modelRoute"] = dict(profile["modelRoute"])


def clear_task_risk_profile(task: dict[str, Any]) -> None:
    """Remove prior risk authority when a later attempt uses legacy task-start."""

    profile = task.pop("riskExecutionProfile", None)
    task.pop("attemptRiskExecutionProfile", None)
    if not isinstance(profile, dict):
        return
    route = task.get("modelRoute")
    if isinstance(route, dict) and route.get("decisionDigest") == profile.get("routeDecisionDigest"):
        task.pop("modelRoute", None)
    attempt_route = task.get("attemptModelRoute")
    if isinstance(attempt_route, dict) and attempt_route.get("decisionDigest") == profile.get("routeDecisionDigest"):
        task.pop("attemptModelRoute", None)


def validate_attempt_risk_usage(task: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Enforce risk or adopted-strategy caps after usage validation succeeds."""

    profile = task.get("attemptRiskExecutionProfile")
    if not isinstance(profile, dict):
        profile = task.get("riskExecutionProfile")
    strategy = task.get("attemptExecutionStrategy")
    if not isinstance(strategy, dict):
        strategy = task.get("executionStrategy")
    binding = profile if isinstance(profile, dict) and profile else strategy
    if not isinstance(binding, dict) or not binding:
        return None
    usage = receipt.get("usage")
    if not isinstance(usage, dict):
        raise LifecycleError("risk-usage-missing", "risk-aware task requires usage metrics")
    invocations = usage.get("invocations")
    if not isinstance(invocations, int) or isinstance(invocations, bool) or invocations < 0:
        raise LifecycleError(
            "risk-usage-invocations-missing", "risk-aware usage requires a non-negative invocations metric"
        )
    caps = binding.get("resourceCaps")
    if not isinstance(caps, dict):
        raise LifecycleError("risk-profile-caps-missing", "attempt risk profile resourceCaps is missing")
    metrics = {
        "billableTokens": usage.get("billableTokens"),
        "invocations": invocations,
        "wallSeconds": usage.get("wallSeconds"),
    }
    cap_fields = {
        "billableTokens": "maxBillableTokens",
        "invocations": "maxInvocations",
        "wallSeconds": "maxWallSeconds",
    }
    checks: list[dict[str, Any]] = []
    for metric, value in metrics.items():
        limit = caps.get(cap_fields[metric])
        passed = isinstance(value, int) and not isinstance(value, bool) and isinstance(limit, int) and value <= limit
        checks.append(
            {"id": f"risk-cap-{metric}", "status": "PASS" if passed else "FAIL", "value": value, "limit": limit}
        )
    if any(item["status"] == "FAIL" for item in checks):
        raise LifecycleError("risk-usage-cap-exceeded", "risk-aware usage exceeded its bound caps", {"checks": checks})
    body = {
        "schemaVersion": "agent-risk-execution-usage-validation.v1",
        "status": "PASS",
        "profileDigest": binding.get("profileDigest"),
        "strategyDigest": binding.get("strategyDigest"),
        "checks": checks,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _validate_quality_floor(value: Any, resolved_tier: str) -> None:
    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise LifecycleError(
            "risk-profile-quality-floor-invalid", "risk execution quality floor must be a PASS decision"
        )
    if value.get("sddTier") != resolved_tier or value.get("qualityFloor") not in QUALITY_MODES:
        raise LifecycleError(
            "risk-profile-quality-floor-mismatch", "risk execution quality floor does not match the resolved tier"
        )
    expected = canonical_digest({key: item for key, item in value.items() if key != "floorDigest"})
    if value.get("floorDigest") != expected:
        raise LifecycleError(
            "risk-profile-quality-floor-digest-mismatch", "risk execution quality floor digest mismatch"
        )


def _validate_usage_evidence(value: Any, resolved_tier: str) -> None:
    if not isinstance(value, dict):
        raise LifecycleError("risk-profile-usage-evidence-invalid", "risk execution usageEvidence is required")
    metrics = value.get("requiredMetrics")
    if not isinstance(metrics, list) or set(metrics) != {"billableTokens", "invocations", "wallSeconds"}:
        raise LifecycleError("risk-profile-usage-evidence-invalid", "risk execution required metrics are incomplete")
    if value.get("estimatesAccepted") is not False:
        raise LifecycleError("risk-profile-usage-evidence-invalid", "risk execution cannot accept estimated usage")
    if resolved_tier in {"S1", "S2"} and (
        value.get("required") is not True or value.get("hostAttestationRequired") is not True
    ):
        raise LifecycleError("risk-profile-usage-evidence-invalid", "S1/S2 execution requires host-attested usage")


def _digest_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)
