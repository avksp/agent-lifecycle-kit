"""Review Mesh result synthesis helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.review_round_schemas import (
    ROUND_EXHAUSTION_OUTCOMES,
    build_review_round_evaluation,
    merge_finding_dispositions,
    validate_finding_disposition,
    validate_review_round_participation,
)
from agent_lifecycle.contracts.review_verdict import (
    BLOCKING_REVIEW_SEVERITIES,
    REVIEW_SEVERITY_RANK,
)
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_synthesis,
    require_review_mesh_result_pass,
    validate_review_mesh_result,
    validate_review_mesh_synthesis,
)


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
            "reviewerResultDigests": sorted(
                str(item.get("resultDigest")) for item in findings if item.get("resultDigest")
            ),
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

        raise LifecycleError(
            "review-mesh-synthesis-validation-failed",
            "Review Mesh synthesis validation failed",
            {"validation": validation},
        )
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
    ordered = sorted(
        findings,
        key=lambda item: (
            REVIEW_SEVERITY_RANK.get(str(item.get("severity", "INFO")), 99),
            str(item.get("resultDigest")),
        ),
    )
    representative = dict(ordered[0])
    representative.setdefault("id", key)
    representative.pop("resultDigest", None)
    return representative


def _blocking_finding(finding: dict[str, Any]) -> bool:
    return (
        str(finding.get("status", "open")).strip().lower() == "open"
        and str(finding.get("severity", "INFO")).strip().upper() in BLOCKING_REVIEW_SEVERITIES
    )


def evaluate_review_round(
    *,
    synthesis: dict[str, Any],
    participations: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
    round_number: int,
    max_rounds: int,
    exhaustion_outcome: str | None = None,
) -> dict[str, Any]:
    """Evaluate one bounded round without treating agreement as remediation."""

    blockers: list[dict[str, Any]] = []
    synthesis_validation = validate_review_mesh_synthesis(synthesis)
    if synthesis_validation["status"] != "PASS":
        blockers.append({"code": "review-round-synthesis-invalid"})

    participating_ids: list[str] = []
    participating_findings: dict[str, dict[str, Any]] = {}
    resource_use_count = 0
    seen_reviewers: set[str] = set()
    for receipt in participations:
        validation = validate_review_round_participation(receipt)
        reviewer_id = receipt.get("reviewerId") if isinstance(receipt, dict) else None
        if validation["status"] != "PASS":
            blockers.append({"code": "review-round-participation-invalid", "reviewerId": reviewer_id})
            continue
        if receipt.get("resourceUseObserved") is True:
            resource_use_count += 1
        if not isinstance(reviewer_id, str) or not reviewer_id:
            blockers.append({"code": "review-round-reviewer-id-invalid"})
            continue
        if reviewer_id in seen_reviewers:
            blockers.append({"code": "review-round-participation-duplicate", "reviewerId": reviewer_id})
            continue
        seen_reviewers.add(reviewer_id)
        if receipt.get("participating") is True:
            participating_ids.append(reviewer_id)
            _collect_participating_findings(receipt, participating_findings, blockers)
    if not participating_ids:
        blockers.append({"code": "review-round-no-participating-reviewer"})

    finding_map = _round_findings(synthesis, blockers)
    for finding_id, finding in participating_findings.items():
        synthesized = finding_map.get(finding_id)
        if synthesized is None:
            blockers.append({"code": "review-round-participation-finding-unjoined", "findingId": finding_id})
            finding_map[finding_id] = finding
        elif canonical_digest(synthesized) != canonical_digest(finding):
            blockers.append({"code": "review-round-participation-finding-lineage-mismatch", "findingId": finding_id})
    try:
        merged_dispositions = merge_finding_dispositions([], dispositions)
    except LifecycleError as exc:
        blockers.append({"code": exc.code})
        merged_dispositions = []
    disposition_map = {item["findingId"]: item for item in merged_dispositions}
    for item in merged_dispositions:
        validation = validate_finding_disposition(item)
        if validation["status"] != "PASS":
            blockers.append({"code": "review-round-disposition-invalid", "findingId": item.get("findingId")})
            continue
        finding = finding_map.get(item["findingId"])
        if finding is None:
            blockers.append({"code": "review-round-disposition-orphan", "findingId": item["findingId"]})
        elif item.get("findingDigest") != canonical_digest(finding):
            blockers.append({"code": "review-round-disposition-lineage-mismatch", "findingId": item["findingId"]})

    missing_disposition_ids = sorted(set(finding_map).difference(disposition_map))
    for finding_id in missing_disposition_ids:
        blockers.append({"code": "review-round-disposition-missing", "findingId": finding_id})

    open_blocking_ids: list[str] = []
    for finding_id, finding in finding_map.items():
        if not _blocking_finding(finding):
            continue
        disposition = disposition_map.get(finding_id)
        rejected_false_positive = (
            isinstance(disposition, dict)
            and disposition.get("disposition") == "REJECTED"
            and disposition.get("reasonCode") == "false-positive"
            and disposition.get("findingDigest") == canonical_digest(finding)
        )
        if not rejected_false_positive:
            open_blocking_ids.append(finding_id)
            blockers.append({"code": "review-round-open-blocking-finding", "findingId": finding_id})

    if blockers:
        if round_number >= max_rounds:
            selected_outcome = exhaustion_outcome or "BLOCKED"
            if selected_outcome not in ROUND_EXHAUSTION_OUTCOMES:
                raise LifecycleError(
                    "review-round-exhaustion-outcome-invalid",
                    "exhausted rounds require an escalation outcome",
                )
        else:
            selected_outcome = "CONTINUE"
    else:
        selected_outcome = "ACCEPTED"
    return build_review_round_evaluation(
        round_number=round_number,
        max_rounds=max_rounds,
        outcome=selected_outcome,
        participating_reviewer_ids=participating_ids,
        resource_use_count=resource_use_count,
        finding_ids=list(finding_map),
        open_blocking_finding_ids=open_blocking_ids,
        missing_disposition_finding_ids=missing_disposition_ids,
        blockers=blockers,
    )


def _round_findings(synthesis: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    for bucket in ("acceptedFindings", "rejectedFindings", "unresolvedFindings"):
        values = synthesis.get(bucket, []) if isinstance(synthesis, dict) else []
        if not isinstance(values, list):
            blockers.append({"code": "review-round-finding-bucket-invalid", "bucket": bucket})
            continue
        for finding in values:
            if not isinstance(finding, dict):
                blockers.append({"code": "review-round-finding-invalid", "bucket": bucket})
                continue
            finding_id = finding.get("id")
            if not isinstance(finding_id, str) or not finding_id:
                blockers.append({"code": "review-round-finding-id-invalid", "bucket": bucket})
                continue
            prior = findings.get(finding_id)
            if prior is not None and prior != finding:
                blockers.append({"code": "review-round-finding-conflict", "findingId": finding_id})
                continue
            findings[finding_id] = dict(finding)
    return findings


def _collect_participating_findings(
    receipt: dict[str, Any],
    findings: dict[str, dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    values = receipt.get("findings")
    if not isinstance(values, list):
        blockers.append({"code": "review-round-participation-findings-invalid", "reviewerId": receipt.get("reviewerId")})
        return
    for finding in values:
        if not isinstance(finding, dict):
            blockers.append({"code": "review-round-participation-finding-invalid", "reviewerId": receipt.get("reviewerId")})
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            blockers.append({"code": "review-round-participation-finding-id-invalid", "reviewerId": receipt.get("reviewerId")})
            continue
        prior = findings.get(finding_id)
        if prior is not None and canonical_digest(prior) != canonical_digest(finding):
            blockers.append({"code": "review-round-participation-finding-conflict", "findingId": finding_id})
            continue
        findings[finding_id] = dict(finding)


__all__ = ["evaluate_review_round", "synthesize_review_mesh_results"]
