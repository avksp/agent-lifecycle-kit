"""Terminal workflow finalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.events import append_event
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import (
    load_state,
    now_iso,
    record_operation,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)


def finalize_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    proof_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    if state.get("phase") != "FINAL_AUDIT":
        raise LifecycleError("invalid-phase", "run finalization requires FINAL_AUDIT phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    missing = _missing_required_acceptance(state)
    if missing:
        raise LifecycleError("finalization-precondition-failed", "required tasks are not accepted", {"tasks": missing})
    root = package_root(state_path, state)
    proof_rel = normalize_repo_path(proof_path)
    proof = _proof_body(state, reason=reason)
    write_json_create(root / proof_rel, proof)
    identity = artifact_identity(root, proof_rel, proof)
    state["finalProof"] = {**identity, "semanticStatus": proof["semanticStatus"]}
    state["phase"] = "COMPLETE"
    _commit(
        state_path,
        state,
        operation_id=operation_id,
        event_type="run-finalized",
        payload={"proof": state["finalProof"], "reason": reason},
    )
    return status(state_path)


def _missing_required_acceptance(state: dict[str, Any]) -> list[str]:
    return [
        str(task.get("id"))
        for task in state.get("tasks", [])
        if task.get("required", True) and task.get("status") != "ACCEPTED"
    ]


def _proof_body(state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    accepted = [
        {
            "id": task.get("id"),
            "attempt": task.get("attempt"),
            "review": task.get("review"),
        }
        for task in state.get("tasks", [])
        if task.get("status") == "ACCEPTED"
    ]
    body = {
        "schemaVersion": "agent-run-final-proof.v1",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevisionBeforeFinalization": state.get("stateRevision"),
        "semanticStatus": "READY_FOR_FINALIZATION",
        "productionPromotionClaimed": False,
        "acceptedTasks": accepted,
        "reason": reason,
        "createdAt": now_iso(),
    }
    return {**body, "bodyDigest": canonical_digest(body)}


def _commit(
    state_path: Path,
    state: dict[str, Any],
    *,
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    state["stateRevision"] += 1
    state["updatedAt"] = now_iso()
    record_operation(state, operation_id=operation_id, event_type=event_type)
    append_event(state_path=state_path, state=state, operation_id=operation_id, event_type=event_type, payload=payload)
    write_state_replace(state_path, state)
