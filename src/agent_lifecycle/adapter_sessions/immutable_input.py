"""A5 request checks. Ordinary classification grants no dispatch authority."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.immutable_input_schemas import (
    validate_a5_boundary_registry,
    validate_a5_invocation_context,
    validate_a5_invocation_request,
    validate_a5_plan_policy,
    validate_a5_policy,
)
from agent_lifecycle.freeze import verify_plan_package_integrity


def normalize_invocation_request(value: Any = None) -> dict[str, Any]:
    """Omission is a request for NONE, never proof of a frozen requirement."""
    request = (
        {"schemaVersion": "agent-a5-invocation-request.v1", "requestedProtection": "NONE"} if value is None else value
    )
    return dict(validate_a5_invocation_request(request))


def require_no_strong_protection(request: Any, *, expected_protection: str) -> dict[str, Any]:
    normalized = normalize_invocation_request(request)
    if type(expected_protection) is not str or expected_protection not in {"NONE", "STRONG_A5"}:
        raise LifecycleError("a5-context-invalid", "Expected protection is unresolved")
    if "STRONG_A5" in (normalized["requestedProtection"], expected_protection):
        raise LifecycleError("a5-strong-unproven", "Continuous input protection is unproven on this route")
    return normalized


def validate_current_invocation(context: Any, request: Any, *, current_context: Any) -> dict[str, Any]:
    """Compare with independently reconstructed inputs; context is not a permit."""
    checked = validate_a5_invocation_context(context)
    current = validate_a5_invocation_context(current_context)
    normalized = normalize_invocation_request(request)
    if checked["operation"] == "VERSION_PREFLIGHT" and (
        checked["taskInputDigest"] is not None
        or checked["requestedProtection"] != "NONE"
        or checked["expectedProtection"] != "NONE"
    ):
        raise LifecycleError("a5-context-invalid", "Version-only context cannot carry a task or strong request")
    if checked["operation"] in {"PLANNING_TASK", "PLANNING_QUALIFICATION"} and checked["taskInputDigest"] is None:
        raise LifecycleError("a5-context-invalid", "Planning input identity is missing")
    if checked != current or checked["normalizedRequestDigest"] != canonical_digest(normalized):
        raise LifecycleError("a5-context-invalid", "Invocation context differs from current inputs")
    if checked["requestedProtection"] != normalized["requestedProtection"]:
        raise LifecycleError("a5-context-invalid", "Invocation request was changed")
    require_no_strong_protection(normalized, expected_protection=checked["expectedProtection"])
    return checked


def invocation_context(
    *,
    operation: str,
    adapter_id: str,
    session_id: str,
    request: Any,
    input_identity: Any,
    profile_digest: str | None,
    workflow_subject: dict[str, Any] | None = None,
    authority_refs: list[dict[str, str]] | None = None,
    policy: dict[str, Any] | None = None,
    expected_protection: str = "NONE",
) -> dict[str, Any]:
    """Bind actual inputs for comparison; this record never authorizes dispatch."""
    normalized = require_no_strong_protection(request, expected_protection=expected_protection)
    origins = {
        "PLANNING_TASK": "EXPLICIT_PLANNING_CALL",
        "PLANNING_QUALIFICATION": "FIXED_QUALIFICATION_CALL",
        "MANAGED_TASK": "FROZEN_WORKFLOW_TASK",
        "VERSION_PREFLIGHT": "VERSION_ONLY_PREFLIGHT",
    }
    if operation not in origins:
        raise LifecycleError("a5-context-invalid", "Unknown invocation operation")
    body = {
        "schemaVersion": "agent-a5-invocation-context.v1",
        "invocationId": session_id,
        "operation": operation,
        "origin": origins[operation],
        "workflowSubject": workflow_subject,
        "frozenAuthorityRefs": authority_refs or [],
        "adapterId": adapter_id,
        "sessionId": session_id,
        "requestedProtection": normalized["requestedProtection"],
        "expectedProtection": expected_protection,
        "policyDigest": policy["policyDigest"] if policy else None,
        "boundaryRecordDigest": policy["boundaryRecordDigest"] if policy else None,
        "normalizedRequestDigest": canonical_digest(normalized),
        "taskInputDigest": canonical_digest(input_identity) if input_identity is not None else None,
        "profileDigest": profile_digest,
        "strongProtectionGranted": False,
    }
    return validate_a5_invocation_context({**body, "contextDigest": canonical_digest(body)})


def planning_invocation_context(
    *,
    adapter_id: str,
    session_id: str,
    request: Any,
    requested_mode: str,
    task_text: str,
    input_source: str,
    argv: list[str],
    env: dict[str, str],
    advisory: dict[str, Any] | None,
    timeout_seconds: float,
    process_cwd: Path | None,
    profile_digest: str | None = None,
    qualification_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return invocation_context(
        operation="PLANNING_QUALIFICATION" if qualification_binding is not None else "PLANNING_TASK",
        adapter_id=adapter_id,
        session_id=session_id,
        request=request,
        profile_digest=profile_digest,
        input_identity={
            "textSha256": hashlib.sha256(task_text.encode("utf-8")).hexdigest(),
            "mode": requested_mode,
            "inputSource": input_source,
            "explicitLaunch": True,
            "argv": argv,
            "environmentDigest": canonical_digest(env),
            "advisory": advisory or {},
            "timeoutSeconds": timeout_seconds,
            "processCwd": str(process_cwd.absolute()) if process_cwd is not None else str(Path.cwd()),
            "qualification": qualification_binding,
        },
    )


def current_managed_invocation(
    *,
    project_root: Path,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    task_id: str,
    operation_id: str,
    source_revision: str,
    adapter_id: str,
    session_id: str,
    request: Any,
    profile: dict[str, Any],
    profile_digest: str,
    risk_profile: dict[str, Any],
) -> dict[str, Any]:
    """Reopen actual frozen inputs at the sink; a supplied context is not evidence."""
    paths = (manifest_path, lock_path, state_path)
    raw = [path.read_bytes() for path in paths]
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    lock = read_json_object(lock_path, label="plan lock")
    state = read_json_object(state_path, label="workflow state")
    verify_plan_package_integrity(manifest, lock, repository_root=project_root)
    if raw != [path.read_bytes() for path in paths]:
        raise LifecycleError("a5-context-invalid", "Workflow inputs changed during A5 comparison")
    selected = [t for t in manifest.get("workstreams", []) if t.get("id") == task_id]
    runtime = [t for t in state.get("tasks", []) if t.get("id") == task_id]
    if (
        manifest.get("status") != "FROZEN"
        or len(selected) != 1
        or len(runtime) != 1
        or state.get("planDigest") != canonical_digest(manifest)
        or state.get("sourceRevision") != source_revision
        or state.get("packageId") != manifest.get("package", {}).get("id")
        or state.get("phase") != "RUNNING"
        or runtime[0].get("status") != "RUNNING"
    ):
        raise LifecycleError("a5-context-invalid", "Current running task and frozen authority differ")
    task, actual_task = selected[0], runtime[0]
    policy = task.get("immutableInput")
    plan_policy = manifest.get("immutableInput")
    if state.get("immutableInput") != plan_policy or actual_task.get("immutableInput") != policy:
        raise LifecycleError("a5-context-invalid", "Current task policy differs from the frozen plan")
    expected = "NONE"
    if plan_policy is not None:
        validate_a5_plan_policy(plan_policy)
        validate_a5_policy(policy)
        if policy["adapterId"] != adapter_id:
            raise LifecycleError("a5-context-invalid", "Frozen task adapter differs")
        registry = validate_a5_boundary_registry(
            read_json_object(
                project_root / "profiles/immutable-input-adapter-capabilities.v1.json", label="A5 boundaries"
            )
        )
        matches = [row for row in registry["records"] if row["adapterId"] == adapter_id]
        if len(matches) != 1 or any(
            policy[field] != matches[0][field] for field in ("expectationId", "targetVersion", "boundaryRecordDigest")
        ):
            raise LifecycleError("a5-context-invalid", "Frozen boundary identity differs")
        if "STRONG_A5" in (plan_policy["defaultRequirement"], policy["frozenTaskRequirement"]):
            expected = "STRONG_A5"
    elif policy is not None:
        raise LifecycleError("a5-context-invalid", "Task policy lacks a frozen plan policy")
    refs = [
        {
            "path": path.absolute().relative_to(project_root.absolute()).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for path, data in zip(paths, raw, strict=True)
    ]
    subject = {
        "runId": state["runId"],
        "packageId": state["packageId"],
        "taskId": task_id,
        "targetAttempt": actual_task["attempt"],
        "operationId": operation_id,
        "stateRevision": state["stateRevision"],
        "planDigest": state["planDigest"],
        "sourceRevision": source_revision,
    }
    return invocation_context(
        operation="MANAGED_TASK",
        adapter_id=adapter_id,
        session_id=session_id,
        request=request,
        profile_digest=profile_digest,
        workflow_subject=subject,
        authority_refs=refs,
        policy=policy,
        expected_protection=expected,
        input_identity={"task": task, "profile": profile, "riskProfile": risk_profile},
    )
