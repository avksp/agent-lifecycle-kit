"""Pure validation for external-job state transitions and child cleanup."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.external_job_schemas import (
    EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA,
    TERMINAL_JOB_STATES,
    validate_external_job_request,
    validate_external_job_status,
)

_ALLOWED_TRANSITIONS = {
    "QUEUED": {"QUEUED", "RUNNING", "CANCELLED", "EXPIRED"},
    "RUNNING": {"RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"},
}


def validate_external_job_transition(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    request: dict[str, Any],
    child_statuses: list[dict[str, Any]] | None = None,
    child_requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one idempotent transition without executing adapter work."""

    blockers: list[dict[str, Any]] = []
    previous_validation = validate_external_job_status(previous, request=request)
    current_validation = validate_external_job_status(current, request=request)
    if previous_validation["status"] != "PASS":
        blockers.append({"code": "external-job-previous-status-invalid"})
    if current_validation["status"] != "PASS":
        blockers.append({"code": "external-job-current-status-invalid"})
    identity_fields = ("jobId", "attempt", "requestDigest")
    if any(previous.get(field) != current.get(field) for field in identity_fields):
        blockers.append({"code": "external-job-transition-lineage-mismatch"})
    previous_state = previous.get("state")
    current_state = current.get("state")
    idempotent = previous.get("statusDigest") == current.get("statusDigest")
    if previous_state in TERMINAL_JOB_STATES:
        if not idempotent:
            blockers.append({"code": "external-job-terminal-status-immutable"})
    elif current_state not in _ALLOWED_TRANSITIONS.get(previous_state, set()):
        blockers.append({"code": "external-job-transition-invalid"})
    if not idempotent:
        previous_sequence = previous.get("sequence")
        current_sequence = current.get("sequence")
        if not isinstance(previous_sequence, int) or not isinstance(current_sequence, int):
            blockers.append({"code": "external-job-transition-sequence-invalid"})
        elif current_sequence <= previous_sequence:
            blockers.append({"code": "external-job-transition-sequence-stale"})
    if _child_refs_removed(previous.get("children"), current.get("children")):
        blockers.append({"code": "external-job-child-lineage-removed"})
    if current_state in TERMINAL_JOB_STATES:
        if current.get("processCleanupStatus") not in {"PASS", "NOT_REQUIRED"}:
            blockers.append({"code": "external-job-terminal-cleanup-incomplete"})
        if current.get("postTerminalWriteDetected") is not False:
            blockers.append({"code": "external-job-terminal-post-write"})
        _check_terminal_children(current, child_statuses or [], child_requests or [], blockers)
    body = {
        "schemaVersion": EXTERNAL_JOB_TRANSITION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "previousState": previous_state if isinstance(previous_state, str) else None,
        "nextState": current_state if isinstance(current_state, str) else None,
        "idempotent": idempotent,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _check_terminal_children(
    parent: dict[str, Any],
    child_statuses: list[dict[str, Any]],
    child_requests: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> None:
    declared = {
        (item.get("jobId"), item.get("attempt")): item
        for item in parent.get("children", [])
        if isinstance(item, dict)
    }
    observed = {
        (item.get("jobId"), item.get("attempt")): item
        for item in child_statuses
        if isinstance(item, dict)
    }
    requests = {
        (item.get("jobId"), item.get("attempt")): item
        for item in child_requests
        if isinstance(item, dict)
    }
    if set(observed).difference(declared):
        blockers.append({"code": "external-job-terminal-child-unexpected"})
    if set(requests).difference(declared):
        blockers.append({"code": "external-job-terminal-child-request-unexpected"})
    for identity, reference in declared.items():
        child_request = requests.get(identity)
        if child_request is None:
            blockers.append({"code": "external-job-terminal-child-request-missing", "child": reference})
            continue
        if validate_external_job_request(child_request)["status"] != "PASS":
            blockers.append({"code": "external-job-terminal-child-request-invalid", "child": reference})
            continue
        if (
            child_request.get("requestDigest") != reference.get("requestDigest")
            or child_request.get("parentJobId") != parent.get("jobId")
            or child_request.get("parentAttempt") != parent.get("attempt")
            or child_request.get("parentRequestDigest") != parent.get("requestDigest")
        ):
            blockers.append({"code": "external-job-terminal-child-parent-lineage-mismatch", "child": reference})
            continue
        child = observed.get(identity)
        if child is None:
            blockers.append({"code": "external-job-terminal-child-status-missing", "child": reference})
            continue
        if validate_external_job_status(child, request=child_request)["status"] != "PASS":
            blockers.append({"code": "external-job-terminal-child-status-invalid", "child": reference})
            continue
        if child.get("requestDigest") != reference.get("requestDigest"):
            blockers.append({"code": "external-job-terminal-child-lineage-mismatch", "child": reference})
        if child.get("state") not in TERMINAL_JOB_STATES:
            blockers.append({"code": "external-job-terminal-child-live", "child": reference})
        if child.get("processCleanupStatus") not in {"PASS", "NOT_REQUIRED"}:
            blockers.append({"code": "external-job-terminal-child-cleanup-failed", "child": reference})
        if child.get("postTerminalWriteDetected") is not False:
            blockers.append({"code": "external-job-terminal-child-post-write", "child": reference})


def _child_refs_removed(previous: Any, current: Any) -> bool:
    if not isinstance(previous, list) or not isinstance(current, list):
        return False
    previous_refs = {(item.get("jobId"), item.get("attempt"), item.get("requestDigest")) for item in previous if isinstance(item, dict)}
    current_refs = {(item.get("jobId"), item.get("attempt"), item.get("requestDigest")) for item in current if isinstance(item, dict)}
    return not previous_refs.issubset(current_refs)


__all__ = ["validate_external_job_transition"]
