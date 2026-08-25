"""Shared workflow gates for implementation audit reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.independent_evidence_schemas import validate_independence_requirement
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.security_analysis_schemas import SECURITY_ANALYSIS_AUDIT_SCHEMA
from agent_lifecycle.quality.security_analysis import (
    security_analysis_high_severity,
    validate_security_analysis_audit,
    validate_security_verification_assignment,
)
from agent_lifecycle.review_mesh.contracts import validate_review_mesh_assignment
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root


def task_implementation_audit_required(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> bool:
    if state.get("implementationAuditRequired") is True or _required(state.get("implementationAudit")):
        return True
    if task.get("implementationAuditRequired") is True:
        return True
    if _security_verification_required(task):
        return True
    # The manifest-to-task security copy is policy data, not a second generic
    # implementation-audit switch. Ordinary tasks remain unaffected.
    if not isinstance(task.get("securityAnalysis"), dict) and _required(task.get("implementationAudit")):
        return True
    manifest = load_state_manifest(state_path, state)
    if manifest is None:
        return False
    if _required(manifest.get("implementationAudit")):
        return True
    for workstream in manifest.get("workstreams", []):
        if isinstance(workstream, dict) and workstream.get("id") == task.get("id"):
            return workstream.get("implementationAuditRequired") is True or _required(
                workstream.get("implementationAudit")
            )
    return False


def final_implementation_audit_required(state_path: Path, state: dict[str, Any]) -> bool:
    if state.get("finalImplementationAuditRequired") is True:
        return True
    implementation_audit = state.get("implementationAudit")
    if isinstance(implementation_audit, dict) and implementation_audit.get("finalRequired") is True:
        return True
    manifest = load_state_manifest(state_path, state)
    if manifest is None:
        return False
    manifest_audit = manifest.get("implementationAudit")
    return isinstance(manifest_audit, dict) and manifest_audit.get("finalRequired") is True


def validate_task_implementation_audit_artifact(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    report_path: str,
) -> dict[str, Any]:
    root = package_root(state_path, state)
    rel = normalize_repo_path(report_path, label="implementation audit report")
    report = read_json_object(root / rel, label="implementation audit report")
    if report.get("schemaVersion") == SECURITY_ANALYSIS_AUDIT_SCHEMA:
        security_validation = validate_security_analysis_audit(report, state=state, task=task)
        if (
            security_validation.get("status") != "PASS"
            or report.get("status") != "PASS"
            or report.get("verdict") != "ACCEPTED"
        ):
            raise LifecycleError(
                "security-analysis-verification-required",
                "security analysis audit is not an accepted independent verification",
                {"taskId": task.get("id"), "validation": security_validation},
            )
        _validate_security_verification_artifact(state_path, state, task, report)
        identity = artifact_identity(root, rel, report)
        return {
            **identity,
            "taskId": report.get("taskId"),
            "attempt": report.get("attempt"),
            "verdict": report.get("verdict"),
            "reportDigest": report.get("auditDigest"),
            "auditor": report.get("auditor"),
            "independentEvidenceIds": list(report.get("independentEvidenceIds", [])),
            "validation": {
                "status": security_validation["status"],
                "validationDigest": security_validation["validationDigest"],
            },
        }
    from agent_lifecycle.contracts.implementation_audit_validation import (
        require_implementation_audit_accepted,
        validate_implementation_audit_report,
    )

    identity = artifact_identity(root, rel, report)
    validation = validate_implementation_audit_report(
        report,
        state=state,
        task=task,
        report_identity=identity,
    )
    require_implementation_audit_accepted(validation, report)
    _validate_security_verification_artifact(state_path, state, task, report)
    return {
        **identity,
        "taskId": report.get("taskId"),
        "attempt": report.get("attempt"),
        "verdict": report.get("verdict"),
        "reportDigest": report.get("reportDigest"),
        "auditor": report.get("auditor"),
        "independentEvidenceIds": list(report.get("independentEvidenceIds", []))
        if isinstance(report.get("independentEvidenceIds"), list)
        else [],
        "validation": {
            "status": validation["status"],
            "validationDigest": validation["validationDigest"],
        },
    }


def validate_task_implementation_audit_for_rework(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    report_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate an independent audit without requiring an accepted verdict."""

    root = package_root(state_path, state)
    rel = normalize_repo_path(report_path, label="implementation audit report")
    report = read_json_object(root / rel, label="implementation audit report")
    if report.get("schemaVersion") == SECURITY_ANALYSIS_AUDIT_SCHEMA:
        security_validation = validate_security_analysis_audit(report, state=state, task=task)
        if security_validation.get("status") != "PASS":
            raise LifecycleError(
                "implementation-audit-invalid",
                "security analysis audit report failed contract validation",
                {"validation": security_validation},
            )
        identity = artifact_identity(root, rel, report)
        summary = {
            **identity,
            "taskId": report.get("taskId"),
            "attempt": report.get("attempt"),
            "verdict": report.get("verdict"),
            "reportDigest": report.get("auditDigest"),
            "auditor": report.get("auditor"),
            "independentEvidenceIds": list(report.get("independentEvidenceIds", [])),
            "validation": {
                "status": security_validation["status"],
                "validationDigest": security_validation["validationDigest"],
            },
        }
        return summary, report
    from agent_lifecycle.contracts.implementation_audit_validation import (
        require_implementation_audit_rework,
        validate_implementation_audit_report,
    )

    identity = artifact_identity(root, rel, report)
    validation = validate_implementation_audit_report(
        report,
        state=state,
        task=task,
        report_identity=identity,
    )
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "implementation-audit-invalid",
            "implementation audit report failed contract validation",
            {"validation": validation},
        )
    if report.get("verdict") == "REWORK":
        require_implementation_audit_rework(validation, report)
    summary = {
        **identity,
        "taskId": report.get("taskId"),
        "attempt": report.get("attempt"),
        "verdict": report.get("verdict"),
        "reportDigest": report.get("reportDigest"),
        "validation": {
            "status": validation["status"],
            "validationDigest": validation["validationDigest"],
        },
    }
    return summary, report


