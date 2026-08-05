"""Review Mesh reviewer result import helpers."""

from __future__ import annotations

import re
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
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
