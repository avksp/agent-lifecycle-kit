"""Workflow artifact path and identity helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.finding_check_schemas import (
    build_finding_check_evidence,
    validate_finding_check_evidence,
)
from agent_lifecycle.contracts.paths import normalize_repo_path

STRUCTURED_RESULT_ARTIFACT_SCHEMA = "agent-workflow-structured-result-artifact.v1"


def package_root(state_path: Path, state: dict[str, Any]) -> Path:
    raw = state.get("packageRoot")
    if isinstance(raw, str) and raw:
        return (state_path.parent / raw).resolve()
    return state_path.parent


def artifact_path(task: dict[str, Any], role: str, attempt: int) -> str:
    artifacts = task.get("artifactPaths")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get(role), str):
        raise LifecycleError(
            "missing-artifact-template",
            f"task {task.get('id')} has no {role} artifact template",
        )
    return normalize_repo_path(artifacts[role].replace("{attempt}", str(attempt)))


def artifact_identity(root: Path, path: str, value: dict[str, Any]) -> dict[str, Any]:
    data = canonical_bytes(value) + b"\n"
    actual = (root / path).read_bytes()
    if actual != data:
        raise LifecycleError(
            "non-canonical-artifact",
            f"artifact is not canonical JSON: {path}",
        )
    return {"path": path, "sha256": canonical_digest(value), "bytes": len(actual)}


def build_finding_check_evidence_artifact(
    binding: dict[str, Any],
    *,
    result: str,
    source_revision: str,
    evidence_ids: list[str],
) -> dict[str, Any]:
    """Build read-only evidence that can advance a finding-check binding."""

    return build_finding_check_evidence(
        binding,
        result=result,
        source_revision=source_revision,
        evidence_ids=evidence_ids,
    )


def validate_finding_check_evidence_artifact(
    evidence: dict[str, Any],
    *,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate finding-check evidence without executing the referenced check."""

    return validate_finding_check_evidence(evidence, binding)


def build_structured_result_artifact(
    *,
    run_id: str,
    package_id: str,
    task_id: str,
    attempt: int,
    plan_digest: str,
    source_revision: str,
    lock_digest: str | None,
    operation_id: str,
    selection: dict[str, Any],
    validation: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Build a portable result artifact that remains advisory to workflow acceptance."""

    body = {
        "schemaVersion": STRUCTURED_RESULT_ARTIFACT_SCHEMA,
        "runId": run_id,
        "packageId": package_id,
        "taskId": task_id,
        "attempt": attempt,
        "planDigest": plan_digest,
        "sourceRevision": source_revision,
        "lockDigest": lock_digest,
        "operationId": operation_id,
        "selection": dict(selection),
        "validation": dict(validation),
        "output": dict(output),
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "artifactDigest": canonical_digest(body)}


def validate_structured_result_artifact(
    artifact: dict[str, Any], *, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate structured-result lineage without accepting the workflow task."""

    blockers: list[dict[str, Any]] = []
    if artifact.get("schemaVersion") != STRUCTURED_RESULT_ARTIFACT_SCHEMA:
        blockers.append({"code": "structured-result-artifact-schema"})
    if artifact.get("authorityClaimed") is not False or artifact.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "structured-result-artifact-authority"})
    for field in ("runId", "packageId", "taskId", "planDigest", "sourceRevision", "operationId"):
        if not isinstance(artifact.get(field), str) or not artifact[field]:
            blockers.append({"code": "structured-result-artifact-lineage", "field": field})
    if not isinstance(artifact.get("attempt"), int) or isinstance(artifact.get("attempt"), bool) or artifact["attempt"] < 1:
        blockers.append({"code": "structured-result-artifact-attempt"})
    for key, value in (expected or {}).items():
        if artifact.get(key) != value:
            blockers.append({"code": "structured-result-artifact-lineage-mismatch", "field": key})
    selection = artifact.get("selection")
    validation = artifact.get("validation")
    output = artifact.get("output")
    if not isinstance(selection, dict) or selection.get("status") != "PASS":
        blockers.append({"code": "structured-result-artifact-selection"})
    if not isinstance(validation, dict) or validation.get("status") != "PASS":
        blockers.append({"code": "structured-result-artifact-validation"})
    if not isinstance(output, dict):
        blockers.append({"code": "structured-result-artifact-output"})
    expected_digest = canonical_digest({key: value for key, value in artifact.items() if key != "artifactDigest"})
    if artifact.get("artifactDigest") != expected_digest:
        blockers.append({"code": "structured-result-artifact-digest"})
    body = {
        "schemaVersion": "agent-workflow-structured-result-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "taskId": artifact.get("taskId"),
        "operationId": artifact.get("operationId"),
        "blockers": blockers,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_artifact_identity(root: Path, identity: dict[str, Any], *, label: str) -> dict[str, Any]:
    path = identity.get("path")
    if not isinstance(path, str):
        raise LifecycleError("artifact-identity-invalid", f"{label} identity has no path")
    artifact = root / normalize_repo_path(path, label=label)
    try:
        actual = artifact.read_bytes()
    except OSError as exc:
        raise LifecycleError("archived-artifact-missing", f"{label} is missing", {"path": path}) from exc
    if len(actual) != identity.get("bytes"):
        raise LifecycleError("archived-artifact-changed", f"{label} byte size changed", {"path": path})
    try:
        from agent_lifecycle.contracts import read_json_object

        value = read_json_object(artifact, label=label)
    except OSError as exc:
        raise LifecycleError("archived-artifact-missing", f"{label} is missing", {"path": path}) from exc
    if canonical_digest(value) != identity.get("sha256") or canonical_bytes(value) + b"\n" != actual:
        raise LifecycleError("archived-artifact-changed", f"{label} content changed", {"path": path})
    return value


def validate_attempt_history(state_path: Path, state: dict[str, Any], task: dict[str, Any]) -> None:
    history = task.get("attemptHistory", [])
    if not isinstance(history, list):
        raise LifecycleError("task-attempt-history-invalid", "task attemptHistory must be an array")
    max_attempts = _max_task_attempts(state)
    if len(history) > max_attempts - 1:
        raise LifecycleError("task-attempt-history-invalid", "task attemptHistory exceeds the attempt budget")
    root = package_root(state_path, state)
    previous_attempt = 0
    current_attempt = _task_attempt(task)
    for entry in history:
        if not isinstance(entry, dict) or entry.get("schemaVersion") != "agent-task-attempt-history-entry.v1":
            raise LifecycleError("task-attempt-history-invalid", "task attempt history entry is invalid")
        attempt = entry.get("attempt")
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt != previous_attempt + 1
            or attempt > current_attempt
        ):
            raise LifecycleError(
                "task-attempt-history-invalid",
                "task attempt history must contain consecutive attempts starting at one",
            )
        expected_lineage = {
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "taskId": task.get("id"),
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
        }
        if any(entry.get(key) != value for key, value in expected_lineage.items()):
            raise LifecycleError("task-attempt-history-lineage-mismatch", "task attempt history lineage changed")
        finding_ids = entry.get("findingIds")
        if (
            not isinstance(finding_ids, list)
            or not finding_ids
            or finding_ids != sorted(set(finding_ids))
            or any(not isinstance(item, str) or not item or len(item) > 256 for item in finding_ids)
            or len(finding_ids) > 128
        ):
            raise LifecycleError("task-attempt-history-invalid", "task attempt history finding IDs are invalid")
        if not isinstance(entry.get("archivedAt"), str) or not entry["archivedAt"]:
            raise LifecycleError("task-attempt-history-invalid", "task attempt history archive time is invalid")
        require_artifact_identity(root, entry.get("result", {}), label="archived task result")
        require_artifact_identity(root, entry.get("review", {}), label="archived task review")
        audit = entry.get("implementationAuditReport")
        if audit is not None:
            require_artifact_identity(root, audit, label="archived implementation audit")
        previous_attempt = attempt


