"""Binding and execution-strategy helpers for the unified start facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.policy.execution_strategy import (
    deferred_execution_strategy_summary,
    execution_strategy_summary,
    resolve_execution_strategy,
)
from agent_lifecycle.resources import builtin_profile_path
from agent_lifecycle.workflow.artifacts import next_available_attempt, package_root
from agent_lifecycle.workflow.selectors import find_task


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
    profile_digest = canonical_digest(project_profile) if project_profile is not None else None
    risk_file = risk_policy_path or builtin_profile_path("risk-execution-policy.v1.json")
    routing_file = routing_profile_path or builtin_profile_path("model-routing-profile.v1.json")
    baseline_file = baseline_profile_path or builtin_profile_path("lifecycle-baselines.v1.json")
    task = find_task(state, task_id)
    selected_attempt = next_available_attempt(state_path, state, task)
    strategy = resolve_execution_strategy(
        manifest=read_json_object(manifest_path, label="frozen plan manifest"),
        lock=read_json_object(lock_path, label="plan lock"),
        state=state,
        task_id=task_id,
        adapter_id=adapter_id,
        adapter_host=str(descriptor.get("host", "")),
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        requested_risk=requested_risk,
        risk_policy=read_json_object(risk_file, label="risk execution policy"),
        routing_profile=read_json_object(routing_file, label="model routing profile"),
        baseline_profile=read_json_object(baseline_file, label="lifecycle baseline profile"),
        host_profile=(
            read_json_object(host_model_profile_path, label="host model profile")
            if host_model_profile_path is not None
            else None
        ),
        project_profile_digest=profile_digest,
        descriptor=descriptor,
        capability_manifest=capability,
        target_attempt=selected_attempt,
        descriptor_path=_repo_relative(root, descriptor_file, label="adapter descriptor"),
        capability_manifest_path=_repo_relative(root, capability_file, label="capability manifest"),
        project_profile_path=_repo_relative(root, profile_file, label="project profile"),
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
