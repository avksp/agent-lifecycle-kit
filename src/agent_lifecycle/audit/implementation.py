"""Deterministic implementation audit facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.audit.ownership import build_ownership_report, report_has_category
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.review_verdict import (
    BLOCKING_REVIEW_SEVERITIES,
    REVIEW_SEVERITY_RANK,
    open_blocking_finding_ids,
)
from agent_lifecycle.planning.task_compatibility import (
    validate_task_plan_compatibility_receipt,
)
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.review_mesh_gate import validate_review_mesh_quorum_path
from agent_lifecycle.workflow.reviews import (
    task_result_freshness_required,
    validate_task_result,
    validate_task_review,
)
from agent_lifecycle.workflow.sandbox_policy import validate_task_sandbox_evidence
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import load_state

IMPLEMENTATION_AUDIT_SCHEMA = "agent-implementation-audit-report.v1"
FINAL_IMPLEMENTATION_AUDIT_SCHEMA = "agent-final-implementation-audit.v1"


def build_implementation_audit_report(
    *,
    manifest_path: Path,
    state_path: Path,
    task_id: str,
    result_path: str,
    review_path: str,
    evidence_paths: list[str] | None = None,
    sandbox_receipt_paths: list[str] | None = None,
    review_mesh_quorum_paths: list[str] | None = None,
    changed_paths: list[str] | None = None,
    expected_revision: int | None = None,
    base: str | None = None,
    auditor_id: str = "implementation-auditor",
    auditor_surface: str = "cli",
) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
    state = load_state(state_path)
    root = package_root(state_path, state)
    task = find_task(state, task_id)
    result_rel = normalize_repo_path(result_path, label="task result")
    review_rel = normalize_repo_path(review_path, label="task review")
    result = read_json_object(root / result_rel, label="task result")
    review = read_json_object(root / review_rel, label="task review")
    result_identity = artifact_identity(root, result_rel, result)
    review_identity = artifact_identity(root, review_rel, review)

    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    snapshot_evidence: list[dict[str, Any]] = []
    _capture("state", findings, blockers, lambda: _validate_state(state, manifest, expected_revision=expected_revision))
    _capture(
        "result",
        findings,
        blockers,
        lambda: _validate_result_with_snapshot(state, task, result, result_identity, root, snapshot_evidence),
    )
    task_for_review = {**task, "result": result_identity}
    _capture("review", findings, blockers, lambda: validate_task_review(state, task_for_review, review, result=result))
    _check_self_certification(result, review, findings, blockers)

    changed, ownership = _resolve_current_ownership(
        manifest_path, result, snapshot_evidence, changed_paths, base, findings, blockers
    )

    evidence = _evidence_summary(root, task, evidence_paths or [])
    for missing in evidence["missingEvidenceIds"]:
        _add_finding(
            findings,
            blockers,
            code="implementation-evidence-missing",
            severity="MEDIUM",
            category="evidence",
            message=f"required evidence is missing: {missing}",
            context={"evidenceId": missing},
        )

    sandbox = _sandbox_summary(root, state, task, sandbox_receipt_paths or [])
    if sandbox["validation"]["status"] != "PASS":
        for blocker in sandbox["validation"]["blockers"]:
            _add_finding(
                findings,
                blockers,
                code=str(blocker.get("code") or "sandbox-evidence-failed"),
                severity="HIGH",
                category="sandbox",
                message="required sandbox evidence did not pass",
                context=blocker,
            )

    review_mesh = _review_mesh_summary(root, state, task, review_mesh_quorum_paths or [])
    if review_mesh["validation"]["status"] != "PASS":
        for blocker in review_mesh["validation"]["blockers"]:
            _add_finding(
                findings,
                blockers,
                code=str(blocker.get("code") or "review-mesh-quorum-failed"),
                severity="HIGH",
                category="review-mesh",
                message="required Review Mesh quorum evidence did not pass",
                context=blocker,
            )

    coverage = _coverage_summary(task, result, review)
    for missing in coverage["missingAcceptanceIds"]:
        _add_finding(
            findings,
            blockers,
            code="implementation-acceptance-missing",
            severity="MEDIUM",
            category="coverage",
            message=f"acceptance criterion is not covered by PASS review: {missing}",
            context={"acceptanceId": missing},
        )

    findings = _sorted_findings(findings)
    verdict = _verdict(findings)
    status = "PASS" if verdict == "ACCEPTED" else "FAIL"
    body = {
        "schemaVersion": IMPLEMENTATION_AUDIT_SCHEMA,
        "status": status,
        "verdict": verdict,
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "auditor": {"id": auditor_id, "surface": auditor_surface, "independent": True},
        "plan": {
            "path": manifest_path.as_posix(),
            "status": manifest.get("status"),
            "planDigest": canonical_digest(manifest),
        },
        "result": {
            **result_identity,
            "changedFiles": changed,
            "changeSetEvidence": snapshot_evidence[0] if snapshot_evidence else None,
            "commands": result.get("commands", []),
        },
        "review": {
            **review_identity,
            "reviewer": review.get("reviewer"),
            "verdict": review.get("verdict"),
        },
        "ownership": {
            "status": "PASS"
            if not blockers_for_categories(ownership, {"forbidden", "read-only", "unowned"})
            else "FAIL",
            "report": ownership,
        },
        "coverage": coverage,
        "evidence": evidence,
        "sandbox": sandbox,
        "reviewMesh": review_mesh,
        "findings": findings,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def _resolve_current_ownership(
    manifest_path: Path,
    result: dict[str, Any],
    snapshot_evidence: list[dict[str, Any]],
    changed_paths: list[str] | None,
    base: str | None,
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    changed = snapshot_evidence[0]["allChangedFiles"] if snapshot_evidence else _result_changed_files(result)
    supplied = sorted(set(changed_paths)) if changed_paths is not None else None
    if supplied is not None and supplied != changed:
        _add_finding(
            findings,
            blockers,
            code="implementation-changed-paths-stale",
            severity="HIGH",
            category="freshness",
            message="caller-supplied changed paths do not match the current repository snapshot",
            context={"expected": changed, "actual": supplied},
        )
    ownership = build_ownership_report(manifest_path, changed, base=base)
    if report_has_category(ownership, {"forbidden", "read-only", "unowned"}):
        _add_finding(
            findings,
            blockers,
            code="implementation-write-scope-violation",
            severity="HIGH",
            category="ownership",
            message="changed files include forbidden, read-only or unowned paths",
            context=ownership["summary"],
        )
    return changed, ownership


def validate_implementation_audit_report(
    report: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    report_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    compatibility_validation: dict[str, Any] | None = None
    if report.get("schemaVersion") != IMPLEMENTATION_AUDIT_SCHEMA:
        blockers.append(
            {"code": "implementation-audit-schema", "message": "unsupported implementation audit schemaVersion"}
        )
    body = {key: value for key, value in report.items() if key != "reportDigest"}
    if report.get("reportDigest") != canonical_digest(body):
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
        expected = {
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
        }
        if any(report.get(key) != value for key, value in expected.items()):
            compatibility_validation = validate_task_plan_compatibility_receipt(
                task.get("planCompatibilityReceipt") if isinstance(task, dict) else None,
                state=state,
                task=task or {},
                report=report,
                report_identity=report_identity,
            )
            if compatibility_validation["status"] != "PASS":
                blockers.append(
                    {
                        "code": "implementation-audit-lineage-mismatch",
                        "message": "prior implementation audit is not covered by a valid task compatibility receipt",
                        "compatibilityValidation": compatibility_validation,
                    }
                )
    if task is not None:
        _check_expected(
            report,
            {"taskId": task.get("id"), "attempt": task.get("attempt")},
            blockers,
            prefix="implementation-audit",
        )
    body = {
        "schemaVersion": "agent-implementation-audit-report-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "verdict": verdict,
        "blockers": blockers,
        "reportDigest": report.get("reportDigest"),
        "planCompatibility": compatibility_validation,
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


def build_final_implementation_audit(
    *,
    manifest_path: Path,
    state_path: Path,
    report_paths: list[str],
    auditor_id: str = "final-implementation-auditor",
    auditor_surface: str = "cli",
) -> dict[str, Any]:
    manifest = read_json_object(manifest_path, label="plan manifest")
    state = load_state(state_path)
    root = package_root(state_path, state)
    reports = []
    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for raw_path in report_paths:
        rel = normalize_repo_path(raw_path, label="implementation audit report")
        report = read_json_object(root / rel, label="implementation audit report")
        task = find_task(state, str(report.get("taskId"))) if isinstance(report.get("taskId"), str) else None
        identity = artifact_identity(root, rel, report)
        validation = validate_implementation_audit_report(
            report,
            state=state,
            task=task,
            report_identity=identity,
        )
        accepted = (
            validation["status"] == "PASS" and report.get("status") == "PASS" and report.get("verdict") == "ACCEPTED"
        )
        if not accepted:
            blockers.append({"code": "implementation-audit-report-not-accepted", "path": rel, "validation": validation})
        reports.append(
            {
                **identity,
                "taskId": report.get("taskId"),
                "attempt": report.get("attempt"),
                "verdict": report.get("verdict"),
                "validation": validation,
            }
        )
        findings.extend(report.get("findings", []) if isinstance(report.get("findings"), list) else [])
    accepted_report_task_ids = {item.get("taskId") for item in reports if item.get("verdict") == "ACCEPTED"}
    missing_task_ids = [
        str(task.get("id"))
        for task in state.get("tasks", [])
        if task.get("required", True)
        and task.get("status") == "ACCEPTED"
        and task.get("id") not in accepted_report_task_ids
    ]
    for task_id in missing_task_ids:
        blockers.append({"code": "implementation-audit-report-missing", "taskId": task_id})
    if manifest.get("status") != "FROZEN":
        blockers.append({"code": "plan-not-frozen", "message": "final implementation audit requires a FROZEN plan"})
    body = {
        "schemaVersion": FINAL_IMPLEMENTATION_AUDIT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "auditor": {"id": auditor_id, "surface": auditor_surface, "independent": True},
        "plan": {
            "path": manifest_path.as_posix(),
            "status": manifest.get("status"),
            "planDigest": canonical_digest(manifest),
        },
        "reports": reports,
        "missingTaskIds": missing_task_ids,
        "findings": _sorted_findings(findings),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


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
    body = {key: value for key, value in audit.items() if key != "auditDigest"}
    if audit.get("auditDigest") != canonical_digest(body):
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


def _validate_state(state: dict[str, Any], manifest: dict[str, Any], *, expected_revision: int | None) -> None:
    if expected_revision is not None and state.get("stateRevision") != expected_revision:
        raise LifecycleError(
            "state-revision-mismatch",
            "workflow state revision mismatch",
            {"expected": expected_revision, "actual": state.get("stateRevision")},
        )
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "implementation audit requires a FROZEN plan")
    if canonical_digest(manifest) != state.get("planDigest"):
        raise LifecycleError("plan-digest-mismatch", "workflow state planDigest does not match manifest")


def _capture(
    category: str,
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    callback: Any,
) -> None:
    try:
        callback()
    except LifecycleError as exc:
        severity = "BLOCKER" if exc.code in {"state-revision-mismatch", "plan-digest-mismatch"} else "HIGH"
        _add_finding(
            findings,
            blockers,
            code=exc.code,
            severity=severity,
            category=category,
            message=exc.message,
            context=exc.details,
        )


def _validate_result_with_snapshot(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    identity: dict[str, Any],
    root: Path,
    snapshot_evidence: list[dict[str, Any]],
) -> None:
    change_set = result.get("changeSet")
    strict = task_result_freshness_required(state) or (
        isinstance(change_set, dict) and change_set.get("provider") == "git-worktree-v2"
    )
    evidence = validate_task_result(
        state,
        task,
        result,
        identity,
        repository_root=root,
        require_freshness=strict,
    )
    if evidence is not None:
        snapshot_evidence.append(evidence)


def _check_self_certification(
    result: dict[str, Any],
    review: dict[str, Any],
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        return
    same_id = reviewer.get("id") == result.get("actor")
    same_run = reviewer.get("runId") == result.get("actorRunId")
    if same_id or same_run:
        _add_finding(
            findings,
            blockers,
            code="worker-self-certification",
            severity="HIGH",
            category="review",
            message="worker and reviewer identity overlap",
            context={"actor": result.get("actor"), "reviewer": reviewer.get("id")},
        )


def _result_changed_files(result: dict[str, Any]) -> list[str]:
    changed = result.get("changedFiles")
    return [item for item in changed if isinstance(item, str)] if isinstance(changed, list) else []


def _evidence_summary(root: Path, task: dict[str, Any], evidence_paths: list[str]) -> dict[str, Any]:
    identities = []
    for raw_path in evidence_paths:
        rel = normalize_repo_path(raw_path, label="evidence")
        payload = read_json_object(root / rel, label="evidence")
        identities.append(artifact_identity(root, rel, payload))
    required_ids = [item for item in task.get("evidenceIds", []) if isinstance(item, str)]
    # The facade is path-based; supplied evidence paths satisfy the task evidence set.
    missing = required_ids if required_ids and not identities else []
    return {
        "requiredEvidenceIds": required_ids,
        "suppliedEvidence": identities,
        "missingEvidenceIds": missing,
    }


def _sandbox_summary(
    root: Path, state: dict[str, Any], task: dict[str, Any], sandbox_receipt_paths: list[str]
) -> dict[str, Any]:
    receipt = None
    receipt_identity = None
    if sandbox_receipt_paths:
        rel = normalize_repo_path(sandbox_receipt_paths[0], label="sandbox receipt")
        receipt = read_json_object(root / rel, label="sandbox receipt")
        receipt_identity = artifact_identity(root, rel, receipt)
    lineage = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    validation = validate_task_sandbox_evidence(
        task, receipt=receipt, expected_lineage=lineage, attempt=task.get("attempt")
    )
    return {"receipt": receipt_identity, "validation": validation}


def _review_mesh_summary(
    root: Path, state: dict[str, Any], task: dict[str, Any], quorum_receipt_paths: list[str]
) -> dict[str, Any]:
    config = task.get("reviewMesh") if isinstance(task.get("reviewMesh"), dict) else state.get("reviewMesh")
    receipt_path = quorum_receipt_paths[0] if quorum_receipt_paths else None
    validation = validate_review_mesh_quorum_path(
        root=root,
        phase="implementation-audit",
        config=config if isinstance(config, dict) else None,
        receipt_path=receipt_path,
    )
    return {"receiptPath": receipt_path, "validation": validation}


def _coverage_summary(task: dict[str, Any], result: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    item_outcomes = [item for item in result.get("itemOutcomes", []) if isinstance(item, dict)]
    acceptance_checks = [item for item in review.get("acceptanceChecks", []) if isinstance(item, dict)]
    required_acceptance = [item for item in task.get("acceptanceIds", []) if isinstance(item, str)]
    passing_acceptance = {item.get("acceptanceId") for item in acceptance_checks if item.get("status") == "PASS"}
    return {
        "plannedItemCount": len(item_outcomes),
        "completedItemCount": sum(1 for item in item_outcomes if item.get("status") == "COMPLETE"),
        "requiredAcceptanceIds": required_acceptance,
        "passingAcceptanceIds": sorted(item for item in passing_acceptance if isinstance(item, str)),
        "missingAcceptanceIds": sorted(set(required_acceptance).difference(passing_acceptance)),
        "validationCommands": result.get("commands", []),
    }


def blockers_for_categories(report: dict[str, Any], categories: set[str]) -> list[dict[str, Any]]:
    return [entry for entry in report.get("entries", []) if entry.get("category") in categories]


def _has_blockers(payload: dict[str, Any]) -> bool:
    blockers = payload.get("blockers")
    return isinstance(blockers, list) and len(blockers) > 0


def _has_open_blocking_findings(payload: dict[str, Any]) -> bool:
    findings = payload.get("findings")
    return isinstance(findings, list) and bool(open_blocking_finding_ids(findings))


def _add_finding(
    findings: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    *,
    code: str,
    severity: str,
    category: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    finding = {
        "id": f"finding-{canonical_digest({'code': code, 'category': category, 'message': message})[:16]}",
        "code": code,
        "severity": severity,
        "category": category,
        "status": "open",
        "message": message,
        "context": context or {},
    }
    findings.append(finding)
    if severity in BLOCKING_REVIEW_SEVERITIES:
        blockers.append({"code": code, "severity": severity, "message": message, "context": context or {}})


def _sorted_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda item: (REVIEW_SEVERITY_RANK.get(str(item.get("severity")), 99), str(item.get("code"))),
    )


def _verdict(findings: list[dict[str, Any]]) -> str:
    if any(item.get("severity") == "BLOCKER" for item in findings):
        return "BLOCKED"
    if any(item.get("category") == "ownership" for item in findings):
        return "CONTRACT_CHANGE"
    if any(item.get("severity") in BLOCKING_REVIEW_SEVERITIES for item in findings):
        return "REWORK"
    return "ACCEPTED"


def _check_expected(
    payload: dict[str, Any], expected: dict[str, Any], blockers: list[dict[str, Any]], *, prefix: str
) -> None:
    for key, value in expected.items():
        if payload.get(key) != value:
            blockers.append(
                {"code": f"{prefix}-lineage-mismatch", "field": key, "expected": value, "actual": payload.get(key)}
            )