def task_has_accepted_implementation_audit(task: dict[str, Any]) -> bool:
    audit = task.get("implementationAuditReport")
    if not isinstance(audit, dict) or audit.get("verdict") != "ACCEPTED":
        return False
    if _security_verification_required(task):
        return (
            bool(audit.get("independentEvidenceIds"))
            and isinstance(audit.get("auditor"), dict)
            and audit["auditor"].get("independent") is True
        )
    return True


def missing_required_implementation_audits(state_path: Path, state: dict[str, Any]) -> list[str]:
    missing = []
    for task in state.get("tasks", []):
        if not isinstance(task, dict) or task.get("status") != "ACCEPTED":
            continue
        if task_implementation_audit_required(state_path, state, task) and not task_has_accepted_implementation_audit(
            task
        ):
            missing.append(str(task.get("id")))
    return missing


def load_state_manifest(state_path: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    manifest_path = state.get("manifestPath")
    if not isinstance(manifest_path, str) or not manifest_path:
        return None
    root = package_root(state_path, state)
    rel = normalize_repo_path(manifest_path, label="manifest path")
    path = root / rel
    if not path.is_file():
        return None
    return read_json_object(path, label="plan manifest")


def implementation_audit_blockers(state_path: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    for task in state.get("tasks", []):
        if not isinstance(task, dict):
            continue
        if task.get("status") not in {"VERIFYING", "ACCEPTED"}:
            continue
        if task_implementation_audit_required(state_path, state, task) and not task_has_accepted_implementation_audit(
            task
        ):
            code = (
                "security-analysis-verification-required"
                if _security_verification_required(task)
                else "implementation-audit-required"
            )
            blockers.append({"code": code, "taskId": task.get("id")})
    return blockers


def require_final_implementation_audit_pass(audit: dict[str, Any]) -> dict[str, Any]:
    if audit.get("status") != "PASS":
        raise LifecycleError(
            "final-implementation-audit-not-pass",
            "final implementation audit did not pass",
            {"blockers": audit.get("blockers", [])},
        )
    return audit


def _required(value: Any) -> bool:
    return isinstance(value, dict) and value.get("required") is True


def _security_verification_required(task: dict[str, Any]) -> bool:
    config = task.get("securityAnalysis")
    if not isinstance(config, dict) or not security_analysis_high_severity(task):
        return False
    policy = config.get("implementationAudit")
    return (
        isinstance(policy, dict)
        and policy.get("required") is True
        and policy.get("independentVerificationRequired") is True
    )


def _validate_security_verification_artifact(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    report: dict[str, Any],
) -> None:
    if not _security_verification_required(task):
        return
    evidence_ids = report.get("independentEvidenceIds")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise LifecycleError(
            "security-analysis-verification-required",
            "high-severity security remediation requires independent verification evidence",
            {"taskId": task.get("id")},
        )
    auditor = report.get("auditor")
    if not isinstance(auditor, dict) or auditor.get("independent") is not True:
        raise LifecycleError(
            "security-analysis-verification-required",
            "high-severity security remediation requires an independent auditor",
            {"taskId": task.get("id")},
        )
    config = task.get("securityAnalysis")
    assignment_path = (
        config.get("verificationEvidence", {}).get("assignmentPath")
        if isinstance(config, dict) and isinstance(config.get("verificationEvidence"), dict)
        else None
    )
    if not isinstance(assignment_path, str) or not assignment_path:
        raise LifecycleError(
            "security-analysis-verification-required",
            "high-severity security remediation requires a verification assignment",
            {"taskId": task.get("id")},
        )
    root = package_root(state_path, state)
    rel = normalize_repo_path(assignment_path, label="security verification assignment")
    assignment = read_json_object(root / rel, label="security verification assignment")
    assignment_for_validation = _security_assignment_payload(assignment, state=state, task=task)
    validation = validate_security_verification_assignment(
        assignment_for_validation,
        state=state,
        task=task,
        implementer_identity=task.get("owner") if isinstance(task.get("owner"), str) else None,
    )
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification assignment is not fresh and independent",
            {"taskId": task.get("id"), "validation": validation},
        )
    assigned_reviewer = assignment_for_validation.get("reviewer")
    if (
        not isinstance(assigned_reviewer, dict)
        or not isinstance(auditor, dict)
        or assigned_reviewer.get("id") != auditor.get("id")
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security audit auditor does not match the assigned reviewer",
            {"taskId": task.get("id")},
        )
    assigned_ids = assignment_for_validation.get("independentEvidenceIds")
    if (
        not isinstance(assigned_ids, list)
        or not assigned_ids
        or not isinstance(evidence_ids, list)
        or not set(assigned_ids).issubset(set(evidence_ids))
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security audit evidence does not match the verification assignment",
            {"taskId": task.get("id")},
        )
    required_ids = (
        config.get("verificationEvidence", {}).get("independentEvidenceIds", [])
        if isinstance(config, dict) and isinstance(config.get("verificationEvidence"), dict)
        else []
    )
    if required_ids and not set(required_ids).issubset(set(evidence_ids)):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification evidence IDs do not match the adopted policy",
            {"taskId": task.get("id")},
        )


