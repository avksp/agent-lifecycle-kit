"""Build read-only lifecycle policy tuning proposals."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics import summarize_regression_signals
from agent_lifecycle.policy.quality_floor import is_downgrade, protected_work

PROPOSAL_SCHEMA = "agent-lifecycle-policy-proposal.v1"
SUMMARY_SCHEMA = "agent-lifecycle-policy-summary.v1"
RECOMMENDATION_SCHEMA = "agent-lifecycle-recommendation.v1"


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
    stats = recommendation.get("statistics") if isinstance(recommendation.get("statistics"), dict) else {}
    totals = stats.get("totals") if isinstance(stats.get("totals"), dict) else {}
    pipeline = totals.get("pipelineCompliance", {}) if isinstance(totals.get("pipelineCompliance"), dict) else {}
    coordination = totals.get("coordination", {}) if isinstance(totals.get("coordination"), dict) else {}
    return {
        "kind": "reduce-process-overhead" if is_downgrade(before, after) else "preserve-or-increase-quality",
        "processOverheadTokens": int(pipeline.get("tokens", 0)) + int(coordination.get("tokens", 0)),
        "pipelineTokenShare": (stats.get("ratios") or {}).get("pipelineTokenShare", 0.0),
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
