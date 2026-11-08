"""Binding and execution-strategy helpers for the unified start facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.accounting.source_usage_context import load_source_usage_context
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_bytes,
    canonical_digest,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.authority_io import authority_location
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.freeze.package_integrity import verify_plan_package_integrity
from agent_lifecycle.model_routing.stage_bindings import availability_probe_only, recompute_stage_binding
from agent_lifecycle.policy.execution_strategy import (
    deferred_execution_strategy_summary,
    execution_strategy_summary,
    resolve_execution_strategy,
    validate_execution_strategy,
)
from agent_lifecycle.resources import builtin_profile_path
from agent_lifecycle.workflow.artifacts import next_available_attempt, package_root
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import require_current_authorization


def resolve_managed_execution_strategy(
    *,
    adapter_id: str,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    requested_risk: str,
    descriptor_path: Path | None = None,
    risk_policy_path: Path | None = None,
    routing_profile_path: Path | None = None,
    baseline_profile_path: Path | None = None,
    host_model_profile_path: Path | None = None,
    project_profile: dict[str, Any] | None = None,
    project_profile_path: Path | None = None,
    stage_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one adoption-eligible strategy from the managed-run inputs."""

    if lock_path is None:
        raise LifecycleError("strategy-lock-required", "managed strategy adoption requires a plan lock")
    state = read_json_object(state_path, label="workflow state")
    root = package_root(state_path, state)
    descriptor_file, descriptor = load_adapter_descriptor(adapter_id, descriptor_path)
    capability_file = _capability_manifest_path(root, descriptor_file, descriptor)
    capability = read_json_object(capability_file, label="capability manifest")
    profile_file = project_profile_path or root / ".alk/project-profile.json"
    if project_profile is None and profile_file.is_file():
        project_profile = read_json_object(profile_file, label="project profile")
    # Native task-start binds actual project bytes, before display normalization.
    source_profile = (
        read_json_object(profile_file, label="current project profile") if profile_file.is_file() else project_profile
    )
    profile_digest = canonical_digest(source_profile) if source_profile is not None else None
    risk_file = risk_policy_path or builtin_profile_path("risk-execution-policy.v1.json")
    routing_file = routing_profile_path or builtin_profile_path("model-routing-profile.v1.json")
    baseline_file = baseline_profile_path or builtin_profile_path("lifecycle-baselines.v1.json")
    task = find_task(state, task_id)
    if stage_binding is None:
        stage_binding = task.get("attemptExecutionStrategy", {}).get("stageBinding")
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    lock = read_json_object(lock_path, label="plan lock")
    policy_objects: dict[str, Any] = {
        "requestedRisk": requested_risk,
        "riskPolicy": read_json_object(risk_file, label="risk execution policy"),
        "routingProfile": read_json_object(routing_file, label="model routing profile"),
        "baselineProfile": read_json_object(baseline_file, label="lifecycle baseline profile"),
        "hostProfile": read_json_object(host_model_profile_path, label="host model profile")
        if host_model_profile_path is not None
        else None,
    }
    active = task.get("status") == "RUNNING" and stage_binding is not None
    if active:
        strategy = _load_managed_attempt_strategy(
            root=root,
            state=state,
            task=task,
            manifest=manifest,
            lock=lock,
            adapter_id=adapter_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            manifest_path=manifest_path,
            descriptor=descriptor,
            capability=capability,
            profile_digest=profile_digest,
            descriptor_path=_repo_relative(root, descriptor_file, label="adapter descriptor"),
            capability_path=_repo_relative(root, capability_file, label="capability manifest"),
            profile_path=_repo_relative(root, profile_file, label="project profile"),
            policy_objects=policy_objects,
            stage_binding=stage_binding,
        )
    else:
        selected_attempt = next_available_attempt(state_path, state, task)
        strategy = resolve_execution_strategy(
            manifest=manifest,
            lock=lock,
            state=state,
            task_id=task_id,
            adapter_id=adapter_id,
            adapter_host=str(descriptor.get("host", "")),
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            requested_risk=requested_risk,
            risk_policy=policy_objects["riskPolicy"],
            routing_profile=policy_objects["routingProfile"],
            baseline_profile=policy_objects["baselineProfile"],
            host_profile=policy_objects["hostProfile"],
            project_profile_digest=profile_digest,
            descriptor=descriptor,
            capability_manifest=capability,
            target_attempt=selected_attempt,
            descriptor_path=_repo_relative(root, descriptor_file, label="adapter descriptor"),
            capability_manifest_path=_repo_relative(root, capability_file, label="capability manifest"),
            project_profile_path=_repo_relative(root, profile_file, label="project profile"),
            repository_root=root,
            stage_binding=stage_binding,
            source_usage_context=load_source_usage_context(
                root,
                manifest,
                state,
                task,
                adapter_id,
                str(descriptor.get("host", "")),
            ),
        )
    return {
        "strategy": strategy,
        "summary": execution_strategy_projection(strategy),
        "inputs": {
            "requestedRisk": requested_risk,
            "riskPolicyPath": risk_file.as_posix(),
            "routingProfilePath": routing_file.as_posix(),
            "baselineProfilePath": baseline_file.as_posix(),
            "hostProfilePath": host_model_profile_path.as_posix() if host_model_profile_path else None,
            "descriptorPath": strategy["adoptionBinding"]["descriptorPath"],
            "capabilityManifestPath": strategy["adoptionBinding"]["capabilityManifestPath"],
            "projectProfilePath": strategy["adoptionBinding"]["projectProfileIdentity"]["path"],
        },
    }


