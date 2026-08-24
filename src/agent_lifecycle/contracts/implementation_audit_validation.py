"""Pure validation of implementation-audit result contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

IMPLEMENTATION_AUDIT_SCHEMA = "agent-implementation-audit-report.v1"
FINAL_IMPLEMENTATION_AUDIT_SCHEMA = "agent-final-implementation-audit.v1"
FINAL_AUDIT_OUTCOME_VERDICTS = {"ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"}


def validate_final_audit_outcome_report(
    report: dict[str, Any],
    *,
    state: dict[str, Any],
    verdict: str,
    task_ids: list[str],
    finding_ids: list[str],
) -> dict[str, Any]:
    """Validate the independent final-audit decision before state mutation."""

    blockers: list[dict[str, Any]] = []
    if verdict not in FINAL_AUDIT_OUTCOME_VERDICTS:
        blockers.append({"code": "final-audit-outcome-verdict-invalid"})
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    _check_expected(report, expected, blockers, prefix="final-audit-outcome")
    if report.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "final-audit-outcome-production-claim"})
    findings = report.get("findings")
    if not isinstance(findings, list):
        blockers.append({"code": "final-audit-outcome-findings-invalid"})
        findings = []
    open_ids = sorted(
        str(item.get("id"))
        for item in findings
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("id")
        and item.get("status") == "open"
    )
    if sorted(set(finding_ids)) != open_ids and verdict == "REWORK":
        blockers.append({
            "code": "final-audit-outcome-findings-mismatch",
            "expected": open_ids,
            "actual": sorted(set(finding_ids)),
        })
    verifier = report.get("verifier")
    if verifier is None and isinstance(report.get("completionSignal"), dict):
        verifier = report["completionSignal"].get("verifier")
    if verifier is None:
        verifier = report.get("auditor")
    if not isinstance(verifier, dict) or verifier.get("independent") is not True:
        blockers.append({"code": "final-audit-outcome-not-independent"})
    if verdict == "ACCEPTED":
        if report.get("status") != "PASS" or report.get("semanticStatus") != "READY_FOR_FINALIZATION":
            blockers.append({"code": "final-audit-outcome-not-accepted"})
        if task_ids or finding_ids:
            blockers.append({"code": "final-audit-outcome-accepted-has-targets"})
    elif verdict == "REWORK":
        if report.get("status") not in {"PASS", "FAIL"}:
            blockers.append({"code": "final-audit-outcome-rework-status-invalid"})
        if not task_ids:
            blockers.append({"code": "final-audit-outcome-tasks-required"})
        if not finding_ids:
            blockers.append({"code": "final-audit-outcome-findings-required"})
    elif verdict == "CONTRACT_CHANGE":
        if not isinstance(report.get("contractChangeRequest"), dict):
            blockers.append({"code": "final-audit-outcome-contract-change-required"})
    elif verdict == "BLOCKED" and not isinstance(report.get("blocker"), dict):
        blockers.append({"code": "final-audit-outcome-blocker-required"})
    body = {
        "schemaVersion": "agent-final-audit-outcome-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "verdict": verdict,
        "taskIds": sorted(set(task_ids)),
        "findingIds": sorted(set(finding_ids)),
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_implementation_audit_report(
    report: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    report_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = report_identity
    blockers: list[dict[str, Any]] = []
    if report.get("schemaVersion") != IMPLEMENTATION_AUDIT_SCHEMA:
        blockers.append(
            {"code": "implementation-audit-schema", "message": "unsupported implementation audit schemaVersion"}
        )
    if report.get("reportDigest") != canonical_digest(
        {key: value for key, value in report.items() if key != "reportDigest"}
    ):
        blockers.append({"code": "implementation-audit-digest", "message": "reportDigest does not match report body"})
    if report.get("productionPromotionClaimed") is not False:
        blockers.append(
            {
                "code": "implementation-audit-production-claim",
                "message": "implementation audit must not claim production promotion",
            }
        )
    if report.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "implementation-audit-status", "message": "status must be PASS or FAIL"})
    verdict = report.get("verdict")
    if verdict not in {"ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"}:
        blockers.append({"code": "implementation-audit-verdict", "message": "verdict is unsupported"})
    if report.get("status") == "PASS" and verdict != "ACCEPTED":
        blockers.append(
            {"code": "implementation-audit-status-verdict", "message": "PASS status requires ACCEPTED verdict"}
        )
    if report.get("status") == "FAIL" and verdict == "ACCEPTED":
        blockers.append(
            {"code": "implementation-audit-status-verdict", "message": "ACCEPTED verdict requires PASS status"}
        )
    if report.get("status") == "PASS" and _has_blockers(report):
        blockers.append(
            {"code": "implementation-audit-open-blockers", "message": "PASS report must not contain blockers"}
        )
    if report.get("status") == "PASS" and _has_open_blocking_findings(report):
        blockers.append(
            {
                "code": "implementation-audit-open-findings",
                "message": "PASS report must not contain open Medium or higher findings",
            }
        )
    auditor = report.get("auditor")
    if not isinstance(auditor, dict) or auditor.get("independent") is not True:
        blockers.append({"code": "implementation-audit-auditor", "message": "auditor must be independent"})
    if state is not None:
        _check_expected(
            report,
            {
                "runId": state.get("runId"),
                "packageId": state.get("packageId"),
                "planRevision": state.get("planRevision"),
                "planDigest": state.get("planDigest"),
                "sourceRevision": state.get("sourceRevision"),
            },
            blockers,
            prefix="implementation-audit",
        )
    if task is not None:
        _check_expected(
            report, {"taskId": task.get("id"), "attempt": task.get("attempt")}, blockers, prefix="implementation-audit"
        )
    body = {
        "schemaVersion": "agent-implementation-audit-report-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "verdict": verdict,
        "blockers": blockers,
        "reportDigest": report.get("reportDigest"),
        "planCompatibility": None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_implementation_audit_accepted(validation: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or report.get("verdict") != "ACCEPTED" or report.get("status") != "PASS":
        raise LifecycleError(
            "implementation-audit-not-accepted",
            "implementation audit report is not accepted",
            {"validation": validation, "verdict": report.get("verdict")},
        )
    return validation


def require_implementation_audit_rework(validation: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Require a valid independent audit that explicitly requests rework."""

    if validation.get("status") != "PASS" or report.get("verdict") != "REWORK" or report.get("status") != "FAIL":
        raise LifecycleError(
            "implementation-audit-not-rework",
            "implementation audit report does not authorize task rework",
            {"validation": validation, "verdict": report.get("verdict")},
        )
    return validation


