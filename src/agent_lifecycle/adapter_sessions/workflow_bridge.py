"""Composition between managed adapter sessions and ALK workflow state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_adapter_session_receipt, build_resume_receipt
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor, managed_launch_profile
from agent_lifecycle.adapter_sessions.session_store import create_session, load_session, update_session
from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.workflow import run_managed_lifecycle_step


def managed_adapter_run(
    *,
    adapter_id: str,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    descriptor_path: Path | None = None,
    session_root: Path | None = None,
) -> dict[str, Any]:
    _descriptor_path, descriptor = load_adapter_descriptor(adapter_id, descriptor_path)
    profile = managed_launch_profile(descriptor)
    runner_receipt = run_managed_lifecycle_step(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=f"managed adapter run for {task_id}",
    )
    state_identity = {**_state_identity(state_path), "taskId": task_id}
    proof = _managed_proof("adapter run", adapter_id=adapter_id, task_id=task_id, state_identity=state_identity)
    session = create_session(
        adapter_id=adapter_id,
        mode="MANAGED_TASK",
        status="READY" if runner_receipt["status"] == "PASS" else "BLOCKED",
        launch_profile=profile,
        session_root=session_root,
        state_identity=state_identity,
        managed_workflow_proof=proof,
    )
    return build_adapter_session_receipt(
        status=session["status"],
        session_id=session["sessionId"],
        adapter_id=adapter_id,
        mode="MANAGED_TASK",
        launch_profile=profile,
        state_identity=state_identity,
        managed_workflow_proof=proof,
        progress_hook_default="stderr",
        host_launch_started=False,
        blockers=runner_receipt.get("blockers", []),
        next_action=runner_receipt.get("nextAction"),
    )


def promote_session_to_workflow(
    *,
    session_id: str,
    state_path: Path,
    task_id: str,
    adapter_id: str | None = None,
    session_root: Path | None = None,
) -> dict[str, Any]:
    session = load_session(session_id, session_root=session_root)
    if adapter_id and session.get("adapterId") != adapter_id:
        return build_resume_receipt(
            session_id=session_id,
            adapter_id=adapter_id,
            expected_identity={"adapterId": adapter_id},
            actual_identity={"adapterId": session.get("adapterId")},
            blockers=[{"code": "adapter-session-adapter-mismatch"}],
        )
    identity = {**_state_identity(state_path), "taskId": task_id}
    proof = _managed_proof("adapter session promote", adapter_id=session["adapterId"], task_id=task_id, state_identity=identity)
    session["mode"] = "PROMOTED"
    session["status"] = "READY"
    session["stateIdentity"] = identity
    session["managedWorkflowProof"] = proof
    update_session(session, session_root=session_root)
    return build_adapter_session_receipt(
        status="READY",
        session_id=session_id,
        adapter_id=session["adapterId"],
        mode="PROMOTED",
        launch_profile=session.get("launchProfile", {}),
        state_identity=identity,
        managed_workflow_proof=proof,
        progress_hook_default="stderr",
    )


def resume_adapter_session(
    *,
    session_id: str,
    session_root: Path | None = None,
    adapter_id: str | None = None,
    state_path: Path | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    session = load_session(session_id, session_root=session_root)
    expected: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []
    if adapter_id:
        if session.get("adapterId") != adapter_id:
            blockers.append({"code": "adapter-session-adapter-mismatch", "expected": adapter_id, "actual": session.get("adapterId")})
    if task_id:
        expected["taskId"] = task_id
    actual = session.get("stateIdentity") if isinstance(session.get("stateIdentity"), dict) else {}
    if state_path is not None:
        expected.update(_state_identity(state_path))
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                blockers.append({"code": "adapter-session-lineage-mismatch", "field": key, "expected": expected_value, "actual": actual.get(key)})
    return build_resume_receipt(
        session_id=session_id,
        adapter_id=session.get("adapterId", adapter_id or ""),
        expected_identity=expected,
        actual_identity=actual,
        blockers=blockers,
    )


def _state_identity(state_path: Path) -> dict[str, Any]:
    state = read_json_object(state_path, label="workflow state")
    return {
        "statePath": state_path.as_posix(),
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
        "phase": state.get("phase"),
    }


def _managed_proof(command: str, *, adapter_id: str, task_id: str, state_identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "alk-managed-adapter-session",
        "status": "PASS",
        "command": command,
        "adapterId": adapter_id,
        "taskId": task_id,
        "stateIdentity": state_identity,
    }