def _security_assignment_payload(
    assignment: dict[str, Any], *, state: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    """Accept the canonical security assignment or a Review Mesh packet wrapper."""

    if assignment.get("schemaVersion") == "agent-security-verification-assignment.v1":
        return assignment
    nested = assignment.get("assignment")
    if not isinstance(nested, dict) or nested.get("schemaVersion") != "agent-review-mesh-assignment.v1":
        return assignment
    if assignment.get("schemaVersion") != "agent-review-mesh-reviewer-packet.v1":
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification assignment wrapper has an invalid Review Mesh schema",
        )
    if assignment.get("packetDigest") != canonical_digest(
        {key: value for key, value in assignment.items() if key != "packetDigest"}
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification assignment wrapper digest is invalid",
        )
    packet_security = assignment.get("securityAnalysis")
    if (
        not isinstance(packet_security, dict)
        or packet_security.get("profileId") != "security-analysis.v1"
        or packet_security.get("independentVerificationRequired") is not True
        or packet_security.get("authorityClaimed") is not False
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification assignment wrapper is not an explicit security packet",
        )
    reviewer_task = assignment.get("reviewerTask")
    if (
        not isinstance(reviewer_task, dict)
        or reviewer_task.get("hostOwnedExecution") is not True
        or reviewer_task.get("alkCoreLaunchAllowed") is not False
        or reviewer_task.get("promptAuthorityGranted") is not False
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification assignment wrapper grants an invalid execution boundary",
        )
    nested_validation = validate_review_mesh_assignment(nested)
    if nested_validation.get("status") != "PASS":
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification Review Mesh assignment is invalid",
            {"validation": nested_validation},
        )
    if nested.get("blocking") is not True or nested.get("advisory") is not False:
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification Review Mesh assignment must be blocking",
        )
    independence_requirement = nested.get("independenceRequirement")
    requirement_validation = validate_independence_requirement(independence_requirement)
    if (
        requirement_validation.get("status") != "PASS"
        or not isinstance(independence_requirement, dict)
        or independence_requirement.get("required") is not True
    ):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification Review Mesh assignment lacks required independence",
            {"validation": requirement_validation},
        )
    subject_value = nested.get("subject")
    subject: dict[str, Any] = subject_value if isinstance(subject_value, dict) else {}
    source_revision = subject.get("sourceRevision")
    if not isinstance(source_revision, str) or not source_revision or source_revision != state.get("sourceRevision"):
        raise LifecycleError(
            "security-analysis-verification-required",
            "security verification Review Mesh assignment has no exact source revision",
        )
    reviewer_value = nested.get("reviewer")
    reviewer: dict[str, Any] = reviewer_value if isinstance(reviewer_value, dict) else {}
    security = {
        "schemaVersion": "agent-security-verification-assignment.v1",
        "status": "READY",
        "assignmentId": nested.get("assignmentId"),
        "runId": state.get("runId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": source_revision,
        "reviewer": {
            **reviewer,
            "independent": reviewer.get("producerClass") not in {"implementer", "primary-implementer"},
        },
        "independentEvidenceIds": list(nested.get("evidenceIds", [])),
        "productionPromotionClaimed": False,
    }
    return {**security, "assignmentDigest": canonical_digest(security)}
