"""Quality-preserving composition of existing execution policy decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.host_protocol.capabilities import validate_capability_manifest
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
PROJECT_PROFILE_IDENTITY_SCHEMA = "agent-project-profile-identity.v1"
PROJECT_PROFILE_ABSENT_DIGEST = canonical_digest({"schemaVersion": PROJECT_PROFILE_IDENTITY_SCHEMA, "status": "ABSENT"})
POLICY_INPUT_IDENTITY_SCHEMA = "agent-execution-strategy-policy-input.v1"


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
    project_profile_digest: str | None = None,
    descriptor: dict[str, Any] | None = None,
    capability_manifest: dict[str, Any] | None = None,
    target_attempt: int | None = None,
    descriptor_path: str | None = None,
    capability_manifest_path: str | None = None,
    project_profile_path: str | None = None,
) -> dict[str, Any]:
    """Resolve one read-only strategy from existing authorities."""

    lock_validation = verify_plan_lock(manifest, lock)
    if state.get("stateRevision") != expected_revision:
        raise LifecycleError(
            "strategy-state-revision-mismatch",
            "workflow state revision does not match --expected-revision",
            {"expected": expected_revision, "actual": state.get("stateRevision")},
        )
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError(
            "strategy-source-revision-mismatch",
            "workflow source revision does not match the strategy input",
        )
    task_state = _task_state(state, task_id)
    adoption = _adoption_binding(
        task_state=task_state,
        target_attempt=target_attempt,
        adapter_id=adapter_id,
        adapter_host=adapter_host,
        descriptor=descriptor,
        capability_manifest=capability_manifest,
        project_profile_digest=project_profile_digest,
        descriptor_path=descriptor_path,
        capability_manifest_path=capability_manifest_path,
        project_profile_path=project_profile_path,
        requested_risk=requested_risk,
        risk_policy=risk_policy,
        routing_profile=routing_profile,
        baseline_profile=baseline_profile,
        host_profile=host_profile,
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
    body = _strategy_body(
        state=state,
        lock=lock,
        lock_validation=lock_validation,
        task_id=task_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        adapter_id=adapter_id,
        adapter_host=adapter_host,
        project_profile_digest=project_profile_digest,
        risk=risk,
        adaptive=adaptive,
        compact=compact,
        review=review,
        packet=packet,
        adoption=adoption,
    )
    strategy = {**body, "strategyDigest": canonical_digest(body)}
    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "execution-strategy-invalid", "resolved execution strategy is invalid", {"validation": validation}
        )
    return strategy


def _strategy_body(
    *,
    state: dict[str, Any],
    lock: dict[str, Any],
    lock_validation: dict[str, Any],
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    adapter_id: str,
    adapter_host: str,
    project_profile_digest: str | None,
    risk: dict[str, Any],
    adaptive: dict[str, Any],
    compact: dict[str, Any],
    review: dict[str, Any],
    packet: dict[str, Any],
    adoption: dict[str, Any],
) -> dict[str, Any]:
    """Build the canonical strategy body from already validated decisions."""

    route = risk["modelRoute"]
    quality = risk["qualityFloorDecision"]
    return {
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
            "adapterHost": adapter_host,
            "targetAttempt": adoption["targetAttempt"],
            "descriptorDigest": adoption["descriptorDigest"],
            "capabilityManifestDigest": adoption["capabilityManifestDigest"],
            "projectProfileIdentity": dict(adoption["projectProfileIdentity"]),
            "policyInputsDigest": adoption["policyInputsDigest"],
        },
        "quality": {
            "resolvedRiskTier": risk["resolvedRiskTier"],
            "qualityFloor": quality["qualityFloor"],
            "selectedMode": adaptive["selectedMode"],
            "qualityFloorPreserved": adaptive["qualityFloorPreserved"],
            "protectedS2": risk["resolvedRiskTier"] == "S2",
        },
        "phaseRoutes": _phase_routes(route, review),
        "modelRoute": dict(route),
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
        "projectProfileDigest": project_profile_digest,
        "adoptionBinding": adoption,
        "authority": {
            "advisoryOnly": True,
            "automaticAdoptionEligible": adoption["status"] == "AVAILABLE",
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


def execution_strategy_summary(strategy: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded projection suitable for the public start receipt."""

    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "execution-strategy-invalid", "cannot summarize an invalid strategy", {"validation": validation}
        )
    implementation: dict[str, Any] = next(
        (item for item in strategy["phaseRoutes"] if item.get("phase") == "task-implementation"),
        {},
    )
    summary = {
        "status": strategy["status"],
        "resolvedRiskTier": strategy["quality"]["resolvedRiskTier"],
        "qualityFloor": strategy["quality"]["qualityFloor"],
        "implementationModelClass": implementation.get("modelClass"),
        "packetMode": strategy["packet"]["mode"],
        "reviewMode": strategy["reviewMesh"]["recommendedMode"],
        "resourceCaps": dict(strategy["resourceCaps"]),
        "advisoryOnly": True,
        "automaticAdoptionEligible": strategy["authority"]["automaticAdoptionEligible"],
        "strategyDigest": strategy["strategyDigest"],
    }
    binding = strategy.get("adoptionBinding")
    if isinstance(binding, dict):
        summary["adoptionBinding"] = {
            "status": binding.get("status"),
            "targetAttempt": binding.get("targetAttempt"),
            "descriptorDigest": binding.get("descriptorDigest"),
            "capabilityManifestDigest": binding.get("capabilityManifestDigest"),
            "projectProfileIdentity": binding.get("projectProfileIdentity"),
            "blockers": list(binding.get("blockers", [])) if isinstance(binding.get("blockers"), list) else [],
        }
    if strategy.get("projectProfileDigest") is not None:
        summary["projectProfileDigest"] = strategy["projectProfileDigest"]
    return summary


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
    quality = _object(strategy.get("quality"))
    floor = quality.get("qualityFloor")
    selected = quality.get("selectedMode")
    preserved = (
        floor in {"light", "standard", "strict", "release"}
        and selected
        in {
            "light",
            "standard",
            "strict",
            "release",
        }
        and mode_index(selected) >= mode_index(floor)
    )
    if not preserved or quality.get("qualityFloorPreserved") is not True:
        blockers.append({"code": "strategy-quality-floor-lowered"})
    packet = _object(strategy.get("packet"))
    if packet.get("mode") == "COMPACT" and (quality.get("resolvedRiskTier") == "S2" or floor in {"strict", "release"}):
        blockers.append({"code": "strategy-protected-compact-route"})
    authority = _object(strategy.get("authority"))
    automatic_adoption = authority.get("automaticAdoptionEligible")
    if not isinstance(automatic_adoption, bool):
        blockers.append({"code": "strategy-adoption-eligibility-invalid"})
    for field in (
        "canFreezePlan",
        "canStartHost",
        "canAuthorizeImplementation",
        "canAcceptTask",
        "canFinalizeRun",
    ):
        if authority.get(field) is not False:
            blockers.append({"code": "strategy-authority-escalation", "field": field})
    if authority.get("advisoryOnly") is not True:
        blockers.append({"code": "strategy-advisory-boundary-invalid"})
    if automatic_adoption is True:
        blockers.extend(_automatic_adoption_blockers(strategy))
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


