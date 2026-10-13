"""Shared workflow gates for implementation audit reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.canonical import sha256_hex
from agent_lifecycle.contracts.evidence_receipt_schemas import (
    classify_evidence_candidate,
    load_evidence_receipt_bytes,
    validate_expected_evidence,
)
from agent_lifecycle.contracts.independent_evidence_schemas import validate_independence_requirement
from agent_lifecycle.contracts.paths import normalize_repo_path, read_stable_repository_file
from agent_lifecycle.contracts.security_analysis_schemas import SECURITY_ANALYSIS_AUDIT_SCHEMA
from agent_lifecycle.quality.security_analysis import (
    security_analysis_high_severity,
    validate_security_analysis_audit,
    validate_security_verification_assignment,
)
from agent_lifecycle.review_mesh.contracts import validate_review_mesh_assignment
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root


from agent_lifecycle.workflow.audit_evidence import (
    validate_task_evidence_paths,
    _validate_command_inventory,
    _expected_task_evidence_subject,
    _current_evidence_component,
    _current_git_commit,
    _path_inventory_digest,
    _validate_evidence_references,
)


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
    _revalidate_task_evidence_report(state_path, state, task, report)
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


def _revalidate_task_evidence_report(
    state_path: Path, state: dict[str, Any], task: dict[str, Any], report: dict[str, Any],
) -> None:
    manifest = load_state_manifest(state_path, state)
    if manifest is None:
        raise LifecycleError("evidence-contract-invalid", "current plan manifest is unavailable")
    acceptance = manifest.get("acceptance")
    entries = acceptance.get("evidence", []) if isinstance(acceptance, dict) else []
    if not isinstance(entries, list) or not any(
        isinstance(item, dict) and isinstance(item.get("validation"), dict) for item in entries
    ):
        return
    if manifest.get("status") != "FROZEN" or canonical_digest(manifest) != state.get("planDigest"):
        raise LifecycleError("evidence-contract-invalid", "frozen plan does not match current state")
    root = package_root(state_path, state)
    result_summary = report.get("result")
    evidence_summary = report.get("evidence")
    if not isinstance(result_summary, dict) or not isinstance(evidence_summary, dict):
        raise LifecycleError("evidence-contract-invalid", "audit evidence summary is missing")
    result_path = normalize_repo_path(result_summary.get("path"), label="task result")
    result = read_json_object(root / result_path, label="task result")
    identity = artifact_identity(root, result_path, result)
    if any(result_summary.get(key) != identity[key] for key in ("path", "sha256", "bytes")):
        raise LifecycleError("evidence-subject-mismatch", "audit result identity is stale")
    from agent_lifecycle.workflow.reviews import validate_task_result

    snapshot = validate_task_result(state, task, result, identity, repository_root=root, require_freshness=True)
    paths = evidence_summary.get("suppliedEvidence")
    if not isinstance(paths, list) or any(not isinstance(item, dict) or not isinstance(item.get("path"), str)
                                           for item in paths):
        raise LifecycleError("evidence-contract-invalid", "audit evidence paths are invalid")
    current = validate_task_evidence_paths(root, manifest, state, task, identity, snapshot,
                                           [item["path"] for item in paths])
    if current["missingEvidenceIds"] or current != evidence_summary:
        raise LifecycleError("evidence-contract-invalid", "audit evidence summary is stale or incomplete")


def validate_final_task_evidence_reports(
    state_path: Path, state: dict[str, Any], audit: dict[str, Any], *, manifest: dict[str, Any] | None = None,
) -> None:
    """Revalidate typed accepted-task receipts at the final accepting boundary."""
    selected = manifest if manifest is not None else load_state_manifest(state_path, state)
    if selected is None:
        raise LifecycleError("evidence-contract-invalid", "final audit plan manifest is unavailable")
    acceptance = selected.get("acceptance")
    entries = acceptance.get("evidence") if isinstance(acceptance, dict) else None
    if not isinstance(entries, list):
        return
    typed_ids = {item["id"] for item in entries if isinstance(item, dict)
                 and isinstance(item.get("id"), str) and isinstance(item.get("validation"), dict)
                 and validate_expected_evidence(item["validation"])["scope"] == "TASK"}
    if not typed_ids:
        return
    if selected.get("status") != "FROZEN" or canonical_digest(selected) != state.get("planDigest"):
        raise LifecycleError("evidence-contract-invalid", "typed final audit plan is stale")
    workstreams = selected.get("workstreams")
    if not isinstance(workstreams, list):
        raise LifecycleError("evidence-contract-invalid", "typed workstream inventory is unavailable")
    frozen = {item["id"]: item for item in workstreams if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if len(frozen) != len(workstreams):
        raise LifecycleError("evidence-contract-invalid", "typed workstream IDs are ambiguous")
    expected = {}
    for task in state.get("tasks", []):
        if not isinstance(task, dict) or task.get("status") != "ACCEPTED":
            continue
        task_id = task.get("id")
        owner = frozen.get(task_id)
        if owner is None:
            raise LifecycleError("evidence-contract-invalid", "accepted task is outside frozen plan")
        required = owner.get("evidenceIds")
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise LifecycleError("evidence-contract-invalid", "frozen task evidence inventory is invalid")
        if typed_ids.intersection(required):
            if task.get("evidenceIds") != required or task_id in expected:
                raise LifecycleError("evidence-contract-invalid", "typed task evidence inventory changed")
            expected[task_id] = task
    for owner in frozen.values():
        ids = owner.get("evidenceIds", [])
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise LifecycleError("evidence-contract-invalid", "frozen evidence IDs are invalid")
        if owner.get("required", True) and typed_ids.intersection(ids) and owner["id"] not in expected:
            raise LifecycleError("evidence-contract-invalid", "required typed task is not accepted")
    reports = audit.get("reports")
    if not isinstance(reports, list) or audit.get("missingTaskIds") != []:
        raise LifecycleError("evidence-contract-invalid", "final audit report inventory is incomplete")
    seen_ids, seen_paths = set(), set()
    for item in reports:
        if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                or not isinstance(item.get("taskId"), str)):
            raise LifecycleError("evidence-contract-invalid", "final audit report identity is invalid")
        task_id, path = item.get("taskId"), item["path"]
        if task_id in seen_ids or path in seen_paths:
            raise LifecycleError("evidence-id-duplicate", "final audit report is duplicated")
        seen_ids.add(task_id)
        seen_paths.add(path)
        task = expected.get(task_id)
        if task is None:
            accepted_other = any(isinstance(t, dict) and t.get("id") == task_id and t.get("status") == "ACCEPTED"
                                 for t in state.get("tasks", []))
            if task_id not in frozen or not accepted_other or typed_ids.intersection(frozen[task_id]["evidenceIds"]):
                raise LifecycleError("evidence-contract-invalid", "final report has no accepted frozen task")
            continue
        accepted = task.get("implementationAuditReport")
        if not isinstance(accepted, dict) or any(
            accepted.get(key) != item.get(key) for key in ("path", "sha256", "bytes", "taskId", "attempt", "verdict")
        ):
            raise LifecycleError("evidence-contract-invalid", "final report differs from accepted task audit")
        current = validate_task_implementation_audit_artifact(state_path, state, task, path)
        if any(current.get(key) != item.get(key) for key in
               ("path", "sha256", "bytes", "taskId", "attempt", "verdict")):
            raise LifecycleError("evidence-contract-invalid", "final report evidence is stale")
        summary = item.get("validation")
        if not isinstance(summary, dict) or any(
            summary.get(key) != current["validation"][key] for key in ("status", "validationDigest")
        ):
            raise LifecycleError("evidence-contract-invalid", "final report validation has changed")
    if set(expected) - seen_ids:
        raise LifecycleError("evidence-contract-invalid", "typed accepted task report is missing")


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
    expected_lineage = {
        "runId": state.get("runId"), "taskId": task.get("id"),
        "attempt": task.get("attempt"), "planDigest": state.get("planDigest"),
    }
    for field, expected in expected_lineage.items():
        value = subject.get(field)
        if type(value) is not type(expected) or value != expected:
            raise LifecycleError(
                "security-analysis-verification-required",
                f"security verification Review Mesh assignment {field} mismatch",
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