def build_current_task_change_set(
    state_path: Path,
    *,
    task_id: str,
) -> dict[str, Any]:
    """Build read-only change-set evidence for the current task attempt."""

    from agent_lifecycle.changesets import capture_task_change_set
    from agent_lifecycle.workflow.selectors import find_task
    from agent_lifecycle.workflow.state import load_state

    state = load_state(state_path)
    task = find_task(state, task_id)
    if task.get("status") != "RUNNING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not RUNNING")
    evidence = capture_task_change_set(
        package_root(state_path, state),
        baseline=str(state.get("sourceRevision") or ""),
        write_paths=[path for path in task.get("writes", []) if isinstance(path, str)],
    )
    return {
        **evidence,
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task_id,
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "readOnly": True,
        "stateWritten": False,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
        "claim": {
            "schemaVersion": "agent-task-change-set-claim.v1",
            **{key: evidence[key] for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")},
        },
    }


def next_available_attempt(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> int:
    max_attempts = _max_task_attempts(state)
    current = _task_attempt(task)
    for attempt in range(current + 1, max_attempts + 1):
        if not attempt_artifacts_exist(state_path, state, task, attempt):
            return attempt
    raise LifecycleError(
        "task-attempt-output-conflict",
        f"task {task.get('id')} has no unoccupied attempt artifact path",
        {"maxTaskAttempts": max_attempts},
    )


def attempt_artifacts_exist(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
) -> bool:
    artifacts = task.get("artifactPaths", {})
    if not isinstance(artifacts, dict):
        return False
    root = package_root(state_path, state)
    for template in artifacts.values():
        if not isinstance(template, str):
            continue
        rendered = normalize_repo_path(template.replace("{attempt}", str(attempt)))
        if (root / rendered).exists():
            return True
    return False


def _max_task_attempts(state: dict[str, Any]) -> int:
    budgets = state.get("budgets")
    value = budgets.get("maxTaskAttempts", 1) if isinstance(budgets, dict) else 1
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10:
        raise LifecycleError("task-attempt-budget-invalid", "maxTaskAttempts must be an integer from 1 through 10")
    return value


def _task_attempt(task: dict[str, Any]) -> int:
    value = task.get("attempt", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("task-attempt-history-invalid", "task attempt number is invalid")
    return value