def validate_final_implementation_audit(
    audit: dict[str, Any], *, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if audit.get("schemaVersion") != FINAL_IMPLEMENTATION_AUDIT_SCHEMA:
        blockers.append(
            {
                "code": "final-implementation-audit-schema",
                "message": "unsupported final implementation audit schemaVersion",
            }
        )
    if audit.get("auditDigest") != canonical_digest(
        {key: value for key, value in audit.items() if key != "auditDigest"}
    ):
        blockers.append(
            {"code": "final-implementation-audit-digest", "message": "auditDigest does not match audit body"}
        )
    if audit.get("status") != "PASS":
        blockers.append(
            {"code": "final-implementation-audit-status", "message": "final implementation audit status must be PASS"}
        )
    if audit.get("status") == "PASS" and _has_blockers(audit):
        blockers.append(
            {
                "code": "final-implementation-audit-open-blockers",
                "message": "PASS final implementation audit must not contain blockers",
            }
        )
    if audit.get("status") == "PASS" and _has_open_blocking_findings(audit):
        blockers.append(
            {
                "code": "final-implementation-audit-open-findings",
                "message": "PASS final implementation audit must not contain open Medium or higher findings",
            }
        )
    if audit.get("productionPromotionClaimed") is not False:
        blockers.append(
            {
                "code": "final-implementation-audit-production-claim",
                "message": "audit must not claim production promotion",
            }
        )
    if state is not None:
        _check_expected(
            audit,
            {
                "runId": state.get("runId"),
                "packageId": state.get("packageId"),
                "planRevision": state.get("planRevision"),
                "planDigest": state.get("planDigest"),
                "sourceRevision": state.get("sourceRevision"),
            },
            blockers,
            prefix="final-implementation-audit",
        )
    body = {
        "schemaVersion": "agent-final-implementation-audit-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "auditDigest": audit.get("auditDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _check_expected(
    payload: dict[str, Any], expected: dict[str, Any], blockers: list[dict[str, Any]], *, prefix: str
) -> None:
    for key, value in expected.items():
        if payload.get(key) != value:
            blockers.append(
                {"code": f"{prefix}-lineage-mismatch", "field": key, "expected": value, "actual": payload.get(key)}
            )


def _has_blockers(payload: dict[str, Any]) -> bool:
    blockers = payload.get("blockers")
    return isinstance(blockers, list) and bool(blockers)


def _has_open_blocking_findings(payload: dict[str, Any]) -> bool:
    findings = payload.get("findings")
    return isinstance(findings, list) and any(
        isinstance(item, dict)
        and item.get("status") == "open"
        and item.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
        for item in findings
    )


__all__ = [
    "FINAL_IMPLEMENTATION_AUDIT_SCHEMA",
    "IMPLEMENTATION_AUDIT_SCHEMA",
    "require_implementation_audit_accepted",
    "require_implementation_audit_rework",
    "validate_final_implementation_audit",
    "validate_implementation_audit_report",
]
