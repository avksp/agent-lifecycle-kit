"""Provider-neutral worktree isolation receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path

LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
OUTCOMES = {"PASS", "FAILED", "BLOCKED"}
CLEANUP_DECISIONS = {"PRESERVE", "REMOVE"}


def validate_worktree_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise LifecycleError("invalid-worktree-policy", "worktree policy must be an object")
    if policy.get("schemaVersion") != "agent-worktree-isolation-policy.v1":
        raise LifecycleError("invalid-worktree-policy", "worktree policy schemaVersion is unsupported")
    worktree_root = normalize_repo_path(_required_string(policy.get("worktreeRoot"), label="worktreeRoot"), label="worktreeRoot")
    allowed_write_roots = _path_list(policy.get("allowedWriteRoots", []), label="allowedWriteRoots", allow_empty=True)
    preserve_failed = _required_bool(policy.get("preserveFailedAttempts"), label="preserveFailedAttempts")
    cleanup_requires_operator = _required_bool(policy.get("cleanupRequiresOperator"), label="cleanupRequiresOperator")
    body = {
        "schemaVersion": "agent-worktree-isolation-policy-validation.v1",
        "status": "PASS",
        "worktreeRoot": worktree_root,
        "allowedWriteRoots": allowed_write_roots,
        "preserveFailedAttempts": preserve_failed,
        "cleanupRequiresOperator": cleanup_requires_operator,
        "policyDigest": canonical_digest(policy),
    }
    return body


def build_attempt_isolation_receipt(
    workflow_state: dict[str, Any],
    *,
    task_id: str,
    attempt: int,
    policy: dict[str, Any],
    worktree_path: str,
    baseline_ref: str,
    baseline_sha: str,
    changed_files: list[str],
    outcome: str,
    cleanup_decision: str | None = None,
    operator_authorization: dict[str, Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    validation = validate_worktree_policy(policy)
    task = _workflow_task(workflow_state, task_id)
    decision = cleanup_decision or "PRESERVE"
    body = {
        "schemaVersion": "agent-worktree-attempt-receipt.v1",
        "status": "PASS",
        "lineage": _lineage_from_workflow(workflow_state),
        "taskId": task_id,
        "attempt": _positive_int(attempt, label="attempt"),
        "policyDigest": validation["policyDigest"],
        "isolation": {
            "strategy": "git-worktree",
            "worktreePath": normalize_repo_path(worktree_path, label="worktreePath"),
            "worktreeRoot": validation["worktreeRoot"],
            "baselineRef": _required_string(baseline_ref, label="baselineRef"),
            "baselineSha": _required_string(baseline_sha, label="baselineSha"),
            "mainWorktreeClean": True,
            "allowedWriteRoots": _allowed_roots(validation["allowedWriteRoots"], task),
            "changedFiles": _path_list(changed_files, label="changedFiles", allow_empty=True),
        },
        "outcome": _enum(outcome, OUTCOMES, label="outcome"),
        "cleanup": {
            "decision": _enum(decision, CLEANUP_DECISIONS, label="cleanupDecision"),
            "operatorAuthorization": operator_authorization,
            "reason": reason,
        },
        "createdAt": _now_iso(),
    }
    result = validate_attempt_isolation_receipt(body, workflow_state=workflow_state, policy=policy)
    return {**body, "receiptDigest": result["receiptDigest"]}


def validate_attempt_isolation_receipt(
    receipt: dict[str, Any],
    *,
    workflow_state: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-worktree-receipt", "worktree receipt must be an object")
    if receipt.get("schemaVersion") != "agent-worktree-attempt-receipt.v1":
        raise LifecycleError("invalid-worktree-receipt", "worktree receipt schemaVersion is unsupported")
    if receipt.get("status") != "PASS":
        raise LifecycleError("worktree-isolation-not-pass", "worktree isolation receipt must be PASS")
    lineage = _lineage(receipt.get("lineage"))
    if workflow_state is not None:
        _validate_workflow_binding(lineage, workflow_state)
    task_id = _required_string(receipt.get("taskId"), label="taskId")
    attempt = _positive_int(receipt.get("attempt"), label="attempt")
    isolation = _isolation(receipt.get("isolation"))
    cleanup = _cleanup(receipt.get("cleanup"))
    if policy is not None:
        policy_validation = validate_worktree_policy(policy)
        if receipt.get("policyDigest") != policy_validation["policyDigest"]:
            raise LifecycleError("worktree-policy-mismatch", "worktree receipt policyDigest mismatch")
        if not is_under_repo_path(isolation["worktreePath"], policy_validation["worktreeRoot"]):
            raise LifecycleError("worktree-path-outside-root", "worktree path is outside policy root")
        if policy_validation["cleanupRequiresOperator"] and cleanup["decision"] == "REMOVE" and cleanup["operatorAuthorization"] is None:
            raise LifecycleError("worktree-cleanup-authorization-required", "worktree cleanup requires operator authorization")
        if policy_validation["preserveFailedAttempts"] and receipt.get("outcome") == "FAILED" and cleanup["decision"] == "REMOVE":
            authorization = cleanup["operatorAuthorization"]
            if not isinstance(authorization, dict) or authorization.get("allowFailedAttemptRemoval") is not True:
                raise LifecycleError("worktree-failed-attempt-preserved", "failed attempt cleanup requires explicit removal authorization")
    if workflow_state is not None:
        task = _workflow_task(workflow_state, task_id)
        _validate_changed_files_in_scope(isolation["changedFiles"], _allowed_roots(isolation["allowedWriteRoots"], task))
    stored_digest = receipt.get("receiptDigest")
    receipt_digest = _receipt_digest(receipt)
    if stored_digest is not None and stored_digest != receipt_digest:
        raise LifecycleError("worktree-receipt-digest-mismatch", "worktree receiptDigest does not match receipt")
    body = {
        "schemaVersion": "agent-worktree-attempt-receipt-validation.v1",
        "status": "PASS",
        "lineage": lineage,
        "taskId": task_id,
        "attempt": attempt,
        "outcome": receipt.get("outcome"),
        "cleanupDecision": cleanup["decision"],
        "receiptDigest": receipt_digest,
    }
    return body


def _isolation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-worktree-receipt", "worktree isolation is required")
    strategy = value.get("strategy")
    if strategy != "git-worktree":
        raise LifecycleError("invalid-worktree-receipt", "worktree isolation strategy is unsupported")
    if value.get("mainWorktreeClean") is not True:
        raise LifecycleError("worktree-main-dirty", "main worktree must be clean before isolated attempt")
    return {
        "strategy": strategy,
        "worktreePath": normalize_repo_path(_required_string(value.get("worktreePath"), label="isolation.worktreePath"), label="isolation.worktreePath"),
        "worktreeRoot": normalize_repo_path(_required_string(value.get("worktreeRoot"), label="isolation.worktreeRoot"), label="isolation.worktreeRoot"),
        "baselineRef": _required_string(value.get("baselineRef"), label="isolation.baselineRef"),
        "baselineSha": _required_string(value.get("baselineSha"), label="isolation.baselineSha"),
        "allowedWriteRoots": _path_list(value.get("allowedWriteRoots", []), label="isolation.allowedWriteRoots", allow_empty=True),
        "changedFiles": _path_list(value.get("changedFiles", []), label="isolation.changedFiles", allow_empty=True),
    }


def _cleanup(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-worktree-receipt", "worktree cleanup is required")
    decision = _enum(value.get("decision"), CLEANUP_DECISIONS, label="cleanup.decision")
    authorization = value.get("operatorAuthorization")
    if authorization is not None and not isinstance(authorization, dict):
        raise LifecycleError("invalid-worktree-receipt", "operatorAuthorization must be an object")
    _required_string(value.get("reason"), label="cleanup.reason")
    return {"decision": decision, "operatorAuthorization": authorization}


def _validate_changed_files_in_scope(changed_files: list[str], allowed_roots: list[str]) -> None:
    for path in changed_files:
        if not any(is_under_repo_path(path, root) for root in allowed_roots):
            raise LifecycleError("worktree-write-scope-violation", "worktree changed file is outside task write scope", {"path": path, "allowedWriteRoots": allowed_roots})


def _allowed_roots(policy_roots: list[str], task: dict[str, Any]) -> list[str]:
    task_writes = _path_list(task.get("writes", []), label="task.writes", allow_empty=False)
    if not policy_roots:
        return task_writes
    return [root for root in policy_roots if any(is_under_repo_path(root, task_root) or is_under_repo_path(task_root, root) for task_root in task_writes)] or task_writes


def _workflow_task(workflow_state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in workflow_state.get("tasks", []):
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise LifecycleError("worktree-task-not-found", "worktree task is missing from workflow state", {"taskId": task_id})


def _lineage_from_workflow(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state.get(key) for key in LINEAGE_KEYS}


def _lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-worktree-receipt", "worktree lineage is required")
    result = {key: value.get(key) for key in LINEAGE_KEYS}
    for key, item in result.items():
        if key == "planRevision":
            _positive_int(item, label="lineage.planRevision")
        elif not isinstance(item, str) or not item:
            raise LifecycleError("invalid-worktree-receipt", f"worktree lineage.{key} is required")
    return result


def _validate_workflow_binding(lineage: dict[str, Any], workflow_state: dict[str, Any]) -> None:
    for key in LINEAGE_KEYS:
        if lineage.get(key) != workflow_state.get(key):
            raise LifecycleError("worktree-lineage-mismatch", f"worktree {key} mismatch")


def _path_list(value: Any, *, label: str, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-worktree-receipt", f"{label} must be a list of non-empty paths")
    if not value and not allow_empty:
        raise LifecycleError("invalid-worktree-receipt", f"{label} must not be empty")
    return [normalize_repo_path(item, label=label) for item in value]


def _enum(value: Any, allowed: set[str], *, label: str) -> str:
    if value not in allowed:
        raise LifecycleError("invalid-worktree-receipt", f"{label} is unsupported")
    return str(value)


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-worktree-receipt", f"{label} is required")
    return value


def _required_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise LifecycleError("invalid-worktree-policy", f"{label} must be boolean")
    return value


def _positive_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("invalid-worktree-receipt", f"{label} must be a positive integer")
    return value


def _receipt_digest(receipt: dict[str, Any]) -> str:
    return canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
