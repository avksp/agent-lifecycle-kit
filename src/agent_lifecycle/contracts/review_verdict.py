"""Provider-neutral structured review-verdict contract validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

REVIEW_VERDICT_SCHEMA = "agent-review-verdict.v1"
REVIEW_VERDICT_VALIDATION_SCHEMA = "agent-review-verdict-validation.v1"
DIMENSIONS = ("requirementFit", "implementationQuality", "evidenceQuality", "residualRisk")
DIMENSION_STATUSES = {"PASS", "WARN", "FAIL"}
OVERALL_VERDICTS = {"ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"}
NEXT_ACTIONS = {"accept", "fix-implementation", "strengthen-evidence", "reopen-contract", "block-external"}


def validate_review_verdict(verdict: dict[str, Any], *, findings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not isinstance(verdict, dict):
        raise LifecycleError("invalid-review-verdict", "review verdict must be an object")
    blockers: list[dict[str, Any]] = []
    if verdict.get("schemaVersion") != REVIEW_VERDICT_SCHEMA:
        blockers.append({"code": "invalid-review-verdict-schema", "message": "unsupported review verdict schemaVersion"})
    overall = verdict.get("overall")
    if overall not in OVERALL_VERDICTS:
        blockers.append({"code": "invalid-review-verdict-overall", "message": "overall verdict is unsupported"})
    dimensions = verdict.get("dimensions")
    if not isinstance(dimensions, dict):
        blockers.append({"code": "invalid-review-verdict-dimensions", "message": "dimensions must be an object"})
        dimensions = {}
    missing = sorted(set(DIMENSIONS).difference(dimensions))
    if missing:
        blockers.append({"code": "review-verdict-dimension-missing", "dimensions": missing})
    failing_dimensions: list[str] = []
    warning_dimensions: list[str] = []
    for name in DIMENSIONS:
        dimension = dimensions.get(name)
        if not isinstance(dimension, dict):
            continue
        status = dimension.get("status")
        if status not in DIMENSION_STATUSES:
            blockers.append({"code": "review-verdict-dimension-status", "dimension": name, "status": status})
            continue
        reason = dimension.get("reasonCode")
        if not isinstance(reason, str) or not reason:
            blockers.append({"code": "review-verdict-dimension-reason-missing", "dimension": name})
        summary = dimension.get("summary")
        if not isinstance(summary, str) or not summary:
            blockers.append({"code": "review-verdict-dimension-summary-missing", "dimension": name})
        if status == "FAIL":
            failing_dimensions.append(name)
        elif status == "WARN":
            warning_dimensions.append(name)
    routing = verdict.get("routing")
    if not isinstance(routing, dict):
        blockers.append({"code": "invalid-review-verdict-routing", "message": "routing must be an object"})
        routing = {}
    next_action = routing.get("nextAction")
    if next_action not in NEXT_ACTIONS:
        blockers.append({"code": "review-verdict-routing-action", "nextAction": next_action})
    target = routing.get("target")
    if target is not None and (not isinstance(target, str) or not target):
        blockers.append({"code": "review-verdict-routing-target", "message": "routing target must be a non-empty string"})
    open_medium_plus = _open_medium_plus(findings or [])
    if open_medium_plus:
        blockers.append({"code": "review-verdict-open-findings", "findings": open_medium_plus})
    if overall == "ACCEPTED" and (failing_dimensions or open_medium_plus):
        blockers.append({"code": "review-verdict-accepted-with-blockers", "dimensions": failing_dimensions, "findings": open_medium_plus})
    if overall == "ACCEPTED" and next_action != "accept":
        blockers.append({"code": "review-verdict-routing-mismatch", "overall": overall, "nextAction": next_action})
    if overall != "ACCEPTED" and next_action == "accept":
        blockers.append({"code": "review-verdict-routing-mismatch", "overall": overall, "nextAction": next_action})
    body = {
        "schemaVersion": REVIEW_VERDICT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "overall": overall,
        "failingDimensions": failing_dimensions,
        "warningDimensions": warning_dimensions,
        "nextAction": next_action,
        "blockers": blockers,
    }
    return {**body, "verdictDigest": canonical_digest(verdict), "validationDigest": canonical_digest(body)}


def require_review_verdict_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("review-verdict-validation-failed", "review verdict validation failed", {"validation": payload})
    return payload


def compact_review_routing(verdict: dict[str, Any]) -> dict[str, Any]:
    validation = validate_review_verdict(verdict)
    dimensions = verdict.get("dimensions", {})
    return {
        "schemaVersion": "agent-review-routing-summary.v1",
        "status": validation["status"],
        "overall": validation["overall"],
        "nextAction": validation["nextAction"],
        "failingDimensions": validation["failingDimensions"],
        "warningDimensions": validation["warningDimensions"],
        "dimensionStatus": {
            key: dimensions.get(key, {}).get("status")
            for key in DIMENSIONS
            if isinstance(dimensions.get(key), dict)
        },
        "verdictDigest": validation["verdictDigest"],
    }


def _open_medium_plus(findings: list[dict[str, Any]]) -> list[str]:
    return [
        str(finding.get("id") or "<unknown>")
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("status") == "open"
        and finding.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
    ]
