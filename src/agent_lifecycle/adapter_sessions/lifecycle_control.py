"""Adapter-session bridge for host-owned lifecycle-control gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.freeze import plan_integrity_required, verify_plan_package_integrity
from agent_lifecycle.host_protocol.lifecycle_control import load_lifecycle_control_policy
from agent_lifecycle.host_protocol.lifecycle_gate import (
    evaluate_post_action_gate,
    evaluate_pre_action_gate,
    evaluate_stop_gate,
    lifecycle_control_selection,
    require_lifecycle_gate_pass,
)


def pre_action_gate(
    *,
    manifest_path: Path,
    lock_path: Path,
    state_path: Path,
    operation: str,
    action_digest: str,
    paths: list[str],
    requested_level: str | None = None,
    policy_path: Path | None = None,
    next_action: dict[str, Any] | None = None,
    task_id: str | None = None,
    expected_state_revision: int | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Return a pre-action decision for a host adapter without launching it."""

    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    lock = read_json_object(lock_path, label="plan lock")
    state = read_json_object(state_path, label="workflow state")
    selected_level, selected_policy, _ = lifecycle_control_selection(state)
    policy = selected_policy or (load_lifecycle_control_policy(policy_path) if policy_path else None)
    package_integrity: dict[str, Any] | None = None
    if plan_integrity_required(manifest):
        if repository_root is None:
            package_integrity = {
                "status": "FAIL",
                "blockers": [{"code": "repository-root-required"}],
            }
        else:
            try:
                package_integrity = verify_plan_package_integrity(
                    manifest,
                    lock,
                    repository_root=repository_root,
                )
            except LifecycleError as exc:
                package_integrity = {
                    "status": "FAIL",
                    "blockers": [{"code": exc.code, "message": exc.message}],
                }
    return evaluate_pre_action_gate(
        manifest=manifest,
        lock=lock,
        state=state,
        operation=operation,
        action_digest=action_digest,
        paths=paths,
        requested_level=requested_level or selected_level,
        policy=policy,
        next_action=next_action,
        task_id=task_id,
        expected_state_revision=(
            expected_state_revision if expected_state_revision is not None else 0
        ),
        package_integrity=package_integrity,
    )


def require_pre_action(**kwargs: Any) -> dict[str, Any]:
    """Raise before the host action when the selected gate blocks it."""

    gate = pre_action_gate(**kwargs)
    return require_lifecycle_gate_pass(gate, gate_type="pre-action")


def post_action_gate(
    *,
    pre_action: dict[str, Any],
    manifest_path: Path,
    actual_changed_paths: list[str],
    outcome: dict[str, Any] | None = None,
    actual_status: str = "PASS",
    event: dict[str, Any] | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Validate host output and changed paths after an authorized action."""

    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    policy = load_lifecycle_control_policy(policy_path) if policy_path else None
    return evaluate_post_action_gate(
        pre_action=pre_action,
        manifest=manifest,
        actual_changed_paths=actual_changed_paths,
        outcome=outcome,
        actual_status=actual_status,
        event=event,
        policy=policy,
    )


def require_post_action(**kwargs: Any) -> dict[str, Any]:
    """Raise when selected post-action evidence does not match the action."""

    gate = post_action_gate(**kwargs)
    return require_lifecycle_gate_pass(gate, gate_type="post-action")


def stop_gate(
    *,
    state_path: Path,
    final_audit: dict[str, Any] | None = None,
    final_proof: dict[str, Any] | None = None,
    pre_action: dict[str, Any] | None = None,
    post_action: dict[str, Any] | None = None,
    requested_level: str | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate the stop boundary from a durable workflow state snapshot."""

    state = read_json_object(state_path, label="workflow state")
    selected_level, selected_policy, _ = lifecycle_control_selection(state)
    policy = selected_policy or (load_lifecycle_control_policy(policy_path) if policy_path else None)
    return evaluate_stop_gate(
        state=state,
        final_audit=final_audit,
        final_proof=final_proof,
        pre_action=pre_action,
        post_action=post_action,
        requested_level=requested_level or selected_level,
        policy=policy,
    )


def require_stop(**kwargs: Any) -> dict[str, Any]:
    """Raise when selected stop evidence is incomplete or inconsistent."""

    gate = stop_gate(**kwargs)
    return require_lifecycle_gate_pass(gate, gate_type="stop")


__all__ = [
    "post_action_gate",
    "pre_action_gate",
    "require_post_action",
    "require_pre_action",
    "require_stop",
    "stop_gate",
]
