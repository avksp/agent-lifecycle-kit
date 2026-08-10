"""Quality-preserving composition of existing execution policy decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.policy.adaptive_lifecycle import (
    build_adaptive_lifecycle_decision,
    small_model_packet_eligibility,
    validate_adaptive_lifecycle_decision,
)
from agent_lifecycle.policy.quality_floor import mode_index
from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile
from agent_lifecycle.review_mesh.recommendation import recommend_review_mesh_for_plan_manifest

EXECUTION_STRATEGY_SCHEMA = "agent-execution-strategy.v1"
EXECUTION_STRATEGY_VALIDATION_SCHEMA = "agent-execution-strategy-validation.v1"
DEFERRED_STRATEGY_STATUS = "DEFERRED_UNTIL_FREEZE"


def resolve_execution_strategy(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    task_id: str,
    adapter_id: str,
    adapter_host: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    requested_risk: str,
    risk_policy: dict[str, Any],
    routing_profile: dict[str, Any],
    baseline_profile: dict[str, Any],
    host_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve one read-only strategy from existing authorities."""

    lock_validation = verify_plan_lock(manifest, lock)
    if state.get("stateRevision") != expected_revision:
        raise LifecycleError(
            "strategy-state-revision-mismatch",
            "workflow state revision does not match --expected-revision",
            {"expected": expected_revision, "actual": state.get("stateRevision")},
        )
    risk = derive_risk_execution_profile(
        manifest=manifest,
        state=state,
        task_id=task_id,
        adapter_id=adapter_id,
        adapter_host=adapter_host,
        operation_id=operation_id,
        source_revision=source_revision,
        requested_risk=requested_risk,
        risk_policy=risk_policy,
        routing_profile=routing_profile,
        baseline_profile=baseline_profile,
        host_profile=host_profile,
    )
    adaptive = _adaptive_decision(manifest, state, task_id, risk, baseline_profile)
    adaptive_validation = validate_adaptive_lifecycle_decision(adaptive)
    if adaptive_validation["status"] != "PASS" or adaptive_validation["decisionStatus"] != "PASS":
        raise LifecycleError(
            "strategy-adaptive-decision-invalid",
            "adaptive lifecycle decision is invalid",
            {"validation": adaptive_validation},
        )
    compact = small_model_packet_eligibility(adaptive)
    review = recommend_review_mesh_for_plan_manifest(manifest)
    packet = _packet_decision(risk, compact)
    route = risk["modelRoute"]
    quality = risk["qualityFloorDecision"]
    body = {
        "schemaVersion": EXECUTION_STRATEGY_SCHEMA,
        "status": "PASS",
        "lineage": {
            "runId": state["runId"],
            "packageId": risk["packageId"],
            "planRevision": risk["planRevision"],
            "planDigest": risk["planDigest"],
            "lockDigest": canonical_digest(lock),
            "lockManifestHash": lock_validation["manifestHash"],
            "taskId": task_id,
            "operationId": operation_id,
            "stateRevision": expected_revision,
            "sourceRevision": source_revision,
            "adapterId": adapter_id,
        },
        "quality": {
            "resolvedRiskTier": risk["resolvedRiskTier"],
            "qualityFloor": quality["qualityFloor"],
            "selectedMode": adaptive["selectedMode"],
            "qualityFloorPreserved": adaptive["qualityFloorPreserved"],
            "protectedS2": risk["resolvedRiskTier"] == "S2",
        },
        "phaseRoutes": _phase_routes(route, review),
        "packet": packet,
        "reviewMesh": {
            "recommendedMode": review["recommendedMode"],
            "phaseCoverage": list(review["phaseCoverage"]),
            "requiredReviewers": review["requiredReviewers"],
            "skipRationale": review.get("skipRationale"),
            "advisoryOnly": True,
            "recommendationDigest": review["recommendationDigest"],
        },
        "resourceCaps": dict(risk["resourceCaps"]),
        "usageEvidence": dict(risk["usageEvidence"]),
        "sourceDecisionDigests": {
            "riskProfile": risk["profileDigest"],
            "qualityFloor": quality["floorDigest"],
            "modelRoute": route["decisionDigest"],
            "adaptiveDecision": adaptive["decisionDigest"],
            "compactEligibility": compact["eligibilityDigest"],
            "reviewMeshRecommendation": review["recommendationDigest"],
        },
        "authority": {
            "advisoryOnly": True,
            "automaticAdoptionEligible": False,
            "canFreezePlan": False,
            "canStartHost": False,
            "canAuthorizeImplementation": False,
            "canAcceptTask": False,
            "canFinalizeRun": False,
        },
        "blockers": [],
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    strategy = {**body, "strategyDigest": canonical_digest(body)}
    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError("execution-strategy-invalid", "resolved execution strategy is invalid", {"validation": validation})
    return strategy


def execution_strategy_summary(strategy: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded projection suitable for the public start receipt."""

    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError("execution-strategy-invalid", "cannot summarize an invalid strategy", {"validation": validation})
    implementation = next(
        (item for item in strategy["phaseRoutes"] if item.get("phase") == "task-implementation"),
        {},
    )
    return {
        "status": strategy["status"],
        "resolvedRiskTier": strategy["quality"]["resolvedRiskTier"],
        "qualityFloor": strategy["quality"]["qualityFloor"],
        "implementationModelClass": implementation.get("modelClass"),
        "packetMode": strategy["packet"]["mode"],
        "reviewMode": strategy["reviewMesh"]["recommendedMode"],
        "resourceCaps": dict(strategy["resourceCaps"]),
        "advisoryOnly": True,
        "strategyDigest": strategy["strategyDigest"],
    }


def deferred_execution_strategy_summary(*, reason: str = "frozen-plan-required") -> dict[str, Any]:
    """Describe why raw intake has no executable strategy yet."""

    return {
        "status": DEFERRED_STRATEGY_STATUS,
        "reason": reason,
        "resolvedRiskTier": None,
        "qualityFloor": None,
        "implementationModelClass": None,
        "packetMode": None,
        "reviewMode": None,
        "resourceCaps": None,
        "advisoryOnly": True,
        "automaticAdoptionEligible": False,
    }


def validate_execution_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    """Validate quality, authority and digest invariants for a strategy."""

    blockers: list[dict[str, Any]] = []
    if strategy.get("schemaVersion") != EXECUTION_STRATEGY_SCHEMA:
        blockers.append({"code": "strategy-schema-invalid"})
    if strategy.get("status") not in {"PASS", "BLOCKED"}:
        blockers.append({"code": "strategy-status-invalid"})
    quality = strategy.get("quality") if isinstance(strategy.get("quality"), dict) else {}
    floor = quality.get("qualityFloor")
    selected = quality.get("selectedMode")
    preserved = floor in {"light", "standard", "strict", "release"} and selected in {
        "light",
        "standard",
        "strict",
        "release",
    } and mode_index(selected) >= mode_index(floor)
    if not preserved or quality.get("qualityFloorPreserved") is not True:
        blockers.append({"code": "strategy-quality-floor-lowered"})
    packet = strategy.get("packet") if isinstance(strategy.get("packet"), dict) else {}
    if packet.get("mode") == "COMPACT" and (
        quality.get("resolvedRiskTier") == "S2" or floor in {"strict", "release"}
    ):
        blockers.append({"code": "strategy-protected-compact-route"})
    authority = strategy.get("authority") if isinstance(strategy.get("authority"), dict) else {}
    for field in (
        "automaticAdoptionEligible",
        "canFreezePlan",
        "canStartHost",
        "canAuthorizeImplementation",
        "canAcceptTask",
        "canFinalizeRun",
    ):
        if authority.get(field) is not False:
            blockers.append({"code": "strategy-authority-escalation", "field": field})
    for field in ("modelCallsStarted", "hostLaunchStarted", "productionPromotionClaimed"):
        if strategy.get(field) is not False:
            blockers.append({"code": "strategy-side-effect-claim", "field": field})
    expected_digest = canonical_digest({key: value for key, value in strategy.items() if key != "strategyDigest"})
    if strategy.get("strategyDigest") != expected_digest:
        blockers.append({"code": "strategy-digest-mismatch"})
    body = {
        "schemaVersion": EXECUTION_STRATEGY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "strategyStatus": strategy.get("status") if strategy.get("status") in {"PASS", "BLOCKED"} else "BLOCKED",
        "qualityFloorPreserved": preserved,
        "blockers": blockers,
        "strategyDigest": strategy.get("strategyDigest") if isinstance(strategy.get("strategyDigest"), str) else None,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _adaptive_decision(
    manifest: dict[str, Any],
    state: dict[str, Any],
    task_id: str,
    risk: dict[str, Any],
    baseline_profile: dict[str, Any],
) -> dict[str, Any]:
    task_state = next(
        (item for item in state.get("tasks", []) if isinstance(item, dict) and item.get("id") == task_id),
        {},
    )
    request = {
        "schemaVersion": "agent-adaptive-lifecycle-policy-request.v1",
        "requestId": f"strategy:{state['runId']}:{task_id}",
        "taskShape": risk["qualityFloorDecision"]["taskShape"],
        "sddTier": risk["resolvedRiskTier"],
        "riskFlags": _active_risks(manifest),
        "requiredEvidence": [],
        "priorAttempts": _attempt_count(task_state),
        "contextTokens": 0,
        "resourceCaps": dict(risk["resourceCaps"]),
        "failureSignals": {},
        "budgetMode": "local",
        "currentMode": risk["qualityFloorDecision"]["qualityFloor"],
        "automaticSelectionEnabled": False,
    }
    return build_adaptive_lifecycle_decision(request, baseline_profile)


def _packet_decision(risk: dict[str, Any], eligibility: dict[str, Any]) -> dict[str, Any]:
    route = risk["modelRoute"]
    protected = (
        risk["resolvedRiskTier"] == "S2"
        or risk["qualityFloorDecision"]["qualityFloor"] in {"strict", "release"}
        or route.get("criticalReview") is True
    )
    compact = eligibility.get("smallModelPacketEligible") is True and not protected
    return {
        "mode": "COMPACT" if compact else "FULL",
        "compactEligible": compact,
        "targetContextWindow": route["targetContextWindow"],
        "eligibilityDigest": eligibility["eligibilityDigest"],
        "authorityPreserved": True,
        "reason": "eligible-non-protected-work" if compact else "quality-or-eligibility-requires-full-packet",
    }


def _phase_routes(route: dict[str, Any], review: dict[str, Any]) -> list[dict[str, Any]]:
    hints = list(review.get("providerNeutralModelClassHints", []))
    review_class = hints[0] if hints else None
    return [
        {
            "phase": "structural-validation",
            "modelClass": "no-model",
            "authority": "deterministic-gates",
            "advisoryOnly": False,
        },
        {
            "phase": "task-implementation",
            "modelClass": route["modelClass"],
            "allowedFallbackModelClasses": list(route["allowedFallbackModelClasses"]),
            "authority": "agent-lifecycle-model-route-decision.v1",
            "decisionDigest": route["decisionDigest"],
            "advisoryOnly": False,
        },
        {
            "phase": "implementation-audit",
            "modelClass": review_class,
            "authority": "agent-review-mesh-recommendation.v1",
            "decisionDigest": review["recommendationDigest"],
            "advisoryOnly": True,
        },
        {
            "phase": "final-audit",
            "modelClass": review_class,
            "authority": "agent-review-mesh-recommendation.v1",
            "decisionDigest": review["recommendationDigest"],
            "advisoryOnly": True,
        },
    ]


def _active_risks(manifest: dict[str, Any]) -> list[str]:
    specification = manifest.get("specification") if isinstance(manifest.get("specification"), dict) else {}
    request = specification.get("tierResolutionRequest") if isinstance(specification.get("tierResolutionRequest"), dict) else {}
    flags = request.get("riskFlags") if isinstance(request.get("riskFlags"), dict) else {}
    return sorted(str(key) for key, value in flags.items() if value)


def _attempt_count(task_state: dict[str, Any]) -> int:
    value = task_state.get("attemptCount")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    attempts = task_state.get("attempts")
    return len(attempts) if isinstance(attempts, list) else 0
