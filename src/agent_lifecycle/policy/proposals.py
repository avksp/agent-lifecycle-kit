"""Build read-only lifecycle policy tuning proposals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    write_json_create,
)
from agent_lifecycle.contracts.audit_optimization_schemas import (
    AUDIT_OPTIMIZATION_APPLIED_PROFILE_SCHEMA,
    AUDIT_OPTIMIZATION_APPLY_RESULT_SCHEMA,
    AUDIT_OPTIMIZATION_PROPOSAL_SCHEMA,
    AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA,
)
from agent_lifecycle.contracts.finding_check_schemas import (
    FINDING_CHECK_PROPOSAL_SCHEMA,
    build_finding_check_binding,
    transition_finding_check_binding,
    validate_finding_check_proposal,
)
from agent_lifecycle.contracts.proof_validation import build_finding_identity
from agent_lifecycle.metrics import summarize_regression_signals
from agent_lifecycle.planning.deltas import finding_check_plan_lineage, validate_plan_delta
from agent_lifecycle.policy.quality_floor import is_downgrade, protected_work

PROPOSAL_SCHEMA = "agent-lifecycle-policy-proposal.v1"
SUMMARY_SCHEMA = "agent-lifecycle-policy-summary.v1"
RECOMMENDATION_SCHEMA = "agent-lifecycle-recommendation.v1"
OPTIMIZATION_APPLIED_SCHEMA = AUDIT_OPTIMIZATION_APPLIED_PROFILE_SCHEMA
_OPTIMIZATION_CHANGE_LIMITS = {
    "packetTokenLimit": (128, 100000),
    "reviewerCountHint": (1, 8),
    "timeoutSeconds": (1, 14400),
    "retryLimit": (0, 4),
}
_OPTIMIZATION_CHANGE_FIELDS = set(_OPTIMIZATION_CHANGE_LIMITS) | {"routeClass"}
_OPTIMIZATION_TARGETS = {"project-profile", "plan-revision"}


def build_finding_check_proposal(
    *,
    finding: dict[str, Any],
    plan_delta: dict[str, Any],
    check_identity: dict[str, Any],
    owner: str,
    scope: dict[str, Any],
    source_revision: str,
    expected_result: str = "PASS",
    proposal_id: str = "finding-check-adoption-proposal",
) -> dict[str, Any]:
    """Create an advisory binding proposal without granting adoption authority."""

    blockers: list[dict[str, Any]] = []
    try:
        identity = build_finding_identity(finding)
    except LifecycleError as exc:
        identity = {}
        blockers.append({"code": exc.code, "message": exc.message})
    delta_validation = validate_plan_delta(plan_delta)
    if delta_validation.get("status") != "PASS":
        blockers.append({"code": "finding-check-plan-delta-invalid", "validation": delta_validation})
    try:
        lineage = finding_check_plan_lineage(plan_delta)
        binding = build_finding_check_binding(
            finding_id=identity.get("findingId", "invalid-finding"),
            finding_digest=identity.get("findingDigest", "0" * 64),
            plan_delta_digest=plan_delta.get("deltaDigest", "0" * 64),
            plan_lineage=lineage,
            check_identity=check_identity,
            owner=owner,
            scope=scope,
            source_revision=source_revision,
            expected_result=expected_result,
        )
    except LifecycleError as exc:
        binding = {}
        blockers.append({"code": exc.code, "message": exc.message})
    body = {
        "schemaVersion": FINDING_CHECK_PROPOSAL_SCHEMA,
        "proposalId": proposal_id,
        "status": "PASS" if not blockers else "FAIL",
        "binding": binding,
        "approvalRequired": True,
        "applyAllowed": False,
        "authorityClaimed": False,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "proposalDigest": canonical_digest(body)}


def accept_finding_check_proposal(proposal: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    """Move a valid proposal to ACCEPTED only after explicit authorization."""

    validation = validate_finding_check_proposal(proposal)
    if validation.get("status") != "PASS" or proposal.get("status") != "PASS":
        raise LifecycleError("finding-check-proposal-invalid", "proposal is not eligible for acceptance", validation)
    return transition_finding_check_binding(
        proposal["binding"],
        "ACCEPTED",
        authorization=authorization,
    )


def build_policy_proposal(
    recommendation: dict[str, Any],
    *,
    regression_signals: list[dict[str, Any]] | None = None,
    risk_flags: list[str] | None = None,
    proposal_id: str = "lifecycle-policy-proposal",
) -> dict[str, Any]:
    blockers = _recommendation_blockers(recommendation)
    regression_summary = summarize_regression_signals(regression_signals)
    if regression_summary["status"] == "FAIL":
        blockers.extend(regression_summary["blockers"])
    if blockers:
        body = _base_proposal(proposal_id, recommendation, regression_summary, status="FAIL")
        body.update({"applyAllowed": False, "refusalReasons": blockers, "candidateChanges": []})
        return _with_summary_and_digest(body)

    before = str(recommendation.get("currentMode") or recommendation.get("recommendedMode") or "standard")
    after = str(recommendation.get("recommendedMode") or before)
    protected = protected_work(recommendation, risk_flags=risk_flags)
    refusing = _refusal_reasons(recommendation, regression_summary, before=before, after=after, protected=protected)
    candidate_changes = [_candidate_change(recommendation, before=before, after=after, applies=not refusing)]
    body = _base_proposal(proposal_id, recommendation, regression_summary, status="PASS")
    body.update(
        {
            "applyAllowed": not refusing,
            "refusalReasons": refusing,
            "candidateChanges": candidate_changes,
            "expectedBenefit": _expected_benefit(recommendation, before=before, after=after),
            "qualityConstraints": _quality_constraints(recommendation, protected=protected),
            "rollback": _rollback(candidate_changes),
        }
    )
    return _with_summary_and_digest(body)


def build_policy_summary(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SUMMARY_SCHEMA,
        "latestUserIntent": "Tune lifecycle policy only when it reduces overhead without lowering required quality.",
        "activeDecisions": [
            f"status={proposal.get('status')}",
            f"applyAllowed={proposal.get('applyAllowed')}",
            f"proposalId={proposal.get('proposalId')}",
        ],
        "openBlockers": list(proposal.get("refusalReasons", [])),
        "acceptedEvidence": [
            {
                "id": "policy-proposal",
                "status": proposal.get("status"),
                "applyAllowed": proposal.get("applyAllowed") is True,
            }
        ],
        "changedFiles": [],
        "nextRequiredAction": "review proposal and apply only with explicit approval",
        "doNotDo": [
            "Do not auto-apply policy changes.",
            "Do not reduce validation for protected task classes.",
        ],
        "applyAllowed": proposal.get("applyAllowed") is True,
        "candidateChanges": proposal.get("candidateChanges", [])[:8],
        "qualityConstraints": proposal.get("qualityConstraints", {}),
    }


def require_policy_proposal_pass(proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("status") == "FAIL":
        raise LifecycleError("policy-proposal-failed", "policy proposal validation failed", {"proposal": proposal})
    return proposal


def build_optimization_proposal(
    recommendation: dict[str, Any],
    *,
    approved: bool = False,
    target_kind: str = "project-profile",
    target_revision: str | None = None,
    frozen_plan: bool = False,
    proposal_id: str = "audit-optimization-proposal",
) -> dict[str, Any]:
    """Turn a quality-safe audit recommendation into an explicit proposal.

    The optimizer never mutates a profile or plan. ``approved`` only records
    the operator decision; a separate apply function writes a new artifact.
    """

    refusal_reasons: list[dict[str, Any]] = []
    if recommendation.get("schemaVersion") != AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA:
        refusal_reasons.append({"code": "optimization-recommendation-schema"})
    if recommendation.get("status") != "PASS":
        refusal_reasons.append({"code": "optimization-recommendation-status", "status": recommendation.get("status")})
    if recommendation.get("advisoryOnly") is not True or recommendation.get("autoApply") is not False:
        refusal_reasons.append({"code": "optimization-advisory-boundary"})
    if recommendation.get("qualityFloorPreserved") is not True:
        refusal_reasons.append({"code": "optimization-quality-floor"})
    if target_kind not in _OPTIMIZATION_TARGETS:
        refusal_reasons.append({"code": "optimization-target-invalid", "target": target_kind})
    if frozen_plan:
        refusal_reasons.append({"code": "optimization-frozen-plan-mutation"})
    if not approved:
        refusal_reasons.append({"code": "optimization-explicit-approval-required"})

    candidate_changes = _bounded_optimization_changes(recommendation.get("changes"))
    if isinstance(recommendation.get("changes"), list) and len(candidate_changes) != len(recommendation["changes"]):
        refusal_reasons.append({"code": "optimization-change-invalid"})
    if recommendation.get("status") == "PASS" and not candidate_changes:
        refusal_reasons.append({"code": "optimization-no-bounded-change"})
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_PROPOSAL_SCHEMA,
        "status": "PASS"
        if recommendation.get("status") == "PASS"
        and not any(
            item.get("code")
            in {
                "optimization-recommendation-schema",
                "optimization-recommendation-status",
                "optimization-advisory-boundary",
                "optimization-quality-floor",
                "optimization-target-invalid",
            }
            for item in refusal_reasons
        )
        else "FAIL",
        "proposalId": proposal_id,
        "sourceRecommendationDigest": recommendation.get("recommendationDigest") or canonical_digest(recommendation),
        "approvalRequired": True,
        "approval": {
            "status": "APPROVED" if approved else "PENDING",
            "recordedBy": "operator",
            "targetRevision": target_revision,
        },
        "target": {"kind": target_kind, "revision": target_revision, "frozenPlan": frozen_plan},
        "applyAllowed": not refusal_reasons,
        "candidateChanges": candidate_changes if recommendation.get("status") == "PASS" else [],
        "refusalReasons": refusal_reasons,
        "rollback": recommendation.get("rollback") or {"strategy": "keep current profile", "requiresReview": True},
        "advisoryOnly": True,
        "autoApply": False,
        "qualityFloorPreserved": recommendation.get("qualityFloorPreserved") is True,
        "productionPromotionClaimed": False,
    }
    return {**body, "proposalDigest": canonical_digest(body)}


def apply_optimization_proposal(proposal: dict[str, Any], output_path: Path) -> dict[str, Any]:
    """Write a new approved profile/revision artifact without mutating plans."""

    expected_digest = canonical_digest({key: value for key, value in proposal.items() if key != "proposalDigest"})
    if proposal.get("proposalDigest") != expected_digest:
        raise LifecycleError(
            "optimization-proposal-digest",
            "optimization proposal digest does not match its contents",
            {"proposal": proposal},
        )
    if proposal.get("status") != "PASS" or proposal.get("applyAllowed") is not True:
        raise LifecycleError(
            "optimization-apply-not-allowed",
            "optimization proposal is not approved for application",
            {"proposal": proposal},
        )
    approval = _object(proposal.get("approval"))
    if proposal.get("approvalRequired") is not True or approval.get("status") != "APPROVED":
        raise LifecycleError(
            "optimization-approval-missing", "explicit operator approval is required", {"proposal": proposal}
        )
    target = _object(proposal.get("target"))
    if target.get("frozenPlan") is True or target.get("kind") not in _OPTIMIZATION_TARGETS:
        raise LifecycleError(
            "optimization-target-not-writable",
            "optimization cannot mutate a frozen plan or unknown target",
            {"target": target},
        )
    if output_path.name in {"plan.manifest.json", "plan.lock.json"}:
        raise LifecycleError(
            "optimization-frozen-artifact",
            "optimization output cannot replace a plan artifact",
            {"path": output_path.as_posix()},
        )
    changes = _bounded_optimization_changes(proposal.get("candidateChanges"))
    if len(changes) != len(proposal.get("candidateChanges", [])):
        raise LifecycleError("optimization-change-invalid", "proposal contains an unbounded optimization change")
    body = {
        "schemaVersion": OPTIMIZATION_APPLIED_SCHEMA,
        "status": "PASS",
        "target": target,
        "sourceProposalDigest": proposal.get("proposalDigest") or canonical_digest(proposal),
        "changes": changes,
        "rollback": proposal.get("rollback"),
        "approval": approval,
        "qualityFloorPreserved": True,
        "productionPromotionClaimed": False,
    }
    payload = write_json_create(output_path, body)
    result = {
        "schemaVersion": AUDIT_OPTIMIZATION_APPLY_RESULT_SCHEMA,
        "status": "PASS",
        "outputPath": output_path.as_posix(),
        "outputBytes": len(payload),
        "outputDigest": canonical_digest(body),
        "proposalDigest": proposal.get("proposalDigest") or canonical_digest(proposal),
        "changed": bool(changes),
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**result, "applyDigest": canonical_digest(result)}


def require_optimization_proposal_pass(proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("status") != "PASS":
        raise LifecycleError(
            "optimization-proposal-failed", "audit optimization proposal failed validation", {"proposal": proposal}
        )
    return proposal


def _bounded_optimization_changes(changes: Any) -> list[dict[str, Any]]:
    if not isinstance(changes, list):
        return []
    bounded: list[dict[str, Any]] = []
    for item in changes:
        if (
            not isinstance(item, dict)
            or item.get("field") not in _OPTIMIZATION_CHANGE_FIELDS
            or item.get("bounded") is not True
        ):
            continue
        value = item.get("after")
        if item["field"] == "routeClass":
            if (
                not isinstance(value, str)
                or len(value) > 64
                or any(token in value.lower() for token in ("openai", "anthropic", "google", "claude", "gpt", "gemini"))
            ):
                continue
        elif (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not (
                _OPTIMIZATION_CHANGE_LIMITS[item["field"]][0] <= value <= _OPTIMIZATION_CHANGE_LIMITS[item["field"]][1]
            )
        ):
            continue
        bounded.append({"field": item["field"], "before": item.get("before"), "after": value, "bounded": True})
    return bounded


def _recommendation_blockers(recommendation: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if recommendation.get("schemaVersion") != RECOMMENDATION_SCHEMA:
        blockers.append({"code": "policy-recommendation-schema"})
    if recommendation.get("status") != "PASS":
        blockers.append({"code": "policy-recommendation-status", "status": recommendation.get("status")})
    if recommendation.get("advisoryOnly") is not True or recommendation.get("autoApply") is not False:
        blockers.append({"code": "policy-recommendation-safety-flags"})
    if recommendation.get("qualityFloorPreserved") is not True:
        blockers.append({"code": "policy-recommendation-quality-floor"})
    return blockers


def _refusal_reasons(
    recommendation: dict[str, Any],
    regression_summary: dict[str, Any],
    *,
    before: str,
    after: str,
    protected: bool,
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    if recommendation.get("confidence") == "LOW":
        reasons.append({"code": "policy-low-confidence"})
    if before == after:
        reasons.append({"code": "policy-no-change", "mode": before})
    if protected and is_downgrade(before, after):
        reasons.append({"code": "policy-protected-downgrade", "before": before, "after": after})
    if regression_summary["status"] == "BLOCK":
        reasons.append({"code": "policy-regression-signals", "count": len(regression_summary["blockingSignals"])})
    return reasons


def _base_proposal(
    proposal_id: str,
    recommendation: dict[str, Any],
    regression_summary: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": PROPOSAL_SCHEMA,
        "status": status,
        "proposalId": proposal_id,
        "taskShape": recommendation.get("taskShape"),
        "sourceRecommendationDigest": recommendation.get("recommendationDigest") or canonical_digest(recommendation),
        "regressionSignals": regression_summary,
        "advisoryOnly": True,
        "autoApply": False,
        "productionPromotionClaimed": False,
    }


def _candidate_change(recommendation: dict[str, Any], *, before: str, after: str, applies: bool) -> dict[str, Any]:
    task_shape = recommendation.get("taskShape") or "feature"
    return {
        "path": f"taskShapes.{task_shape}.defaultMode",
        "before": before,
        "after": after,
        "applies": applies,
    }


def _expected_benefit(recommendation: dict[str, Any], *, before: str, after: str) -> dict[str, Any]:
    stats = _object(recommendation.get("statistics"))
    selected_signal = _object(stats.get("selectedSignal"))
    totals = _object(stats.get("totals"))
    pipeline = _object(totals.get("pipelineCompliance"))
    coordination = _object(totals.get("coordination"))
    ratios = _object(stats.get("ratios"))
    return {
        "kind": "reduce-process-overhead" if is_downgrade(before, after) else "preserve-or-increase-quality",
        "processOverheadTokens": int(pipeline.get("tokens", 0)) + int(coordination.get("tokens", 0)),
        "pipelineTokenShare": ratios.get("pipelineTokenShare", 0.0),
        "localAverageTokens": selected_signal.get("averageTokens"),
        "localSuccessRate": selected_signal.get("successRate"),
    }


def _quality_constraints(recommendation: dict[str, Any], *, protected: bool) -> dict[str, Any]:
    return {
        "qualityFloor": recommendation.get("qualityFloor"),
        "qualityFloorPreserved": True,
        "protectedWork": protected,
        "nonNegotiable": [
            "acceptance evidence",
            "final proof",
            "security review for security-sensitive work",
            "release review for release work",
            "adapter promotion evidence for adapter maturity claims",
        ],
    }


def _rollback(changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "strategy": "restore previous policy values and rerun recommendation",
        "restore": [{"path": item["path"], "value": item["before"]} for item in changes],
        "requiresReview": True,
    }


def _with_summary_and_digest(body: dict[str, Any]) -> dict[str, Any]:
    body["compactSummary"] = build_policy_summary(body)
    return {**body, "proposalDigest": canonical_digest(body)}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
