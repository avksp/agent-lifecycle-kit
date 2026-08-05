"""Provider-neutral Review Mesh contract helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.quality.cross_check import (
    INDEPENDENCE_IDENTITY_FIELDS,
    MONEY_KEYS,
    RESOURCE_CAP_KEYS,
    USAGE_KEYS,
    build_cross_check_profile,
    build_cross_check_receipt,
    validate_cross_check_profile,
    validate_cross_check_receipt,
)

REVIEW_MESH_PROFILE_SCHEMA = "agent-review-mesh-profile.v1"
REVIEW_MESH_ASSIGNMENT_SCHEMA = "agent-review-mesh-assignment.v1"
REVIEW_MESH_RESULT_SCHEMA = "agent-review-mesh-result.v1"
REVIEW_MESH_SYNTHESIS_SCHEMA = "agent-review-mesh-synthesis.v1"
REVIEW_MESH_QUORUM_RECEIPT_SCHEMA = "agent-review-mesh-quorum-receipt.v1"
REVIEW_MESH_QUORUM_VALIDATION_SCHEMA = "agent-review-mesh-quorum-validation.v1"

RESULT_STATUSES = {"PASS", "FAIL", "SKIPPED"}
SYNTHESIS_STATUSES = {"PASS", "FAIL", "INCONCLUSIVE"}
PROVIDER_MODEL_NAME_KEYS = {
    "provider",
    "providerName",
    "providerModel",
    "providerModelName",
    "model",
    "modelName",
    "modelId",
    "accountName",
}


def build_review_mesh_profile(
    *,
    profile_id: str = "optional-review-mesh",
    modes: list[str] | None = None,
    default_mode: str = "leader-draft-multi-review",
    budget_cap: dict[str, int] | None = None,
    live_calls_allowed: bool = False,
    independence_required: bool = True,
    independence_dimensions: list[str] | None = None,
    reviewer_model_classes: list[str] | None = None,
) -> dict[str, Any]:
    """Build an optional Review Mesh profile from shared cross-check semantics."""

    selected_modes = _string_list(list(modes or REVIEW_MESH_MODE_IDS), "invalid-review-mesh-profile", label="modes")
    _validate_modes(selected_modes, "review-mesh-mode-invalid")
    if default_mode not in selected_modes:
        raise LifecycleError("invalid-review-mesh-profile", "defaultMode must be one of modes", {"defaultMode": default_mode})
    classes = _model_classes(reviewer_model_classes or ["strong-reasoning", "local-strong-review", "specialist-review"])
    cross_profile = build_cross_check_profile(
        profile_id=f"{profile_id}-cross-check",
        budget_cap=budget_cap,
        live_calls_allowed=live_calls_allowed,
        independence_required=independence_required,
        independence_dimensions=independence_dimensions,
    )
    body = {
        "schemaVersion": REVIEW_MESH_PROFILE_SCHEMA,
        "profileId": _required_string(profile_id, "invalid-review-mesh-profile", label="profileId"),
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "activationMode": "opt-in",
        "modes": selected_modes,
        "defaultMode": default_mode,
        "advisoryByDefault": True,
        "blockingRequiresPlanOptIn": True,
        "requiresExplicitActivation": True,
        "liveCallsAllowed": bool(live_calls_allowed),
        "budgetUnits": "tokens-and-resources",
        "budgetCap": dict(cross_profile["budgetCap"]),
        "independencePolicy": dict(cross_profile["independencePolicy"]),
        "reviewerModelClasses": classes,
        "crossCheckProfile": cross_profile,
        "concreteProviderModelNamesInPortableContract": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def validate_review_mesh_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-review-mesh-profile", "Review Mesh profile must be an object")
    if profile.get("schemaVersion") != REVIEW_MESH_PROFILE_SCHEMA:
        blockers.append({"code": "review-mesh-profile-schema-invalid"})
    _check_required_string(profile.get("profileId"), "review-mesh-profile-id-missing", blockers)
    if profile.get("status") != "OPTIONAL":
        blockers.append({"code": "review-mesh-profile-not-optional"})
    _check_const(profile, "enabledByDefault", False, "review-mesh-profile-default-enabled", blockers)
    _check_const(profile, "activationMode", "opt-in", "review-mesh-profile-not-opt-in", blockers)
    modes = profile.get("modes")
    if not isinstance(modes, list) or not modes:
        blockers.append({"code": "review-mesh-profile-modes-invalid"})
        modes = []
    else:
        unknown = sorted(set(modes).difference(REVIEW_MESH_MODE_IDS))
        if unknown:
            blockers.append({"code": "review-mesh-profile-mode-unknown", "modes": unknown})
    if profile.get("defaultMode") not in modes:
        blockers.append({"code": "review-mesh-profile-default-mode-invalid"})
    _check_const(profile, "advisoryByDefault", True, "review-mesh-profile-not-advisory", blockers)
    _check_const(profile, "blockingRequiresPlanOptIn", True, "review-mesh-profile-blocking-not-plan-gated", blockers)
    _check_const(profile, "requiresExplicitActivation", True, "review-mesh-profile-activation-not-explicit", blockers)
    if not isinstance(profile.get("liveCallsAllowed"), bool):
        blockers.append({"code": "review-mesh-profile-live-calls-invalid"})
    if profile.get("budgetUnits") != "tokens-and-resources":
        blockers.append({"code": "review-mesh-profile-budget-units-invalid"})
    _validate_resource_cap(profile.get("budgetCap"), blockers, prefix="review-mesh-profile")
    _validate_model_classes(profile.get("reviewerModelClasses"), blockers)
    cross_profile = profile.get("crossCheckProfile")
    if not isinstance(cross_profile, dict):
        blockers.append({"code": "review-mesh-cross-check-profile-invalid"})
        cross_validation: dict[str, Any] | None = None
    else:
        cross_validation = validate_cross_check_profile(cross_profile)
        if cross_validation["status"] != "PASS":
            blockers.append({"code": "review-mesh-cross-check-profile-invalid", "validation": cross_validation})
        if profile.get("budgetCap") != cross_profile.get("budgetCap"):
            blockers.append({"code": "review-mesh-budget-cap-not-cross-check"})
        if profile.get("independencePolicy") != cross_profile.get("independencePolicy"):
            blockers.append({"code": "review-mesh-independence-not-cross-check"})
    if profile.get("concreteProviderModelNamesInPortableContract") is not False:
        blockers.append({"code": "review-mesh-provider-model-names-in-core"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-production-claim"})
    blockers.extend(_money_key_blockers(profile))
    blockers.extend(_provider_model_name_blockers(profile))
    expected_digest = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
    if profile.get("profileDigest") != expected_digest:
        blockers.append({"code": "review-mesh-profile-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "profileId": profile.get("profileId") if isinstance(profile.get("profileId"), str) else None,
        "defaultMode": profile.get("defaultMode") if isinstance(profile.get("defaultMode"), str) else None,
        "crossCheckProfileStatus": cross_validation.get("status") if isinstance(cross_validation, dict) else None,
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_review_mesh_assignment(
    *,
    profile: dict[str, Any],
    assignment_id: str,
    subject: dict[str, Any],
    reviewer: dict[str, Any],
    mode: str | None = None,
    phase: str = "plan-review",
    blocking: bool = False,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a reviewer assignment without launching the reviewer."""

    require_review_mesh_profile_pass(validate_review_mesh_profile(profile))
    selected_mode = mode or profile["defaultMode"]
    if selected_mode not in profile["modes"]:
        raise LifecycleError("invalid-review-mesh-assignment", "mode is not allowed by profile", {"mode": selected_mode})
    body = {
        "schemaVersion": REVIEW_MESH_ASSIGNMENT_SCHEMA,
        "assignmentId": _required_string(assignment_id, "invalid-review-mesh-assignment", label="assignmentId"),
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "mode": selected_mode,
        "phase": _required_string(phase, "invalid-review-mesh-assignment", label="phase"),
        "subject": dict(subject),
        "reviewer": dict(reviewer),
        "budgetCap": dict(profile["budgetCap"]),
        "blocking": bool(blocking),
        "advisory": not blocking,
        "evidenceIds": _string_list(evidence_ids or [], "invalid-review-mesh-assignment", label="evidenceIds", allow_empty=True),
        "productionPromotionClaimed": False,
    }
    return {**body, "assignmentDigest": canonical_digest(body)}


