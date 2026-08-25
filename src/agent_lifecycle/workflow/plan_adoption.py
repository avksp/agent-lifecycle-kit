"""Frozen-plan adoption and execution-start transitions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.freeze import verify_plan_package_integrity
from agent_lifecycle.planning.completeness import require_plan_completeness_pass, validate_plan_completeness
from agent_lifecycle.planning.task_compatibility import (
    build_task_plan_compatibility_receipt,
    task_contracts_compatible,
)
from agent_lifecycle.planning.validation import validate_plan_manifest
from agent_lifecycle.specification import validate_completion_check
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.checkpoint_gate import normalize_context_checkpoint_policy
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.review_mesh_gate import (
    require_review_mesh_quorum_gate_pass,
    validate_review_mesh_quorum_path,
)
from agent_lifecycle.workflow.selectors import unlock_ready_tasks
from agent_lifecycle.workflow.state import (
    TERMINAL_PHASES,
    deadline_after,
    now_iso,
)

# Preserve the existing internal extension point while keeping one algorithm.
_task_contract_compatible = task_contracts_compatible


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
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
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
        tasks = _preserve_accepted_tasks(
            state,
            tasks,
            current_plan={
                "runId": state.get("runId"),
                "packageId": state.get("packageId"),
                "planRevision": revision,
                "planDigest": digest,
                "sourceRevision": source_revision,
            },
        )
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
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="plan-adopted",
        payload={
            "previousPhase": previous_phase,
            "planRevision": revision,
            "resetTasks": reset_tasks,
            "preserveAcceptedCompatible": preserve_accepted_compatible,
            "taskCompatibilityReceipts": [
                {
                    "taskId": task.get("id"),
                    "receiptDigest": task["planCompatibilityReceipt"]["receiptDigest"],
                }
                for task in tasks
                if isinstance(task.get("planCompatibilityReceipt"), dict)
            ],
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
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("startMode") == "plan-only" or state.get("phase") == "PLAN_ONLY":
        raise LifecycleError("plan-only-not-executable", "plan-only workflow cannot start execution")
    if state["phase"] != "READY":
        raise LifecycleError("invalid-phase", "execution can only start from READY")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "execution authorization is required")
    previous = state["phase"]
    state["phase"] = "RUNNING"
    commit_state(
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
    validate_plan_manifest(manifest)
    if manifest.get("status") != "FROZEN":
        raise LifecycleError("plan-not-frozen", "only FROZEN plans can be adopted")
    if isinstance(manifest.get("packageIntegrity"), dict):
        require_plan_completeness_pass(validate_plan_completeness(manifest))
    digest = canonical_digest(manifest)
    plan_root = manifest.get("package", {}).get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    review_mesh = manifest.get("reviewMesh") if isinstance(manifest.get("reviewMesh"), dict) else None
    require_review_mesh_quorum_gate_pass(
        validate_review_mesh_quorum_path(
            root=root,
            phase="freeze",
            config=review_mesh,
            receipt_path=None,
        )
    )
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
    security_analysis = _security_analysis_config(manifest)
    for workstream in manifest.get("workstreams", []):
        task_id = workstream["id"]
        depends_on = list(workstream.get("dependsOn", []))
        task = {
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
                "acceptanceIds": list(workstream.get("acceptanceIds", [])),
                "evidenceIds": list(workstream.get("evidenceIds", [])),
                "executionPolicy": workstream.get("executionPolicy", {}),
                "modelRoute": dict(workstream.get("modelRoute", {}))
                if isinstance(workstream.get("modelRoute"), dict)
                else None,
                "reviewMesh": dict(workstream.get("reviewMesh", {}))
                if isinstance(workstream.get("reviewMesh"), dict)
                else None,
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
            }
        if security_analysis is not None:
            # Keep the extension advisory until the authoritative acceptance gate
            # reads the copy materialized into this adopted task.
            task["securityAnalysis"] = dict(security_analysis)
            task["securityAnalysisProfile"] = security_analysis.get("profileId")
            audit = security_analysis.get("implementationAudit")
            if isinstance(audit, dict):
                task["implementationAudit"] = dict(audit)
        tasks.append(task)
    return tasks


def _security_analysis_config(manifest: dict[str, Any]) -> dict[str, Any] | None:
    extensions = manifest.get("extensions")
    if not isinstance(extensions, dict):
        return None
    value = extensions.get("securityAnalysis")
    if not isinstance(value, dict):
        return None
    return {
        **value,
        "enabled": True,
        "authorityClaimed": False,
        "trustedByDefault": False,
    }


def _preserve_accepted_tasks(
    previous_state: dict[str, Any],
    new_tasks: list[dict[str, Any]],
    *,
    current_plan: dict[str, Any],
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
        if not accepted or not task_contracts_compatible(accepted, task):
            continue
        compatibility_receipt = build_task_plan_compatibility_receipt(
            previous_state=previous_state,
            current_plan=current_plan,
            previous_task=accepted,
            current_task=task,
        )
        _copy_accepted_runtime(task, accepted)
        task["adoptedFromPlanDigest"] = prior_digest
        task["adoptedFromPlanRevision"] = prior_revision
        task["planCompatibilityReceipt"] = compatibility_receipt
    return new_tasks


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
        "ownershipReceipt",
        "implementationAuditReport",
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
    base = f"{artifact_root}/workflow/work/{task_id}/attempt-{{attempt}}"
    return {"result": f"{base}/task-result.json", "review": f"{base}/task-review.json"}


def _archive_prior_snapshot(state: dict[str, Any]) -> None:
    state.setdefault("priorSnapshots", []).append(
        {
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "phase": state.get("phase"),
            "taskSummary": {task.get("id"): task.get("status") for task in state.get("tasks", [])},
            "archivedAt": now_iso(),
        }
    )


def _replace_plan_state(
    state: dict[str, Any],
    *,
    state_path: Path,  # noqa: ARG001
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
    try:
        state["manifestPath"] = manifest_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError(
            "manifest-path-outside-package-root",
            "adopted manifest must be contained by the workflow package root",
        ) from exc
    state["planRevision"] = revision
    state["planDigest"] = digest
    state["sourceRevision"] = source_revision
    state["startMode"] = start_mode
    state["budgets"] = dict(manifest.get("orchestration", {}))
    state["contextCheckpointPolicy"] = normalize_context_checkpoint_policy(manifest.get("contextCheckpointPolicy"))
    state["writePolicy"] = {
        "readOnly": list(manifest.get("readOnly", [])),
        "forbiddenWrites": list(manifest.get("forbiddenWrites", [])),
        "leadOwned": list(manifest.get("leadOwned", [])),
    }
    if isinstance(manifest.get("reviewMesh"), dict):
        state["reviewMesh"] = dict(manifest["reviewMesh"])
    else:
        state.pop("reviewMesh", None)
    _replace_completion_check_state(state, manifest)
    state["runDeadlineAt"] = deadline_after(
        state["runStartedAt"], int(state["budgets"].get("maxRunWallSeconds", 86400))
    )
    state["packetSet"] = packet_set
    state["tasks"] = tasks
    unlock_ready_tasks(state)
    state["taskAcceptanceActions"] = []
    state["blocker"] = None
    state["reconciliation"] = None
    state["authorization"] = _authorization(start_mode, authorized_by)
    if start_mode == "plan-only":
        state["phase"] = "PLAN_ONLY"
    else:
        state["phase"] = "READY" if state["authorization"].get("granted") else "AWAITING_AUTHORIZATION"
    state["lastPlanReview"] = _last_plan_review(root, manifest)


def _replace_completion_check_state(state: dict[str, Any], manifest: dict[str, Any]) -> None:
    specification = manifest.get("specification", {})
    check = specification.get("completionCheck") if isinstance(specification, dict) else None
    if check is None:
        state.pop("completionCheck", None)
        state.pop("completionCheckValidation", None)
        state.pop("completionCheckReceipt", None)
        return
    validation = validate_completion_check(check)
    state["completionCheck"] = {
        **check,
        "receiptPath": validation["receiptPath"],
    }
    state["completionCheckValidation"] = validation
    state.pop("completionCheckReceipt", None)


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
    review = manifest.get("planReview", {})
    report = review.get("report") if isinstance(review, dict) else None
    if not isinstance(report, str):
        return _last_plan_lock_review(root, manifest)
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


def _last_plan_lock_review(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    plan_root = manifest.get("package", {}).get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    review_path = lock.get("reviewPath")
    if not isinstance(review_path, str) or not review_path:
        raise LifecycleError("invalid-plan-manifest", "planReview.report or plan lock reviewPath is required")
    identity = _raw_file_identity(root / review_path)
    return {
        **identity,
        "path": review_path,
        "reviewId": lock.get("reviewId"),
        "reviewer": lock.get("frozenBy"),
        "reviewerRunId": None,
        "surface": "plan-lock",
        "verdict": manifest.get("planReview", {}).get("requiredVerdict"),
        "reviewedPlanHash": lock.get("reviewedPlanHash"),
    }


def _raw_file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
