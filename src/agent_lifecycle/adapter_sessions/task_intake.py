"""Adapter task intake classifier and managed-run delegator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.workflow_bridge import managed_adapter_run
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    load_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.imports import import_planning_input, import_planning_text
from agent_lifecycle.quality.bug_forensics_advisor import (
    bug_forensics_recommended,
    build_bug_forensics_advisory,
)
from agent_lifecycle.review_mesh.recommendation import recommend_review_mesh_for_text

ADAPTER_TASK_START_RECEIPT_SCHEMA = "agent-adapter-task-start-receipt.v1"
ADAPTER_TASK_RUN_REQUEST_SCHEMA = "agent-adapter-task-run-request.v1"

_ANALYSIS_FIRST_MARKERS = (
    "analyze code",
    "analyse code",
    "analysis before",
    "inspect before",
    "investigate before",
    "review code before",
    "risk scan",
    "проанализ",
    "анализ кода",
    "перед внедрением",
    "перед реализацией",
    "сначала анализ",
    "сначала проверь",
    "исследуй",
)


def start_adapter_task(
    *,
    adapter_id: str,
    task_file: Path | None = None,
    task_text: str | None = None,
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
    package_id: str = "adapter-task-intake",
    requested_risk: str | None = None,
    risk_policy_path: Path | None = None,
    routing_profile_path: Path | None = None,
    baseline_profile_path: Path | None = None,
    host_model_profile_path: Path | None = None,
) -> dict[str, Any]:
    """Classify adapter task input without turning raw text into authority."""

    source, source_blockers = _load_source(task_file=task_file, task_text=task_text)
    if source is None:
        return _receipt(
            adapter_id=adapter_id,
            source=_empty_source(),
            action="BLOCKED",
            status="BLOCKED",
            blockers=source_blockers,
        )
    parsed = _parse_json(source["data"])
    if parsed is not None and parsed.get("schemaVersion") == ADAPTER_TASK_RUN_REQUEST_SCHEMA:
        return _from_run_request(
            adapter_id=adapter_id,
            request=parsed,
            source=_source_summary(source),
            descriptor_path=descriptor_path,
            session_root=session_root,
            requested_risk=requested_risk,
            risk_policy_path=risk_policy_path,
            routing_profile_path=routing_profile_path,
            baseline_profile_path=baseline_profile_path,
            host_model_profile_path=host_model_profile_path,
        )
    if parsed is not None and parsed.get("schemaVersion") == "agent-plan-manifest.v1":
        if parsed.get("status") == "FROZEN":
            if source.get("path") is None:
                return _receipt(
                    adapter_id=adapter_id,
                    source=_source_summary(source),
                    action="BLOCKED",
                    status="BLOCKED",
                    blockers=[{"code": "adapter-task-frozen-manifest-file-required"}],
                )
            return _from_frozen_manifest(
                adapter_id=adapter_id,
                manifest_path=Path(source["path"]),
                source=_source_summary(source),
                descriptor_path=descriptor_path,
                session_root=session_root,
                state_path=state_path,
                lock_path=lock_path,
                task_id=task_id,
                operation_id=operation_id,
                expected_revision=expected_revision,
                source_revision=source_revision,
                requested_risk=requested_risk,
                risk_policy_path=risk_policy_path,
                routing_profile_path=routing_profile_path,
                baseline_profile_path=baseline_profile_path,
                host_model_profile_path=host_model_profile_path,
            )
    return _planning_intake(
        adapter_id=adapter_id,
        source=source,
        candidate_out=candidate_out,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
        package_id=package_id,
        requested_risk=requested_risk,
    )


def _load_source(*, task_file: Path | None, task_text: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if (task_file is None and task_text is None) or (task_file is not None and task_text is not None):
        return None, [{"code": "adapter-task-source-invalid", "message": "exactly one of --file/--task-file or --text/--task-text is required"}]
    if task_text is not None:
        data = task_text.encode("utf-8")
        return {"kind": "TEXT", "label": "inline-task", "data": data, "text": task_text, "path": None}, []
    assert task_file is not None
    if not task_file.is_file():
        return None, [{"code": "adapter-task-file-missing", "sourceLabel": task_file.name}]
    data = task_file.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    return {"kind": "FILE", "label": task_file.name, "data": data, "text": text, "path": task_file.as_posix()}, []


def _planning_intake(
    *,
    adapter_id: str,
    source: dict[str, Any],
    candidate_out: Path | None,
    max_input_bytes: int,
    target_tokens: int,
    package_id: str,
    requested_risk: str | None,
) -> dict[str, Any]:
    if source["kind"] == "TEXT":
        planning = import_planning_text(
            source["text"],
            source_label=source["label"],
            package_id=package_id,
            max_input_bytes=max_input_bytes,
            target_tokens=target_tokens,
        )
    else:
        planning = import_planning_input(
            Path(source["path"]),
            package_id=package_id,
            max_input_bytes=max_input_bytes,
            target_tokens=target_tokens,
        )
    if candidate_out is not None:
        write_json_create(candidate_out, planning)
    shape = _classify_task(source.get("text", ""))
    review_mesh_recommendation = recommend_review_mesh_for_text(
        source.get("text", ""),
        source_label=source["label"],
    )
    blockers = [{"code": item.get("code", "planning-import-blocker"), **({"source": "planning-import"} if "code" in item else {})} for item in planning.get("blockers", [])]
    status = "BLOCKED" if planning.get("status") != "PASS" else "REVIEW_REQUIRED"
    action = "BLOCKED" if status == "BLOCKED" else ("DRAFT_PLAN_REVIEW" if _parse_json(source["data"]) else "DRAFT_INTAKE")
    return _receipt(
        adapter_id=adapter_id,
        source=_source_summary(source),
        action=action,
        status=status,
        blockers=blockers,
        planning_import=_planning_summary(planning),
        detected_task_shape=shape["taskShape"],
        recommended_quality_profiles=shape["recommendedQualityProfiles"],
        bug_forensics_advisory=shape["bugForensicsAdvisory"],
        pre_implementation_analysis=shape["preImplementationAnalysis"],
        review_mesh_recommendation=review_mesh_recommendation,
        requires_review=True,
        audit_required=True,
        freeze_blocked=True,
        risk_advisory=_risk_advisory(requested_risk),
    )


def _from_run_request(
    *,
    adapter_id: str,
    request: dict[str, Any],
    source: dict[str, Any],
    descriptor_path: Path | None,
    session_root: Path | None,
    requested_risk: str | None,
    risk_policy_path: Path | None,
    routing_profile_path: Path | None,
    baseline_profile_path: Path | None,
    host_model_profile_path: Path | None,
) -> dict[str, Any]:
    blockers = _run_request_blockers(adapter_id, request)
    if blockers:
        return _receipt(adapter_id=adapter_id, source=source, action="BLOCKED", status="BLOCKED", blockers=blockers)
    return _managed_run_receipt(
        adapter_id=adapter_id,
        source=source,
        descriptor_path=descriptor_path,
        session_root=session_root,
        state_path=Path(str(request["state"])),
        manifest_path=Path(str(request["manifest"])),
        lock_path=Path(str(request["lock"])) if request.get("lock") else None,
        task_id=str(request["task"]),
        operation_id=str(request["operationId"]),
        expected_revision=int(request["expectedRevision"]),
        source_revision=str(request["sourceRevision"]),
        requested_risk=requested_risk,
        risk_policy_path=risk_policy_path,
        routing_profile_path=routing_profile_path,
        baseline_profile_path=baseline_profile_path,
        host_model_profile_path=host_model_profile_path,
    )


def _from_frozen_manifest(
    *,
    adapter_id: str,
    manifest_path: Path,
    source: dict[str, Any],
    descriptor_path: Path | None,
    session_root: Path | None,
    state_path: Path | None,
    lock_path: Path | None,
    task_id: str | None,
    operation_id: str | None,
    expected_revision: int | None,
    source_revision: str | None,
    requested_risk: str | None,
    risk_policy_path: Path | None,
    routing_profile_path: Path | None,
    baseline_profile_path: Path | None,
    host_model_profile_path: Path | None,
) -> dict[str, Any]:
    missing = [
        name
        for name, value in {
            "state": state_path,
            "lock": lock_path,
            "task": task_id,
            "operationId": operation_id,
            "expectedRevision": expected_revision,
            "sourceRevision": source_revision,
        }.items()
        if value in {None, ""}
    ]
    if missing:
        return _receipt(
            adapter_id=adapter_id,
            source=source,
            action="BLOCKED",
            status="BLOCKED",
            blockers=[{"code": "adapter-task-frozen-binding-missing", "fields": missing}],
        )
    return _managed_run_receipt(
        adapter_id=adapter_id,
        source=source,
        descriptor_path=descriptor_path,
        session_root=session_root,
        state_path=state_path or Path(""),
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=str(task_id),
        operation_id=str(operation_id),
        expected_revision=int(expected_revision or 0),
        source_revision=str(source_revision),
        requested_risk=requested_risk,
        risk_policy_path=risk_policy_path,
        routing_profile_path=routing_profile_path,
        baseline_profile_path=baseline_profile_path,
        host_model_profile_path=host_model_profile_path,
    )


def _managed_run_receipt(
    *,
    adapter_id: str,
    source: dict[str, Any],
    descriptor_path: Path | None,
    session_root: Path | None,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    requested_risk: str | None,
    risk_policy_path: Path | None,
    routing_profile_path: Path | None,
    baseline_profile_path: Path | None,
    host_model_profile_path: Path | None,
) -> dict[str, Any]:
    try:
        session_receipt = managed_adapter_run(
            adapter_id=adapter_id,
            descriptor_path=descriptor_path,
            session_root=session_root,
            state_path=state_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            task_id=task_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            requested_risk=requested_risk,
            risk_policy_path=risk_policy_path,
            routing_profile_path=routing_profile_path,
            baseline_profile_path=baseline_profile_path,
            host_model_profile_path=host_model_profile_path,
        )
    except LifecycleError as exc:
        return _receipt(
            adapter_id=adapter_id,
            source=source,
            action="BLOCKED",
            status="BLOCKED",
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
        )
    blockers = list(session_receipt.get("blockers", []))
    status = "BLOCKED" if session_receipt.get("status") == "BLOCKED" or blockers else "READY"
    return _receipt(
        adapter_id=adapter_id,
        source=source,
        action="MANAGED_RUN" if status == "READY" else "BLOCKED",
        status=status,
        blockers=blockers,
        adapter_session_receipt=session_receipt,
        execution_started=status == "READY",
        lifecycle_coverage_claimed=bool(session_receipt.get("lifecycleCoverageClaimed")) and status == "READY",
        requires_review=False,
        audit_required=False,
        freeze_blocked=False,
        workflow_binding={
            "state": state_path.as_posix(),
            "manifest": manifest_path.as_posix(),
            "lock": lock_path.as_posix() if lock_path else None,
            "task": task_id,
            "operationId": operation_id,
            "expectedRevision": expected_revision,
            "sourceRevision": source_revision,
        },
    )


def _run_request_blockers(adapter_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field in ("state", "manifest", "task", "operationId", "expectedRevision", "sourceRevision"):
        value = request.get(field)
        if value in {None, ""}:
            blockers.append({"code": "adapter-task-run-request-field-missing", "field": field})
    expected_revision = request.get("expectedRevision")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        blockers.append({"code": "adapter-task-run-request-revision-invalid"})
    request_adapter = request.get("adapterId") or request.get("adapter")
    if isinstance(request_adapter, str) and request_adapter and request_adapter != adapter_id:
        blockers.append({"code": "adapter-task-run-request-adapter-mismatch", "expected": adapter_id, "actual": request_adapter})
    if request.get("productionPromotionClaimed") is not False and "productionPromotionClaimed" in request:
        blockers.append({"code": "adapter-task-run-request-production-claim"})
    digest = request.get("requestDigest")
    if digest is not None:
        expected = canonical_digest({key: value for key, value in request.items() if key != "requestDigest"})
        if digest != expected:
            blockers.append({"code": "adapter-task-run-request-digest-mismatch"})
    return blockers


def _classify_task(text: str) -> dict[str, Any]:
    lowered = text.lower()
    advisory = build_bug_forensics_advisory(text)
    defect = bug_forensics_recommended(advisory)
    analysis = any(marker in lowered for marker in _ANALYSIS_FIRST_MARKERS)
    profiles = list(advisory["recommendedQualityProfiles"]) if defect else []
    task_shape = "bugfix" if defect else ("analysis-first" if analysis else ("feature" if text.strip() else "unknown"))
    purpose = None
    if analysis:
        purpose = "bug-investigation" if defect else "feature-discovery"
    return {
        "taskShape": task_shape,
        "recommendedQualityProfiles": profiles,
        "bugForensicsAdvisory": advisory,
        "preImplementationAnalysis": {
            "required": analysis,
            "purpose": purpose,
            "activeWorkflowGateClaimed": False,
        },
    }


def _planning_summary(planning: dict[str, Any]) -> dict[str, Any]:
    candidate = planning.get("candidatePlan")
    return {
        "schemaVersion": planning.get("schemaVersion"),
        "status": planning.get("status"),
        "candidateLifecycleStatus": planning.get("candidateLifecycleStatus"),
        "requiresReview": planning.get("requiresReview"),
        "auditRequired": planning.get("auditRequired"),
        "freezeBlocked": planning.get("freezeBlocked"),
        "source": planning.get("source"),
        "candidateDigest": canonical_digest(candidate) if isinstance(candidate, dict) else None,
        "importDigest": planning.get("importDigest"),
        "blockerCodes": [item.get("code") for item in planning.get("blockers", []) if isinstance(item, dict)],
    }


def _source_summary(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": source["kind"],
        "label": source["label"],
        "digest": sha256_hex(source["data"]),
        "byteCount": len(source["data"]),
        "rawTextStored": False,
    }


def _empty_source() -> dict[str, Any]:
    return {"type": "NONE", "label": None, "digest": sha256_hex(b""), "byteCount": 0, "rawTextStored": False}


def _parse_json(data: bytes) -> dict[str, Any] | None:
    try:
        return load_json_object(data, label="adapter task input")
    except LifecycleError:
        return None


def _receipt(
    *,
    adapter_id: str,
    source: dict[str, Any],
    action: str,
    status: str,
    blockers: list[dict[str, Any]] | None = None,
    planning_import: dict[str, Any] | None = None,
    adapter_session_receipt: dict[str, Any] | None = None,
    detected_task_shape: str = "unknown",
    recommended_quality_profiles: list[str] | None = None,
    pre_implementation_analysis: dict[str, Any] | None = None,
    execution_started: bool = False,
    lifecycle_coverage_claimed: bool = False,
    requires_review: bool = False,
    audit_required: bool = False,
    freeze_blocked: bool = False,
    workflow_binding: dict[str, Any] | None = None,
    review_mesh_recommendation: dict[str, Any] | None = None,
    bug_forensics_advisory: dict[str, Any] | None = None,
    risk_advisory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": ADAPTER_TASK_START_RECEIPT_SCHEMA,
        "status": status,
        "adapterId": adapter_id,
        "input": source,
        "action": action,
        "detectedTaskShape": detected_task_shape,
        "recommendedQualityProfiles": recommended_quality_profiles or [],
        "preImplementationAnalysis": pre_implementation_analysis
        or {"required": False, "purpose": None, "activeWorkflowGateClaimed": False},
        "executionStarted": execution_started,
        "lifecycleCoverageClaimed": lifecycle_coverage_claimed,
        "requiresReview": requires_review,
        "auditRequired": audit_required,
        "freezeBlocked": freeze_blocked,
        "reviewBlockers": blockers or [],
        "planningImport": planning_import,
        "adapterSessionReceipt": adapter_session_receipt,
        "workflowBinding": workflow_binding,
        "reviewMeshRecommendation": review_mesh_recommendation,
        "bugForensicsAdvisory": bug_forensics_advisory,
        "riskAdvisory": risk_advisory,
        "modelCallsStarted": False,
        "hostLaunchStarted": bool(adapter_session_receipt.get("hostLaunchStarted")) if isinstance(adapter_session_receipt, dict) else False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "rawTaskTextStored": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _risk_advisory(requested_risk: str | None) -> dict[str, Any] | None:
    if requested_risk is None:
        return None
    return {
        "requestedRisk": requested_risk,
        "status": "ADVISORY_ONLY",
        "executionProfileCreated": False,
        "activeUsageGateClaimed": False,
    }