def validate_review_mesh_assignment(assignment: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(assignment, dict):
        raise LifecycleError("invalid-review-mesh-assignment", "Review Mesh assignment must be an object")
    if assignment.get("schemaVersion") != REVIEW_MESH_ASSIGNMENT_SCHEMA:
        blockers.append({"code": "review-mesh-assignment-schema-invalid"})
    _check_required_string(assignment.get("assignmentId"), "review-mesh-assignment-id-missing", blockers)
    _check_digest(assignment.get("profileDigest"), "review-mesh-assignment-profile-digest-invalid", blockers)
    if assignment.get("mode") not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-assignment-mode-invalid", "mode": assignment.get("mode")})
    _check_required_string(assignment.get("phase"), "review-mesh-assignment-phase-missing", blockers)
    subject = _object_or_blocker(assignment.get("subject"), "review-mesh-assignment-subject-invalid", blockers)
    reviewer = _object_or_blocker(assignment.get("reviewer"), "review-mesh-assignment-reviewer-invalid", blockers)
    _validate_resource_cap(assignment.get("budgetCap"), blockers, prefix="review-mesh-assignment")
    if not isinstance(assignment.get("blocking"), bool):
        blockers.append({"code": "review-mesh-assignment-blocking-invalid"})
    if assignment.get("advisory") is not (assignment.get("blocking") is not True):
        blockers.append({"code": "review-mesh-assignment-advisory-mismatch"})
    if assignment.get("blocking") is True and not _subject_has_blocking_opt_in(subject):
        blockers.append({"code": "review-mesh-blocking-without-plan-opt-in"})
    _check_string_list(assignment.get("evidenceIds", []), "review-mesh-assignment-evidence-ids-invalid", blockers, allow_empty=True)
    if assignment.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-assignment-production-claim"})
    blockers.extend(_money_key_blockers(assignment))
    blockers.extend(_provider_model_name_blockers(assignment))
    if profile is not None:
        profile_validation = validate_review_mesh_profile(profile)
        if profile_validation["status"] != "PASS":
            blockers.append({"code": "review-mesh-profile-invalid", "validation": profile_validation})
        if assignment.get("profileDigest") != profile.get("profileDigest"):
            blockers.append({"code": "review-mesh-assignment-profile-digest-mismatch"})
        if assignment.get("mode") not in profile.get("modes", []):
            blockers.append({"code": "review-mesh-assignment-mode-not-profile"})
        blockers.extend(_cross_check_probe_blockers(profile, subject, reviewer, assignment.get("blocking") is True))
    expected_digest = canonical_digest({key: value for key, value in assignment.items() if key != "assignmentDigest"})
    if assignment.get("assignmentDigest") != expected_digest:
        blockers.append({"code": "review-mesh-assignment-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-assignment-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "assignmentId": assignment.get("assignmentId") if isinstance(assignment.get("assignmentId"), str) else None,
        "mode": assignment.get("mode") if isinstance(assignment.get("mode"), str) else None,
        "blocking": assignment.get("blocking") if isinstance(assignment.get("blocking"), bool) else None,
        "blockers": blockers,
        "assignmentDigest": assignment.get("assignmentDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_review_mesh_result(
    *,
    profile: dict[str, Any],
    assignment: dict[str, Any],
    budget_usage: dict[str, int],
    findings: list[dict[str, Any]] | None = None,
    status: str | None = None,
    live_calls_started: bool = False,
) -> dict[str, Any]:
    """Build a normalized reviewer result receipt from an assignment."""

    require_review_mesh_profile_pass(validate_review_mesh_profile(profile))
    require_review_mesh_assignment_pass(validate_review_mesh_assignment(assignment, profile=profile))
    cross_receipt = build_cross_check_receipt(
        profile=profile["crossCheckProfile"],
        subject=_cross_check_subject(assignment["subject"]),
        reviewer=assignment["reviewer"],
        budget_usage=budget_usage,
        findings=findings or [],
        blocking=assignment["blocking"],
        live_calls_started=live_calls_started,
        evidence_ids=assignment.get("evidenceIds", []),
        status=status,
    )
    cross_validation = validate_cross_check_receipt(cross_receipt, profile=profile["crossCheckProfile"])
    body = {
        "schemaVersion": REVIEW_MESH_RESULT_SCHEMA,
        "status": cross_receipt["status"],
        "resultId": f"{assignment['assignmentId']}-result",
        "assignmentId": assignment["assignmentId"],
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "mode": assignment["mode"],
        "phase": assignment["phase"],
        "subject": dict(assignment["subject"]),
        "reviewer": dict(assignment["reviewer"]),
        "findings": list(findings or []),
        "budgetUsage": dict(cross_receipt["budgetUsage"]),
        "independence": dict(cross_receipt["independence"]),
        "crossCheckReceipt": cross_receipt,
        "blockers": list(cross_validation["blockers"]),
        "productionPromotionClaimed": False,
    }
    return {**body, "resultDigest": canonical_digest(body)}


def validate_review_mesh_result(result: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(result, dict):
        raise LifecycleError("invalid-review-mesh-result", "Review Mesh result must be an object")
    if result.get("schemaVersion") != REVIEW_MESH_RESULT_SCHEMA:
        blockers.append({"code": "review-mesh-result-schema-invalid"})
    if result.get("status") not in RESULT_STATUSES:
        blockers.append({"code": "review-mesh-result-status-invalid"})
    _check_required_string(result.get("resultId"), "review-mesh-result-id-missing", blockers)
    _check_required_string(result.get("assignmentId"), "review-mesh-result-assignment-id-missing", blockers)
    _check_digest(result.get("profileDigest"), "review-mesh-result-profile-digest-invalid", blockers)
    if result.get("mode") not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-result-mode-invalid"})
    _check_object_list(result.get("findings"), "review-mesh-result-findings-invalid", blockers)
    _validate_budget_usage(result.get("budgetUsage"), blockers, prefix="review-mesh-result")
    cross_receipt = result.get("crossCheckReceipt")
    if not isinstance(cross_receipt, dict):
        blockers.append({"code": "review-mesh-result-cross-check-receipt-invalid"})
    else:
        cross_profile = profile.get("crossCheckProfile") if isinstance(profile, dict) else None
        cross_validation = validate_cross_check_receipt(cross_receipt, profile=cross_profile)
        if cross_validation["status"] != "PASS":
            blockers.append({"code": "review-mesh-result-cross-check-invalid", "validation": cross_validation})
        if result.get("independence") != cross_receipt.get("independence"):
            blockers.append({"code": "review-mesh-result-independence-mismatch"})
        if result.get("budgetUsage") != cross_receipt.get("budgetUsage"):
            blockers.append({"code": "review-mesh-result-budget-usage-mismatch"})
    _check_object_list(result.get("blockers", []), "review-mesh-result-blockers-invalid", blockers)
    if result.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-result-production-claim"})
    blockers.extend(_money_key_blockers(result))
    blockers.extend(_provider_model_name_blockers(result))
    if profile is not None and result.get("profileDigest") != profile.get("profileDigest"):
        blockers.append({"code": "review-mesh-result-profile-digest-mismatch"})
    expected_digest = canonical_digest({key: value for key, value in result.items() if key != "resultDigest"})
    if result.get("resultDigest") != expected_digest:
        blockers.append({"code": "review-mesh-result-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-result-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "resultId": result.get("resultId") if isinstance(result.get("resultId"), str) else None,
        "receiptStatus": result.get("status") if isinstance(result.get("status"), str) else None,
        "blockers": blockers,
        "resultDigest": result.get("resultDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_review_mesh_synthesis(
    *,
    profile: dict[str, Any],
    mode: str,
    subject: dict[str, Any],
    result_digests: list[str],
    agreement: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    accepted_findings: list[dict[str, Any]] | None = None,
    rejected_findings: list[dict[str, Any]] | None = None,
    unresolved_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic synthesis skeleton from reviewer result digests."""

    body = {
        "schemaVersion": REVIEW_MESH_SYNTHESIS_SCHEMA,
        "status": "INCONCLUSIVE" if unresolved_findings else "PASS",
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "mode": _enum(mode, set(REVIEW_MESH_MODE_IDS), "invalid-review-mesh-synthesis", label="mode"),
        "subject": dict(subject),
        "resultDigests": _digest_list(result_digests, "invalid-review-mesh-synthesis", label="resultDigests"),
        "agreement": list(agreement or []),
        "conflicts": list(conflicts or []),
        "acceptedFindings": list(accepted_findings or []),
        "rejectedFindings": list(rejected_findings or []),
        "unresolvedFindings": list(unresolved_findings or []),
        "productionPromotionClaimed": False,
    }
    return {**body, "synthesisDigest": canonical_digest(body)}


def validate_review_mesh_synthesis(synthesis: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(synthesis, dict):
        raise LifecycleError("invalid-review-mesh-synthesis", "Review Mesh synthesis must be an object")
    if synthesis.get("schemaVersion") != REVIEW_MESH_SYNTHESIS_SCHEMA:
        blockers.append({"code": "review-mesh-synthesis-schema-invalid"})
    if synthesis.get("status") not in SYNTHESIS_STATUSES:
        blockers.append({"code": "review-mesh-synthesis-status-invalid"})
    if synthesis.get("mode") not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-synthesis-mode-invalid"})
    _check_digest_list(synthesis.get("resultDigests"), "review-mesh-synthesis-result-digests-invalid", blockers)
    for field in ("agreement", "conflicts", "acceptedFindings", "rejectedFindings", "unresolvedFindings"):
        _check_object_list(synthesis.get(field), f"review-mesh-synthesis-{field}-invalid", blockers)
    if synthesis.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-synthesis-production-claim"})
    blockers.extend(_money_key_blockers(synthesis))
    blockers.extend(_provider_model_name_blockers(synthesis))
    if profile is not None and synthesis.get("profileDigest") != profile.get("profileDigest"):
        blockers.append({"code": "review-mesh-synthesis-profile-digest-mismatch"})
    expected_digest = canonical_digest({key: value for key, value in synthesis.items() if key != "synthesisDigest"})
    if synthesis.get("synthesisDigest") != expected_digest:
        blockers.append({"code": "review-mesh-synthesis-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-synthesis-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "mode": synthesis.get("mode") if isinstance(synthesis.get("mode"), str) else None,
        "blockers": blockers,
        "synthesisDigest": synthesis.get("synthesisDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_review_mesh_quorum_receipt(
    *,
    profile: dict[str, Any],
    mode: str,
    subject: dict[str, Any],
    quorum_policy: dict[str, Any],
    reviewer_count: int,
    required_roles_satisfied: bool = True,
    blocking_findings_unresolved: bool = False,
) -> dict[str, Any]:
    """Build a quorum receipt without enforcing it outside explicit opt-in."""

    min_reviewers = quorum_policy.get("minReviewers") if isinstance(quorum_policy, dict) else None
    quorum_satisfied = isinstance(min_reviewers, int) and reviewer_count >= min_reviewers and required_roles_satisfied
    blockers: list[dict[str, Any]] = []
    if not quorum_satisfied:
        blockers.append({"code": "review-mesh-quorum-not-satisfied"})
    if blocking_findings_unresolved:
        blockers.append({"code": "review-mesh-blocking-findings-unresolved"})
    if subject.get("reviewMeshRequired") is not True and blockers:
        status = "SKIPPED"
    else:
        status = "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": REVIEW_MESH_QUORUM_RECEIPT_SCHEMA,
        "status": status,
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "mode": _enum(mode, set(REVIEW_MESH_MODE_IDS), "invalid-review-mesh-quorum", label="mode"),
        "subject": dict(subject),
        "quorumPolicy": dict(quorum_policy),
        "reviewerCount": _non_negative_int(reviewer_count, "invalid-review-mesh-quorum", label="reviewerCount"),
        "requiredRolesSatisfied": bool(required_roles_satisfied),
        "quorumSatisfied": quorum_satisfied,
        "blockingFindingsUnresolved": bool(blocking_findings_unresolved),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_review_mesh_quorum_receipt(receipt: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-review-mesh-quorum", "Review Mesh quorum receipt must be an object")
    if receipt.get("schemaVersion") != REVIEW_MESH_QUORUM_RECEIPT_SCHEMA:
        blockers.append({"code": "review-mesh-quorum-schema-invalid"})
    if receipt.get("status") not in {"PASS", "FAIL", "SKIPPED"}:
        blockers.append({"code": "review-mesh-quorum-status-invalid"})
    if receipt.get("mode") not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-quorum-mode-invalid"})
    _validate_quorum_policy(receipt.get("quorumPolicy"), blockers)
    if not isinstance(receipt.get("reviewerCount"), int) or isinstance(receipt.get("reviewerCount"), bool) or receipt["reviewerCount"] < 0:
        blockers.append({"code": "review-mesh-quorum-reviewer-count-invalid"})
    if not isinstance(receipt.get("requiredRolesSatisfied"), bool):
        blockers.append({"code": "review-mesh-quorum-roles-invalid"})
    if not isinstance(receipt.get("quorumSatisfied"), bool):
        blockers.append({"code": "review-mesh-quorum-satisfied-invalid"})
    if not isinstance(receipt.get("blockingFindingsUnresolved"), bool):
        blockers.append({"code": "review-mesh-quorum-blocking-findings-invalid"})
    _check_object_list(receipt.get("blockers", []), "review-mesh-quorum-blockers-invalid", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-quorum-production-claim"})
    blockers.extend(_money_key_blockers(receipt))
    blockers.extend(_provider_model_name_blockers(receipt))
    if profile is not None and receipt.get("profileDigest") != profile.get("profileDigest"):
        blockers.append({"code": "review-mesh-quorum-profile-digest-mismatch"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "review-mesh-quorum-digest-mismatch"})
    body = {
        "schemaVersion": REVIEW_MESH_QUORUM_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileId": receipt.get("profileId") if isinstance(receipt.get("profileId"), str) else None,
        "mode": receipt.get("mode") if isinstance(receipt.get("mode"), str) else None,
        "quorumSatisfied": receipt.get("quorumSatisfied") if isinstance(receipt.get("quorumSatisfied"), bool) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_review_mesh_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("review-mesh-profile-validation-failed", "Review Mesh profile validation failed", {"validation": validation})
    return validation


def require_review_mesh_assignment_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("review-mesh-assignment-validation-failed", "Review Mesh assignment validation failed", {"validation": validation})
    return validation


def require_review_mesh_result_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("review-mesh-result-validation-failed", "Review Mesh result validation failed", {"validation": validation})
    return validation


def require_review_mesh_quorum_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("quorumSatisfied") is not True:
        raise LifecycleError("review-mesh-quorum-validation-failed", "Review Mesh quorum validation failed", {"validation": validation})
    return validation


def _cross_check_probe_blockers(profile: dict[str, Any], subject: dict[str, Any], reviewer: dict[str, Any], blocking: bool) -> list[dict[str, Any]]:
    try:
        receipt = build_cross_check_receipt(
            profile=profile["crossCheckProfile"],
            subject=_cross_check_subject(subject),
            reviewer=reviewer,
            budget_usage={"invocations": 0, "inputTokens": 0, "outputTokens": 0, "wallSeconds": 0},
            blocking=blocking,
        )
        validation = validate_cross_check_receipt(receipt, profile=profile["crossCheckProfile"])
    except LifecycleError as error:
        return [{"code": "review-mesh-cross-check-probe-invalid", "error": error.code}]
    return [{"code": "review-mesh-cross-check-probe-failed", "validation": validation}] if validation["status"] != "PASS" else []


def _cross_check_subject(subject: dict[str, Any]) -> dict[str, Any]:
    return {**subject, "blockingCrossCheckRequired": _subject_has_blocking_opt_in(subject)}


def _subject_has_blocking_opt_in(subject: dict[str, Any]) -> bool:
    return subject.get("reviewMeshBlockingOptIn") is True or subject.get("blockingCrossCheckRequired") is True


def _validate_quorum_policy(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "review-mesh-quorum-policy-invalid"})
        return
    min_reviewers = value.get("minReviewers")
    if not isinstance(min_reviewers, int) or isinstance(min_reviewers, bool) or min_reviewers <= 0:
        blockers.append({"code": "review-mesh-quorum-min-reviewers-invalid"})
    required_roles = value.get("requiredRoles", [])
    if required_roles is not None:
        _check_string_list(required_roles, "review-mesh-quorum-required-roles-invalid", blockers, allow_empty=True)
    threshold = value.get("blockingSeverityThreshold")
    if threshold is not None and threshold not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        blockers.append({"code": "review-mesh-quorum-threshold-invalid"})


def _validate_modes(modes: list[str], code: str) -> None:
    unknown = sorted(set(modes).difference(REVIEW_MESH_MODE_IDS))
    if unknown:
        raise LifecycleError(code, "unknown Review Mesh mode", {"modes": unknown})


def _model_classes(values: list[str]) -> list[str]:
    classes = _string_list(values, "invalid-review-mesh-profile", label="reviewerModelClasses")
    unknown = sorted(set(classes).difference(ALLOWED_MODEL_CLASSES))
    if unknown:
        raise LifecycleError("invalid-review-mesh-profile", "unknown provider-neutral model classes", {"classes": unknown})
    return classes


def _validate_model_classes(values: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(values, list) or not values:
        blockers.append({"code": "review-mesh-model-classes-invalid"})
        return
    unknown = sorted({item for item in values if not isinstance(item, str) or item not in ALLOWED_MODEL_CLASSES})
    if unknown:
        blockers.append({"code": "review-mesh-model-classes-unknown", "classes": unknown})


def _validate_resource_cap(value: Any, blockers: list[dict[str, Any]], *, prefix: str) -> None:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": f"{prefix}-budget-cap-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "review-mesh-money-cap-not-allowed", "field": key})
        elif key not in RESOURCE_CAP_KEYS:
            blockers.append({"code": f"{prefix}-budget-cap-unsupported", "field": key})
        elif not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            blockers.append({"code": f"{prefix}-budget-cap-value-invalid", "field": key})


def _validate_budget_usage(value: Any, blockers: list[dict[str, Any]], *, prefix: str) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": f"{prefix}-budget-usage-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "review-mesh-money-usage-not-allowed", "field": key})
        elif key not in USAGE_KEYS:
            blockers.append({"code": f"{prefix}-budget-usage-unsupported", "field": key})
        elif not isinstance(item, int) or isinstance(item, bool) or item < 0:
            blockers.append({"code": f"{prefix}-budget-usage-value-invalid", "field": key})


def _money_key_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else key
            if key in MONEY_KEYS:
                blockers.append({"code": "review-mesh-monetary-field-not-allowed", "path": next_path})
            blockers.extend(_money_key_blockers(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_money_key_blockers(item, path=f"{path}[{index}]"))
    return blockers


def _provider_model_name_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else key
            if key in PROVIDER_MODEL_NAME_KEYS and not _is_neutral_identity_field_mapping(path, key):
                blockers.append({"code": "review-mesh-provider-model-name-not-portable", "path": next_path})
            blockers.extend(_provider_model_name_blockers(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_provider_model_name_blockers(item, path=f"{path}[{index}]"))
    return blockers


def _is_neutral_identity_field_mapping(path: str, key: str) -> bool:
    return path.endswith("identityFields") and key in INDEPENDENCE_IDENTITY_FIELDS


def _object_or_blocker(value: Any, code: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": code})
        return {}
    return value


def _required_string(value: Any, code: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value


def _string_list(value: Any, code: str, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} must be a list of strings")
    return list(value)


def _digest_list(value: Any, code: str, *, label: str) -> list[str]:
    values = _string_list(value, code, label=label)
    if any(len(item) != 64 for item in values):
        raise LifecycleError(code, f"{label} must contain 64-character digests")
    return values


def _enum(value: Any, allowed: set[str], code: str, *, label: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is unsupported", {label: value})
    return str(value)


def _non_negative_int(value: Any, code: str, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError(code, f"{label} must be a non-negative integer")
    return value


def _check_const(payload: dict[str, Any], field: str, expected: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if payload.get(field) != expected:
        blockers.append({"code": code})


def _check_required_string(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code})


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": code})


def _check_digest_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and len(item) == 64 for item in value):
        blockers.append({"code": code})


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
