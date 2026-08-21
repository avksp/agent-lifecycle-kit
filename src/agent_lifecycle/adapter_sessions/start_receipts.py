"""Receipt and authority helpers for the unified adapter start facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_lifecycle_start_receipt
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, sha256_hex
from agent_lifecycle.contracts.project_profile_schemas import GUIDED_ACTION_RECEIPT_SCHEMA
from agent_lifecycle.policy.execution_strategy import (
    deferred_execution_strategy_summary,
    execution_strategy_summary,
    resolve_execution_strategy,
)
from agent_lifecycle.project.guidance import build_stage_guidance_projection

def _profile_plan_authority(
    *,
    task_file: Path | None,
    task_text: str | None,
    lock_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Read plan authority only from a structured frozen file input.

    Raw text and Markdown remain draft-only and do not cause ALK to inspect
    arbitrary project files. Frozen manifests and adapter run requests already
    carry explicit plan paths, so their profile merge can enforce the same
    plan/lock precedence as the atomic commands.
    """

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
        lock = read_json_object(selected_lock, label="project-profile plan lock") if selected_lock is not None else None
    except (LifecycleError, OSError):
        return None, None
    return plan, lock


def _build_guided_action_receipt(
    base: dict[str, Any],
    *,
    effective: dict[str, Any],
    profile_path: Path | None,
    project_root: Path | None,
) -> dict[str, Any]:
    del profile_path
    base = _with_project_profile_digest(base, effective["effectiveProfileDigest"])
    stage = _guided_stage(base)
    stage_guidance = build_stage_guidance_projection(
        effective,
        stage=stage,
        project_root=project_root,
    )
    body = {
        "schemaVersion": GUIDED_ACTION_RECEIPT_SCHEMA,
        "status": base.get("status", "BLOCKED"),
        "startReceipt": base,
        "effectiveProfile": _effective_profile_summary(effective),
        "profileDigest": effective["effectiveProfileDigest"],
        "stageGuidance": stage_guidance,
        "nextAction": {
            "stage": stage,
            "type": base.get("action", "BLOCKED"),
            "status": base.get("status", "BLOCKED"),
            "requiresReview": bool(base.get("requiresReview")),
            "executionStarted": bool(base.get("executionStarted")),
            "lifecycleCoverageClaimed": bool(base.get("lifecycleCoverageClaimed")),
        },
        "blockers": _blocker_summaries(base.get("blockers")),
        "modelCallsStarted": False,
        "hostLaunchStarted": bool(base.get("hostLaunchStarted")),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _with_project_profile_digest(receipt: dict[str, Any], digest: str) -> dict[str, Any]:
    """Attach the active profile identity without changing the legacy path."""

    if receipt.get("projectProfileDigest") == digest:
        return receipt
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    body["projectProfileDigest"] = digest
    return {**body, "receiptDigest": canonical_digest(body)}


def _guided_stage(base: dict[str, Any]) -> str:
    """Map the public start mode to the stable project-profile stage."""

    mode = base.get("requestedMode")
    return {
        "research": "research",
        "plan": "planning",
        "review": "review",
        "implement": "implementation",
    }.get(mode, "intake")


def _effective_profile_summary(effective: dict[str, Any]) -> dict[str, Any]:
    """Keep the guided receipt bounded while retaining the resolved authority."""

    return {
        "schemaVersion": effective.get("schemaVersion"),
        "status": effective.get("status"),
        "profileId": effective.get("profileId"),
        "sourceProfileDigest": effective.get("sourceProfileDigest"),
        "defaultAdapter": effective.get("defaultAdapter"),
        "defaultMode": effective.get("defaultMode"),
        "defaultRisk": effective.get("defaultRisk"),
        "stages": effective.get("stages", {}),
        "authority": effective.get("authority", {}),
        "effectiveProfileDigest": effective.get("effectiveProfileDigest"),
    }


def _strategy_summary_for_receipt(
    receipt: dict[str, Any],
    *,
    adapter_id: str,
    descriptor_path: Path | None,
    requested_risk: str,
    risk_policy_path: Path | None,
    routing_profile_path: Path | None,
    baseline_profile_path: Path | None,
    host_model_profile_path: Path | None,
    project_profile_digest: str | None = None,
) -> dict[str, Any]:
    if receipt.get("status") != "READY" or receipt.get("action") != "MANAGED_RUN":
        return deferred_execution_strategy_summary()
    binding = receipt.get("workflowBinding") if isinstance(receipt.get("workflowBinding"), dict) else {}
    try:
        manifest_path = _required_binding_path(binding, "manifest")
        lock_path = _required_binding_path(binding, "lock")
        state_path = _required_binding_path(binding, "state")
        _descriptor_file, descriptor = load_adapter_descriptor(adapter_id, descriptor_path)
        strategy = resolve_execution_strategy(
            manifest=read_json_object(manifest_path, label="frozen plan manifest"),
            lock=read_json_object(lock_path, label="plan lock"),
            state=read_json_object(state_path, label="workflow state"),
            task_id=_required_binding_string(binding, "task"),
            adapter_id=adapter_id,
            adapter_host=str(descriptor.get("host", "")),
            operation_id=_required_binding_string(binding, "operationId"),
            expected_revision=_required_binding_revision(binding),
            source_revision=_required_binding_string(binding, "sourceRevision"),
            requested_risk=requested_risk,
            risk_policy=read_json_object(
                risk_policy_path or Path("profiles/risk-execution-policy.v1.json"),
                label="risk execution policy",
            ),
            routing_profile=read_json_object(
                routing_profile_path or Path("profiles/model-routing-profile.v1.json"),
                label="model routing profile",
            ),
            baseline_profile=read_json_object(
                baseline_profile_path or Path("profiles/lifecycle-baselines.v1.json"),
                label="lifecycle baseline profile",
            ),
            host_profile=(
                read_json_object(host_model_profile_path, label="host model profile")
                if host_model_profile_path is not None
                else None
            ),
            project_profile_digest=project_profile_digest,
        )
        return execution_strategy_summary(strategy)
    except (LifecycleError, OSError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "strategy-input-read-failed"
        return {
            **deferred_execution_strategy_summary(reason=code),
            "status": "BLOCKED",
        }


def _required_binding_path(binding: dict[str, Any], field: str) -> Path:
    value = _required_binding_string(binding, field)
    return Path(value)


def _required_binding_string(binding: dict[str, Any], field: str) -> str:
    value = binding.get(field)
    if not isinstance(value, str) or not value:
        raise LifecycleError("strategy-binding-missing", "managed strategy binding is missing", {"field": field})
    return value


def _required_binding_revision(binding: dict[str, Any]) -> int:
    value = binding.get("expectedRevision")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError(
            "strategy-binding-revision-invalid",
            "managed strategy expected revision is invalid",
        )
    return value


def _binding_path(binding: dict[str, Any], field: str) -> Path | None:
    value = binding.get(field)
    return Path(value) if isinstance(value, str) and value else None


def _planning_launch_blocked_receipt(
    *,
    adapter_id: str,
    session_id: str,
    requested_mode: str,
    input_summary: dict[str, Any],
    code: str,
    message: str,
) -> dict[str, Any]:
    preparation = _planning_preparation(adapter_id)
    blocker = {"code": code, "message": message, **preparation}
    body = {
        "schemaVersion": "agent-planning-launch-receipt.v1",
        "status": "BLOCKED",
        "action": "PLANNING_LAUNCH",
        "adapterId": adapter_id,
        "sessionId": session_id,
        "requestedMode": requested_mode,
        "input": _planning_input(input_summary),
        "process": {
            "status": "NOT_STARTED",
            "exitCode": None,
            "timedOut": False,
            "inputBytes": 0,
            "outputBytes": 0,
            "outputLimitExceeded": False,
            "redactionApplied": False,
            "rawOutputStored": False,
        },
        "result": None,
        "usageEvidence": {
            "confidence": "MISSING",
            "inputTokens": None,
            "outputTokens": None,
            "moneyFieldsCanonical": False,
        },
        "processCalls": 0,
        "implementationAuthorized": False,
        "requiresReview": True,
        "rawTaskTextStored": False,
        "hostLaunchStarted": False,
        "modelCallsStarted": False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": [blocker],
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


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


def _resume_summary(receipt: dict[str, Any], *, session: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = {
        "schemaVersion": receipt.get("schemaVersion"),
        "status": receipt.get("status"),
        "lineageStatus": receipt.get("lineageStatus"),
        "managedWorkflow": bool(receipt.get("managedWorkflow")),
        "lifecycleCoverageClaimed": bool(receipt.get("lifecycleCoverageClaimed")),
        "receiptDigest": receipt.get("receiptDigest"),
    }
    if session and isinstance(session.get("contextCheckpointPolicy"), dict):
        summary["contextCheckpointPolicy"] = session["contextCheckpointPolicy"]
    return summary


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


def _planning_input(input_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(input_summary.get("type", "NONE")),
        "sha256": str(input_summary.get("digest", sha256_hex(b""))),
        "byteCount": int(input_summary.get("byteCount", 0)),
        "rawTaskTextStored": False,
    }


def _planning_preparation(adapter_id: str) -> dict[str, str]:
    profile = f".alk/host-launch/{adapter_id}.json"
    return {
        "profileCommand": f"agent-lifecycle adapter launch-profile --adapter {adapter_id} --out {profile}",
        "preflightCommand": f"agent-lifecycle host-launch preflight --profile {profile}",
    }


def _portable_planning_receipt(receipt: dict[str, Any], *, task_text: str) -> dict[str, Any]:
    """Remove exact input echoes before a host receipt crosses the public facade."""

    body = {
        str(key): _redact_task_echo(value, task_text=task_text)
        for key, value in receipt.items()
        if key != "receiptDigest"
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _redact_task_echo(value: Any, *, task_text: str) -> Any:
    if isinstance(value, str):
        return value.replace(task_text, "[REDACTED_TASK_INPUT]") if task_text else value
    if isinstance(value, list):
        return [_redact_task_echo(item, task_text=task_text) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _redact_task_echo(item, task_text=task_text)
            for key, item in value.items()
        }
    return value


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
            if isinstance(item.get("message"), str):
                summary["message"] = item["message"]
            for field in ("profileCommand", "preflightCommand", "preparationCommand"):
                if isinstance(item.get(field), str):
                    summary[field] = item[field]
            context = item.get("context")
            if isinstance(context, dict):
                for field in ("profileCommand", "preflightCommand", "preparationCommand"):
                    if isinstance(context.get(field), str):
                        summary[field] = context[field]
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
