"""Managed workflow step-function.

This module is intentionally read-only. It checks the frozen plan and durable
workflow state, then returns the next host action as a typed receipt. Host
adapters remain responsible for launching model/tool work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.freeze import verify_plan_package_integrity
from agent_lifecycle.workflow.next_action import MODEL_CALLS_STARTED, build_managed_next_action
from agent_lifecycle.workflow.implementation_audit_gate import implementation_audit_blockers
from agent_lifecycle.workflow.state import load_state, state_identity


def run_managed_lifecycle_step(
    *,
    state_path: Path,
    manifest_path: Path,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    lock_path: Path | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    lock: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    next_action: dict[str, Any] | None = None

    try:
        manifest = read_json_object(manifest_path, label="frozen plan manifest")
        _require_frozen_manifest(manifest)
        lock = _load_lock(manifest_path, lock_path)
        verify_plan_package_integrity(manifest, lock, repository_root=Path.cwd())
    except LifecycleError as exc:
        blockers.append(_blocker(exc.code, exc.message, exc.details))

    try:
        state = load_state(state_path)
        _require_state_lineage(
            state,
            manifest=manifest,
            expected_revision=expected_revision,
            source_revision=source_revision,
        )
        if not blockers:
            next_action = build_managed_next_action(state)
            audit_blockers = implementation_audit_blockers(state_path, state)
            if audit_blockers:
                blockers.extend(audit_blockers)
                next_action = None
    except LifecycleError as exc:
        blockers.append(_blocker(exc.code, exc.message, exc.details))

    status = "FAIL" if blockers else "PASS"
    body = {
        "schemaVersion": "agent-managed-lifecycle-runner-receipt.v1",
        "status": status,
        "operationId": operation_id,
        "reason": reason,
        "expectedRevision": expected_revision,
        "sourceRevision": source_revision,
        "state": _state_summary(state_path, state),
        "plan": _plan_summary(manifest, manifest_path),
        "nextAction": next_action or _blocked_next_action(blockers),
        "blockers": blockers,
        "modelCallsStarted": MODEL_CALLS_STARTED,
        "stateWritten": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _load_lock(manifest_path: Path, lock_path: Path | None) -> dict[str, Any]:
    path = lock_path or manifest_path.with_name("plan.lock.json")
    return read_json_object(path, label="plan lock")


def _require_frozen_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "managed lifecycle run requires a FROZEN plan")
    revision = manifest.get("planRevision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise LifecycleError("invalid-plan-manifest", "planRevision must be a positive integer")


def _require_state_lineage(
    state: dict[str, Any],
    *,
    manifest: dict[str, Any] | None,
    expected_revision: int,
    source_revision: str,
) -> None:
    if state["stateRevision"] != expected_revision:
        raise LifecycleError(
            "state-revision-mismatch",
            "workflow state revision mismatch",
            {"expected": expected_revision, "actual": state["stateRevision"]},
        )
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    if manifest is None:
        return
    package = manifest.get("package", {}) if isinstance(manifest.get("package"), dict) else {}
    package_id = package.get("id")
    if isinstance(package_id, str) and state.get("packageId") != package_id:
        raise LifecycleError("package-id-mismatch", "workflow state packageId does not match manifest")
    if state.get("planRevision") != manifest.get("planRevision"):
        raise LifecycleError("plan-revision-mismatch", "workflow state planRevision does not match manifest")
    digest = canonical_digest(manifest)
    if state.get("planDigest") != digest:
        raise LifecycleError("plan-digest-mismatch", "workflow state planDigest does not match manifest")


def _state_summary(state_path: Path, state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        **state_identity(state_path, state),
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "phase": state.get("phase"),
    }


def _plan_summary(manifest: dict[str, Any] | None, manifest_path: Path) -> dict[str, Any] | None:
    if manifest is None:
        return None
    package = manifest.get("package", {}) if isinstance(manifest.get("package"), dict) else {}
    return {
        "path": manifest_path.as_posix(),
        "packageId": package.get("id"),
        "planRevision": manifest.get("planRevision"),
        "planDigest": canonical_digest(manifest),
        "status": manifest.get("status"),
    }


def _blocked_next_action(blockers: list[dict[str, Any]]) -> dict[str, Any]:
    action = {
        "schemaVersion": "agent-managed-lifecycle-next-action.v1",
        "type": "blocked",
        "status": "BLOCKED",
        "hostActionRequired": False,
        "modelCallsStarted": MODEL_CALLS_STARTED,
        "stateMutationRequired": False,
        "projectedAction": None,
        "taskIds": [],
        "blockers": blockers,
    }
    return {**action, "actionDigest": canonical_digest(action)}


def _blocker(code: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": code, "message": message}
    if context:
        blocker["context"] = context
    return blocker
