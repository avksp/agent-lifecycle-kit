"""Provider-neutral Review Mesh contract helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.authority_text import require_review_text
from agent_lifecycle.contracts.external_job_schemas import validate_cumulative_session_usage
from agent_lifecycle.contracts.independent_evidence_schemas import validate_independence_requirement
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS as REVIEW_MESH_MODE_IDS
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES as ALLOWED_MODEL_CLASSES
from agent_lifecycle.quality.cross_check import (
    INDEPENDENCE_IDENTITY_FIELDS as INDEPENDENCE_IDENTITY_FIELDS,
)
from agent_lifecycle.quality.cross_check import (
    MONEY_KEYS as MONEY_KEYS,
)
from agent_lifecycle.quality.cross_check import (
    RESOURCE_CAP_KEYS as RESOURCE_CAP_KEYS,
)
from agent_lifecycle.quality.cross_check import (
    USAGE_KEYS as USAGE_KEYS,
)
from agent_lifecycle.quality.cross_check import (
    _budget_blockers as _budget_blockers,
)
from agent_lifecycle.quality.cross_check import (
    build_cross_check_profile,
    build_cross_check_receipt,
    validate_cross_check_profile,
    validate_cross_check_receipt,
)
from agent_lifecycle.review_mesh.independence import (
    quorum_independence_blockers,
    result_independence_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    PROVIDER_MODEL_NAME_KEYS as PROVIDER_MODEL_NAME_KEYS,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_const as _check_const,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_digest as _check_digest,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_digest_list as _check_digest_list,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_object_list as _check_object_list,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_required_string as _check_required_string,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _check_string_list as _check_string_list,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _command_outcome_blockers as _command_outcome_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _digest_list as _digest_list,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _enum as _enum,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _is_neutral_identity_field_mapping as _is_neutral_identity_field_mapping,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _known_usage_budget_blockers as _known_usage_budget_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _live_call_policy_blockers as _live_call_policy_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _model_classes as _model_classes,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _money_key_blockers as _money_key_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _non_negative_int as _non_negative_int,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _object_or_blocker as _object_or_blocker,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _provider_model_name_blockers as _provider_model_name_blockers,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _required_string as _required_string,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _string_list as _string_list,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _validate_budget_usage as _validate_budget_usage,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _validate_model_classes as _validate_model_classes,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _validate_modes as _validate_modes,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _validate_quorum_policy as _validate_quorum_policy,
)
from agent_lifecycle.review_mesh.validation_helpers import (
    _validate_resource_cap as _validate_resource_cap,
)

REVIEW_MESH_PROFILE_SCHEMA = "agent-review-mesh-profile.v1"
REVIEW_MESH_ASSIGNMENT_SCHEMA = "agent-review-mesh-assignment.v1"
REVIEW_MESH_RESULT_SCHEMA = "agent-review-mesh-result.v1"
REVIEW_MESH_SYNTHESIS_SCHEMA = "agent-review-mesh-synthesis.v1"
REVIEW_MESH_QUORUM_RECEIPT_SCHEMA = "agent-review-mesh-quorum-receipt.v1"
REVIEW_MESH_QUORUM_VALIDATION_SCHEMA = "agent-review-mesh-quorum-validation.v1"

RESULT_STATUSES = {"PASS", "FAIL", "SKIPPED"}
SYNTHESIS_STATUSES = {"PASS", "FAIL", "INCONCLUSIVE"}


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
        raise LifecycleError(
            "invalid-review-mesh-profile", "defaultMode must be one of modes", {"defaultMode": default_mode}
        )
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
        if profile.get("liveCallsAllowed") != cross_profile.get("liveCallsAllowed"):
            blockers.append({"code": "review-mesh-live-calls-not-cross-check"})
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
    independence_requirement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reviewer assignment without launching the reviewer."""

    require_review_mesh_profile_pass(validate_review_mesh_profile(profile))
    selected_mode = mode or profile["defaultMode"]
    if selected_mode not in profile["modes"]:
        raise LifecycleError(
            "invalid-review-mesh-assignment", "mode is not allowed by profile", {"mode": selected_mode}
        )
    if independence_requirement is not None:
        requirement_validation = validate_independence_requirement(independence_requirement)
        if requirement_validation["status"] != "PASS":
            raise LifecycleError(
                "invalid-review-mesh-assignment",
                "independence requirement is invalid",
                {"validation": requirement_validation},
            )
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
        "evidenceIds": _string_list(
            evidence_ids or [], "invalid-review-mesh-assignment", label="evidenceIds", allow_empty=True
        ),
        "independenceRequirement": dict(independence_requirement) if independence_requirement is not None else None,
        "productionPromotionClaimed": False,
    }
    return {**body, "assignmentDigest": canonical_digest(body)}


