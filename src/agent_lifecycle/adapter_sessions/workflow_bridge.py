"""Composition between managed adapter sessions and ALK workflow state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_adapter_session_receipt, build_resume_receipt
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor, managed_launch_profile
from agent_lifecycle.adapter_sessions.session_store import create_session, load_session, update_session
from agent_lifecycle.adapter_sessions.start_routing import resolve_managed_execution_strategy
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.policy.execution_strategy import deferred_execution_strategy_summary
from agent_lifecycle.policy.risk_execution import derive_risk_execution_profile
from agent_lifecycle.resources import builtin_profile_path
from agent_lifecycle.workflow import run_workflow_step
from agent_lifecycle.workflow.transition_contract import validate_action_catalog


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
    requested_risk: str | None = None,
    risk_policy_path: Path | None = None,
    routing_profile_path: Path | None = None,
    baseline_profile_path: Path | None = None,
    host_model_profile_path: Path | None = None,
    project_profile: dict[str, Any] | None = None,
    project_profile_path: Path | None = None,
    strategy_out_path: Path | None = None,
) -> dict[str, Any]:
    descriptor_file, descriptor = load_adapter_descriptor(adapter_id, descriptor_path)
    profile = managed_launch_profile(descriptor)
    workflow_receipt = run_workflow_step(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=f"managed adapter run for {task_id}",
    )
    next_action = workflow_receipt.get("nextAction")
    if workflow_receipt["status"] == "PASS" and (requested_risk is not None or strategy_out_path is not None):
        risk_request = requested_risk or "auto"
        risk_profile = derive_risk_execution_profile(
            manifest=read_json_object(manifest_path, label="frozen plan manifest"),
            state=read_json_object(state_path, label="workflow state"),
            task_id=task_id,
            adapter_id=adapter_id,
            adapter_host=str(descriptor.get("host", "")),
            operation_id=operation_id,
            source_revision=source_revision,
            requested_risk=risk_request,
            risk_policy=read_json_object(
                risk_policy_path or builtin_profile_path("risk-execution-policy.v1.json"),
                label="risk execution policy",
            ),
            routing_profile=read_json_object(
                routing_profile_path or builtin_profile_path("model-routing-profile.v1.json"),
                label="model routing profile",
            ),
            baseline_profile=read_json_object(
                baseline_profile_path or builtin_profile_path("lifecycle-baselines.v1.json"),
                label="lifecycle baseline profile",
            ),
            host_profile=read_json_object(host_model_profile_path, label="host model profile")
            if host_model_profile_path is not None
            else None,
        )
        strategy_result: dict[str, Any] | None = None
        strategy_error: LifecycleError | None = None
        strategy_display_path: str | None = None
        try:
            strategy_result = resolve_managed_execution_strategy(
                adapter_id=adapter_id,
                descriptor_path=descriptor_file,
                state_path=state_path,
                manifest_path=manifest_path,
                lock_path=lock_path,
                task_id=task_id,
                operation_id=operation_id,
                expected_revision=expected_revision,
                source_revision=source_revision,
                requested_risk=risk_request,
                risk_policy_path=risk_policy_path,
                routing_profile_path=routing_profile_path,
                baseline_profile_path=baseline_profile_path,
                host_model_profile_path=host_model_profile_path,
                project_profile=project_profile,
                project_profile_path=project_profile_path,
            )
            strategy = strategy_result["strategy"]
            if strategy_out_path is not None:
                if strategy["authority"]["automaticAdoptionEligible"] is not True:
                    raise LifecycleError(
                        "execution-strategy-adoption-ineligible",
                        "strategy output requires a complete automatic-adoption binding",
                    )
                strategy_display_path = _strategy_display_path(strategy_out_path, state_path)
                try:
                    write_json_create(strategy_out_path, strategy)
                except FileExistsError as exc:
                    raise LifecycleError(
                        "output-already-exists",
                        "execution strategy output already exists",
                    ) from exc
        except LifecycleError as exc:
            strategy_error = exc
            if strategy_out_path is not None:
                raise
        next_action = _strategy_aware_next_action(
            next_action,
            risk_profile,
            strategy_result=strategy_result,
            strategy_error=strategy_error,
            strategy_display_path=strategy_display_path,
        )
    state_identity = {**_state_identity(state_path), "taskId": task_id}
    catalog = validate_action_catalog()
    proof = _managed_proof(
        "adapter run",
        adapter_id=adapter_id,
        task_id=task_id,
        state_identity=state_identity,
        action_catalog_digest=catalog["catalogDigest"],
    )
    session = create_session(
        adapter_id=adapter_id,
        mode="MANAGED_TASK",
        status="READY" if workflow_receipt["status"] == "PASS" else "BLOCKED",
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
        blockers=workflow_receipt.get("blockers", []),
        next_action=next_action,
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
    proof = _managed_proof(
        "adapter session promote", adapter_id=session["adapterId"], task_id=task_id, state_identity=identity
    )
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
    if adapter_id and session.get("adapterId") != adapter_id:
        blockers.append(
            {"code": "adapter-session-adapter-mismatch", "expected": adapter_id, "actual": session.get("adapterId")}
        )
    if task_id:
        expected["taskId"] = task_id
    actual_value = session.get("stateIdentity")
    actual: dict[str, Any] = actual_value if isinstance(actual_value, dict) else {}
    if state_path is not None:
        expected.update(_state_identity(state_path))
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                blockers.append(
                    {
                        "code": "adapter-session-lineage-mismatch",
                        "field": key,
                        "expected": expected_value,
                        "actual": actual.get(key),
                    }
                )
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


def _managed_proof(
    command: str,
    *,
    adapter_id: str,
    task_id: str,
    state_identity: dict[str, Any],
    action_catalog_digest: str | None = None,
) -> dict[str, Any]:
    proof = {
        "kind": "alk-managed-adapter-session",
        "status": "PASS",
        "command": command,
        "adapterId": adapter_id,
        "taskId": task_id,
        "stateIdentity": state_identity,
    }
    if action_catalog_digest is not None:
        proof["actionCatalogDigest"] = action_catalog_digest
    return proof


def _strategy_aware_next_action(
    next_action: Any,
    profile: dict[str, Any],
    *,
    strategy_result: dict[str, Any] | None,
    strategy_error: LifecycleError | None,
    strategy_display_path: str | None,
) -> dict[str, Any]:
    if not isinstance(next_action, dict):
        next_action = {}
    body = {key: value for key, value in next_action.items() if key != "actionDigest"}
    body["riskExecutionProfile"] = profile
    body["riskProfileRequiredAtTaskStart"] = True
    if strategy_result is not None:
        body["executionStrategy"] = strategy_result["strategy"]
        body["executionStrategyProjection"] = strategy_result["summary"]
        strategy_inputs = strategy_result["inputs"]
        body["executionStrategyInputs"] = {
            "requestedRisk": strategy_inputs["requestedRisk"],
            "descriptorPath": strategy_inputs["descriptorPath"],
            "capabilityManifestPath": strategy_inputs["capabilityManifestPath"],
            "projectProfilePath": strategy_inputs["projectProfilePath"],
            "policyInputsDigest": strategy_result["strategy"]["adoptionBinding"]["policyInputsDigest"],
        }
        if strategy_display_path is not None:
            body["executionStrategyPath"] = strategy_display_path
    else:
        reason = strategy_error.code if strategy_error is not None else "strategy-adoption-unavailable"
        body["executionStrategyProjection"] = {
            **deferred_execution_strategy_summary(reason=reason),
            "status": "BLOCKED",
            "modelCallsStarted": False,
        }
    body["stateMutationRequired"] = True
    return {**body, "actionDigest": canonical_digest(body)}


def _strategy_display_path(path: Path, state_path: Path) -> str:
    state = read_json_object(state_path, label="workflow state")
    from agent_lifecycle.workflow.artifacts import package_root

    root = package_root(state_path, state)
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        return candidate.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise LifecycleError(
            "strategy-output-outside-package",
            "execution strategy output must stay inside the workflow package root",
        ) from exc
