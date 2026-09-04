"""Task-start transition and exact execution-strategy adoption."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import agent_lifecycle.workflow.state as workflow_state
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.ownership_paths import normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.freeze import verify_plan_lock_envelope
from agent_lifecycle.host_protocol.capabilities import validate_capability_manifest
from agent_lifecycle.policy.execution_strategy import (
    POLICY_INPUT_IDENTITY_SCHEMA,
    PROJECT_PROFILE_ABSENT_DIGEST,
    resolve_execution_strategy,
    validate_execution_strategy,
)
from agent_lifecycle.workflow.artifacts import (
    artifact_identity,
    next_available_attempt,
    package_root,
    validate_attempt_history,
)
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.model_usage import validate_attempt_model_route
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.risk_execution_gate import (
    apply_task_risk_profile,
    clear_task_risk_profile,
    load_task_risk_profile,
)
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import deadline_after


def start_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    risk_profile_path: str | None = None,
    strategy_path: str | None = None,
    strategy_inputs: dict[str, Any] | None = None,
    reason: str,
) -> dict[str, Any]:
    """Start one dependency-ready task with optional exact strategy authority."""

    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] not in {"RUNNING", "REMEDIATING"}:
        raise LifecycleError("invalid-phase", f"cannot start task from phase {state['phase']}")
    require_source_and_authorization(state, source_revision)
    task = find_task(state, task_id)
    if task.get("status") not in {"READY", "REWORK"}:
        raise LifecycleError("invalid-task-status", f"task {task_id} is not launchable")
    _require_dependencies_accepted(state, task)
    _require_parallel_capacity(state)
    validate_attempt_history(state_path, state, task)
    _validate_task_authority_paths(state, task)
    attempt = next_available_attempt(state_path, state, task)

    clear_task_risk_profile(task)
    _clear_task_execution_strategy(task)
    risk_profile: dict[str, Any] | None = None
    if risk_profile_path is not None:
        risk_profile, profile_identity = load_task_risk_profile(
            state_path,
            state,
            task,
            risk_profile_path,
            operation_id=operation_id,
            source_revision=source_revision,
        )
        apply_task_risk_profile(task, risk_profile, profile_identity)
    strategy_identity = None
    if strategy_path is not None:
        strategy, strategy_identity = _load_task_execution_strategy(
            state_path,
            state,
            task,
            strategy_path,
            operation_id=operation_id,
            source_revision=source_revision,
            target_attempt=attempt,
            strategy_inputs=strategy_inputs,
        )
        _apply_task_execution_strategy(task, strategy, strategy_identity, risk_profile=risk_profile)

    gate_receipts = validate_controller_gates(
        state_path,
        state,
        task,
        phase="pre-launch",
        operation_id=operation_id,
        attempt=attempt,
    )
    _mark_task_running(state, task, attempt, reason)
    record_gate_receipts(task, gate_receipts)
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-started",
        payload={
            "taskId": task_id,
            "attempt": attempt,
            "executionStrategy": strategy_identity,
            "reason": reason,
        },
    )
    return status(state_path)


def _load_task_execution_strategy(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    strategy_path: str,
    *,
    operation_id: str,
    source_revision: str,
    target_attempt: int,
    strategy_inputs: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = package_root(state_path, state)
    relative = normalize_repo_path(strategy_path, label="execution strategy")
    strategy = read_json_object(root / relative, label="execution strategy")
    validation = validate_execution_strategy(strategy)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "execution-strategy-invalid",
            "task start requires a valid execution strategy",
            {"validation": validation},
        )
    authority = _object(strategy.get("authority"))
    if authority.get("automaticAdoptionEligible") is not True:
        raise LifecycleError(
            "execution-strategy-adoption-ineligible",
            "task start requires an adoption-eligible execution strategy",
        )
    lineage = _object(strategy.get("lineage"))
    manifest, lock, lock_validation = _current_plan_envelope(root, state)
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "lockDigest": canonical_digest(lock),
        "lockManifestHash": lock_validation.get("manifestHash"),
        "taskId": task.get("id"),
        "operationId": operation_id,
        "stateRevision": state.get("stateRevision"),
        "sourceRevision": source_revision,
        "targetAttempt": target_attempt,
    }
    for field, value in expected.items():
        if lineage.get(field) != value:
            raise LifecycleError(
                "execution-strategy-lineage-mismatch",
                f"execution strategy {field} mismatch",
            )
    if canonical_digest(manifest) != state.get("planDigest"):
        raise LifecycleError("execution-strategy-lineage-mismatch", "current plan digest changed")
    inputs = _load_strategy_inputs(root, strategy_inputs)
    descriptor, capability = _validate_bound_capability(
        root,
        strategy,
        lineage,
        descriptor_path=inputs["descriptorPath"],
        capability_path=inputs["capabilityManifestPath"],
    )
    project_profile_digest = _validate_bound_project_profile(
        root,
        strategy,
        lineage,
        project_profile_path=inputs["projectProfilePath"],
    )
    _validate_bound_policy_inputs(strategy, inputs)
    expected_strategy = resolve_execution_strategy(
        manifest=manifest,
        lock=lock,
        state=state,
        task_id=_required_string(task.get("id"), label="strategy task id"),
        adapter_id=_required_string(lineage.get("adapterId"), label="strategy adapter id"),
        adapter_host=_required_string(lineage.get("adapterHost"), label="strategy adapter host"),
        operation_id=operation_id,
        expected_revision=int(state["stateRevision"]),
        source_revision=source_revision,
        requested_risk=inputs["requestedRisk"],
        risk_policy=inputs["riskPolicy"],
        routing_profile=inputs["routingProfile"],
        baseline_profile=inputs["baselineProfile"],
        host_profile=inputs["hostProfile"],
        project_profile_digest=project_profile_digest,
        descriptor=descriptor,
        capability_manifest=capability,
        target_attempt=target_attempt,
        descriptor_path=inputs["descriptorPath"],
        capability_manifest_path=inputs["capabilityManifestPath"],
        project_profile_path=inputs["projectProfilePath"],
    )
    if strategy.get("strategyDigest") != expected_strategy.get("strategyDigest"):
        raise LifecycleError(
            "execution-strategy-policy-content-mismatch",
            "execution strategy does not match the current trusted policy inputs",
        )
    return strategy, artifact_identity(root, relative, strategy)


def _current_plan_envelope(
    root: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest_path = state.get("manifestPath")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise LifecycleError("execution-strategy-plan-context-missing", "adopted manifest path is required")
    manifest_relative = normalize_repo_path(manifest_path, label="frozen plan manifest")
    manifest = read_json_object(root / manifest_relative, label="frozen plan manifest")
    lock_relative = normalize_repo_path(
        Path(manifest_relative).with_name("plan.lock.json").as_posix(),
        label="plan lock",
    )
    lock = read_json_object(root / lock_relative, label="plan lock")
    return manifest, lock, verify_plan_lock_envelope(manifest, lock)


def _validate_bound_capability(
    root: Path,
    strategy: dict[str, Any],
    lineage: dict[str, Any],
    *,
    descriptor_path: str,
    capability_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = _object(strategy.get("adoptionBinding"))
    if binding.get("descriptorPath") != descriptor_path or binding.get("capabilityManifestPath") != capability_path:
        raise LifecycleError(
            "execution-strategy-capability-path-mismatch",
            "execution strategy capability paths do not match trusted task-start inputs",
        )
    descriptor = read_json_object(root / descriptor_path, label="adapter descriptor")
    capability = read_json_object(root / capability_path, label="capability manifest")
    if canonical_digest(descriptor) != binding.get("descriptorDigest"):
        raise LifecycleError(
            "execution-strategy-descriptor-stale", "adapter descriptor changed after strategy resolution"
        )
    if canonical_digest(capability) != binding.get("capabilityManifestDigest"):
        raise LifecycleError(
            "execution-strategy-capability-stale",
            "capability manifest changed after strategy resolution",
        )
    if descriptor.get("adapterId") != lineage.get("adapterId") or descriptor.get("host") != lineage.get("adapterHost"):
        raise LifecycleError("execution-strategy-descriptor-mismatch", "adapter descriptor identity changed")
    capability_validation = validate_capability_manifest(capability, descriptor=descriptor)
    if capability_validation.get("status") != "PASS":
        raise LifecycleError(
            "execution-strategy-capability-invalid",
            "capability manifest no longer matches the adapter descriptor",
            {"validation": capability_validation},
        )
    return descriptor, capability


def _validate_bound_project_profile(
    root: Path,
    strategy: dict[str, Any],
    lineage: dict[str, Any],
    *,
    project_profile_path: str,
) -> str | None:
    binding = _object(strategy.get("adoptionBinding"))
    identity = binding.get("projectProfileIdentity")
    if not isinstance(identity, dict) or lineage.get("projectProfileIdentity") != identity:
        raise LifecycleError("execution-strategy-project-profile-mismatch", "project profile identity changed")
    if identity.get("path") != project_profile_path:
        raise LifecycleError(
            "execution-strategy-project-profile-mismatch",
            "project profile path does not match trusted task-start inputs",
        )
    path = root / project_profile_path
    if identity.get("status") == "ABSENT":
        if identity.get("digest") != PROJECT_PROFILE_ABSENT_DIGEST or path.exists():
            raise LifecycleError(
                "execution-strategy-project-profile-stale",
                "an absent project profile identity no longer matches the filesystem",
            )
        return None
    if identity.get("status") != "PRESENT":
        raise LifecycleError("execution-strategy-project-profile-invalid", "project profile identity is unavailable")
    profile = read_json_object(path, label="project profile")
    if canonical_digest(profile) != identity.get("digest"):
        raise LifecycleError(
            "execution-strategy-project-profile-stale", "project profile changed after strategy resolution"
        )
    return canonical_digest(profile)


def _load_strategy_inputs(root: Path, value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(
            "execution-strategy-inputs-required",
            "task start requires policy inputs independent from the strategy receipt",
        )
    requested_risk = _required_string(value.get("requestedRisk"), label="strategy requested risk")
    if requested_risk not in {"auto", "S0", "S1", "S2"}:
        raise LifecycleError("execution-strategy-input-invalid", "strategy requested risk is unsupported")
    descriptor_path = _trusted_repo_path(value, "descriptorPath", label="adapter descriptor")
    capability_path = _trusted_repo_path(value, "capabilityManifestPath", label="capability manifest")
    project_profile_path = _trusted_repo_path(value, "projectProfilePath", label="project profile")
    return {
        "requestedRisk": requested_risk,
        "riskPolicy": _read_policy_input(root, value, "riskPolicyPath", label="risk execution policy"),
        "routingProfile": _read_policy_input(root, value, "routingProfilePath", label="model routing profile"),
        "baselineProfile": _read_policy_input(root, value, "baselineProfilePath", label="lifecycle baseline profile"),
        "hostProfile": _read_policy_input(
            root,
            value,
            "hostProfilePath",
            label="host model profile",
            required=False,
        ),
        "descriptorPath": descriptor_path,
        "capabilityManifestPath": capability_path,
        "projectProfilePath": project_profile_path,
    }


def _validate_bound_policy_inputs(strategy: dict[str, Any], inputs: dict[str, Any]) -> None:
    binding = _object(strategy.get("adoptionBinding"))
    identities = _object(binding.get("policyInputs"))
    if identities.get("requestedRisk") != inputs["requestedRisk"]:
        raise LifecycleError(
            "execution-strategy-policy-input-stale",
            "requested risk does not match the trusted task-start input",
        )
    fields = {
        "riskPolicy": inputs["riskPolicy"],
        "routingProfile": inputs["routingProfile"],
        "baselineProfile": inputs["baselineProfile"],
        "hostProfile": inputs["hostProfile"],
    }
    for name, current in fields.items():
        identity = identities.get(name)
        if not isinstance(identity, dict):
            raise LifecycleError("execution-strategy-policy-input-stale", f"{name} binding is missing")
        if current is None:
            body = {
                "schemaVersion": POLICY_INPUT_IDENTITY_SCHEMA,
                "name": name,
                "status": "ABSENT",
            }
            expected_digest = canonical_digest(body)
            expected_status = "ABSENT"
        else:
            expected_digest = canonical_digest(current)
            expected_status = "PRESENT"
        if identity.get("status") != expected_status or identity.get("digest") != expected_digest:
            raise LifecycleError(
                "execution-strategy-policy-input-stale",
                f"{name} changed after strategy resolution",
            )


def _trusted_repo_path(value: dict[str, Any], field: str, *, label: str) -> str:
    return normalize_repo_path(_required_string(value.get(field), label=f"{label} path"), label=label)


def _read_policy_input(
    root: Path,
    value: dict[str, Any],
    field: str,
    *,
    label: str,
    required: bool = True,
) -> dict[str, Any] | None:
    raw = value.get(field)
    if raw is None and not required:
        return None
    path_value = _required_string(raw, label=f"{label} path")
    path = Path(path_value)
    if not path.is_absolute():
        path = root / normalize_repo_path(path_value, label=label)
    return read_json_object(path, label=label)


def _apply_task_execution_strategy(
    task: dict[str, Any],
    strategy: dict[str, Any],
    identity: dict[str, Any],
    *,
    risk_profile: dict[str, Any] | None,
) -> None:
    route = _object(strategy.get("modelRoute"))
    source_decisions = _object(strategy.get("sourceDecisionDigests"))
    risk_route = _object(risk_profile.get("modelRoute")) if risk_profile is not None else {}
    if risk_profile is not None and (
        source_decisions.get("riskProfile") != risk_profile.get("profileDigest")
        or route.get("decisionDigest") != risk_route.get("decisionDigest")
    ):
        raise LifecycleError(
            "execution-strategy-risk-profile-mismatch",
            "execution strategy and risk profile were not derived from the same decision",
        )
    task["executionStrategy"] = {
        **identity,
        "strategyDigest": strategy["strategyDigest"],
        "adoptionBindingDigest": canonical_digest(strategy["adoptionBinding"]),
        "adapterId": strategy["lineage"]["adapterId"],
        "targetAttempt": strategy["lineage"]["targetAttempt"],
        "quality": dict(_object(strategy.get("quality"))),
        "packet": dict(_object(strategy.get("packet"))),
        "reviewMesh": dict(_object(strategy.get("reviewMesh"))),
        "resourceCaps": dict(_object(strategy.get("resourceCaps"))),
        "usageEvidence": dict(_object(strategy.get("usageEvidence"))),
        "modelRoute": dict(route),
    }
    task["adapterId"] = strategy["lineage"]["adapterId"]
    task["modelRoute"] = dict(route)


def _clear_task_execution_strategy(task: dict[str, Any]) -> None:
    strategy = task.pop("executionStrategy", None)
    task.pop("attemptExecutionStrategy", None)
    if not isinstance(strategy, dict):
        return
    route = task.get("modelRoute")
    strategy_route = strategy.get("modelRoute")
    if (
        isinstance(route, dict)
        and isinstance(strategy_route, dict)
        and (route.get("decisionDigest") == strategy_route.get("decisionDigest"))
    ):
        task.pop("modelRoute", None)


def require_source_and_authorization(state: dict[str, Any], source_revision: str) -> None:
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "execution authorization is required")


def _require_dependencies_accepted(state: dict[str, Any], task: dict[str, Any]) -> None:
    accepted = {item.get("id") for item in state["tasks"] if item.get("status") == "ACCEPTED"}
    missing = sorted(set(task.get("dependsOn", [])).difference(accepted))
    if missing:
        raise LifecycleError(
            "task-dependencies-missing",
            f"task {task.get('id')} dependencies are not accepted",
            {"missing": missing},
        )


def _require_parallel_capacity(state: dict[str, Any]) -> None:
    running = sum(1 for item in state["tasks"] if item.get("status") in {"RUNNING", "VALIDATING", "VERIFYING"})
    max_parallel = int(state.get("budgets", {}).get("maxParallelTasks", 1))
    if running >= max_parallel:
        raise LifecycleError("parallelism-budget-exhausted", "maxParallelTasks budget reached")


def _mark_task_running(state: dict[str, Any], task: dict[str, Any], attempt: int, reason: str) -> None:
    history = task.get("attemptHistory")
    task.setdefault("attemptHistoryStart", history[0]["attempt"] if history else attempt)
    task["attempt"] = attempt
    task["status"] = "RUNNING"
    clear_active_attempt_references(task)
    task["attemptStartedAt"] = workflow_state.now_iso()
    task["attemptBaseRevision"] = state.get("sourceRevision")
    task["attemptDeadlineAt"] = deadline_after(
        task["attemptStartedAt"],
        int(state.get("budgets", {}).get("maxTaskWallSeconds", 3600)),
    )
    task["lastReason"] = reason
    if isinstance(task.get("modelRoute"), dict) and task["modelRoute"]:
        validate_attempt_model_route(task)
        task["attemptModelRoute"] = {**task["modelRoute"], "attempt": attempt}
    if isinstance(task.get("riskExecutionProfile"), dict) and task["riskExecutionProfile"]:
        task["attemptRiskExecutionProfile"] = {**task["riskExecutionProfile"], "attempt": attempt}
    if isinstance(task.get("executionStrategy"), dict) and task["executionStrategy"]:
        if task["executionStrategy"].get("targetAttempt") != attempt:
            raise LifecycleError("execution-strategy-attempt-mismatch", "execution strategy targets another attempt")
        task["attemptExecutionStrategy"] = {**task["executionStrategy"], "attempt": attempt}
    _apply_attempt_wall_cap(state, task)
    state["phase"] = "RUNNING"


def _apply_attempt_wall_cap(state: dict[str, Any], task: dict[str, Any]) -> None:
    candidates = [task.get("attemptRiskExecutionProfile"), task.get("attemptExecutionStrategy")]
    limits = [
        item.get("resourceCaps", {}).get("maxWallSeconds")
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("resourceCaps"), dict)
    ]
    limits = [item for item in limits if isinstance(item, int) and not isinstance(item, bool) and item > 0]
    if not limits:
        return
    task["attemptDeadlineAt"] = deadline_after(
        task["attemptStartedAt"],
        min(min(limits), int(state.get("budgets", {}).get("maxTaskWallSeconds", 3600))),
    )


def clear_active_attempt_references(task: dict[str, Any]) -> None:
    task["usageIterations"] = []
    task["controllerGateReceipts"] = []
    for key in (
        "result",
        "review",
        "resultChangeSetEvidence",
        "implementationAuditReport",
        "ownershipReceipt",
        "modelUsageReceipt",
        "lifecycleControlPostAction",
        "attemptModelRoute",
        "attemptRiskExecutionProfile",
        "attemptExecutionStrategy",
        "attemptBaseRevision",
        "attemptStartedAt",
        "attemptDeadlineAt",
        "budgetDecision",
        "budgetDecisionApplied",
        "lifecycleControlPreAction",
    ):
        task.pop(key, None)


def _validate_task_authority_paths(state: dict[str, Any], task: dict[str, Any]) -> None:
    for path in task.get("writes", []):
        if isinstance(path, str):
            normalize_authority_path(path, label="task write path")
    policy = state.get("writePolicy", {}) if isinstance(state.get("writePolicy"), dict) else {}
    for field in ("readOnly", "forbiddenWrites"):
        for path in policy.get(field, []):
            if isinstance(path, str):
                normalize_authority_path(path, label=f"{field} path")


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("execution-strategy-binding-invalid", f"{label} is required")
    return value
