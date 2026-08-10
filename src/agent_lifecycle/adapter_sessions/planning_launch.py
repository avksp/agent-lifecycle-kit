"""Bounded planning-only host launch composition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.redaction import redact_process_text
from agent_lifecycle.contracts import canonical_digest

MAX_TASK_INPUT_BYTES = 32_768
MAX_ENVELOPE_BYTES = 49_152
MAX_CAPTURED_OUTPUT_BYTES = 262_144
MAX_PLANNING_WALL_SECONDS = 300
PLANNING_MODES = {"auto", "research", "plan", "review"}


def build_planning_envelope(
    *,
    adapter_id: str,
    session_id: str,
    requested_mode: str,
    task_text: str,
    input_source: str,
    advisory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if requested_mode not in PLANNING_MODES:
        raise ValueError(f"unsupported planning mode: {requested_mode}")
    encoded = task_text.encode("utf-8")
    if not encoded:
        raise ValueError("planning task must not be empty")
    if len(encoded) > MAX_TASK_INPUT_BYTES:
        raise ValueError("planning task exceeds max input bytes")
    return {
        "schemaVersion": "agent-planning-launch-envelope.v1",
        "adapterId": adapter_id,
        "sessionId": session_id,
        "requestedMode": requested_mode,
        "input": {
            "source": input_source,
            "sha256": canonical_digest({"text": task_text}),
            "byteCount": len(encoded),
            "rawTaskTextStored": False,
        },
        "task": {"untrustedText": task_text},
        "authority": {
            "planningOnly": True,
            "implementationAuthorized": False,
            "freezeRequired": True,
        },
        "limits": {
            "maxInputBytes": MAX_TASK_INPUT_BYTES,
            "maxCapturedOutputBytes": MAX_CAPTURED_OUTPUT_BYTES,
            "maxWallSeconds": MAX_PLANNING_WALL_SECONDS,
            "maxHostProcesses": 1,
        },
        "advisory": advisory or {},
        "responseContract": {
            "schemaVersion": "agent-planning-result.v1",
            "format": "single-json-object",
            "requiredSections": ["summary", "requirements", "workstreams", "evidenceRoutes"],
            "implementationAuthorized": False,
        },
    }


def run_planning_launch(
    *,
    adapter_id: str,
    session_id: str,
    requested_mode: str,
    task_text: str,
    input_source: str,
    argv: list[str],
    env: dict[str, str],
    advisory: dict[str, Any] | None = None,
    timeout_seconds: float = MAX_PLANNING_WALL_SECONDS,
    process_cwd: Path | None = None,
) -> dict[str, Any]:
    try:
        envelope = build_planning_envelope(
            adapter_id=adapter_id,
            session_id=session_id,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            advisory=advisory,
        )
    except ValueError as exc:
        return _receipt(
            adapter_id=adapter_id,
            session_id=session_id,
            requested_mode=requested_mode,
            input_identity=_input_identity(task_text, input_source),
            process=None,
            result=None,
            blockers=[{"code": "planning-input-invalid", "message": str(exc)}],
        )
    process = run_process(
        argv,
        env=env,
        timeout_seconds=min(timeout_seconds, MAX_PLANNING_WALL_SECONDS),
        cwd=process_cwd,
        stdin_text=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        max_input_bytes=MAX_ENVELOPE_BYTES,
        max_output_bytes=MAX_CAPTURED_OUTPUT_BYTES,
    )
    blockers = list(process.get("blockers", []))
    result: dict[str, Any] | None = None
    if process.get("status") == "PASS":
        result, result_blockers = parse_planning_result(str(process.get("stdout", "")))
        blockers.extend(result_blockers)
    return _receipt(
        adapter_id=adapter_id,
        session_id=session_id,
        requested_mode=requested_mode,
        input_identity=envelope["input"],
        process=process,
        result=result,
        blockers=blockers,
    )


def parse_planning_result(raw_output: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        payload = json.loads(raw_output.strip())
    except json.JSONDecodeError:
        return None, [{"code": "planning-result-json-invalid"}]
    if not isinstance(payload, dict):
        return None, [{"code": "planning-result-not-object"}]
    blockers: list[dict[str, Any]] = []
    if payload.get("schemaVersion") != "agent-planning-result.v1":
        blockers.append({"code": "planning-result-schema"})
    if payload.get("status") != "REVIEW_REQUIRED":
        blockers.append({"code": "planning-result-status"})
    for field in ("summary", "requirements", "workstreams", "evidenceRoutes"):
        value = payload.get(field)
        if field == "summary" and (not isinstance(value, str) or not value.strip()):
            blockers.append({"code": "planning-result-section", "field": field})
        if field != "summary" and (not isinstance(value, list) or not value):
            blockers.append({"code": "planning-result-section", "field": field})
    if payload.get("implementationAuthorized") is not False:
        blockers.append({"code": "planning-result-authority-claim"})
    if payload.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "planning-result-production-claim"})
    sanitized = _sanitize(payload)
    return (sanitized if not blockers else None), blockers


def _receipt(
    *,
    adapter_id: str,
    session_id: str,
    requested_mode: str,
    input_identity: dict[str, Any],
    process: dict[str, Any] | None,
    result: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    process_started = bool(process and process.get("processStarted"))
    process_summary = {
        "status": process.get("status") if process else "NOT_STARTED",
        "exitCode": process.get("exitCode") if process else None,
        "timedOut": bool(process and process.get("timedOut")),
        "inputBytes": process.get("inputBytes", 0) if process else 0,
        "outputBytes": process.get("outputBytes", 0) if process else 0,
        "outputLimitExceeded": bool(process and process.get("outputLimitExceeded")),
        "redactionApplied": bool(
            process and (process.get("stdoutRedacted") or process.get("stderrRedacted"))
        ),
        "rawOutputStored": False,
    }
    usage = _usage_evidence(result)
    body = {
        "schemaVersion": "agent-planning-launch-receipt.v1",
        "status": "REVIEW_REQUIRED" if result is not None and not blockers else "BLOCKED",
        "action": "PLANNING_LAUNCH",
        "adapterId": adapter_id,
        "sessionId": session_id,
        "requestedMode": requested_mode,
        "input": {**input_identity, "rawTaskTextStored": False},
        "process": process_summary,
        "result": result,
        "usageEvidence": usage,
        "processCalls": 1 if process_started else 0,
        "implementationAuthorized": False,
        "requiresReview": True,
        "rawTaskTextStored": False,
        "hostLaunchStarted": process_started,
        "modelCallsStarted": process_started,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def _input_identity(task_text: str, input_source: str) -> dict[str, Any]:
    return {
        "source": input_source,
        "sha256": canonical_digest({"text": task_text}),
        "byteCount": len(task_text.encode("utf-8")),
        "rawTaskTextStored": False,
    }


def _usage_evidence(result: dict[str, Any] | None) -> dict[str, Any]:
    usage = result.get("usage") if isinstance(result, dict) and isinstance(result.get("usage"), dict) else {}
    confidence = usage.get("confidence") if usage.get("confidence") in {"ATTESTED", "ESTIMATED"} else "MISSING"
    return {
        "confidence": confidence,
        "inputTokens": usage.get("inputTokens") if isinstance(usage.get("inputTokens"), int) else None,
        "outputTokens": usage.get("outputTokens") if isinstance(usage.get("outputTokens"), int) else None,
        "moneyFieldsCanonical": False,
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact_process_text(value)[0]
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    return value