def validate_review_mesh_assignment(
    assignment: dict[str, Any], *, profile: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    independence_requirement = assignment.get("independenceRequirement")
    if independence_requirement is not None:
        requirement_validation = validate_independence_requirement(independence_requirement)
        if requirement_validation["status"] != "PASS":
            blockers.append(
                {"code": "review-mesh-assignment-independence-invalid", "validation": requirement_validation}
            )
    _check_string_list(
        assignment.get("evidenceIds", []), "review-mesh-assignment-evidence-ids-invalid", blockers, allow_empty=True
    )
    if assignment.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-assignment-production-claim"})
    blockers.extend(_money_key_blockers(assignment))
    blockers.extend(_provider_model_name_blockers(assignment))
    if profile is not None:
        blockers.extend(_profile_binding_blockers(assignment, profile, prefix="review-mesh-assignment"))
        if assignment.get("budgetCap") != profile.get("budgetCap"):
            blockers.append({"code": "review-mesh-assignment-budget-cap-not-profile"})
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
    budget_usage: Mapping[str, int | None],
    findings: list[dict[str, Any]] | None = None,
    status: str | None = None,
    live_calls_started: bool = False,
    independent_evidence: dict[str, Any] | None = None,
    session_usage_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized reviewer result receipt from an assignment."""

    require_review_mesh_profile_pass(validate_review_mesh_profile(profile))
    require_review_mesh_assignment_pass(validate_review_mesh_assignment(assignment, profile=profile))
    budget_usage = dict(budget_usage)
    session_check = cumulative_reviewer_budget(
        profile,
        assignment,
        budget_usage,
        session_usage_context,
    )
    usage_blockers: list[dict[str, Any]] = []
    _validate_budget_usage(budget_usage, usage_blockers, prefix="review-mesh-result", allow_unknown=True)
    if usage_blockers or set(budget_usage) != USAGE_KEYS:
        raise LifecycleError("invalid-review-mesh-result", "budget usage must contain every supported resource")
    unavailable = any(value is None for value in budget_usage.values())
    cross_receipt = None
    if unavailable:
        result_status = _enum(status or "FAIL", RESULT_STATUSES, "invalid-review-mesh-result", label="status")
        independence = {"status": "NOT_PROVEN"}
        cross_blockers = [
            {"code": "review-mesh-result-usage-unavailable"},
            *_known_usage_budget_blockers(budget_usage, profile),
            *_live_call_policy_blockers(live_calls_started, profile),
        ]
    else:
        cross_receipt = build_cross_check_receipt(
            profile=profile["crossCheckProfile"],
            subject=_cross_check_subject(assignment["subject"]),
            reviewer=assignment["reviewer"],
            budget_usage=cast(dict[str, int], dict(budget_usage)),
            findings=findings or [],
            blocking=assignment["blocking"],
            live_calls_started=live_calls_started,
            evidence_ids=assignment.get("evidenceIds", []),
            status=status,
        )
        cross_blockers = validate_cross_check_receipt(cross_receipt, profile=profile["crossCheckProfile"])["blockers"]
        result_status = cross_receipt["status"]
        independence = dict(cross_receipt["independence"])
    independence_requirement = assignment.get("independenceRequirement")
    independence_blockers = result_independence_blockers(
        requirement=independence_requirement,
        evidence=independent_evidence,
        subject=assignment["subject"],
    )
    body = {
        "schemaVersion": REVIEW_MESH_RESULT_SCHEMA,
        "status": result_status,
        "resultId": f"{assignment['assignmentId']}-result",
        "assignmentId": assignment["assignmentId"],
        "profileId": profile["profileId"],
        "profileDigest": profile["profileDigest"],
        "mode": assignment["mode"],
        "phase": assignment["phase"],
        "subject": dict(assignment["subject"]),
        "reviewer": dict(assignment["reviewer"]),
        "independenceRequirement": independence_requirement,
        "findings": list(findings or []),
        "budgetUsage": dict(budget_usage),
        "independence": independence,
        "crossCheckReceipt": cross_receipt,
        "independentEvidence": dict(independent_evidence) if independent_evidence is not None else None,
        "blockers": [*cross_blockers, *independence_blockers],
        "productionPromotionClaimed": False,
    }
    if unavailable:
        body["budgetUsageStatus"] = "UNAVAILABLE"
        body["roundParticipation"] = {"eligible": False, "reasonCode": "budget-usage-unavailable"}
        body["liveCallsStarted"] = live_calls_started
    if session_check is not None and session_usage_context is not None:
        body["sessionUsage"] = dict(session_usage_context["receipt"])
        body["assignmentDigest"] = assignment["assignmentDigest"]
        body["sessionBudgetBasis"] = "CUMULATIVE_PROVIDER_SESSION"
    return {**body, "resultDigest": canonical_digest(body)}


def cumulative_reviewer_budget(
    profile: dict[str, Any],
    assignment: dict[str, Any],
    usage: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """A selected session route cannot fall back to prompt or per-call usage."""
    subject = assignment.get("subject", {})
    if subject.get("cumulativeUsageRequired") is not True and context is None:
        return None
    if not isinstance(context, dict):
        raise LifecycleError("review-session-usage-required", "Qualified cumulative usage is required")
    binding = {
        "sessionDigest": subject.get("sessionDigest"),
        "sourceRevision": subject.get("sourceRevision"),
        "subjectDigest": canonical_digest(subject),
        "assignmentDigest": assignment.get("assignmentDigest"),
    }
    cap = profile["budgetCap"]
    names = {
        "maxInputTokens": "inputTokens",
        "maxOutputTokens": "outputTokens",
        "maxInvocations": "invocations",
        "maxWallSeconds": "wallSeconds",
    }
    check = validate_cumulative_session_usage(
        context.get("receipt"),
        binding=binding,
        qualification=context.get("qualification"),
        previous=context.get("previous"),
        limits={names[key]: value for key, value in cap.items() if key in names},
    )
    receipt = context.get("receipt", {})
    if check["status"] != "PASS" or any(usage.get(key) != receipt.get("usage", {}).get(key) for key in USAGE_KEYS):
        raise LifecycleError("review-session-usage-invalid", "Cumulative reviewer usage is unavailable or invalid")
    return check


def _imported_independence_claimed(result: dict[str, Any]) -> bool:
    participation = result.get("roundParticipation")
    receipt = result.get("crossCheckReceipt")
    blocker_lists = (result.get("blockers"), receipt.get("blockers") if isinstance(receipt, dict) else None)
    explicitly_unproven = any(
        isinstance(items, list)
        and any(isinstance(item, dict) and item.get("code") == "cross-check-independence-not-proven" for item in items)
        for items in blocker_lists
    )
    imported = (
        "import" in result
        or (
            isinstance(participation, dict)
            and participation.get("reasonCode") == "review-verdict-and-terminal-job-required"
        )
        or explicitly_unproven
    )
    independence = result.get("independence")
    return imported and isinstance(independence, dict) and independence.get("status") == "INDEPENDENT"


def validate_review_mesh_result(
    result: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    session_usage_context: dict[str, Any] | None = None,
    assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(result, dict):
        raise LifecycleError("invalid-review-mesh-result", "Review Mesh result must be an object")
    require_review_text(result)
    subject = result.get("subject")
    if "sessionUsage" in result or (isinstance(subject, dict) and subject.get("cumulativeUsageRequired") is True):
        try:
            if profile is None or not isinstance(session_usage_context, dict) or assignment is None:
                raise LifecycleError("review-session-usage-required", "Bound session context is required")
            if result.get("sessionUsage") != session_usage_context.get("receipt"):
                raise LifecycleError("review-session-usage-invalid", "Session receipt differs")
            require_review_mesh_assignment_pass(validate_review_mesh_assignment(assignment, profile=profile))
            if any(result.get(key) != assignment.get(key) for key in ("subject", "assignmentId", "assignmentDigest")):
                raise LifecycleError("review-session-usage-invalid", "Assignment binding differs")
            cumulative_reviewer_budget(profile, assignment, result.get("budgetUsage", {}), session_usage_context)
        except (LifecycleError, KeyError):
            blockers.append({"code": "review-mesh-result-session-usage-invalid"})
    if _imported_independence_claimed(result):
        blockers.append({"code": "review-mesh-result-import-independence-not-proven"})
    if result.get("schemaVersion") != REVIEW_MESH_RESULT_SCHEMA:
        blockers.append({"code": "review-mesh-result-schema-invalid"})
    if result.get("status") not in RESULT_STATUSES:
        blockers.append({"code": "review-mesh-result-status-invalid"})
    _check_required_string(result.get("resultId"), "review-mesh-result-id-missing", blockers)
    _check_required_string(result.get("assignmentId"), "review-mesh-result-assignment-id-missing", blockers)
    _check_required_string(result.get("phase"), "review-mesh-result-phase-missing", blockers)
    _check_digest(result.get("profileDigest"), "review-mesh-result-profile-digest-invalid", blockers)
    if result.get("mode") not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-result-mode-invalid"})
    _check_object_list(result.get("findings"), "review-mesh-result-findings-invalid", blockers)
    unavailable = result.get("budgetUsageStatus") == "UNAVAILABLE"
    _validate_budget_usage(result.get("budgetUsage"), blockers, prefix="review-mesh-result", allow_unknown=unavailable)
    if unavailable:
        blockers.append({"code": "review-mesh-result-usage-unavailable"})
        blockers.extend(_known_usage_budget_blockers(result.get("budgetUsage"), profile))
        blockers.extend(_live_call_policy_blockers(result.get("liveCallsStarted"), profile))
        participation = result.get("roundParticipation")
        if not isinstance(participation, dict) or participation.get("eligible") is not False:
            blockers.append({"code": "review-mesh-result-unavailable-participation"})
    cross_receipt = result.get("crossCheckReceipt")
    if not isinstance(cross_receipt, dict) and not (unavailable and cross_receipt is None):
        blockers.append({"code": "review-mesh-result-cross-check-receipt-invalid"})
    elif isinstance(cross_receipt, dict):
        cross_profile = profile.get("crossCheckProfile") if isinstance(profile, dict) else None
        cross_validation = validate_cross_check_receipt(cross_receipt, profile=cross_profile)
        if cross_validation["status"] != "PASS":
            blockers.append({"code": "review-mesh-result-cross-check-invalid", "validation": cross_validation})
        if result.get("independence") != cross_receipt.get("independence"):
            blockers.append({"code": "review-mesh-result-independence-mismatch"})
        if result.get("budgetUsage") != cross_receipt.get("budgetUsage"):
            blockers.append({"code": "review-mesh-result-budget-usage-mismatch"})
        subject = result.get("subject")
        joined_fields = {
            "status": result.get("status"),
            "subject": _cross_check_subject(subject) if isinstance(subject, dict) else None,
            "reviewer": result.get("reviewer"),
            "findings": result.get("findings"),
        }
        for field, value in joined_fields.items():
            if canonical_digest(value) != canonical_digest(cross_receipt.get(field)):
                blockers.append({"code": f"review-mesh-result-{field}-mismatch"})
    if "commandOutcomes" in result:
        commands = result["commandOutcomes"]
        command_blockers = _command_outcome_blockers(commands)
        blockers.extend(command_blockers)
        if (
            not command_blockers
            and result.get("status") != "FAIL"
            and any(command["status"] == "FAIL" or command["exitCode"] != 0 for command in commands)
        ):
            blockers.append({"code": "review-mesh-result-failed-command-status-mismatch"})
    requirement = result.get("independenceRequirement")
    subject_value = result.get("subject")
    subject = subject_value if isinstance(subject_value, dict) else {}
    blockers.extend(
        result_independence_blockers(
            requirement=requirement,
            evidence=result.get("independentEvidence"),
            subject=subject,
        )
    )
    _check_object_list(result.get("blockers", []), "review-mesh-result-blockers-invalid", blockers)
    if result.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-result-production-claim"})
    blockers.extend(_money_key_blockers(result))
    blockers.extend(_provider_model_name_blockers(result))
    blockers.extend(_profile_binding_blockers(result, profile, prefix="review-mesh-result"))
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


def validate_review_mesh_synthesis(
    synthesis: dict[str, Any], *, profile: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    blockers.extend(_profile_binding_blockers(synthesis, profile, prefix="review-mesh-synthesis"))
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
    independence_requirement: dict[str, Any] | None = None,
    independent_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a quorum receipt without enforcing it outside explicit opt-in."""

    min_reviewers = quorum_policy.get("minReviewers") if isinstance(quorum_policy, dict) else None
    quorum_satisfied = isinstance(min_reviewers, int) and reviewer_count >= min_reviewers and required_roles_satisfied
    blockers: list[dict[str, Any]] = []
    if not quorum_satisfied:
        blockers.append({"code": "review-mesh-quorum-not-satisfied"})
    if blocking_findings_unresolved:
        blockers.append({"code": "review-mesh-blocking-findings-unresolved"})
    evidence_values = list(independent_evidence or [])
    subject_value = subject if isinstance(subject, dict) else {}
    blockers.extend(
        quorum_independence_blockers(
            requirement=independence_requirement,
            evidence_values=evidence_values,
            subject=subject_value,
        )
    )
    if subject.get("reviewMeshRequired") is not True and blockers and independence_requirement is None:
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
        "independenceRequirement": dict(independence_requirement) if independence_requirement is not None else None,
        "independentEvidence": evidence_values,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_review_mesh_quorum_receipt(
    receipt: dict[str, Any], *, profile: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    if (
        not isinstance(receipt.get("reviewerCount"), int)
        or isinstance(receipt.get("reviewerCount"), bool)
        or receipt["reviewerCount"] < 0
    ):
        blockers.append({"code": "review-mesh-quorum-reviewer-count-invalid"})
    if not isinstance(receipt.get("requiredRolesSatisfied"), bool):
        blockers.append({"code": "review-mesh-quorum-roles-invalid"})
    if not isinstance(receipt.get("quorumSatisfied"), bool):
        blockers.append({"code": "review-mesh-quorum-satisfied-invalid"})
    if not isinstance(receipt.get("blockingFindingsUnresolved"), bool):
        blockers.append({"code": "review-mesh-quorum-blocking-findings-invalid"})
    policy = receipt.get("quorumPolicy")
    minimum = policy.get("minReviewers") if isinstance(policy, dict) else None
    count = receipt.get("reviewerCount")
    roles_satisfied = receipt.get("requiredRolesSatisfied")
    if type(minimum) is int and type(count) is int and type(roles_satisfied) is bool:
        expected_quorum = count >= minimum and roles_satisfied
        if receipt.get("quorumSatisfied") is not expected_quorum:
            blockers.append({"code": "review-mesh-quorum-count-roles-mismatch"})
    if receipt.get("status") == "PASS" and (
        receipt.get("quorumSatisfied") is not True or receipt.get("blockingFindingsUnresolved") is not False
    ):
        blockers.append({"code": "review-mesh-quorum-outcome-mismatch"})
    _check_object_list(receipt.get("blockers", []), "review-mesh-quorum-blockers-invalid", blockers)
    subject_value = receipt.get("subject")
    subject = subject_value if isinstance(subject_value, dict) else {}
    blockers.extend(
        quorum_independence_blockers(
            requirement=receipt.get("independenceRequirement"),
            evidence_values=receipt.get("independentEvidence"),
            subject=subject,
        )
    )
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-mesh-quorum-production-claim"})
    blockers.extend(_money_key_blockers(receipt))
    blockers.extend(_provider_model_name_blockers(receipt))
    blockers.extend(_profile_binding_blockers(receipt, profile, prefix="review-mesh-quorum"))
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "review-mesh-quorum-digest-mismatch"})
    body = {
        "schemaVersion": REVIEW_MESH_QUORUM_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": receipt.get("status"),
        "blockingFindingsUnresolved": receipt.get("blockingFindingsUnresolved"),
        "profileId": receipt.get("profileId") if isinstance(receipt.get("profileId"), str) else None,
        "mode": receipt.get("mode") if isinstance(receipt.get("mode"), str) else None,
        "quorumSatisfied": receipt.get("quorumSatisfied") if isinstance(receipt.get("quorumSatisfied"), bool) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_review_mesh_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "review-mesh-profile-validation-failed", "Review Mesh profile validation failed", {"validation": validation}
        )
    return validation


