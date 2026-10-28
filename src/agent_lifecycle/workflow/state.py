"""Workflow state loading, validation and atomic persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest, prepare_json_object
from agent_lifecycle.contracts.persistence import replace_private_json as write_json_replace_private
from agent_lifecycle.contracts.workflow_state_authority import (
    BLOCKER_RECOVERY_ROUTES as BLOCKER_RECOVERY_ROUTES,
)
from agent_lifecycle.contracts.workflow_state_authority import (
    read_workflow_authority,
)
from agent_lifecycle.contracts.workflow_state_authority import (
    require_storage_root as require_storage_root,
)
from agent_lifecycle.contracts.workflow_state_authority import (
    storage_root_for_state as storage_root_for_state,
)
from agent_lifecycle.contracts.workflow_state_authority import (
    validate_typed_blocker as validate_typed_blocker,
)

TERMINAL_PHASES = {"COMPLETE", "FAILED", "CANCELLED"}
EXECUTION_PHASES = {"RUNNING", "STEP_REVIEW", "REMEDIATING"}
EXTERNAL_ACTION_PHASES = {"RUNNING", "FINAL_AUDIT", "STEP_REVIEW", "REMEDIATING"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_current_authorization(state: dict[str, Any]) -> None:
    """Honor revocation and a consumed receipt's expiry on every mutation."""
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "workflow mutation requires execution authorization")
    expires = authorization.get("expiresAt")
    if expires is None:
        return  # Existing immediate/legacy grants retain their original contract.
    try:
        deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise LifecycleError("authorization-invalid", "workflow authorization expiry is invalid") from None
    if datetime.now(UTC) >= deadline:
        raise LifecycleError("authorization-expired", "workflow execution authorization has expired")


def load_state(path: Path) -> dict[str, Any]:
    return read_workflow_authority(path)


def state_identity(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    data = canonical_bytes(state) + b"\n"
    return {
        "path": path.as_posix(),
        "sha256": canonical_digest(state),
        "bytes": len(data),
        "stateRevision": state["stateRevision"],
    }


def require_expected_revision(state: dict[str, Any], expected_revision: int) -> None:
    if state["stateRevision"] != expected_revision:
        raise LifecycleError(
            "state-revision-mismatch",
            "workflow state revision mismatch",
            {"expected": expected_revision, "actual": state["stateRevision"]},
        )


def require_operation_unused(state: dict[str, Any], operation_id: str) -> None:
    ledger = state.setdefault("operationLedger", {})
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    if operation_id in ledger:
        raise LifecycleError("duplicate-operation", f"operation already recorded: {operation_id}")


def record_operation(state: dict[str, Any], *, operation_id: str, event_type: str) -> None:
    ledger = state.setdefault("operationLedger", {})
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    ledger[operation_id] = {
        "stateRevision": state["stateRevision"],
        "eventType": event_type,
        "recordedAt": now_iso(),
    }


def deadline_after(started_at: str, seconds: int) -> str:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("invalid-timestamp", f"invalid timestamp: {started_at}") from exc
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def write_state_replace(path: Path, state: dict[str, Any]) -> None:
    prepare_json_object(state, label="prospective workflow state")
    write_json_replace_private(path, state)


def summarize_state(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "id": task.get("id"),
            "status": task.get("status"),
            "attempt": task.get("attempt"),
            "dependsOn": task.get("dependsOn", []),
            "required": task.get("required", True),
        }
        for task in state["tasks"]
    ]
    return {
        "schemaVersion": "agent-workflow-status.v1",
        "identity": state_identity(path, state),
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "phase": state["phase"],
        "blocker": state.get("blocker"),
        "authorization": state.get("authorization"),
        "tasks": tasks,
    }
