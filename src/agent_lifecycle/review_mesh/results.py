"""Review Mesh reviewer result import helpers."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.thread_bridge_schemas import (
    validate_thread_context_import,
)
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_result,
    require_review_mesh_result_pass,
    validate_review_mesh_result,
)

_SECRET_PATTERNS = (
    re.compile(r"\b[A-Z][A-Z0-9_]{2,}_API_KEY\s*=\s*[^\s]+"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
)
_LOCAL_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?:/Volumes|/Users|/private|/var/folders)/[^\s\"'`]+")


def import_review_mesh_result(
    *,
    profile: dict[str, Any],
    assignment: dict[str, Any],
    reviewer_output: dict[str, Any],
    allow_local_evidence_refs: bool = False,
) -> dict[str, Any]:
    """Normalize a reviewer output object into a redacted Review Mesh result."""

    sanitized, redaction = _sanitize_payload(reviewer_output, allow_local_evidence_refs=allow_local_evidence_refs)
    findings = sanitized.get("findings", []) if isinstance(sanitized.get("findings"), list) else []
    budget_usage = sanitized.get("budgetUsage") if isinstance(sanitized.get("budgetUsage"), dict) else {}
    result = build_review_mesh_result(
        profile=profile,
        assignment=assignment,
        budget_usage={
            "invocations": _non_negative_int(budget_usage.get("invocations"), 0),
            "inputTokens": _non_negative_int(budget_usage.get("inputTokens"), 0),
            "outputTokens": _non_negative_int(budget_usage.get("outputTokens"), 0),
            "wallSeconds": _non_negative_int(budget_usage.get("wallSeconds"), 0),
        },
        findings=findings,
        status=sanitized.get("status") if sanitized.get("status") in {"PASS", "FAIL", "SKIPPED"} else None,
        live_calls_started=bool(sanitized.get("liveCallsStarted")),
    )
    body = {
        **{key: value for key, value in result.items() if key != "resultDigest"},
        "redaction": redaction,
        "import": {
            "schemaVersion": str(reviewer_output.get("schemaVersion") or "reviewer-output.unknown"),
            "rawOutputStored": False,
            "outputDigest": canonical_digest(reviewer_output),
            "sanitizedOutputDigest": canonical_digest(sanitized),
        },
    }
    normalized = {**body, "resultDigest": canonical_digest(body)}
    require_review_mesh_result_pass(validate_review_mesh_result(normalized, profile=profile))
    return normalized


def build_thread_context_review_input(imported_context: dict[str, Any]) -> dict[str, Any]:
    """Project thread context into a Review Mesh input without elevating authority."""

    validation = validate_thread_context_import(imported_context)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "review-mesh-thread-context-invalid",
            "thread context cannot be used for review",
            {"validation": validation},
        )
    source = imported_context.get("source") if isinstance(imported_context.get("source"), dict) else {}
    body = {
        "schemaVersion": "agent-review-mesh-thread-context-input.v1",
        "sourceRole": "optional-thread-context",
        "sourceId": source.get("sourceId", "redacted"),
        "importDigest": imported_context["importDigest"],
        "content": imported_context.get("content", {}),
        "sourceOfTruth": False,
        "proof": False,
        "promptAuthorityGranted": False,
        "toolApprovalGranted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "inputDigest": canonical_digest(body)}


def project_review_result_for_optimization(result: dict[str, Any]) -> dict[str, Any]:
    """Project a Review Mesh result without copying reviewer output or identity names."""

    if not isinstance(result, dict):
        raise LifecycleError("review-mesh-result-projection-invalid", "Review Mesh result must be an object")
    findings = result.get("findings") if isinstance(result.get("findings"), list) else []
    severity_counts: dict[str, int] = {}
    accepted = 0
    rejected = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity = finding.get("severity") if isinstance(finding.get("severity"), str) else "INFO"
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        status = str(finding.get("status", "open")).lower()
        if status in {"accepted", "fixed", "closed"}:
            accepted += 1
        if status in {"rejected", "dismissed"}:
            rejected += 1
    reviewer = result.get("reviewer") if isinstance(result.get("reviewer"), dict) else {}
    independence = result.get("independence") if isinstance(result.get("independence"), dict) else {}
    subject = result.get("subject") if isinstance(result.get("subject"), dict) else {}
    projection = {
        "status": result.get("status") if result.get("status") in {"PASS", "FAIL", "SKIPPED"} else "UNKNOWN",
        "findingCount": len(findings),
        "severityCounts": dict(sorted(severity_counts.items())),
        "acceptedCount": accepted,
        "rejectedCount": rejected,
        "disagreementCount": int(result.get("disagreementCount", 0)) if isinstance(result.get("disagreementCount"), int) else 0,
        "independenceStatus": independence.get("status") if independence.get("status") in {"INDEPENDENT", "NOT_REQUIRED", "NOT_PROVEN"} else "MISSING",
        "reviewerRole": reviewer.get("role") if isinstance(reviewer.get("role"), str) else "unknown",
        "modelRouteClass": reviewer.get("modelClass") if isinstance(reviewer.get("modelClass"), str) else "unknown",
        "phase": result.get("phase") if isinstance(result.get("phase"), str) else subject.get("phase", "unknown"),
    }
    for field in ("hostIdentityHash", "modelIdentityHash"):
        if isinstance(reviewer.get(field), str) and len(reviewer[field]) == 64:
            projection[field] = reviewer[field]
    return projection


def _sanitize_payload(value: Any, *, allow_local_evidence_refs: bool) -> tuple[Any, dict[str, Any]]:
    stats = {"secretLikeMarkersRedacted": 0, "localPathsRedacted": 0}
    sanitized = _sanitize_value(value, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path="$")
    status = "REDACTED" if stats["secretLikeMarkersRedacted"] or stats["localPathsRedacted"] else "PASS"
    return sanitized, {
        "status": status,
        "secretLikeMarkersRedacted": stats["secretLikeMarkersRedacted"],
        "localPathsRedacted": stats["localPathsRedacted"],
        "localPathPolicy": "explicit-plan-owned-reference" if allow_local_evidence_refs else "reject-local-absolute-paths",
    }


def _sanitize_value(value: Any, *, stats: dict[str, int], allow_local_evidence_refs: bool, path: str) -> Any:
    if isinstance(value, str):
        text = value
        for pattern in _SECRET_PATTERNS:
            text, count = pattern.subn("[REDACTED]", text)
            stats["secretLikeMarkersRedacted"] += count
        matches = list(_LOCAL_PATH_PATTERN.finditer(text))
        if matches and not allow_local_evidence_refs:
            raise LifecycleError("review-mesh-local-path-leakage", "reviewer output contains a local absolute path", {"path": path})
        if matches:
            text = _LOCAL_PATH_PATTERN.sub("[LOCAL_PATH]", text)
            stats["localPathsRedacted"] += len(matches)
        return text
    if isinstance(value, dict):
        return {key: _sanitize_value(item, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path=f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, stats=stats, allow_local_evidence_refs=allow_local_evidence_refs, path=f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default