def require_review_mesh_assignment_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "review-mesh-assignment-validation-failed",
            "Review Mesh assignment validation failed",
            {"validation": validation},
        )
    return validation


def require_review_mesh_result_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "review-mesh-result-validation-failed", "Review Mesh result validation failed", {"validation": validation}
        )
    return validation


def require_review_mesh_quorum_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if (
        validation.get("status") != "PASS"
        or validation.get("receiptStatus") != "PASS"
        or validation.get("quorumSatisfied") is not True
        or validation.get("blockingFindingsUnresolved") is not False
    ):
        raise LifecycleError(
            "review-mesh-quorum-validation-failed", "Review Mesh quorum validation failed", {"validation": validation}
        )
    return validation


def _profile_binding_blockers(
    value: dict[str, Any], profile: dict[str, Any] | None, *, prefix: str
) -> list[dict[str, Any]]:
    if profile is None:
        return []
    blockers: list[dict[str, Any]] = []
    validation = validate_review_mesh_profile(profile)
    if validation["status"] != "PASS":
        blockers.append({"code": "review-mesh-profile-invalid", "validation": validation})
    if value.get("profileId") != profile.get("profileId"):
        blockers.append({"code": f"{prefix}-profile-id-mismatch"})
    if value.get("profileDigest") != profile.get("profileDigest"):
        blockers.append({"code": f"{prefix}-profile-digest-mismatch"})
    modes = profile.get("modes")
    if isinstance(modes, list) and value.get("mode") not in modes:
        blockers.append({"code": f"{prefix}-mode-not-profile"})
    if prefix in {"review-mesh-assignment", "review-mesh-result"}:
        classes = profile.get("reviewerModelClasses")
        reviewer = value.get("reviewer")
        selected = reviewer.get("modelClass") if isinstance(reviewer, dict) else None
        if isinstance(classes, list) and selected not in classes:
            blockers.append({"code": f"{prefix}-reviewer-class-not-profile"})
    return blockers


def _cross_check_probe_blockers(
    profile: dict[str, Any], subject: dict[str, Any], reviewer: dict[str, Any], blocking: bool
) -> list[dict[str, Any]]:
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
    return (
        [{"code": "review-mesh-cross-check-probe-failed", "validation": validation}]
        if validation["status"] != "PASS"
        else []
    )


def _cross_check_subject(subject: dict[str, Any]) -> dict[str, Any]:
    return {**subject, "blockingCrossCheckRequired": _subject_has_blocking_opt_in(subject)}


def _subject_has_blocking_opt_in(subject: dict[str, Any]) -> bool:
    return subject.get("reviewMeshBlockingOptIn") is True or subject.get("blockingCrossCheckRequired") is True
