"""Leaf process context and outcome handling for local managed launches."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    publish_attempt_result, record_uncertain_attempt, require_positive_attempt_result,
)
from agent_lifecycle.adapter_sessions.codex_prompt_preparation import (
    CLAIM as CODEX_SCOPED_CLAIM, ROUTE_ID as CODEX_EXACT_ROUTE, cleanup_prestart_raw,
)
from agent_lifecycle.adapter_sessions.contracts import build_launch_receipt
from agent_lifecycle.adapter_sessions.input_lifecycle import record_proven_no_start
from agent_lifecycle.adapter_sessions.launch_execution import _attach_qualification_receipt
from agent_lifecycle.adapter_sessions.local_launch_profile import local_receipt_argv
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object

@dataclass(frozen=True)
class _LaunchContext:
    root: Path
    relative: Path
    profile: dict[str, Any]
    profile_digest: str
    profile_adapter: str
    env: dict[str, str]
    env_receipt: dict[str, Any]
    timeout_seconds: float
    shipped_digest: str | None
    runner: Callable[..., dict[str, Any]]


def _original_attempt_deadline(state: dict[str, Any], task: dict[str, Any], *, clock=datetime) -> int:
    """Bridge the earlier immutable UTC deadline once, conservatively, before preparation."""
    mono = time.monotonic_ns()
    now = clock.now(timezone.utc)
    try:
        deadlines = [clock.fromisoformat(value.replace("Z", "+00:00")) for value in
                     (state.get("runDeadlineAt"), task.get("attemptDeadlineAt"))
                     if isinstance(value, str)]
        if len(deadlines) != 2 or any(value.utcoffset() is None or value.utcoffset().total_seconds() != 0
                                      for value in deadlines):
            raise ValueError("original UTC deadlines required")
        remaining = min(deadlines) - now
        ns = ((remaining.days * 86_400 + remaining.seconds) * 1_000_000 + remaining.microseconds) * 1_000
        if ns <= 0:
            raise ValueError("original deadline expired")
    except (TypeError, ValueError, OverflowError) as exc:
        raise LifecycleError("codex-exact-deadline-unavailable", "original run/attempt deadline is missing or expired") from exc
    return mono + ns



def _requires_exact_route(context, manifest, route_id, requested_claim, input_request, *, run_process=run_process):
    exact_required = (
        manifest.get("package", {}).get("id") == "release-2-16"
        and isinstance(manifest.get("runtimePolicy", {}).get("preExecutionBootstrap"), dict)
        and context.profile_adapter == "codex"
    )
    if not (exact_required or any(value is not None for value in (route_id, requested_claim, input_request))):
        return False
    if context.profile_adapter != "codex":
        raise LifecycleError("codex-exact-adapter-mismatch", "exact prompt route requires Codex")
    if route_id != CODEX_EXACT_ROUTE or requested_claim != CODEX_SCOPED_CLAIM or input_request is None:
        raise LifecycleError("codex-exact-route-required", "explicit limited route request is required")
    if context.runner is not run_process:
        raise LifecycleError("codex-exact-runner-unobserved", "selected runner cannot prove child-start boundary")
    return True


def _finish_exact_process(
    context, *, prepared, audit, result, session_id, risk_profile, host_identity,
    publish_attempt_result=publish_attempt_result, require_positive_attempt_result=require_positive_attempt_result,
    record_uncertain_attempt=record_uncertain_attempt, cleanup_prestart_raw=cleanup_prestart_raw,
    record_proven_no_start=record_proven_no_start, build_launch_receipt=build_launch_receipt,
    read_json_object=read_json_object, canonical_digest=canonical_digest, receipt_sha=None,
):
    if receipt_sha is None:
        receipt_sha = _optional_receipt_sha
    # Hash and expose only this closed observation. Full stdout/stderr stay
    # internal to the runner; only its bounded redacted tails leave this sink.
    result = {key: result[key] for key in (
        "status", "exitCode", "timedOut", "cancelled", "processStarted",
        "inputBytes", "outputBytes", "outputLimitExceeded", "stdoutTail", "stderrTail",
        "stdoutRedacted", "stderrRedacted", "cleanup", "processReceipt", "blockers",
        "deadlineMonotonicNs", "observerDisposition", "startObservation", "inputObservation",
        "absoluteDeadlineMonotonicNs", "startedMonotonicNs",
    ) if key in result}
    started = result["processStarted"]
    terminal = None
    if not started:
        try:
            cleanup_prestart_raw(
                context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
                attempt_id=prepared["attemptId"], operation_id=prepared.get("operationId"), staging_source=None,
                proven_no_start=True)
            record_proven_no_start(context.root, prepared["startReceiptPath"])
        except LifecycleError as exc:
            if exc.code == "codex-exact-start-uncertain":
                raise
            result = {**result, "status":"BLOCKED",
                      "blockers":[*result.get("blockers",[]), {"code":exc.code}]}
    if started and result.get("status") == "PASS":
        try:
            start = read_json_object(prepared["startReceiptPath"], label="observed process start")
            delivered = read_json_object(prepared["inputReceiptPath"], label="observed process input")
            if (start.get("stdinStatus") != "PENDING"
                    or delivered.get("status") != "COMPLETE"
                    or delivered.get("acceptedSha256") != prepared["finalPromptSha256"]):
                raise LifecycleError("codex-exact-process-join-invalid", "process start/input receipts differ")
        except (LifecycleError, OSError) as exc:
            code = exc.code if isinstance(exc, LifecycleError) else "codex-exact-process-join-missing"
            result = {**result, "status":"FAIL",
                      "blockers":[*result.get("blockers",[]), {"code":code,"costStatus":"UNAVAILABLE"}]}
    if started:
        try:
            terminal = publish_attempt_result(context.root, intent_path=prepared["intentPath"],
                                              process_result=result)
            if result["status"] == "PASS":
                terminal = require_positive_attempt_result(
                    context.root, intent_path=prepared["intentPath"], process_result=result)
        except (LifecycleError, OSError, ValueError, TypeError) as exc:
            terminal = None
            code = exc.code if isinstance(exc, LifecycleError) else "r11-result-publication-failed"
            blockers = [*result.get("blockers", []), {"code": code, "costStatus": "UNAVAILABLE"}]
            try:
                record_uncertain_attempt(context.root, intent_path=prepared["intentPath"])
            except (LifecycleError, OSError, ValueError):
                blockers.append({"code": "r11-result-uncertain-marker-failed", "costStatus": "UNAVAILABLE"})
            result = {**result, "status": "BLOCKED", "blockers": blockers}
    payload = build_launch_receipt(
        status=str(result["status"]), adapter_id="codex", session_id=session_id,
        launch_mode="managedTask", argv=prepared["argv"],
        timeout_seconds=context.timeout_seconds, env=context.env_receipt,
        exit_code=result.get("exitCode"), timed_out=bool(result.get("timedOut")),
        stdout_tail=str(result.get("stdoutTail", "")),
        stderr_tail=str(result.get("stderrTail", "")),
        stdout_redacted=bool(result.get("stdoutRedacted")),
        stderr_redacted=bool(result.get("stderrRedacted")),
        host_launch_started=started, blockers=list(result.get("blockers", [])),
        profile_digest=context.profile_digest,
        risk_profile_digest=str(risk_profile["profileDigest"]),
        receipt_argv=["codex", "exec", "--json", "--ephemeral", "-m", "<model>", "-C", "<cwd>", "-"],
        host_identity=host_identity,
    )
    payload["exactPrompt"] = {
        "routeId":CODEX_EXACT_ROUTE, "requestedClaim":CODEX_SCOPED_CLAIM,
        "scope":"ALK_CONTROLLED_OUTBOUND_INPUT_FIT", "hostOwnedInput":"UNAVAILABLE",
        "wholeCallUpperBoundU":"UNAVAILABLE", "fullFinancial":False,
        "sealedRequestSha256":prepared["sealedSha256"],
        "finalPromptSha256":prepared["finalPromptSha256"],
        "fitReceiptDigest":prepared["fitReceiptDigest"],
        "bootstrapAuditSha256":audit["auditSha256"],
        "startReceiptSha256":receipt_sha(prepared["startReceiptPath"]) if started else None,
        "inputReceiptSha256":receipt_sha(prepared["inputReceiptPath"]) if started else None,
        "terminalResultSha256":receipt_sha(
            prepared["intentPath"].with_name("attempt-result-terminal.json")) if terminal else None,
        "terminalStatus":terminal["status"] if terminal else ("START_UNCERTAIN" if started else "NOT_STARTED"),
        "retryAuthorized":False,
        "costStatus":"UNAVAILABLE" if started else "NOT_STARTED",
    }
    payload["modelCallsStarted"] = started
    # This safe projection was hashed at terminal publication above.
    # Exit zero alone cannot prove a native model completion.
    payload["exactPrompt"]["observedProcessResult"] = result
    payload["receiptDigest"] = canonical_digest({k:v for k,v in payload.items() if k != "receiptDigest"})
    return payload


def _optional_receipt_sha(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest() if data else None



def _finish_managed_process(
    context, *, argv, session_id, risk_profile, qualification_receipt, host_identity,
    build_launch_receipt=build_launch_receipt, local_receipt_argv=local_receipt_argv,
    _attach_qualification_receipt=_attach_qualification_receipt,
):
    try:
        result = context.runner(argv, env=context.env, timeout_seconds=context.timeout_seconds)
        if not isinstance(result, dict) or type(result.get("processStarted")) is not bool or (
            result["processStarted"] is False and (result.get("status") == "PASS"
                or result.get("startedFailure") is True or result.get("processReceipt") is not None)
        ):
            raise ValueError("runner did not establish a consistent physical start")
    except Exception as exc:
        raise LifecycleError("local-launch-start-uncertain", "runner result cannot establish physical start",
                             {"costStatus": "UNAVAILABLE", "retryAuthorized": False}) from exc
    payload = build_launch_receipt(
        status=str(result["status"]),
        adapter_id=context.profile_adapter,
        session_id=session_id,
        launch_mode="managedTask",
        argv=argv,
        timeout_seconds=context.timeout_seconds,
        env=context.env_receipt,
        exit_code=result.get("exitCode"),
        timed_out=bool(result.get("timedOut")),
        stdout_tail=str(result.get("stdoutTail", "")),
        stderr_tail=str(result.get("stderrTail", "")),
        stdout_redacted=bool(result.get("stdoutRedacted")),
        stderr_redacted=bool(result.get("stderrRedacted")),
        host_launch_started=result["processStarted"],
        blockers=list(result.get("blockers", [])),
        profile_digest=context.profile_digest,
        risk_profile_digest=str(risk_profile["profileDigest"]),
        receipt_argv=local_receipt_argv(context.profile),
        host_identity=host_identity,
    )
    return _attach_qualification_receipt(payload, qualification_receipt)



def _cleanup_owned_no_start(
    context, prepared, *, cleanup_prestart_raw=cleanup_prestart_raw, record_proven_no_start=record_proven_no_start,
):
    try:
        dispatch = prepared["startReceiptPath"].with_name("attempt-result-dispatched.json")
        if dispatch.exists() or dispatch.is_symlink():
            raise LifecycleError("codex-exact-start-uncertain", "existing dispatch forbids no-start cleanup")
        cleanup_prestart_raw(context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
            attempt_id=prepared["attemptId"], operation_id=prepared.get("operationId"), staging_source=None, proven_no_start=True)
        record_proven_no_start(context.root, prepared["startReceiptPath"])
    except (LifecycleError, OSError, ValueError) as exc:
        raise LifecycleError("codex-exact-start-uncertain", "owned no-start cleanup could not be persisted",
            {"costStatus": "UNAVAILABLE", "retryAuthorized": False}) from exc

