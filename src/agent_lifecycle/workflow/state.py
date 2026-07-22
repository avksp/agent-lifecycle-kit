"""Workflow state loading, validation and atomic persistence."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest

TERMINAL_PHASES = {"COMPLETE", "FAILED", "CANCELLED"}
EXECUTION_PHASES = {"RUNNING", "STEP_REVIEW", "REMEDIATING"}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict[str, Any]:
    state = read_json_object(path, label="workflow state")
    if state.get("schemaVersion") != "agent-workflow-state.v3":
        raise LifecycleError("unsupported-workflow-state", "workflow state schemaVersion is unsupported")
    if not isinstance(state.get("stateRevision"), int) or state["stateRevision"] < 1:
        raise LifecycleError("invalid-workflow-state", "stateRevision must be a positive integer")
    if not isinstance(state.get("phase"), str) or not state["phase"]:
        raise LifecycleError("invalid-workflow-state", "phase is required")
    if not isinstance(state.get("tasks"), list):
        raise LifecycleError("invalid-workflow-state", "tasks must be an array")
    return state


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
    data = canonical_bytes(state) + b"\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(tmp, flags, 0o644), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


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


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
