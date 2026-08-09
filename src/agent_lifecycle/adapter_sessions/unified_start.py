"""Fail-closed facade over task intake, managed run and session resume."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_lifecycle_start_receipt
from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile
from agent_lifecycle.adapter_sessions.local_launch_profile import load_local_launch_profile
from agent_lifecycle.adapter_sessions.session_store import load_session
from agent_lifecycle.adapter_sessions.task_intake import (
    ADAPTER_TASK_RUN_REQUEST_SCHEMA,
    start_adapter_task,
)
from agent_lifecycle.adapter_sessions.workflow_bridge import resume_adapter_session
from agent_lifecycle.contracts import LifecycleError, load_json_object, sha256_hex
from agent_lifecycle.policy.risk_execution import RISK_REQUESTS

START_MODES = ("auto", "research", "plan", "review", "implement")
_NON_EXECUTING_MODES = frozenset({"auto", "research", "plan", "review"})
_SESSION_STATE_SCHEMA = "agent-adapter-session-state.v1"
_MANAGED_PROOF_KIND = "alk-managed-adapter-session"
_LINEAGE_STRING_FIELDS = ("runId", "packageId", "planDigest", "sourceRevision", "phase")
_LINEAGE_INTEGER_FIELDS = ("planRevision", "stateRevision")


def start_lifecycle(
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
) -> dict[str, Any]:
    """Select one existing lifecycle action without creating new authority."""

    if not adapter_id:
        return _blocked(adapter_id="", mode=mode, input_summary=_empty_input(), code="start-adapter-required")
    if mode not in START_MODES:
        return _blocked(adapter_id=adapter_id, mode="auto", input_summary=_empty_input(), code="start-mode-invalid")
    if requested_risk not in RISK_REQUESTS:
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_empty_input(), code="start-risk-invalid")
    if launch != (host_launch_profile_path is not None):
        return _blocked(
            adapter_id=adapter_id,
            mode=mode,
            input_summary=_empty_input(),
            code="start-launch-arguments-incomplete",
        )
    if launch and mode != "implement":
        return _blocked(
            adapter_id=adapter_id,
            mode=mode,
            input_summary=_empty_input(),
            code="start-launch-implement-mode-required",
        )

    has_task_source = task_file is not None or task_text is not None
    if resume_session_id is not None:
        if has_task_source or launch:
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_session_input(resume_session_id), code="start-action-conflict")
        if mode != "auto":
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_session_input(resume_session_id), code="start-resume-mode-invalid")
        return _resume(adapter_id=adapter_id, session_id=resume_session_id, session_root=session_root)
    if not has_task_source or (task_file is not None and task_text is not None):
        return _blocked(adapter_id=adapter_id, mode=mode, input_summary=_empty_input(), code="start-task-source-invalid")

    input_summary, payload = _inspect_task_source(task_file=task_file, task_text=task_text)
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
    if launch:
        try:
            _relative, local_profile, _validation = load_local_launch_profile(host_launch_profile_path or Path(""))
        except (LifecycleError, OSError) as exc:
            code = exc.code if isinstance(exc, LifecycleError) else "local-launch-profile-read-failed"
            return _blocked(adapter_id=adapter_id, mode=mode, input_summary=input_summary, code=code)
        if local_profile.get("adapterId") != adapter_id:
            return _blocked(
                adapter_id=adapter_id,
                mode=mode,
                input_summary=input_summary,
                code="local-launch-profile-adapter-mismatch",
            )

    receipt = start_adapter_task(
        adapter_id=adapter_id,
        task_file=task_file,
        task_text=task_text,
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
    if not launch:
        return _from_task_receipt(adapter_id=adapter_id, mode=mode, receipt=receipt)
    return _launch_managed_receipt(
        adapter_id=adapter_id,
        mode=mode,
        receipt=receipt,
        profile_path=host_launch_profile_path or Path(""),
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
            delegate_summary=_resume_summary(receipt),
            blockers=_blocker_summaries(receipt.get("blockers")),
        )
    return build_lifecycle_start_receipt(
        status=status,
        adapter_id=adapter_id,
        requested_mode="auto",
        action="RESUME",
        input_summary=input_summary,
        delegate_summary=_resume_summary(receipt),
        lifecycle_coverage_claimed=status == "PASS" and bool(receipt.get("lifecycleCoverageClaimed")),
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


def _inspect_task_source(*, task_file: Path | None, task_text: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if task_text is not None:
        data = task_text.encode("utf-8")
        return _source_input("TEXT", "inline-task", data), _parse_payload(data)
    if task_file is None or not task_file.is_file():
        label = task_file.name if task_file is not None else None
        return {**_empty_input(), "label": label}, None
    try:
        data = task_file.read_bytes()
    except OSError:
        return {**_empty_input(), "label": task_file.name}, None
    return _source_input("FILE", task_file.name, data), _parse_payload(data)


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
    )


def _launch_managed_receipt(
    *,
    adapter_id: str,
    mode: str,
    receipt: dict[str, Any],
    profile_path: Path,
) -> dict[str, Any]:
    if receipt.get("status") != "READY" or receipt.get("action") != "MANAGED_RUN":
        return _from_task_receipt(adapter_id=adapter_id, mode=mode, receipt=receipt)
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
    )


def _binding_path(binding: dict[str, Any], field: str) -> Path | None:
    value = binding.get(field)
    return Path(value) if isinstance(value, str) and value else None


def _binding_string(binding: dict[str, Any], field: str) -> str | None:
    value = binding.get(field)
    return value if isinstance(value, str) and value else None


def _task_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    planning = receipt.get("planningImport") if isinstance(receipt.get("planningImport"), dict) else {}
    session = receipt.get("adapterSessionReceipt") if isinstance(receipt.get("adapterSessionReceipt"), dict) else {}
    next_action = session.get("nextAction") if isinstance(session.get("nextAction"), dict) else {}
    recommendation = (
        receipt.get("reviewMeshRecommendation")
        if isinstance(receipt.get("reviewMeshRecommendation"), dict)
        else {}
    )
    return {
        "schemaVersion": receipt.get("schemaVersion"),
        "status": receipt.get("status"),
        "action": receipt.get("action"),
        "detectedTaskShape": receipt.get("detectedTaskShape"),
        "recommendedQualityProfiles": list(receipt.get("recommendedQualityProfiles", [])),
        "planningImportDigest": planning.get("importDigest"),
        "sessionReceiptDigest": session.get("receiptDigest"),
        "riskAdvisory": receipt.get("riskAdvisory") if isinstance(receipt.get("riskAdvisory"), dict) else None,
        "riskExecutionProfile": next_action.get("riskExecutionProfile")
        if isinstance(next_action.get("riskExecutionProfile"), dict)
        else None,
        "riskProfileRequiredAtTaskStart": bool(next_action.get("riskProfileRequiredAtTaskStart")),
        "reviewRecommendation": {
            "recommendedMode": recommendation.get("recommendedMode"),
            "phaseCoverage": list(recommendation.get("phaseCoverage", [])),
            "requiredReviewers": recommendation.get("requiredReviewers"),
            "advisoryOnly": recommendation.get("advisoryOnly"),
            "recommendationDigest": recommendation.get("recommendationDigest"),
        }
        if recommendation
        else None,
        "receiptDigest": receipt.get("receiptDigest"),
    }


def _resume_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": receipt.get("schemaVersion"),
        "status": receipt.get("status"),
        "lineageStatus": receipt.get("lineageStatus"),
        "managedWorkflow": bool(receipt.get("managedWorkflow")),
        "lifecycleCoverageClaimed": bool(receipt.get("lifecycleCoverageClaimed")),
        "receiptDigest": receipt.get("receiptDigest"),
    }


def _claims_execution(receipt: dict[str, Any]) -> bool:
    return any(bool(receipt.get(field)) for field in ("executionStarted", "hostLaunchStarted", "lifecycleCoverageClaimed"))


def _safe_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _empty_input()
    return {
        "type": value.get("type", "NONE"),
        "label": value.get("label"),
        "digest": value.get("digest", sha256_hex(b"")),
        "byteCount": value.get("byteCount", 0),
        "rawTextStored": False,
    }


def _source_input(kind: str, label: str, data: bytes) -> dict[str, Any]:
    return {"type": kind, "label": label, "digest": sha256_hex(data), "byteCount": len(data), "rawTextStored": False}


def _session_input(session_id: str) -> dict[str, Any]:
    encoded = session_id.encode("utf-8")
    return {"type": "SESSION", "label": session_id, "digest": sha256_hex(encoded), "byteCount": len(encoded), "rawTextStored": False}


def _empty_input() -> dict[str, Any]:
    return {"type": "NONE", "label": None, "digest": sha256_hex(b""), "byteCount": 0, "rawTextStored": False}


def _blocker_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            summary = {"code": str(item.get("code", "start-delegate-blocked"))}
            if isinstance(item.get("field"), str):
                summary["field"] = item["field"]
            if isinstance(item.get("fields"), list):
                summary["fields"] = [str(field) for field in item["fields"]]
            summaries.append(summary)
    return summaries


def _blocked(*, adapter_id: str, mode: str, input_summary: dict[str, Any], code: str) -> dict[str, Any]:
    return build_lifecycle_start_receipt(
        status="BLOCKED",
        adapter_id=adapter_id,
        requested_mode=mode,
        action="BLOCKED",
        input_summary=input_summary,
        blockers=[{"code": code}],
    )
