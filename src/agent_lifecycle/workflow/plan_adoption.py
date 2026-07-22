"""Frozen-plan adoption and execution-start transitions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.events import append_event
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.selectors import unlock_ready_tasks
from agent_lifecycle.workflow.state import (
    TERMINAL_PHASES,
    deadline_after,
    load_state,
    now_iso,
    record_operation,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)


def adopt_plan(
    state_path: Path,
    *,
    manifest_path: Path,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reset_tasks: bool,
    preserve_accepted_compatible: bool = False,
    start_mode: str,
    authorized_by: str | None = None,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    _require_adoptable(state, reset_tasks=reset_tasks)
    root = package_root(state_path, state)
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    digest = _verify_frozen_manifest(root, manifest)
    revision = _plan_revision(manifest)
    _require_revision_upgrade(state, digest, revision, reset_tasks=reset_tasks)
    packet_set, packets = _packet_set(root, manifest, digest)
    tasks = _build_tasks(manifest, packets)
    if preserve_accepted_compatible:
        if not reset_tasks:
            raise LifecycleError(
                "reset-required",
                "preserving accepted tasks requires resetTasks",
            )
        tasks = _preserve_accepted_tasks(state, tasks)
    previous_phase = state["phase"]
    _archive_prior_snapshot(state)
    _replace_plan_state(
        state,
        state_path=state_path,
        manifest_path=manifest_path,
        manifest=manifest,
        digest=digest,
        revision=revision,
        root=root,
        source_revision=source_revision,
        start_mode=start_mode,
        authorized_by=authorized_by,
        packet_set=packet_set,
        tasks=tasks,
    )
    _commit(
        state_path,
        state,
        operation_id=operation_id,
        event_type="plan-adopted",
        payload={
            "previousPhase": previous_phase,
            "planRevision": revision,
            "resetTasks": reset_tasks,
            "preserveAcceptedCompatible": preserve_accepted_compatible,
        },
    )
    return status(state_path)


def start_execution(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    if state["phase"] != "READY":
        raise LifecycleError("invalid-phase", "execution can only start from READY")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "execution authorization is required")
    previous = state["phase"]
    state["phase"] = "RUNNING"
    state["updatedAt"] = now_iso()
    _commit(
        state_path,
        state,
        operation_id=operation_id,
        event_type="execution-started",
        payload={"previousPhase": previous, "reason": reason},
    )
    return status(state_path)


def _require_adoptable(state: dict[str, Any], *, reset_tasks: bool) -> None:
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot adopt a plan")
    task_started = any(task.get("attempt") or task.get("status") not in {"PENDING", "READY"} for task in state["tasks"])
    if task_started and not reset_tasks:
        raise LifecycleError("reset-required", "adopting a changed plan after task start requires resetTasks")


def _verify_frozen_manifest(root: Path, manifest: dict[str, Any]) -> str:
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "only FROZEN plans can be adopted")
    digest = canonical_digest(manifest)
    plan_root = manifest.get("package", {}).get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    if lock.get("manifestHash") != digest:
        raise LifecycleError("plan-lock-mismatch", "plan lock manifestHash does not match manifest")
    if lock.get("planRevision") != manifest.get("planRevision"):
        raise LifecycleError("plan-lock-mismatch", "plan lock revision does not match manifest")
    return digest


def _plan_revision(manifest: dict[str, Any]) -> int:
    revision = manifest.get("planRevision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise LifecycleError("invalid-plan-manifest", "planRevision must be a positive integer")
    return revision


def _require_revision_upgrade(
    state: dict[str, Any],
    digest: str,
    revision: int,
    *,
    reset_tasks: bool,
) -> None:
    if revision < int(state.get("planRevision", 0)):
        raise LifecycleError("older-plan", "cannot adopt an older plan revision")
    if reset_tasks and digest == state.get("planDigest"):
        raise LifecycleError("same-plan-reset", "resetTasks requires a changed plan digest")


def _packet_set(root: Path, manifest: dict[str, Any], digest: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    artifact_root = manifest.get("package", {}).get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    index_rel = f"{artifact_root.rstrip('/')}/workflow/task-packets/index.json"
    index = read_json_object(root / index_rel, label="task packet index")
    if index.get("manifestDigest") != digest:
        raise LifecycleError("packet-set-mismatch", "task packet index is not bound to the adopted plan")
    packets = {
        packet["taskId"]: packet
        for packet in index.get("packets", [])
        if isinstance(packet, dict) and isinstance(packet.get("taskId"), str)
    }
    identity = artifact_identity(root, index_rel, index)
    lock_rel = f"{manifest['package']['planArtifactRoot'].rstrip('/')}/plan.lock.json"
    return {
        **identity,
        "manifestDigest": digest,
        "packetSetHash": index.get("packetSetHash"),
        "controllerValidation": index.get("controllerValidation"),
        "planLockSha256": _raw_file_identity(root / lock_rel)["sha256"],
    }, packets


def _build_tasks(
    manifest: dict[str, Any],
    packets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    gates = manifest.get("controllerGates", {}).get("gates", [])
    tasks: list[dict[str, Any]] = []
    for workstream in manifest.get("workstreams", []):
        task_id = workstream["id"]
        depends_on = list(workstream.get("dependsOn", []))
        tasks.append({
            "id": task_id,
            "title": workstream.get("title"),
            "owner": workstream.get("owner"),
            "dependsOn": depends_on,
            "writes": list(workstream.get("writes", [])),
            "reviewer": workstream.get("reviewer"),
            "launchGate": workstream.get("launchGate"),
            "capabilityHints": list(workstream.get("capabilityHints", [])),
            "requiredTools": list(workstream.get("requiredTools", [])),
            "contextRefs": list(workstream.get("contextRefs", [])),
            "evidenceIds": list(workstream.get("evidenceIds", [])),
            "executionPolicy": workstream.get("executionPolicy", {}),
            "artifactPaths": workstream.get("artifactPaths", _default_artifacts(manifest, task_id)),
            "controllerGates": _task_gates(gates, task_id),
            "packet": packets.get(task_id),
            "required": workstream.get("required", True),
            "status": "READY" if not depends_on else "PENDING",
            "attempt": 0,
            "attemptHistory": [],
            "usageIterations": [],
            "usageTotals": {"iterations": 0, "reportedTokens": 0, "toolCalls": 0},
            "validationRuns": 0,
            "controllerGateReceipts": [],
            "remediationFindingIds": [],
        })
    return tasks


def _preserve_accepted_tasks(
    previous_state: dict[str, Any],
    new_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous = {
        task.get("id"): task
        for task in previous_state.get("tasks", [])
        if isinstance(task, dict) and task.get("status") == "ACCEPTED"
    }
    prior_digest = previous_state.get("planDigest")
    prior_revision = previous_state.get("planRevision")
    for task in new_tasks:
        accepted = previous.get(task.get("id"))
        if not accepted or not _task_contract_compatible(accepted, task):
            continue
        _copy_accepted_runtime(task, accepted)
        task["adoptedFromPlanDigest"] = prior_digest
        task["adoptedFromPlanRevision"] = prior_revision
    return new_tasks


def _task_contract_compatible(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    keys = (
        "id",
        "title",
        "owner",
        "dependsOn",
        "writes",
        "reviewer",
        "launchGate",
        "capabilityHints",
        "requiredTools",
        "contextRefs",
        "evidenceIds",
        "executionPolicy",
        "artifactPaths",
        "required",
    )
    return all(previous.get(key) == current.get(key) for key in keys)


def _copy_accepted_runtime(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    preserved_keys = (
        "attempt",
        "attemptHistory",
        "result",
        "review",
        "status",
        "usageIterations",
        "usageTotals",
        "validationRuns",
        "controllerGateReceipts",
        "remediationFindingIds",
        "lastReason",
    )
    for key in preserved_keys:
        if key in source:
            target[key] = source[key]


def _task_gates(gates: list[Any], task_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": gate.get("id"),
            "phases": gate.get("phases", []),
            "receiptPath": gate.get("receiptPath"),
            "maxAgeSeconds": gate.get("maxAgeSeconds"),
            "attestationRequired": gate.get("attestationRequired", False),
            "dependsOnGateIds": gate.get("dependsOnGateIds", []),
        }
        for gate in gates
        if isinstance(gate, dict) and task_id in gate.get("appliesTo", [])
    ]


def _default_artifacts(manifest: dict[str, Any], task_id: str) -> dict[str, str]:
    artifact_root = manifest["package"]["artifactRoot"].rstrip("/")
    base = f"{artifact_root}/workflow/tasks/{task_id}/attempt-{{attempt}}"
    return {"result": f"{base}/task-result.json", "review": f"{base}/task-review.json"}


def _archive_prior_snapshot(state: dict[str, Any]) -> None:
    state.setdefault("priorSnapshots", []).append({
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "phase": state.get("phase"),
        "taskSummary": {task.get("id"): task.get("status") for task in state.get("tasks", [])},
        "archivedAt": now_iso(),
    })


def _replace_plan_state(
    state: dict[str, Any],
    *,
    state_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    digest: str,
    revision: int,
    root: Path,
    source_revision: str,
    start_mode: str,
    authorized_by: str | None,
    packet_set: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> None:
    state["manifestPath"] = os.path.relpath(manifest_path, state_path.parent)
    state["planRevision"] = revision
    state["planDigest"] = digest
    state["sourceRevision"] = source_revision
    state["startMode"] = start_mode
    state["budgets"] = dict(manifest.get("orchestration", {}))
    state["runDeadlineAt"] = deadline_after(state["runStartedAt"], int(state["budgets"].get("maxRunWallSeconds", 86400)))
    state["packetSet"] = packet_set
    state["tasks"] = tasks
    unlock_ready_tasks(state)
    state["taskAcceptanceActions"] = []
    state["blocker"] = None
    state["reconciliation"] = None
    state["authorization"] = _authorization(start_mode, authorized_by)
    state["phase"] = "READY" if state["authorization"].get("granted") else "AWAITING_AUTHORIZATION"
    state["lastPlanReview"] = _last_plan_review(root, manifest)


def _authorization(start_mode: str, authorized_by: str | None) -> dict[str, Any]:
    if start_mode == "auto-after-freeze":
        if not authorized_by:
            raise LifecycleError("authorization-required", "auto-after-freeze requires authorizedBy")
        return {"required": False, "granted": True, "grantedBy": authorized_by, "grantedAt": now_iso()}
    if start_mode == "approval-required":
        return {"required": True, "granted": False}
    if start_mode == "plan-only":
        return {"required": False, "granted": False}
    raise LifecycleError("invalid-start-mode", "unsupported start mode")


def _last_plan_review(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    report = manifest.get("planReview", {}).get("report")
    if not isinstance(report, str):
        raise LifecycleError("invalid-plan-manifest", "planReview.report is required")
    review = read_json_object(root / report, label="plan review")
    identity = _raw_file_identity(root / report)
    return {
        **identity,
        "path": report,
        "reviewId": review.get("reviewId"),
        "reviewer": review.get("reviewer", {}).get("id"),
        "reviewerRunId": review.get("reviewer", {}).get("runId"),
        "surface": review.get("reviewer", {}).get("surface"),
        "verdict": review.get("verdict"),
    }


def _raw_file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


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
