"""Fail-closed facade over task intake, managed run and session resume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_lifecycle_start_receipt
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor, launch_from_local_profile
from agent_lifecycle.adapter_sessions.local_launch_profile import load_local_launch_profile
from agent_lifecycle.adapter_sessions.planning_session import (
    create_planning_session,
    load_planning_session,
    planning_session_exists,
    transition_planning_session,
)
from agent_lifecycle.adapter_sessions.session_store import load_session
from agent_lifecycle.adapter_sessions.task_intake import (
    ADAPTER_TASK_RUN_REQUEST_SCHEMA,
    start_adapter_task,
)
from agent_lifecycle.adapter_sessions.workflow_bridge import resume_adapter_session
from agent_lifecycle.contracts import LifecycleError, canonical_digest, load_json_object, read_json_object, sha256_hex
from agent_lifecycle.policy.risk_execution import RISK_REQUESTS
from agent_lifecycle.policy.execution_strategy import (
    deferred_execution_strategy_summary,
    execution_strategy_summary,
    resolve_execution_strategy,
)
from agent_lifecycle.project.merge import build_effective_project_profile
from agent_lifecycle.contracts.project_profile_schemas import GUIDED_ACTION_RECEIPT_SCHEMA
from agent_lifecycle.project.guidance import build_stage_guidance_projection
from agent_lifecycle.adapter_sessions.start_input import (
    _blocker_summaries,
    _empty_input,
    _planning_input,
    _safe_input,
    _session_input,
    _source_input,
)
from agent_lifecycle.adapter_sessions.start_receipts import (
    _blocked,
    _build_guided_action_receipt,
    _claims_execution,
    _planning_launch_blocked_receipt,
    _portable_planning_receipt,
    _resume_summary,
    _task_summary,
)
from agent_lifecycle.adapter_sessions.start_routing import (
    _binding_path,
    _binding_string,
    _profile_plan_authority,
    _strategy_summary_for_receipt,
)

START_MODES = ("auto", "research", "plan", "review", "implement")
_NON_EXECUTING_MODES = frozenset({"auto", "research", "plan", "review"})
_SESSION_STATE_SCHEMA = "agent-adapter-session-state.v1"
_MANAGED_PROOF_KIND = "alk-managed-adapter-session"
_LINEAGE_STRING_FIELDS = ("runId", "packageId", "planDigest", "sourceRevision", "phase")
_LINEAGE_INTEGER_FIELDS = ("planRevision", "stateRevision")


def _start_lifecycle_core(
    *,
    adapter_id: str,
    mode: str = "auto",
    task_file: Path | None = None,
    task_text: str | None = None,
    resume_session_id: str | None = None,
    candidate_out: Path | None = None,
    descriptor_path: Path | None = None,
    session_root: Path | None = None,
    state_path: Path | None = None,
    lock_path: Path | None = None,
    task_id: str | None = None,
    operation_id: str | None = None,
    expected_revision: int | None = None,
    source_revision: str | None = None,
    max_input_bytes: int = 32768,
    target_tokens: int = 4096,
    package_id: str = "unified-start",
    requested_risk: str = "auto",
    risk_policy_path: Path | None = None,
    routing_profile_path: Path | None = None,
    baseline_profile_path: Path | None = None,
    host_model_profile_path: Path | None = None,
    launch: bool = False,
    host_launch_profile_path: Path | None = None,
    project_profile_digest: str | None = None,
) -> dict[str, Any]:
    """Select one existing lifecycle action without creating new authority."""

    if not adapter_id:
        return _blocked(adapter_id="", mode=mode, input_summary=_empty_input(), code="start-adapter-required")
    if mode not in START_MODES:
        return _blocked(adapter_id=adapter_id, mode="auto", input_summary=_empty_input(), code="start-mode-invalid")
    if requested_risk not in RISK_REQUESTS:
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_empty_input(), code="start-risk-invalid")
    if host_launch_profile_path is not None and not launch:
        return _blocked(
            adapter_id=adapter_id,
            mode=mode,
            input_summary=_empty_input(),
            code="start-launch-arguments-incomplete",
        )
    has_task_source = task_file is not None or task_text is not None
    if resume_session_id is not None:
        if has_task_source or launch or host_launch_profile_path is not None:
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_session_input(resume_session_id), code="start-action-conflict")
        if mode != "auto":
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_session_input(resume_session_id), code="start-resume-mode-invalid")
        try:
            if planning_session_exists(resume_session_id, session_root=session_root):
                return _resume_planning(
                    adapter_id=adapter_id,
                    session_id=resume_session_id,
                    session_root=session_root,
                )
        except LifecycleError:
            pass
        return _resume(adapter_id=adapter_id, session_id=resume_session_id, session_root=session_root)
    if not has_task_source or (task_file is not None and task_text is not None):
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_empty_input(), code="start-task-source-invalid")

    input_summary, payload, input_bytes = _inspect_task_source(task_file=task_file, task_text=task_text)
    structured_frozen = _is_frozen_input(payload)
    if mode == "implement" and not structured_frozen:
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code="start-implement-frozen-input-required")
    if mode == "implement":
        missing = _missing_frozen_bindings(
            payload,
            state_path=state_path,
            lock_path=lock_path,
            task_id=task_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
        )
        if missing:
            return build_lifecycle_start_receipt(
                status="BLOCKED",
                adapter_id=adapter_id,
                requested_mode=mode,
                action="BLOCKED",
                input_summary=input_summary,
                blockers=[{"code": "start-frozen-binding-missing", "fields": missing}],
            )
    if mode in _NON_EXECUTING_MODES and structured_frozen:
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code="start-mode-implement-required")
    planning_launch = launch and mode in _NON_EXECUTING_MODES
    intake_text: str | None = None
    if planning_launch:
        try:
            intake_text = input_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code="start-task-utf8-required")
    receipt = start_adapter_task(
        adapter_id=adapter_id,
        task_file=None if planning_launch else task_file,
        task_text=intake_text if planning_launch else task_text,
        candidate_out=candidate_out,
        descriptor_path=descriptor_path,
        session_root=session_root,
        state_path=state_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        package_id=package_id,
        requested_risk=requested_risk,
        risk_policy_path=risk_policy_path,
        routing_profile_path=routing_profile_path,
        baseline_profile_path=baseline_profile_path,
        host_model_profile_path=host_model_profile_path,
    )
    if mode in _NON_EXECUTING_MODES and _claims_execution(receipt):
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code="start-non-implement-execution-claim")
    strategy_summary = _strategy_summary_for_receipt(
        receipt,
        adapter_id=adapter_id,
        descriptor_path=descriptor_path,
        requested_risk=requested_risk,
        risk_policy_path=risk_policy_path,
        routing_profile_path=routing_profile_path,
        baseline_profile_path=baseline_profile_path,
        host_model_profile_path=host_model_profile_path,
        project_profile_digest=project_profile_digest,
    )
    return _finish_start(
        adapter_id=adapter_id,
        mode=mode,
        receipt=receipt,
        strategy_summary=strategy_summary,
        launch=launch,
        planning_launch=planning_launch,
        host_launch_profile_path=host_launch_profile_path,
        task_text=intake_text or "",
        input_summary=input_summary,
        session_root=session_root,
    )


def _finish_start(
    *,
    adapter_id: str,
    mode: str,
    receipt: dict[str, Any],
    strategy_summary: dict[str, Any],
    launch: bool,
    planning_launch: bool,
    host_launch_profile_path: Path | None,
    task_text: str,
    input_summary: dict[str, Any],
    session_root: Path | None,
) -> dict[str, Any]:
    if not launch:
        return _from_task_receipt(adapter_id=adapter_id, mode=mode, receipt=receipt, execution_strategy=strategy_summary)
    profile_path = host_launch_profile_path or Path(".alk/host-launch") / f"{adapter_id}.json"
    if planning_launch:
        return _launch_planning_receipt(
            adapter_id=adapter_id,
            mode=mode,
            receipt=receipt,
            profile_path=profile_path,
            task_text=task_text,
            input_summary=input_summary,
            session_root=session_root,
        )
    return _launch_managed_receipt(
        adapter_id=adapter_id,
        mode=mode,
        receipt=receipt,
        profile_path=profile_path,
        execution_strategy=strategy_summary,
    )


def _resume(*, adapter_id: str, session_id: str, session_root: Path | None) -> dict[str, Any]:
    input_summary = _session_input(session_id)
    try:
        session = load_session(session_id, session_root=session_root)
    except (LifecycleError, OSError):
        return _blocked(adapter_id=adapter_id, mode="auto", input_summary=input_summary, code="start-resume-session-missing")

    blockers = _session_blockers(session, session_id=session_id, adapter_id=adapter_id)
    if blockers:
        return build_lifecycle_start_receipt(
            status="BLOCKED",
            adapter_id=adapter_id,
            requested_mode="auto",
            action="BLOCKED",
            input_summary=input_summary,
            blockers=blockers,
        )
    try:
        receipt = resume_adapter_session(session_id=session_id, session_root=session_root, adapter_id=adapter_id)
    except (LifecycleError, OSError):
        return _blocked(adapter_id=adapter_id, mode="auto", input_summary=input_summary, code="start-resume-session-invalid")
    status = str(receipt.get("status", "BLOCKED"))
    if status not in {"PASS", "UNMANAGED"}:
        return build_lifecycle_start_receipt(
            status="BLOCKED",
            adapter_id=adapter_id,
            requested_mode="auto",
            action="BLOCKED",
            input_summary=input_summary,
            delegate_summary=_resume_summary(receipt, session=session),
            blockers=_blocker_summaries(receipt.get("blockers")),
        )
    return build_lifecycle_start_receipt(
        status=status,
        adapter_id=adapter_id,
        requested_mode="auto",
        action="RESUME",
        input_summary=input_summary,
        delegate_summary=_resume_summary(receipt, session=session),
        lifecycle_coverage_claimed=status == "PASS" and bool(receipt.get("lifecycleCoverageClaimed")),
    )


def _resume_planning(*, adapter_id: str, session_id: str, session_root: Path | None) -> dict[str, Any]:
    input_summary = _session_input(session_id)
    try:
        session = load_planning_session(
            session_id,
            session_root=session_root,
            expected_adapter_id=adapter_id,
        )
    except LifecycleError as exc:
        return _blocked(adapter_id=adapter_id, mode="auto", input_summary=input_summary, code=exc.code)
    state = str(session.get("state"))
    blockers = _blocker_summaries(session.get("blockers"))
    if state == "PLANNING_RUNNING":
        blockers.append({"code": "planning-session-native-reattach-unsupported"})
    status = "REVIEW_REQUIRED" if state in {"INTAKE_ACCEPTED", "REVIEW_REQUIRED"} else "BLOCKED"
    return build_lifecycle_start_receipt(
        status=status,
        adapter_id=adapter_id,
        requested_mode="auto",
        action="RESUME" if status == "REVIEW_REQUIRED" else "BLOCKED",
        input_summary=input_summary,
        delegate_summary={
            "schemaVersion": session.get("schemaVersion"),
            "sessionId": session_id,
            "requestedMode": session.get("requestedMode"),
            "planningState": state,
            "sessionRevision": session.get("sessionRevision"),
            "planningReceiptDigest": session.get("planningReceiptDigest"),
            "resultDigest": session.get("resultDigest"),
            "implementationAuthorized": False,
        },
        requires_review=True,
        blockers=blockers,
    )


def _session_blockers(session: dict[str, Any], *, session_id: str, adapter_id: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if session.get("schemaVersion") != _SESSION_STATE_SCHEMA:
        blockers.append({"code": "start-resume-session-schema-invalid"})
    if session.get("sessionId") != session_id:
        blockers.append({"code": "start-resume-session-id-mismatch"})
    if session.get("adapterId") != adapter_id:
        blockers.append({"code": "start-resume-adapter-mismatch"})
    identity = session.get("stateIdentity")
    if identity is None:
        return blockers
    if not isinstance(identity, dict):
        blockers.append({"code": "start-resume-lineage-invalid"})
        return blockers
    missing = [field for field in _LINEAGE_STRING_FIELDS if not isinstance(identity.get(field), str) or not identity.get(field)]
    missing.extend(
        field
        for field in _LINEAGE_INTEGER_FIELDS
        if not isinstance(identity.get(field), int) or isinstance(identity.get(field), bool) or identity.get(field) < 1
    )
    if missing:
        blockers.append({"code": "start-resume-lineage-invalid", "fields": sorted(missing)})
        return blockers
    proof = session.get("managedWorkflowProof")
    if not isinstance(proof, dict):
        blockers.append({"code": "start-resume-proof-missing"})
        return blockers
    if (
        proof.get("kind") != _MANAGED_PROOF_KIND
        or proof.get("status") != "PASS"
        or proof.get("adapterId") != adapter_id
        or proof.get("stateIdentity") != identity
    ):
        blockers.append({"code": "start-resume-proof-mismatch"})
    return blockers


def _inspect_task_source(
    *,
    task_file: Path | None,
    task_text: str | None,
) -> tuple[dict[str, Any], dict[str, Any] | None, bytes]:
    if task_text is not None:
        data = task_text.encode("utf-8")
        return _source_input("TEXT", "inline-task", data), _parse_payload(data), data
    if task_file is None or not task_file.is_file():
        label = task_file.name if task_file is not None else None
        return {**_empty_input(), "label": label}, None, b""
    try:
        data = task_file.read_bytes()
    except OSError:
        return {**_empty_input(), "label": task_file.name}, None, b""
    return _source_input("FILE", task_file.name, data), _parse_payload(data), data


def _parse_payload(data: bytes) -> dict[str, Any] | None:
    try:
        return load_json_object(data, label="lifecycle start input")
    except LifecycleError:
        return None


def _is_frozen_input(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("schemaVersion") == ADAPTER_TASK_RUN_REQUEST_SCHEMA:
        return True
    return payload.get("schemaVersion") == "agent-plan-manifest.v1" and payload.get("status") == "FROZEN"


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
    if not isinstance(payload, dict):
        return ["frozenInput"]
    if payload.get("schemaVersion") == ADAPTER_TASK_RUN_REQUEST_SCHEMA:
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


def _from_task_receipt(
    *,
    adapter_id: str,
    mode: str,
    receipt: dict[str, Any],
    launch_receipt: dict[str, Any] | None = None,
    execution_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(receipt.get("status", "BLOCKED"))
    action = str(receipt.get("action", "BLOCKED"))
    if status not in {"REVIEW_REQUIRED", "READY", "BLOCKED"}:
        status = "BLOCKED"
        action = "BLOCKED"
    blockers = _blocker_summaries(receipt.get("reviewBlockers"))
    if launch_receipt is not None and launch_receipt.get("status") != "PASS":
        status = "BLOCKED"
        action = "BLOCKED"
        blockers.extend(_blocker_summaries(launch_receipt.get("blockers")))
    return build_lifecycle_start_receipt(
        status=status,
        adapter_id=adapter_id,
        requested_mode=mode,
        action=action,
        input_summary=_safe_input(receipt.get("input")),
        delegate_summary=_task_summary(receipt),
        execution_started=mode == "implement" and bool(receipt.get("executionStarted")),
        lifecycle_coverage_claimed=mode == "implement" and bool(receipt.get("lifecycleCoverageClaimed")),
        requires_review=bool(receipt.get("requiresReview")),
        blockers=blockers,
        host_launch_started=bool(launch_receipt and launch_receipt.get("hostLaunchStarted")),
        launch_receipt=launch_receipt,
        execution_strategy=execution_strategy or deferred_execution_strategy_summary(),
    )


def _launch_planning_receipt(
    *,
    adapter_id: str,
    mode: str,
    receipt: dict[str, Any],
    profile_path: Path,
    task_text: str,
    input_summary: dict[str, Any],
    session_root: Path | None,
) -> dict[str, Any]:
    if receipt.get("status") != "REVIEW_REQUIRED" or _claims_execution(receipt):
        return _from_task_receipt(adapter_id=adapter_id, mode=mode, receipt=receipt)
    try:
        session = create_planning_session(
            adapter_id=adapter_id,
            requested_mode=mode,
            input_summary=_planning_input(input_summary),
            session_root=session_root,
        )
    except LifecycleError as exc:
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code=exc.code)
    session_id = str(session["sessionId"])
    try:
        _relative, local_profile, _validation = load_local_launch_profile(profile_path)
        if local_profile.get("adapterId") != adapter_id:
            raise LifecycleError(
                "local-launch-profile-adapter-mismatch",
                "local launch profile belongs to another adapter",
            )
        transition_planning_session(
            session_id=session_id,
            adapter_id=adapter_id,
            expected_state="INTAKE_ACCEPTED",
            new_state="PLANNING_RUNNING",
            session_root=session_root,
        )
        launch_receipt = launch_from_local_profile(
            profile_path=profile_path,
            operation="planningTask",
            adapter_id=adapter_id,
            session_id=session_id,
            explicit_launch=True,
            requested_mode=mode,
            task_text=task_text,
            input_source=str(input_summary.get("type", "TEXT")).lower(),
            advisory=_task_summary(receipt),
        )
    except (LifecycleError, OSError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "local-launch-profile-read-failed"
        message = exc.message if isinstance(exc, LifecycleError) else "local launch profile could not be read"
        launch_receipt = _planning_launch_blocked_receipt(
            adapter_id=adapter_id,
            session_id=session_id,
            requested_mode=mode,
            input_summary=input_summary,
            code=code,
            message=message,
        )

    launch_receipt = _portable_planning_receipt(launch_receipt, task_text=task_text)

    current = load_planning_session(
        session_id,
        session_root=session_root,
        expected_adapter_id=adapter_id,
    )
    if current["state"] == "INTAKE_ACCEPTED":
        session = transition_planning_session(
            session_id=session_id,
            adapter_id=adapter_id,
            expected_state="INTAKE_ACCEPTED",
            new_state="BLOCKED",
            session_root=session_root,
            planning_receipt=launch_receipt,
            blockers=_blocker_summaries(launch_receipt.get("blockers")),
        )
    else:
        target = "REVIEW_REQUIRED" if launch_receipt.get("status") == "REVIEW_REQUIRED" else "BLOCKED"
        session = transition_planning_session(
            session_id=session_id,
            adapter_id=adapter_id,
            expected_state="PLANNING_RUNNING",
            new_state=target,
            session_root=session_root,
            planning_receipt=launch_receipt,
            blockers=_blocker_summaries(launch_receipt.get("blockers")),
        )
    accepted = session["state"] == "REVIEW_REQUIRED"
    delegate = _task_summary(receipt)
    delegate["planningSession"] = {
        "sessionId": session_id,
        "state": session["state"],
        "sessionRevision": session["sessionRevision"],
        "lineageDigest": session["lineageDigest"],
        "planningReceiptDigest": session["planningReceiptDigest"],
        "resultDigest": session["resultDigest"],
        "implementationAuthorized": False,
    }
    return build_lifecycle_start_receipt(
        status="REVIEW_REQUIRED" if accepted else "BLOCKED",
        adapter_id=adapter_id,
        requested_mode=mode,
        action="DRAFT_PLAN_REVIEW" if accepted else "BLOCKED",
        input_summary=input_summary,
        delegate_summary=delegate,
        execution_started=False,
        lifecycle_coverage_claimed=False,
        requires_review=True,
        blockers=_blocker_summaries(launch_receipt.get("blockers")),
        host_launch_started=bool(launch_receipt.get("hostLaunchStarted")),
        launch_receipt=launch_receipt,
        execution_strategy=deferred_execution_strategy_summary(),
    )


def _launch_managed_receipt(
    *,
    adapter_id: str,
    mode: str,
    receipt: dict[str, Any],
    profile_path: Path,
    execution_strategy: dict[str, Any],
) -> dict[str, Any]:
    if receipt.get("status") != "READY" or receipt.get("action") != "MANAGED_RUN":
        return _from_task_receipt(
            adapter_id=adapter_id,
            mode=mode,
            receipt=receipt,
            execution_strategy=execution_strategy,
        )
    binding = receipt.get("workflowBinding") if isinstance(receipt.get("workflowBinding"), dict) else {}
    session = receipt.get("adapterSessionReceipt") if isinstance(receipt.get("adapterSessionReceipt"), dict) else {}
    next_action = session.get("nextAction") if isinstance(session.get("nextAction"), dict) else {}
    risk_profile = next_action.get("riskExecutionProfile") if isinstance(next_action.get("riskExecutionProfile"), dict) else None
    try:
        launch_receipt = launch_from_local_profile(
            profile_path=profile_path,
            operation="managedTask",
            adapter_id=adapter_id,
            session_id=str(session.get("sessionId", "managed-start")),
            explicit_launch=True,
            state_path=_binding_path(binding, "state"),
            manifest_path=_binding_path(binding, "manifest"),
            lock_path=_binding_path(binding, "lock"),
            task_id=_binding_string(binding, "task"),
            operation_id=_binding_string(binding, "operationId"),
            source_revision=_binding_string(binding, "sourceRevision"),
            risk_profile=risk_profile,
        )
    except (LifecycleError, OSError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "local-launch-profile-read-failed"
        message = exc.message if isinstance(exc, LifecycleError) else "local launch profile could not be read"
        launch_receipt = {
            "schemaVersion": "agent-managed-adapter-launch-receipt.v1",
            "status": "BLOCKED",
            "hostLaunchStarted": False,
            "blockers": [{"code": code, "message": message}],
        }
    return _from_task_receipt(
        adapter_id=adapter_id,
        mode=mode,
        receipt=receipt,
        launch_receipt=launch_receipt,
        execution_strategy=execution_strategy,
    )


def start_lifecycle(
    *,
    adapter_id: str | None,
    mode: str = "auto",
    task_file: Path | None = None,
    task_text: str | None = None,
    resume_session_id: str | None = None,
    candidate_out: Path | None = None,
    descriptor_path: Path | None = None,
    session_root: Path | None = None,
    state_path: Path | None = None,
    lock_path: Path | None = None,
    task_id: str | None = None,
    operation_id: str | None = None,
    expected_revision: int | None = None,
    source_revision: str | None = None,
    max_input_bytes: int = 32768,
    target_tokens: int = 4096,
    package_id: str = "unified-start",
    requested_risk: str = "auto",
    risk_policy_path: Path | None = None,
    routing_profile_path: Path | None = None,
    baseline_profile_path: Path | None = None,
    host_model_profile_path: Path | None = None,
    launch: bool = False,
    host_launch_profile_path: Path | None = None,
    project_profile: dict[str, Any] | None = None,
    project_profile_path: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Run the existing start path, optionally wrapped by a project profile."""

    if project_profile is None:
        return _start_lifecycle_core(
            adapter_id=adapter_id or "",
            mode=mode,
            task_file=task_file,
            task_text=task_text,
            resume_session_id=resume_session_id,
            candidate_out=candidate_out,
            descriptor_path=descriptor_path,
            session_root=session_root,
            state_path=state_path,
            lock_path=lock_path,
            task_id=task_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            max_input_bytes=max_input_bytes,
            target_tokens=target_tokens,
            package_id=package_id,
            requested_risk=requested_risk,
            risk_policy_path=risk_policy_path,
            routing_profile_path=routing_profile_path,
            baseline_profile_path=baseline_profile_path,
            host_model_profile_path=host_model_profile_path,
            launch=launch,
            host_launch_profile_path=host_launch_profile_path,
        )

    overrides: dict[str, Any] = {}
    if adapter_id:
        overrides["defaultAdapter"] = adapter_id
    if mode != "auto":
        overrides["defaultMode"] = mode
    if requested_risk != "auto":
        overrides["defaultRisk"] = requested_risk
    plan_authority, profile_lock = _profile_plan_authority(
        task_file=task_file,
        task_text=task_text,
        lock_path=lock_path,
    )
    effective = build_effective_project_profile(
        project_profile,
        plan=plan_authority,
        lock=profile_lock,
        cli_overrides=overrides,
        project_root=project_root,
    )
    resolved_adapter = adapter_id or effective.get("defaultAdapter")
    resolved_mode = mode if mode != "auto" else str(effective.get("defaultMode", "auto"))
    resolved_risk = requested_risk if requested_risk != "auto" else str(effective.get("defaultRisk", "S0"))
    base = _start_lifecycle_core(
        adapter_id=str(resolved_adapter or ""),
        mode=resolved_mode,
        task_file=task_file,
        task_text=task_text,
        resume_session_id=resume_session_id,
        candidate_out=candidate_out,
        descriptor_path=descriptor_path,
        session_root=session_root,
        state_path=state_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        package_id=package_id,
        requested_risk=resolved_risk,
        risk_policy_path=risk_policy_path,
        routing_profile_path=routing_profile_path,
        baseline_profile_path=baseline_profile_path,
        host_model_profile_path=host_model_profile_path,
        launch=launch,
        host_launch_profile_path=host_launch_profile_path,
        project_profile_digest=effective["effectiveProfileDigest"],
    )
    return _build_guided_action_receipt(
        base,
        effective=effective,
        profile_path=project_profile_path,
        project_root=project_root,
    )