def _adoption_binding(
    *,
    task_state: dict[str, Any],
    target_attempt: int | None,
    adapter_id: str,
    adapter_host: str,
    descriptor: dict[str, Any] | None,
    capability_manifest: dict[str, Any] | None,
    project_profile_digest: str | None,
    descriptor_path: str | None,
    capability_manifest_path: str | None,
    project_profile_path: str | None,
    requested_risk: str,
    risk_policy: dict[str, Any],
    routing_profile: dict[str, Any],
    baseline_profile: dict[str, Any],
    host_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    project_identity = _project_profile_identity(project_profile_digest, project_profile_path)
    blockers: list[dict[str, Any]] = []
    current_attempt = _attempt_count(task_state)
    if not isinstance(target_attempt, int) or isinstance(target_attempt, bool) or target_attempt <= current_attempt:
        blockers.append(
            {
                "code": "strategy-target-attempt-unavailable",
                "currentAttempt": current_attempt,
                "targetAttempt": target_attempt,
            }
        )
    descriptor_digest = canonical_digest(descriptor) if isinstance(descriptor, dict) else None
    capability_digest = canonical_digest(capability_manifest) if isinstance(capability_manifest, dict) else None
    descriptor_binding_path = _binding_path(descriptor_path, "adapter descriptor")
    capability_binding_path = _binding_path(capability_manifest_path, "capability manifest")
    policy_inputs: dict[str, Any] = {
        "requestedRisk": requested_risk,
        "riskPolicy": _policy_input_identity(risk_policy, name="riskPolicy", required=True),
        "routingProfile": _policy_input_identity(
            routing_profile,
            name="routingProfile",
            required=True,
        ),
        "baselineProfile": _policy_input_identity(
            baseline_profile,
            name="baselineProfile",
            required=True,
        ),
        "hostProfile": _policy_input_identity(
            host_profile,
            name="hostProfile",
            required=False,
        ),
    }
    capability_validation: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "blockers": [{"code": "strategy-capability-binding-unavailable"}],
    }
    if not isinstance(descriptor, dict) or not isinstance(capability_manifest, dict):
        blockers.append({"code": "strategy-capability-binding-unavailable"})
    else:
        capability_validation = validate_capability_manifest(capability_manifest, descriptor=descriptor)
        if descriptor.get("adapterId") != adapter_id or descriptor.get("host") != adapter_host:
            blockers.append(
                {
                    "code": "strategy-descriptor-identity-mismatch",
                    "expectedAdapterId": adapter_id,
                    "expectedHost": adapter_host,
                }
            )
        if capability_validation.get("status") != "PASS":
            blockers.append(
                {
                    "code": "strategy-capability-manifest-invalid",
                    "validationBlockers": list(capability_validation.get("blockers", [])),
                }
            )
    if descriptor_binding_path is None or capability_binding_path is None:
        blockers.append({"code": "strategy-capability-binding-path-unavailable"})
    for name in ("riskPolicy", "routingProfile", "baselineProfile"):
        if policy_inputs[name]["status"] != "PRESENT":
            blockers.append({"code": "strategy-policy-input-unavailable", "input": name})
    if policy_inputs["hostProfile"]["status"] == "UNAVAILABLE":
        blockers.append({"code": "strategy-policy-input-unavailable", "input": "hostProfile"})
    return {
        "status": "AVAILABLE" if not blockers else "UNAVAILABLE",
        "targetAttempt": target_attempt,
        "descriptorDigest": descriptor_digest,
        "descriptorPath": descriptor_binding_path,
        "capabilityManifestDigest": capability_digest,
        "capabilityManifestPath": capability_binding_path,
        "projectProfileIdentity": project_identity,
        "policyInputs": policy_inputs,
        "policyInputsDigest": canonical_digest(policy_inputs),
        "capabilityValidation": capability_validation,
        "blockers": blockers,
    }


