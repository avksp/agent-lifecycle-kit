"""Review Mesh result synthesis helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_synthesis,
    require_review_mesh_result_pass,
    validate_review_mesh_result,
    validate_review_mesh_synthesis,
)

_SEVERITY_RANK = {"CRITICAL": 0, "BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def synthesize_review_mesh_results(
    *,
    profile: dict[str, Any],
    results: list[dict[str, Any]],
    mode: str | None = None,
    subject: dict[str, Any] | None = None,
    accepted_finding_ids: list[str] | None = None,
    rejected_finding_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build deterministic agreement/conflict/unresolved lists from results."""

    for result in results:
        require_review_mesh_result_pass(validate_review_mesh_result(result, profile=profile))
    selected_mode = mode or (results[0]["mode"] if results else profile["defaultMode"])
    selected_subject = subject or (dict(results[0].get("subject", {})) if results else {})
    accepted_ids = set(accepted_finding_ids or [])
    rejected_ids = set(rejected_finding_ids or [])
    grouped = _group_findings(results)
    agreement: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for key, findings in sorted(grouped.items()):
        severities = {str(item.get("severity", "INFO")) for item in findings}
        statuses = {str(item.get("status", "open")) for item in findings}
        current_conflict = len(severities) > 1 or len(statuses) > 1
        summary = {
            "findingKey": key,
            "count": len(findings),
            "severities": sorted(severities),
            "reviewerResultDigests": sorted(str(item.get("resultDigest")) for item in findings if item.get("resultDigest")),
        }
        if len(findings) > 1 and len(severities) == 1 and len(statuses) == 1:
            agreement.append(summary)
        if current_conflict:
            conflicts.append(summary)
        representative = _representative_finding(key, findings)
        finding_id = str(representative.get("id") or key)
        if finding_id in rejected_ids:
            rejected.append(representative)
        elif finding_id in accepted_ids or (len(findings) > 1 and not current_conflict):
            accepted.append(representative)
        elif _blocking_finding(representative) or current_conflict:
            unresolved.append(representative)
    synthesis = build_review_mesh_synthesis(
        profile=profile,
        mode=selected_mode,
        subject=selected_subject,
        result_digests=[str(result["resultDigest"]) for result in results],
        agreement=agreement,
        conflicts=conflicts,
        accepted_findings=accepted,
        rejected_findings=rejected,
        unresolved_findings=unresolved,
    )
    validation = validate_review_mesh_synthesis(synthesis, profile=profile)
    if validation["status"] != "PASS":
        from agent_lifecycle.contracts import LifecycleError

        raise LifecycleError("review-mesh-synthesis-validation-failed", "Review Mesh synthesis validation failed", {"validation": validation})
    return synthesis


def _group_findings(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        for finding in result.get("findings", []):
            if not isinstance(finding, dict):
                continue
            key = str(finding.get("id") or finding.get("code") or canonical_digest(finding)[:16])
            grouped.setdefault(key, []).append({**finding, "resultDigest": result.get("resultDigest")})
    return grouped


def _representative_finding(key: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(findings, key=lambda item: (_SEVERITY_RANK.get(str(item.get("severity", "INFO")), 99), str(item.get("resultDigest"))))
    representative = dict(ordered[0])
    representative.setdefault("id", key)
    representative.pop("resultDigest", None)
    return representative


def _blocking_finding(finding: dict[str, Any]) -> bool:
    return str(finding.get("status", "open")) == "open" and str(finding.get("severity", "INFO")) in {"BLOCKER", "CRITICAL", "HIGH", "MEDIUM"}
