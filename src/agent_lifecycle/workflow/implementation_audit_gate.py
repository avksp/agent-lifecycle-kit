"""Shared workflow gates for implementation audit reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root


def task_implementation_audit_required(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> bool:
    if state.get("implementationAuditRequired") is True or _required(state.get("implementationAudit")):
        return True
    if task.get("implementationAuditRequired") is True or _required(task.get("implementationAudit")):
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
    return {
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
    return isinstance(audit, dict) and audit.get("verdict") == "ACCEPTED"


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
            blockers.append({"code": "implementation-audit-required", "taskId": task.get("id")})
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