def _project_profile_identity(project_profile_digest: str | None, project_profile_path: str | None) -> dict[str, Any]:
    path = _binding_path(project_profile_path, "project profile")
    if path is None:
        return {
            "schemaVersion": PROJECT_PROFILE_IDENTITY_SCHEMA,
            "status": "UNAVAILABLE",
            "digest": None,
            "path": None,
        }
    if project_profile_digest is None:
        return {
            "schemaVersion": PROJECT_PROFILE_IDENTITY_SCHEMA,
            "status": "ABSENT",
            "digest": PROJECT_PROFILE_ABSENT_DIGEST,
            "path": path,
        }
    if not _digest_string(project_profile_digest):
        raise LifecycleError(
            "strategy-project-profile-digest-invalid",
            "project profile digest must be a lowercase SHA-256 value",
        )
    return {
        "schemaVersion": PROJECT_PROFILE_IDENTITY_SCHEMA,
        "status": "PRESENT",
        "digest": project_profile_digest,
        "path": path,
    }


def _policy_input_identity(
    value: dict[str, Any] | None,
    *,
    name: str,
    required: bool,
) -> dict[str, Any]:
    if value is None:
        if required:
            return {
                "schemaVersion": POLICY_INPUT_IDENTITY_SCHEMA,
                "name": name,
                "status": "UNAVAILABLE",
                "digest": None,
            }
        body = {"schemaVersion": POLICY_INPUT_IDENTITY_SCHEMA, "name": name, "status": "ABSENT"}
        return {**body, "digest": canonical_digest(body)}
    return {
        "schemaVersion": POLICY_INPUT_IDENTITY_SCHEMA,
        "name": name,
        "status": "PRESENT",
        "digest": canonical_digest(value),
    }


