"""Create and explicitly migrate durable workflow state."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.persistence import create_private_json
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_MIGRATION_RECEIPT,
    WORKFLOW_STATE_V3,
    WORKFLOW_STATE_V4,
    validate_workflow_state,
)
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import now_iso


def initialize_workflow_state(
    state_path: Path,
    *,
    run_id: str,
    package_id: str,
    package_root: str = ".",
    event_log: str = "events.jsonl",
) -> dict[str, Any]:
    """Create one unbound v4 state without replacing an existing state file."""

    if not run_id or not package_id:
        raise LifecycleError("invalid-workflow-state", "runId and packageId are required")
    state = {
        "schemaVersion": WORKFLOW_STATE_V4,
        "runId": run_id,
        "packageId": package_id,
        "planRevision": 0,
        "planDigest": "",
        "sourceRevision": "",
        "stateRevision": 1,
        "phase": "AWAITING_AUTHORIZATION",
        "runStartedAt": now_iso(),
        "packageRoot": package_root,
        "eventLog": event_log,
        "operationLedger": {},
        "tasks": [],
        "budgets": {},
        "authorization": {"required": True, "granted": False},
        "blocker": None,
        "priorSnapshots": [],
    }
    validate_workflow_state(state, allow_legacy=False)
    create_private_json(state_path, state)
    return status(state_path)


def migrate_workflow_state(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
) -> dict[str, Any]:
    """Migrate a v3 state once, preserving lineage and immutable artifact identities."""

    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("schemaVersion") != WORKFLOW_STATE_V3:
        raise LifecycleError("workflow-state-migration-not-required", "state migration requires v3 input")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    migrated = _migrate_copy(state)
    source_state_revision = int(state["stateRevision"])
    receipt_body = {
        "schemaVersion": WORKFLOW_STATE_MIGRATION_RECEIPT,
        "status": "PASS",
        "runId": migrated["runId"],
        "packageId": migrated["packageId"],
        "fromSchemaVersion": WORKFLOW_STATE_V3,
        "toSchemaVersion": WORKFLOW_STATE_V4,
        "sourceStateRevision": source_state_revision,
        "targetStateRevision": source_state_revision + 1,
        "operationId": operation_id,
    }
    migration_receipt = {**receipt_body, "receiptDigest": canonical_digest(receipt_body)}
    migrated["migration"] = migration_receipt
    validate_workflow_state(migrated, allow_legacy=False)
    state.clear()
    state.update(migrated)
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="workflow-state-migrated",
        payload={"migrationReceipt": migration_receipt},
    )
    return {**status(state_path), "migrationReceipt": migration_receipt}


def _migrate_copy(state: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(state)
    migrated["schemaVersion"] = WORKFLOW_STATE_V4
    phase = migrated.get("phase")
    if phase in {"STEP_REVIEW", "REMEDIATING"}:
        migrated["phase"] = "RUNNING"
    for task in migrated.get("tasks", []):
        if not isinstance(task, dict):
            raise LifecycleError("invalid-workflow-state", "legacy task entries must be objects")
        if task.get("status") in {"VALIDATING", "ACCEPTANCE_PENDING"}:
            raise LifecycleError(
                "workflow-state-migration-unsupported-status",
                "legacy task status has no v4 producer contract",
                {"taskId": task.get("id"), "status": task.get("status")},
            )
    migrated.setdefault("operationLedger", {})
    migrated.setdefault("priorSnapshots", [])
    migrated.setdefault("blocker", None)
    migrated.setdefault("authorization", {"required": False, "granted": True})
    return migrated


__all__ = ["initialize_workflow_state", "migrate_workflow_state"]