def _load_managed_attempt_strategy(
    *,
    root: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    manifest: dict[str, Any],
    lock: dict[str, Any],
    adapter_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    manifest_path: Path,
    descriptor: dict[str, Any],
    capability: dict[str, Any],
    profile_digest: str | None,
    descriptor_path: str,
    capability_path: str,
    profile_path: str,
    policy_objects: dict[str, Any],
    stage_binding: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project the adopted current attempt; prospective adoption remains separate."""
    require_current_authorization(state)
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    _require_managed_projection(
        state.get("phase") == "RUNNING"
        and state.get("stateRevision") == expected_revision
        and state.get("sourceRevision") == source_revision,
        "current revision/source/run differs",
    )
    _require_managed_projection(
        _repo_relative(root, manifest_path, label="manifest") == state.get("manifestPath")
        and canonical_digest(manifest) == state.get("planDigest"),
        "current frozen plan differs",
    )
    adopted = task.get("attemptExecutionStrategy")
    _require_managed_projection(isinstance(adopted, dict), "running task lacks adopted strategy")
    assert isinstance(adopted, dict)
    strategy_path = adopted.get("path")
    _require_managed_projection(isinstance(strategy_path, str), "adopted strategy path missing")
    assert isinstance(strategy_path, str)
    relative = normalize_repo_path(strategy_path, label="adopted strategy")
    strategy = read_json_object(root / relative, label="adopted current strategy")
    validation = validate_execution_strategy(strategy)
    _require_managed_projection(
        validation["status"] == "PASS"
        and canonical_digest(strategy) == adopted.get("sha256")
        and len(canonical_bytes(strategy) + b"\n") == adopted.get("bytes")
        and strategy["strategyDigest"] == adopted.get("strategyDigest"),
        "adopted strategy identity differs",
    )
    lineage, binding = strategy["lineage"], strategy["adoptionBinding"]
    actual_lineage = {key: state[key] for key in ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")}
    actual_lineage.update(
        taskId=task["id"],
        operationId=operation_id,
        adapterId=adapter_id,
        targetAttempt=task["attempt"],
        lockDigest=canonical_digest(lock),
    )
    _require_managed_projection(
        all(lineage.get(key) == value for key, value in actual_lineage.items()), "adopted attempt lineage differs"
    )
    _require_managed_projection(
        adopted.get("attempt") == task["attempt"]
        and adopted.get("targetAttempt") == task["attempt"]
        and strategy["modelRoute"] == adopted.get("modelRoute")
        and task.get("attemptModelRoute")
        in (strategy["modelRoute"], {**strategy["modelRoute"], "attempt": task["attempt"]})
        and strategy["resourceCaps"] == adopted.get("resourceCaps")
        and canonical_digest(binding) == adopted.get("adoptionBindingDigest"),
        "active route/hold differs",
    )
    _require_current_strategy_inputs(
        binding, descriptor, capability, descriptor_path, capability_path, profile_digest, profile_path, policy_objects
    )
    checked = recompute_stage_binding(
        root=root,
        profile_path=profile_path,
        proposed=stage_binding,
        profile_digest=profile_digest,
        host_profile=policy_objects["hostProfile"],
        adapter_id=adapter_id,
        route=strategy["modelRoute"],
    )
    _require_managed_projection(
        checked == strategy.get("stageBinding") == adopted.get("stageBinding"), "current stage binding differs"
    )
    load_source_usage_context(root, manifest, state, task, adapter_id, str(descriptor.get("host", "")))
    return strategy


def _require_current_strategy_inputs(
    binding: dict[str, Any],
    descriptor: dict[str, Any],
    capability: dict[str, Any],
    descriptor_path: str,
    capability_path: str,
    profile_digest: str | None,
    profile_path: str,
    policy_objects: dict[str, Any],
) -> None:
    _require_managed_projection(
        binding.get("descriptorDigest") == canonical_digest(descriptor)
        and binding.get("capabilityManifestDigest") == canonical_digest(capability)
        and binding.get("descriptorPath") == descriptor_path
        and binding.get("capabilityManifestPath") == capability_path,
        "descriptor/capability inputs changed",
    )
    identity = binding["projectProfileIdentity"]
    _require_managed_projection(
        identity.get("path") == profile_path and identity.get("digest") == profile_digest, "project profile changed"
    )
    inputs = binding["policyInputs"]
    _require_managed_projection(inputs.get("requestedRisk") == policy_objects["requestedRisk"], "risk request changed")
    for name in ("riskPolicy", "routingProfile", "baselineProfile", "hostProfile"):
        current, original = policy_objects[name], inputs[name]
        expected_status = "ABSENT" if current is None else "PRESENT"
        _require_managed_projection(original.get("status") == expected_status, "policy input presence changed")
        if current is not None:
            _require_managed_projection(original.get("digest") == canonical_digest(current), "policy input changed")


def _require_managed_projection(condition: bool, reason: str) -> None:
    if not condition:
        raise LifecycleError("strategy-active-attempt-mismatch", reason)


def prepare_stage_start(
    arguments: dict[str, Any],
    *,
    stage: str | None,
    binding_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve local opt-in before workflow mutation or adapter-session adoption."""
    from agent_lifecycle.adapter_sessions.stage_launch import select_stage_binding

    profile = arguments.get("project_profile")
    if not profile or not profile.get("policies", {}).get("executionBindings"):
        if binding_id is not None or stage is not None:
            raise LifecycleError(
                "stage-binding-opt-in-required", "explicit stage/binding requires project executionBindings"
            )
        return arguments, None
    if arguments.get("resume_session_id"):
        raise LifecycleError("stage-binding-active-attempt", "resume must preserve the active native binding")
    root = (arguments.get("project_root") or Path.cwd()).absolute()
    arguments = _normalize_stage_start_paths(arguments)
    profile_path = arguments.get("project_profile_path") or root / ".alk/project-profile.json"
    mode = arguments.get("mode", "auto")
    if mode == "auto":
        mode = profile.get("defaultMode", "auto")
    state_path = arguments.get("state_path")
    manifest_path = arguments.get("task_file")
    state = read_json_object(state_path, label="workflow state") if state_path is not None else None
    plan, plan_lock = _profile_plan_authority(
        task_file=manifest_path, task_text=arguments.get("task_text"), lock_path=arguments.get("lock_path")
    )
    tier = plan.get("specification", {}).get("tier", "S0") if plan else "S0"
    request: dict[str, Any] = {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": arguments.get("operation_id") or "stage-start-projection",
        "phase": "task-implementation" if mode == "implement" else mode,
        "sddTier": tier,
        "routingPolicy": "balanced",
        "targetContextWindow": "8k",
        "capabilityRequirements": [],
    }
    routing_file = arguments.get("routing_profile_path") or builtin_profile_path("model-routing-profile.v1.json")
    probe_preparation = _probe_preparation(arguments, plan, plan_lock, state, binding_id, root)
    selected = select_stage_binding(
        root=root,
        profile=profile,
        profile_path=profile_path,
        mode=mode,
        stage=stage,
        binding_id=binding_id,
        request=request,
        routing_profile=read_json_object(routing_file, label="routing profile"),
        state=state,
        task_id=arguments.get("task_id"),
        probe_preparation=probe_preparation,
    )
    if selected["status"] != "READY":
        raise LifecycleError(
            "stage-binding-selection-blocked",
            "stage selection cannot adopt a model task",
            {
                "selection": {
                    key: selected[key]
                    for key in ("status", "stage", "modelClass", "reasonCodes", "alternatives")
                    if key in selected
                }
            },
        )
    updated = _stage_start_model_inputs(arguments, selected, root)
    if mode == "implement":
        required = (
            "state_path",
            "task_file",
            "lock_path",
            "task_id",
            "operation_id",
            "expected_revision",
            "source_revision",
        )
        if any(updated.get(key) is None for key in required):
            raise LifecycleError(
                "stage-binding-native-input-required",
                "managed stage selection requires all existing frozen task bindings",
            )
        assert state is not None
        selected_task = find_task(state, updated["task_id"])
        if selected_task.get("status") not in {"RUNNING", "VALIDATING", "VERIFYING"}:
            selected["preparationReceipt"] = _prepare_stage_strategy(updated, selected, profile_path, root)
    return updated, selected


def _probe_preparation(
    arguments: dict[str, Any],
    manifest: dict[str, Any] | None,
    lock: dict[str, Any] | None,
    state: dict[str, Any] | None,
    binding_id: str | None,
    root: Path,
) -> bool:
    if manifest is None or state is None or not arguments.get("task_id"):
        return False
    if not availability_probe_only(manifest, arguments["task_id"]):
        return False
    task = find_task(state, arguments["task_id"])
    if task.get("status") in {"RUNNING", "VALIDATING", "VERIFYING"}:
        return False
    if not binding_id or not arguments.get("strategy_out_path") or arguments.get("launch") or lock is None:
        return False
    require_current_authorization(state)
    verify_plan_package_integrity(manifest, lock, repository_root=root)
    _require_probe_preparation_lineage(arguments, manifest, state, task)
    actual = root.resolve() / state["manifestPath"]
    if arguments.get("task_file") != actual or read_json_object(actual, label="actual frozen manifest") != manifest:
        raise LifecycleError(
            "stage-binding-probe-preparation-refused", "caller purpose differs from actual frozen manifest"
        )
    return True


def _require_probe_preparation_lineage(
    arguments: dict[str, Any],
    manifest: dict[str, Any],
    state: dict[str, Any],
    task: dict[str, Any],
) -> None:
    if (
        manifest.get("status") != "FROZEN"
        or state.get("phase") != "RUNNING"
        or state.get("planDigest") != canonical_digest(manifest)
        or state.get("sourceRevision") != arguments.get("source_revision")
        or state.get("stateRevision") != arguments.get("expected_revision")
        or state.get("planRevision") != manifest.get("planRevision")
    ):
        raise LifecycleError(
            "stage-binding-probe-preparation-refused", "probe preparation requires current frozen authority"
        )
    tasks = {row["id"]: row for row in state["tasks"]}
    if (
        task.get("attempt") != 0
        or task.get("status") not in {"PENDING", "READY"}
        or any(tasks.get(dep, {}).get("status") != "ACCEPTED" for dep in task.get("dependsOn", []))
    ):
        raise LifecycleError(
            "stage-binding-probe-preparation-refused", "probe preparation requires dependency-ready original admission"
        )


def _normalize_stage_start_paths(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments)
    for field in ("state_path", "task_file", "lock_path", "descriptor_path"):
        path = normalized.get(field)
        if path is not None:
            anchor, relative = authority_location(path)
            normalized[field] = anchor / relative
    return normalized


def _stage_start_model_inputs(arguments: dict[str, Any], selected: dict[str, Any], root: Path) -> dict[str, Any]:
    inspected = selected["inspected"]
    updates = {
        "adapter_id": inspected["entry"]["adapterId"],
        "host_model_profile_path": root / inspected["entry"]["hostModelProfile"]["path"],
        "host_launch_profile_path": root / inspected["entry"]["launchProfile"]["path"],
    }
    for key, value in updates.items():
        if arguments.get(key) is not None and str(arguments[key]) not in {
            str(value),
            str(value.relative_to(root)) if isinstance(value, Path) else str(value),
        }:
            raise LifecycleError(
                "stage-binding-cli-conflict", "explicit host inputs conflict with approved stage selection"
            )
    return {**arguments, **updates}


def _prepare_stage_strategy(
    arguments: dict[str, Any], selected: dict[str, Any], profile_path: Path, root: Path
) -> dict[str, Any]:
    """Prepare only the existing strategy artifact; never adopt or create a session."""
    from agent_lifecycle.adapter_sessions.contracts import build_lifecycle_start_receipt

    result = resolve_managed_execution_strategy(
        adapter_id=arguments["adapter_id"],
        state_path=arguments["state_path"],
        manifest_path=arguments["task_file"],
        lock_path=arguments["lock_path"],
        task_id=arguments["task_id"],
        operation_id=arguments["operation_id"],
        expected_revision=arguments["expected_revision"],
        source_revision=arguments["source_revision"],
        requested_risk=arguments["requested_risk"],
        descriptor_path=arguments["descriptor_path"],
        risk_policy_path=arguments["risk_policy_path"],
        routing_profile_path=arguments["routing_profile_path"],
        baseline_profile_path=arguments["baseline_profile_path"],
        host_model_profile_path=arguments["host_model_profile_path"],
        project_profile=arguments["project_profile"],
        project_profile_path=profile_path,
        stage_binding=selected["neutralBinding"],
    )
    output = arguments.get("strategy_out_path")
    if output is not None:
        candidate = output if output.is_absolute() else root / output
        anchor, relative = authority_location(candidate)
        candidate = anchor / relative
        candidate.relative_to(root.resolve())
        write_json_create(candidate, result["strategy"])
    blockers = (
        []
        if output is not None and not arguments.get("launch")
        else [
            {
                "code": "stage-binding-adoption-required",
                "preparation": (
                    "prepare with --strategy-out, then workflow task-start --strategy using the matching current inputs"
                ),
            }
        ]
    )
    receipt = build_lifecycle_start_receipt(
        status="BLOCKED" if blockers else "READY",
        adapter_id=arguments["adapter_id"],
        requested_mode=arguments["mode"],
        action="MANAGED_RUN",
        input_summary={"source": "file"},
        delegate_summary={
            "preparation": {
                "action": "WORKFLOW_TASK_START",
                "strategyPath": str(output) if output else None,
                "strategyInputs": result["inputs"],
            }
        },
        execution_started=False,
        lifecycle_coverage_claimed=False,
        requires_review=False,
        blockers=blockers,
        execution_strategy=result["summary"],
    )
    # Policy input paths are local preparation data. The public receipt carries digests.
    receipt["delegate"]["preparation"].pop("strategyInputs", None)
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    return {**body, "receiptDigest": canonical_digest(body)}


def execution_strategy_projection(strategy: dict[str, Any]) -> dict[str, Any]:
    """Return the common transparent projection used by start and continuation."""

    projection = execution_strategy_summary(strategy)
    projection["selectedValidationMode"] = strategy["quality"]["selectedMode"]
    projection["sourceDecisionDigests"] = dict(strategy["sourceDecisionDigests"])
    projection["selectionReasons"] = {
        "quality": "frozen-plan-and-risk-policy",
        "packet": "validated-quality-floor",
        "review": "frozen-plan-review-policy",
        "route": "validated-model-routing-profile",
    }
    projection["blockers"] = list(strategy.get("blockers", []))
    projection["modelCallsStarted"] = False
    return projection


def strategy_projection_for_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Read the already resolved strategy projection from a managed receipt."""

    if receipt.get("status") != "READY" or receipt.get("action") != "MANAGED_RUN":
        return deferred_execution_strategy_summary()
    session = receipt.get("adapterSessionReceipt")
    next_action = session.get("nextAction") if isinstance(session, dict) else None
    strategy = next_action.get("executionStrategy") if isinstance(next_action, dict) else None
    if not isinstance(strategy, dict):
        return {**deferred_execution_strategy_summary(reason="strategy-adoption-unavailable"), "status": "BLOCKED"}
    return execution_strategy_projection(strategy)


def _capability_manifest_path(root: Path, descriptor_path: Path, descriptor: dict[str, Any]) -> Path:
    raw = descriptor.get("capabilityManifest")
    if not isinstance(raw, str) or not raw:
        raise LifecycleError(
            "strategy-capability-manifest-missing",
            "adapter descriptor must declare a capability manifest",
        )
    configured = Path(raw)
    candidates = [configured if configured.is_absolute() else root / configured]
    candidates.append(descriptor_path.parent / configured.name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LifecycleError(
        "strategy-capability-manifest-missing",
        "configured capability manifest was not found",
    )


def _repo_relative(root: Path, path: Path, *, label: str) -> str:
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        return candidate.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError(
            "strategy-binding-path-outside-package",
            f"{label} must stay inside the workflow package root",
        ) from exc


def _profile_plan_authority(
    *,
    task_file: Path | None,
    task_text: str | None,
    lock_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Read plan authority only from a structured frozen file input."""

    if task_file is None or task_text is not None or not task_file.is_file():
        return None, None
    try:
        payload = read_json_object(task_file, label="project-profile start input")
    except (LifecycleError, OSError):
        return None, None
    schema = payload.get("schemaVersion")
    if schema == "agent-adapter-task-run-request.v1":
        manifest_value = payload.get("manifest")
        request_lock = payload.get("lock")
        if not isinstance(manifest_value, str) or not manifest_value:
            return None, None
        manifest_path = Path(manifest_value)
        lock_value = request_lock if isinstance(request_lock, str) and request_lock else None
        selected_lock = Path(lock_value) if lock_value else lock_path
    elif schema == "agent-plan-manifest.v1":
        manifest_path = task_file
        selected_lock = lock_path
    else:
        return None, None
    try:
        plan = read_json_object(manifest_path, label="project-profile plan manifest")
        lock = read_json_object(selected_lock, label="project-profile plan lock") if selected_lock else None
    except (LifecycleError, OSError):
        return None, None
    return plan, lock


def _missing_frozen_bindings(
    payload: dict[str, Any] | None,
    *,
    state_path: Path | None,
    lock_path: Path | None,
    task_id: str | None,
    operation_id: str | None,
    expected_revision: int | None,
    source_revision: str | None,
) -> list[str]:
    """Return missing exact bindings for an implementation start."""

    if not isinstance(payload, dict):
        return ["frozenInput"]
    if payload.get("schemaVersion") == "agent-adapter-task-run-request.v1":
        values = {
            "state": payload.get("state"),
            "manifest": payload.get("manifest"),
            "lock": payload.get("lock"),
            "task": payload.get("task"),
            "operationId": payload.get("operationId"),
            "expectedRevision": payload.get("expectedRevision"),
            "sourceRevision": payload.get("sourceRevision"),
        }
    else:
        values = {
            "state": state_path,
            "manifest": "provided-input",
            "lock": lock_path,
            "task": task_id,
            "operationId": operation_id,
            "expectedRevision": expected_revision,
            "sourceRevision": source_revision,
        }
    missing = [field for field, value in values.items() if value in {None, ""}]
    revision = values.get("expectedRevision")
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool) or revision < 1):
        missing.append("expectedRevision")
    return sorted(set(missing))


def _binding_path(binding: dict[str, Any], field: str) -> Path | None:
    value = binding.get(field)
    return Path(value) if isinstance(value, str) and value else None


def _binding_string(binding: dict[str, Any], field: str) -> str | None:
    value = binding.get(field)
    return value if isinstance(value, str) and value else None


__all__ = [
    "_binding_path",
    "_binding_string",
    "_missing_frozen_bindings",
    "_profile_plan_authority",
    "execution_strategy_projection",
    "resolve_managed_execution_strategy",
    "strategy_projection_for_receipt",
]