def _automatic_adoption_blockers(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    binding = _object(strategy.get("adoptionBinding"))
    lineage = _object(strategy.get("lineage"))
    if binding.get("status") != "AVAILABLE" or binding.get("blockers") != []:
        blockers.append({"code": "strategy-auto-adoption-binding-incomplete"})
    target_attempt = binding.get("targetAttempt")
    if not isinstance(target_attempt, int) or isinstance(target_attempt, bool) or target_attempt < 1:
        blockers.append({"code": "strategy-auto-adoption-attempt-invalid"})
    for field in ("descriptorDigest", "capabilityManifestDigest"):
        if not _digest_string(binding.get(field)):
            blockers.append({"code": "strategy-auto-adoption-digest-invalid", "field": field})
        if lineage.get(field) != binding.get(field):
            blockers.append({"code": "strategy-auto-adoption-lineage-mismatch", "field": field})
    for field in ("descriptorPath", "capabilityManifestPath"):
        if not isinstance(binding.get(field), str) or not binding.get(field):
            blockers.append({"code": "strategy-auto-adoption-path-invalid", "field": field})
    if lineage.get("targetAttempt") != target_attempt:
        blockers.append({"code": "strategy-auto-adoption-lineage-mismatch", "field": "targetAttempt"})
    project_identity = binding.get("projectProfileIdentity")
    if not _valid_project_profile_identity(project_identity):
        blockers.append({"code": "strategy-auto-adoption-project-profile-invalid"})
    if lineage.get("projectProfileIdentity") != project_identity:
        blockers.append({"code": "strategy-auto-adoption-lineage-mismatch", "field": "projectProfileIdentity"})
    policy_inputs = binding.get("policyInputs")
    if not _valid_policy_inputs(policy_inputs):
        blockers.append({"code": "strategy-auto-adoption-policy-inputs-invalid"})
    policy_inputs_digest = canonical_digest(policy_inputs) if isinstance(policy_inputs, dict) else None
    if (
        binding.get("policyInputsDigest") != policy_inputs_digest
        or lineage.get("policyInputsDigest") != policy_inputs_digest
    ):
        blockers.append({"code": "strategy-auto-adoption-policy-inputs-lineage-mismatch"})
    capability_validation = binding.get("capabilityValidation")
    if not isinstance(capability_validation, dict) or capability_validation.get("status") != "PASS":
        blockers.append({"code": "strategy-auto-adoption-capability-unverified"})
    route = _object(strategy.get("modelRoute"))
    expected_route_digest = canonical_digest({key: value for key, value in route.items() if key != "decisionDigest"})
    if not route or route.get("decisionDigest") != expected_route_digest:
        blockers.append({"code": "strategy-auto-adoption-route-invalid"})
    source_digests = strategy.get("sourceDecisionDigests")
    if not isinstance(source_digests, dict) or source_digests.get("modelRoute") != route.get("decisionDigest"):
        blockers.append({"code": "strategy-auto-adoption-route-lineage-mismatch"})
    return blockers


def _valid_project_profile_identity(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schemaVersion") != PROJECT_PROFILE_IDENTITY_SCHEMA:
        return False
    status = value.get("status")
    digest = value.get("digest")
    if status == "ABSENT":
        return digest == PROJECT_PROFILE_ABSENT_DIGEST and isinstance(value.get("path"), str)
    return status == "PRESENT" and _digest_string(digest) and isinstance(value.get("path"), str)


def _valid_policy_inputs(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("requestedRisk") not in {"auto", "S0", "S1", "S2"}:
        return False
    for name in ("riskPolicy", "routingProfile", "baselineProfile"):
        if not _valid_policy_input_identity(value.get(name), name=name, optional=False):
            return False
    return _valid_policy_input_identity(value.get("hostProfile"), name="hostProfile", optional=True)


def _valid_policy_input_identity(value: Any, *, name: str, optional: bool) -> bool:
    if not isinstance(value, dict) or value.get("schemaVersion") != POLICY_INPUT_IDENTITY_SCHEMA:
        return False
    if value.get("name") != name:
        return False
    status = value.get("status")
    if status == "PRESENT":
        return _digest_string(value.get("digest"))
    if optional and status == "ABSENT":
        body = {"schemaVersion": POLICY_INPUT_IDENTITY_SCHEMA, "name": name, "status": "ABSENT"}
        return value.get("digest") == canonical_digest(body)
    return False


def _binding_path(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    return normalize_repo_path(value, label=label)


def _task_state(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    task = next(
        (item for item in state.get("tasks", []) if isinstance(item, dict) and item.get("id") == task_id),
        None,
    )
    if task is None:
        raise LifecycleError("strategy-task-missing", "strategy task is not present in workflow state")
    return task


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
    specification = _object(manifest.get("specification"))
    request = _object(specification.get("tierResolutionRequest"))
    flags = _object(request.get("riskFlags"))
    return sorted(str(key) for key, value in flags.items() if value)


def _attempt_count(task_state: dict[str, Any]) -> int:
    attempt = task_state.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0:
        return attempt
    value = task_state.get("attemptCount")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    attempts = task_state.get("attempts")
    return len(attempts) if isinstance(attempts, list) else 0


def _digest_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
