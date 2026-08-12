"""Typed receipts for managed adapter sessions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.adapter_sessions.redaction import redact_process_text

ADAPTER_SESSION_RECEIPT_SCHEMA = "agent-adapter-session-receipt.v1"
MANAGED_ADAPTER_LAUNCH_RECEIPT_SCHEMA = "agent-managed-adapter-launch-receipt.v1"
ADAPTER_SESSION_RESUME_RECEIPT_SCHEMA = "agent-adapter-session-resume-receipt.v1"
LIFECYCLE_START_RECEIPT_SCHEMA = "agent-lifecycle-start-receipt.v1"
LOCAL_HOST_LAUNCH_PROFILE_RECEIPT_SCHEMA = "agent-local-host-launch-profile-receipt.v1"
LOCAL_HOST_LAUNCH_PROBE_RECEIPT_SCHEMA = "agent-local-host-launch-probe-receipt.v1"


def build_adapter_session_receipt(
    *,
    status: str,
    session_id: str,
    adapter_id: str,
    mode: str,
    launch_profile: dict[str, Any],
    state_identity: dict[str, Any] | None = None,
    managed_workflow_proof: dict[str, Any] | None = None,
    progress_hook_default: str = "off",
    host_launch_started: bool = False,
    state_written: bool = True,
    blockers: list[dict[str, Any]] | None = None,
    next_action: dict[str, Any] | None = None,
    launch_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    managed_workflow = managed_workflow_proof is not None
    body = {
        "schemaVersion": ADAPTER_SESSION_RECEIPT_SCHEMA,
        "status": status,
        "sessionId": session_id,
        "adapterId": adapter_id,
        "mode": mode,
        "managedWorkflow": managed_workflow,
        "lifecycleCoverageClaimed": managed_workflow and status not in {"WAITING_FOR_TASK", "BLOCKED", "UNMANAGED"},
        "launchProfile": _profile_summary(launch_profile),
        "stateIdentity": state_identity,
        "managedWorkflowProof": managed_workflow_proof,
        "progressHookDefault": progress_hook_default,
        "hostLaunchStarted": host_launch_started,
        "modelCallsStarted": False,
        "stateWritten": state_written,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers or [],
        "nextAction": next_action,
        "launchReceipt": launch_receipt,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_launch_receipt(
    *,
    status: str,
    adapter_id: str,
    session_id: str,
    launch_mode: str,
    argv: list[str],
    timeout_seconds: float,
    env: dict[str, Any],
    exit_code: int | None,
    timed_out: bool,
    cancelled: bool = False,
    stdout_tail: str = "",
    stderr_tail: str = "",
    stdout_redacted: bool = False,
    stderr_redacted: bool = False,
    host_launch_started: bool = False,
    blockers: list[dict[str, Any]] | None = None,
    profile_digest: str | None = None,
    risk_profile_digest: str | None = None,
    receipt_argv: list[str] | None = None,
) -> dict[str, Any]:
    stdout_tail, stdout_changed = redact_process_text(stdout_tail[-2000:])
    stderr_tail, stderr_changed = redact_process_text(stderr_tail[-2000:])
    safe_argv, argv_changed = redact_value(receipt_argv if receipt_argv is not None else argv)
    body = {
        "schemaVersion": MANAGED_ADAPTER_LAUNCH_RECEIPT_SCHEMA,
        "status": status,
        "adapterId": adapter_id,
        "sessionId": session_id,
        "launchMode": launch_mode,
        "argv": safe_argv,
        "shell": False,
        "timeoutSeconds": timeout_seconds,
        "env": env,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "cancelled": cancelled,
        "stdout": {"tail": stdout_tail, "redacted": stdout_redacted or stdout_changed},
        "stderr": {"tail": stderr_tail, "redacted": stderr_redacted or stderr_changed},
        "argvRedacted": argv_changed,
        "profileDigest": profile_digest,
        "riskProfileDigest": risk_profile_digest,
        "hostLaunchStarted": host_launch_started,
        "modelCallsStarted": False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers or [],
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_local_launch_profile_receipt(
    *,
    status: str,
    operation: str,
    profile_path: str,
    profile_summary: dict[str, Any],
    profile_digest: str | None,
    process_calls: int,
    probe_receipt: dict[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a portable inspect or preflight receipt without local values."""

    safe_summary, summary_changed = redact_value(profile_summary)
    body = {
        "schemaVersion": LOCAL_HOST_LAUNCH_PROFILE_RECEIPT_SCHEMA,
        "status": status,
        "operation": operation,
        "profilePath": profile_path,
        "profile": safe_summary,
        "profileDigest": profile_digest,
        "processCalls": process_calls,
        "probeReceipt": probe_receipt,
        "redactionApplied": summary_changed
        or bool(probe_receipt and (probe_receipt.get("stdout", {}).get("redacted") or probe_receipt.get("stderr", {}).get("redacted"))),
        "hostLaunchStarted": process_calls > 0,
        "modelCallsStarted": False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers or [],
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_local_launch_probe_receipt(
    *,
    argv: list[str],
    timeout_seconds: float,
    env: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build a redacted receipt for one bounded executable version probe."""

    safe_argv, argv_changed = redact_value(argv)
    stdout_tail, stdout_changed = redact_process_text(str(result.get("stdoutTail", ""))[-2000:])
    stderr_tail, stderr_changed = redact_process_text(str(result.get("stderrTail", ""))[-2000:])
    body = {
        "schemaVersion": LOCAL_HOST_LAUNCH_PROBE_RECEIPT_SCHEMA,
        "status": result.get("status", "FAIL"),
        "argv": safe_argv,
        "argvRedacted": argv_changed,
        "shell": False,
        "timeoutSeconds": timeout_seconds,
        "env": env,
        "exitCode": result.get("exitCode"),
        "timedOut": bool(result.get("timedOut")),
        "stdout": {
            "tail": stdout_tail,
            "redacted": bool(result.get("stdoutRedacted")) or stdout_changed,
        },
        "stderr": {
            "tail": stderr_tail,
            "redacted": bool(result.get("stderrRedacted")) or stderr_changed,
        },
        "hostLaunchStarted": True,
        "modelCallsStarted": False,
        "blockers": list(result.get("blockers", [])),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_resume_receipt(
    *,
    session_id: str,
    adapter_id: str,
    expected_identity: dict[str, Any],
    actual_identity: dict[str, Any],
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = blockers or []
    lineage_status = "FAIL" if items else ("PASS" if actual_identity else "NOT_BOUND")
    status = "BLOCKED" if items else ("PASS" if actual_identity else "UNMANAGED")
    body = {
        "schemaVersion": ADAPTER_SESSION_RESUME_RECEIPT_SCHEMA,
        "status": status,
        "sessionId": session_id,
        "adapterId": adapter_id,
        "lineageStatus": lineage_status,
        "expectedIdentity": expected_identity,
        "actualIdentity": actual_identity,
        "managedWorkflow": not items and bool(actual_identity),
        "lifecycleCoverageClaimed": not items and bool(actual_identity),
        "blockers": items,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_lifecycle_start_receipt(
    *,
    status: str,
    adapter_id: str,
    requested_mode: str,
    action: str,
    input_summary: dict[str, Any],
    delegate_summary: dict[str, Any] | None = None,
    execution_started: bool = False,
    lifecycle_coverage_claimed: bool = False,
    requires_review: bool = False,
    blockers: list[dict[str, Any]] | None = None,
    host_launch_started: bool = False,
    launch_receipt: dict[str, Any] | None = None,
    execution_strategy: dict[str, Any] | None = None,
    project_profile_digest: str | None = None,
) -> dict[str, Any]:
    """Build the public, path-safe receipt for the unified start facade."""

    body = {
        "schemaVersion": LIFECYCLE_START_RECEIPT_SCHEMA,
        "status": status,
        "adapterId": adapter_id,
        "requestedMode": requested_mode,
        "action": action,
        "input": input_summary,
        "delegate": delegate_summary,
        "executionStrategy": execution_strategy,
        "executionStarted": execution_started,
        "lifecycleCoverageClaimed": lifecycle_coverage_claimed,
        "requiresReview": requires_review,
        "modelCallsStarted": False,
        "hostLaunchStarted": host_launch_started,
        "launchReceipt": launch_receipt,
        "nativeSessionAttached": False,
        "rawTaskTextStored": False,
        "secretsWritten": False,
        "nativeConfigWritten": False,
        "blockers": blockers or [],
        "productionPromotionClaimed": False,
    }
    if project_profile_digest is not None:
        body["projectProfileDigest"] = project_profile_digest
    return {**body, "receiptDigest": canonical_digest(body)}


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": profile.get("status"),
        "reason": profile.get("reason"),
        "source": "adapter.descriptor.json",
        "shell": False,
        "writesNativeConfig": bool(profile.get("writesNativeConfig", False)),
        "promptInjectionDefault": bool(profile.get("promptInjectionDefault", False)),
    }
