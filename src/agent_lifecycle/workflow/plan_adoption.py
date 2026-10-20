"""Frozen-plan adoption and execution-start transitions."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from typing import cast as _validated_cast

from agent_lifecycle.compiler.task_packets import packet_publication_lock
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.authority_io import read_authority_bytes
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, load_json_object
from agent_lifecycle.contracts.immutable_input_schemas import validate_a5_plan_policy, validate_a5_policy
from agent_lifecycle.contracts.ownership_paths import require_manifest_authority_paths
from agent_lifecycle.freeze import verify_plan_lock_envelope, verify_plan_package_integrity
from agent_lifecycle.planning.completeness import require_plan_completeness_pass, validate_plan_completeness
from agent_lifecycle.planning.prerequisites import validate_prerequisite_acceptance
from agent_lifecycle.planning.task_compatibility import (
    build_task_plan_compatibility_receipt,
    task_contracts_compatible,
)
from agent_lifecycle.planning.validation import validate_plan_manifest
from agent_lifecycle.specification import validate_completion_check
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root, require_artifact_identity
from agent_lifecycle.workflow.checkpoint_gate import normalize_context_checkpoint_policy
from agent_lifecycle.workflow.events import event_log_path, read_events
from agent_lifecycle.workflow.immutable_input import adoption_binding, policies_compatible_for_adoption
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
    require_current_authorization,
)
from agent_lifecycle.workflow.transactions import workflow_transaction

# Preserve the existing internal extension point while keeping one algorithm.
_task_contract_compatible = task_contracts_compatible


@workflow_transaction
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
    state = load_for_update(
        state_path, operation_id=operation_id, expected_revision=expected_revision, authorization_required=False
    )
    _require_adoptable(state, reset_tasks=reset_tasks)
    root = package_root(state_path, state)
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    digest = _verify_frozen_manifest(root, manifest)
    validate_prerequisite_acceptance(manifest, repository_root=root)
    artifact_root = manifest.get("package", {}).get("artifactRoot")
    if not isinstance(artifact_root, str) or not artifact_root:
        raise LifecycleError("invalid-plan-manifest", "package.artifactRoot is required")
    with packet_publication_lock(root / artifact_root / "workflow/task-packets"):
        revision = _plan_revision(manifest)
        _require_revision_upgrade(state, digest, revision, reset_tasks=reset_tasks)
        packet_set, packets = _packet_set(root, manifest, digest)
        tasks = _build_tasks(manifest, packets)
        previous_tasks = {task["id"]: task for task in state["tasks"]}
        unresolved = {item["taskId"]: copy.deepcopy(item) for item in state.get("unresolvedPlanIncompatibilities", [])}
        for previous in state["tasks"]:
            if "planIncompatibility" in previous:
                unresolved[previous["id"]] = copy.deepcopy(previous["planIncompatibility"])
        for task in tasks:
            previous = previous_tasks.get(task["id"], {})
            if task["id"] in unresolved:
                task["planIncompatibility"] = copy.deepcopy(unresolved[task["id"]])
                if "usageTotals" in previous:
                    task["usageTotals"] = copy.deepcopy(previous["usageTotals"])
                elif "cumulativeUsageTotals" in unresolved[task["id"]]:
                    task["usageTotals"] = copy.deepcopy(unresolved[task["id"]]["cumulativeUsageTotals"])
                else:
                    task.pop("usageTotals", None)
                task["priorFinancialObligations"] = copy.deepcopy(
                    previous.get(
                        "priorFinancialObligations", unresolved[task["id"]].get("financialObligations", previous)
                    )
                )
        original_admissions: dict[str, dict[str, Any]] = {}
        original_legacy_plans: dict[str, str] = {}
        if preserve_accepted_compatible:
            if not reset_tasks:
                raise LifecycleError(
                    "reset-required",
                    "preserving accepted tasks requires resetTasks",
                )
            if any(task.get("status") == "ACCEPTED" for task in state["tasks"]):
                original_admissions, original_legacy_plans = _reconcile_previous_a5_authority(
                    state_path, state, legacy_start_required={task["id"] for task in tasks if "immutableInput" in task}
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
                current_plan_policy=manifest.get("immutableInput"),
                original_admissions=original_admissions,
                original_legacy_plans=original_legacy_plans,
            )
        for task in tasks:
            if "planIncompatibility" in task:
                unresolved[task["id"]] = copy.deepcopy(task["planIncompatibility"])
        incompatibilities = list(unresolved.values())
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
        if incompatibilities:
            state["unresolvedPlanIncompatibilities"] = incompatibilities
            state["phase"] = "BLOCKED"
            state["blocker"] = {
                "code": "plan-drift",
                "reason": "Accepted A5 evidence is incompatible; bounded disposition is required",
                "resumePhase": "READY",
            }
        plan_root = manifest["package"]["planArtifactRoot"]
        frozen_lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
        verify_plan_lock_envelope(manifest, frozen_lock)
        commit_state(
            state_path,
            state,
            operation_id=operation_id,
            event_type="plan-adopted",
            payload={
                "previousPhase": previous_phase,
                "planRevision": revision,
                "planDigest": digest,
                "frozenPlanAuthority": {"manifest": manifest, "lock": frozen_lock},
                "incompatibilities": incompatibilities,
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


@workflow_transaction
def start_execution(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(
        state_path, operation_id=operation_id, expected_revision=expected_revision, authorization_required=False
    )
    if state.get("startMode") == "plan-only" or state.get("phase") == "PLAN_ONLY":
        raise LifecycleError("plan-only-not-executable", "plan-only workflow cannot start execution")
    if state["phase"] != "READY":
        raise LifecycleError("invalid-phase", "execution can only start from READY")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    require_current_authorization(state)
    previous = state["phase"]
    required = [task for task in state.get("tasks", []) if task.get("required", True)]
    state["phase"] = (
        "FINAL_AUDIT" if required and all(task.get("status") == "ACCEPTED" for task in required) else "RUNNING"
    )
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="execution-started",
        payload={"previousPhase": previous, "phase": state["phase"], "reason": reason},
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
    require_manifest_authority_paths(manifest, operation_root=root)
    if isinstance(manifest.get("packageIntegrity"), dict):
        require_plan_completeness_pass(validate_plan_completeness(manifest))
    digest = canonical_digest(manifest)
    plan_root = manifest.get("package", {}).get("planArtifactRoot")
    if not isinstance(plan_root, str) or not plan_root:
        raise LifecycleError("invalid-plan-manifest", "package.planArtifactRoot is required")
    lock = read_json_object(root / plan_root / "plan.lock.json", label="plan lock")
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    review_mesh = (
        _validated_cast(dict[str, Any], manifest.get("reviewMesh"))
        if isinstance(manifest.get("reviewMesh"), dict)
        else None
    )
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
        if "immutableInput" in manifest:
            validate_a5_plan_policy(manifest["immutableInput"])
            task["immutableInput"] = copy.deepcopy(validate_a5_policy(workstream.get("immutableInput")))
        for field in ("readOnly", "forbiddenWrites", "leadOwned"):
            if field in workstream:
                task[field] = copy.deepcopy(workstream[field])
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
    current_plan_policy: dict[str, Any] | None = None,
    original_admissions: dict[str, Any] | None = None,
    original_legacy_plans: dict[str, str] | None = None,
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
        if not policies_compatible_for_adoption(
            accepted,
            task,
            previous_plan_policy=previous_state.get("immutableInput"),
            current_plan_policy=current_plan_policy,
        ):
            task["planIncompatibility"] = {
                "taskId": task["id"],
                "code": "a5-policy-incompatible",
                "previousPlanDigest": previous_state["planDigest"],
                "previousAttempt": accepted["attempt"],
                "originalEvidenceArchived": True,
                "automaticRetryAuthorized": False,
                **(
                    {"cumulativeUsageTotals": copy.deepcopy(accepted["usageTotals"])}
                    if "usageTotals" in accepted
                    else {}
                ),
                "financialObligations": copy.deepcopy(accepted),
            }
            task["priorFinancialObligations"] = copy.deepcopy(accepted)
            if "usageTotals" in accepted:
                task["usageTotals"] = copy.deepcopy(accepted["usageTotals"])
            else:
                task.pop("usageTotals", None)
            continue
        identity = {
            key: current_plan.get(key) for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
        }
        compatibility_receipt = build_task_plan_compatibility_receipt(
            previous_state=previous_state,
            current_plan=identity,
            previous_task=accepted,
            current_task=task,
        )
        a5_binding = adoption_binding(
            previous_state,
            accepted,
            task,
            identity,
            compatibility_receipt,
            trusted_original_admission=(original_admissions or {}).get(task["id"]),
            trusted_legacy_plan_digest=(original_legacy_plans or {}).get(task["id"]),
        )
        _copy_accepted_runtime(task, accepted)
        task["adoptedFromPlanDigest"] = prior_digest
        task["adoptedFromPlanRevision"] = prior_revision
        task["planCompatibilityReceipt"] = compatibility_receipt
        if a5_binding is not None:
            task["immutableInputAdoption"] = a5_binding
    return new_tasks


def _reconcile_previous_a5_authority(
    state_path: Path,
    state: dict[str, Any],
    *,
    legacy_start_required: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    from agent_lifecycle.workflow.immutable_input import (
        is_unadopted_ordinary_context,
        original_admission_from_events,
        original_legacy_plan_from_history,
        require_task_consumer_admission,
    )

    accepted = [task for task in state["tasks"] if task.get("status") == "ACCEPTED"]
    events = list(read_events(event_log_path(state_path, state)))
    original_admissions = {
        task["id"]: original_admission_from_events(
            state, task, events, require_legacy_start=task["id"] in (legacy_start_required or set())
        )
        for task in accepted
    }
    original_legacy_plans = {
        task["id"]: original_legacy_plan_from_history(state, task, events)
        for task in accepted
        if original_admissions[task["id"]] is None and task["id"] in (legacy_start_required or set())
    }
    if all(is_unadopted_ordinary_context(state, task) for task in accepted):
        return original_admissions, original_legacy_plans
    root = package_root(state_path, state)
    matches = [
        event
        for event in events
        if event.get("eventType") == "plan-adopted"
        and event.get("runId") == state["runId"]
        and event.get("packageId") == state["packageId"]
        and event.get("payload", {}).get("planDigest") == state["planDigest"]
        and "frozenPlanAuthority" in event.get("payload", {})
    ]
    if matches:
        event = matches[-1]
        operation = state.get("operationLedger", {}).get(event.get("operationId"))
        if (
            not isinstance(operation, dict)
            or operation.get("eventType") != "plan-adopted"
            or operation.get("stateRevision") != event.get("stateRevision")
            or event["stateRevision"] > state["stateRevision"]
        ):
            raise LifecycleError("a5-context-invalid", "Previous frozen authority lacks its native adoption")
        authority = event["payload"]["frozenPlanAuthority"]
        if not isinstance(authority, dict) or set(authority) != {"manifest", "lock"}:
            raise LifecycleError("a5-context-invalid", "Previous frozen authority is malformed")
        manifest, lock = authority["manifest"], authority["lock"]
        validate_plan_manifest(manifest)
        verify_plan_lock_envelope(manifest, lock)
        if canonical_digest(manifest) != state["planDigest"] or manifest["planRevision"] != state["planRevision"]:
            raise LifecycleError("a5-context-invalid", "Previous journal authority differs from the adopted plan")
    else:
        manifest = read_json_object(root / state["manifestPath"], label="previous frozen manifest")
        if _verify_frozen_manifest(root, manifest) != state["planDigest"]:
            raise LifecycleError("a5-context-invalid", "Previous frozen authority is unavailable")
    registry = (
        read_json_object(root / "profiles/immutable-input-adapter-capabilities.v1.json", label="A5 route boundaries")
        if "immutableInput" in manifest
        else None
    )
    original_admissions = {}
    for task in accepted:
        for role in ("result", "review", "implementationAuditReport"):
            if isinstance(task.get(role), dict):
                require_artifact_identity(root, task[role], label="preserved " + role)
        original = original_admission_from_events(state, task, events)
        require_task_consumer_admission(
            manifest,
            state,
            task,
            {
                "runId": state["runId"],
                "packageId": state["packageId"],
                "taskId": task["id"],
                "targetAttempt": task["attempt"],
                "operationId": "preservation-check",
                "stateRevision": state["stateRevision"],
                "planDigest": state["planDigest"],
                "sourceRevision": state["sourceRevision"],
            },
            registry=registry,
            trusted_original_admission=original,
        )
        original_admissions[task["id"]] = original
    return original_admissions, original_legacy_plans


def _copy_accepted_runtime(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    preserved_keys = (
        "attempt",
        "attemptHistoryStart",
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
        "immutableInputAdmission",
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
            "tasks": copy.deepcopy(state.get("tasks", [])),
            "immutableInput": copy.deepcopy(state.get("immutableInput")),
            "sourceRevision": state.get("sourceRevision"),
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "financialRole": "HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING",
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
    if "immutableInput" in manifest:
        state["immutableInput"] = copy.deepcopy(validate_a5_plan_policy(manifest["immutableInput"]))
    else:
        state.pop("immutableInput", None)
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
    data = read_authority_bytes(root / report, root=root, max_bytes=MAX_JSON_INPUT_BYTES)
    review = load_json_object(data, label="plan review")
    identity = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
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
    data = read_authority_bytes(path, max_bytes=MAX_JSON_INPUT_BYTES)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
